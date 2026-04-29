from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any


_TAG_PATTERN = re.compile(r"<\s*(/?)\s*(if|choose|when|otherwise|where|trim|foreach)\b([^>]*)>", re.IGNORECASE | re.DOTALL)
_ATTR_PATTERN = re.compile(r'([A-Za-z_][A-Za-z0-9_]*)\s*=\s*"([^"]*)"|([A-Za-z_][A-Za-z0-9_]*)\s*=\s*\'([^\']*)\'')
_BIND_PATTERN = re.compile(r"([#$])\{\s*([^}]+?)\s*\}")
_AND_OR_PATTERN = re.compile(r"\b(and|or)\b", re.IGNORECASE)
_NOT_PATTERN = re.compile(r"(?<![=!<>])!(?!=)")
_IDENTIFIER_PATTERN = re.compile(r"\b([A-Za-z_][A-Za-z0-9_\.]*)\b")
_KEYWORDS = {"and", "or", "not", "None", "True", "False", "in", "is"}


@dataclass
class _Node:
    tag: str | None
    attrs: dict[str, str] = field(default_factory=dict)
    items: list[Any] = field(default_factory=list)


def materialize_sql(sql_text: str, bind_case: dict[str, Any] | None = None) -> str:
    root = _parse_template(sql_text or "")
    context = dict(bind_case or {})
    rendered = _render_items(root.items, context)
    rendered = _replace_bind_tokens(rendered, context)
    rendered = _cleanup_sql(rendered)
    return rendered


def _parse_template(sql_text: str) -> _Node:
    root = _Node(tag="root")
    stack = [root]
    cursor = 0
    for match in _TAG_PATTERN.finditer(sql_text):
        text = sql_text[cursor:match.start()]
        if text:
            stack[-1].items.append(text)

        is_closing = bool(match.group(1))
        tag = match.group(2).lower()
        raw_attrs = match.group(3) or ""

        if is_closing:
            while len(stack) > 1 and stack[-1].tag != tag:
                stack.pop()
            if len(stack) > 1 and stack[-1].tag == tag:
                stack.pop()
        else:
            node = _Node(tag=tag, attrs=_parse_attrs(raw_attrs))
            stack[-1].items.append(node)
            stack.append(node)
        cursor = match.end()

    tail = sql_text[cursor:]
    if tail:
        stack[-1].items.append(tail)
    return root


def _parse_attrs(raw_attrs: str) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for match in _ATTR_PATTERN.finditer(raw_attrs):
        key = match.group(1) or match.group(3)
        value = match.group(2) if match.group(1) else match.group(4)
        if key:
            attrs[key.lower()] = value or ""
    return attrs


def _render_node(node: _Node, context: dict[str, Any]) -> str:
    body = _render_items(node.items, context)

    if node.tag == "if":
        return body if _evaluate_test(node.attrs.get("test", ""), context) else ""
    if node.tag == "when":
        return body if _evaluate_test(node.attrs.get("test", ""), context) else ""
    if node.tag == "otherwise":
        return body
    if node.tag == "choose":
        for child in node.items:
            if not isinstance(child, _Node):
                continue
            if child.tag == "when" and _evaluate_test(child.attrs.get("test", ""), context):
                return _render_node(child, context)
        for child in node.items:
            if not isinstance(child, _Node):
                continue
            if child.tag == "otherwise":
                return _render_node(child, context)
        return ""
    if node.tag == "where":
        content = _cleanup_clause(body)
        if not content:
            return ""
        content = re.sub(r"^(AND|OR)\b", "", content, flags=re.IGNORECASE).strip()
        return f" WHERE {content}" if content else ""
    if node.tag == "trim":
        content = _cleanup_clause(body)
        if not content:
            return ""
        content = _apply_overrides(content, node.attrs.get("prefixoverrides", ""), prefix=True)
        content = _apply_overrides(content, node.attrs.get("suffixoverrides", ""), prefix=False)
        prefix = node.attrs.get("prefix", "")
        suffix = node.attrs.get("suffix", "")
        return f"{prefix}{content}{suffix}"
    if node.tag == "foreach":
        return _render_foreach(node, context)
    return body


def _render_foreach(node: _Node, context: dict[str, Any]) -> str:
    collection_name = node.attrs.get("collection", "")
    item_name = node.attrs.get("item", "item")
    index_name = node.attrs.get("index", "index")
    open_text = node.attrs.get("open", "")
    close_text = node.attrs.get("close", "")
    separator = node.attrs.get("separator", ",")

    collection_value = _resolve_name(collection_name, context)
    iterable = _normalize_collection(collection_value)
    if not iterable:
        return ""

    parts: list[str] = []
    for idx, item in enumerate(iterable):
        child_context = dict(context)
        child_context[item_name] = item
        child_context[index_name] = idx
        body = _render_items(node.items, child_context)
        body = _replace_bind_tokens(body, child_context)
        body = _cleanup_clause(body)
        if body:
            parts.append(body)
    if not parts:
        return ""
    return f"{open_text}{separator.join(parts)}{close_text}"


def _render_items(items: list[Any], context: dict[str, Any]) -> str:
    rendered: list[str] = []
    for item in items:
        if isinstance(item, _Node):
            rendered.append(_render_node(item, context))
        else:
            rendered.append(str(item))
    return "".join(rendered)


def _normalize_collection(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]


def _evaluate_test(expression: str, context: dict[str, Any]) -> bool:
    expr = (expression or "").strip()
    if not expr:
        return False

    expr = _AND_OR_PATTERN.sub(lambda m: m.group(1).lower(), expr)
    expr = re.sub(r"\bnull\b", "None", expr, flags=re.IGNORECASE)
    expr = re.sub(r"\btrue\b", "True", expr, flags=re.IGNORECASE)
    expr = re.sub(r"\bfalse\b", "False", expr, flags=re.IGNORECASE)
    expr = _NOT_PATTERN.sub(" not ", expr)

    def repl_identifier(match: re.Match[str]) -> str:
        token = match.group(1)
        if token in _KEYWORDS or token.isdigit():
            return token
        if "." in token:
            root = token.split(".", 1)[0]
            if root in _KEYWORDS:
                return token
        return f"_resolve_name('{token}', _ctx)"

    expr = _IDENTIFIER_PATTERN.sub(repl_identifier, expr)
    try:
        return bool(eval(expr, {"__builtins__": {}}, {"_ctx": context, "_resolve_name": _resolve_name}))
    except Exception:
        return False


def _resolve_name(name: str, context: dict[str, Any]) -> Any:
    token = (name or "").strip()
    if not token:
        return None

    current: Any = context
    for part in token.split("."):
        if isinstance(current, dict):
            lowered_map = {str(key).lower(): value for key, value in current.items()}
            current = lowered_map.get(part.lower())
        else:
            current = getattr(current, part, None)
        if current is None:
            return None
    return current


def _replace_bind_tokens(sql_text: str, context: dict[str, Any]) -> str:
    def repl(match: re.Match[str]) -> str:
        token_type = match.group(1)
        raw_name = match.group(2)
        normalized_name = raw_name.split(",")[0].strip()
        value = _resolve_name(normalized_name, context)
        if token_type == "$":
            return "" if value is None else str(value)
        return _sql_literal(value)

    return _BIND_PATTERN.sub(repl, sql_text or "")


def _sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float, Decimal)):
        return str(value)
    if isinstance(value, datetime):
        return f"TO_DATE('{value.strftime('%Y-%m-%d')}', 'YYYY-MM-DD')"
    if isinstance(value, date):
        return f"TO_DATE('{value.isoformat()}', 'YYYY-MM-DD')"
    text = str(value).replace("'", "''")
    return f"'{text}'"


def _cleanup_clause(text: str) -> str:
    cleaned = text.replace("\r", " ").replace("\n", " ")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def _cleanup_sql(text: str) -> str:
    cleaned = _cleanup_clause(text)
    cleaned = re.sub(r"\bWHERE\s+(AND|OR)\b", "WHERE ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\(\s+", "(", cleaned)
    cleaned = re.sub(r"\s+\)", ")", cleaned)
    return cleaned.strip()


def _apply_overrides(content: str, raw_overrides: str, prefix: bool) -> str:
    result = content
    overrides = [item.strip() for item in raw_overrides.split("|") if item.strip()]
    for override in overrides:
        pattern = re.escape(override)
        if prefix:
            result = re.sub(rf"^\s*{pattern}", "", result, flags=re.IGNORECASE).strip()
        else:
            result = re.sub(rf"{pattern}\s*$", "", result, flags=re.IGNORECASE).strip()
    return result
