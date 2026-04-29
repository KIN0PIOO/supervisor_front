"""SQL 실행/검증 책임을 모아둔 서비스."""

import re
from typing import Any

from agents.sql_pipeline.services.db_runtime import get_connection
from agents.sql_pipeline.core.exceptions import DBSqlError


_FORBIDDEN_RUNTIME_TOKENS = (
    "<if",
    "<choose",
    "<when",
    "<otherwise",
    "<where",
    "<trim",
    "#{",
    "${",
)


def _shorten_sql_for_log(sql_text: str, max_len: int = 700) -> str:
    one_line = re.sub(r"\s+", " ", (sql_text or "")).strip()
    if len(one_line) <= max_len:
        return one_line
    return one_line[:max_len] + "...(truncated)"


def execute_binding_query(binding_query_sql: str, max_rows: int = 20) -> list[dict[str, Any]]:
    clean_sql = _prepare_runtime_sql(binding_query_sql, stage="EXECUTE_BIND_SQL")
    if not clean_sql:
        raise DBSqlError("Binding query SQL is empty.")

    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(clean_sql)
            columns = [column[0] for column in cursor.description] if cursor.description else []
            rows = cursor.fetchmany(max_rows)
    except Exception as exc:
        raise DBSqlError(
            f"EXECUTE_BIND_SQL failed: {exc} | SQL={_shorten_sql_for_log(clean_sql)}"
        ) from exc

    bind_sets: list[dict[str, Any]] = []
    for row in rows:
        bind_item: dict[str, Any] = {}
        for idx, column in enumerate(columns):
            bind_item[column] = row[idx]
        bind_sets.append(bind_item)
    return bind_sets


def execute_test_query(test_sql: str) -> list[dict[str, Any]]:
    clean_sql = _prepare_runtime_sql(test_sql, stage="EXECUTE_TEST_SQL")
    if not clean_sql:
        raise DBSqlError("TEST SQL is empty.")

    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(clean_sql)
            columns = [column[0] for column in cursor.description] if cursor.description else []
            rows = cursor.fetchall()
    except Exception as exc:
        raise DBSqlError(
            f"EXECUTE_TEST_SQL failed: {exc} | SQL={_shorten_sql_for_log(clean_sql)}"
        ) from exc

    result = []
    for row in rows:
        item: dict[str, Any] = {}
        for idx, col in enumerate(columns):
            item[col] = row[idx]
        result.append(item)
    return result


def _to_int_or_none(value) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None


def _get_value_case_insensitive(row: dict[str, Any], key: str):
    if key in row:
        return row[key]
    lowered = key.lower()
    for existing_key, value in row.items():
        if str(existing_key).lower() == lowered:
            return value
    return None


def evaluate_status_from_test_rows(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "FAIL"

    required_cols = {"case_no", "from_count", "to_count"}
    sample_keys = {str(key).lower() for key in rows[0].keys()}
    if not required_cols.issubset(sample_keys):
        raise DBSqlError(
            "TEST SQL must return CASE_NO, FROM_COUNT, TO_COUNT columns. "
            f"Actual columns: {sorted(sample_keys)}"
        )

    all_match = True
    for row in rows:
        from_count = _to_int_or_none(_get_value_case_insensitive(row, "from_count"))
        to_count = _to_int_or_none(_get_value_case_insensitive(row, "to_count"))

        if from_count is None or to_count is None:
            all_match = False
            continue

        if from_count == 0 and to_count == 0:
            all_match = False
            continue

        if from_count != to_count:
            all_match = False

    return "PASS" if all_match else "FAIL"


def _prepare_runtime_sql(sql_text: str, stage: str) -> str:
    clean_sql = (sql_text or "").replace("﻿", "").strip().rstrip(";").strip()
    if not clean_sql:
        return clean_sql

    if stage in {"EXECUTE_BIND_SQL", "EXECUTE_TEST_SQL"}:
        clean_sql = _normalize_select_row_limit(clean_sql)

    lowered = clean_sql.lower()
    for token in _FORBIDDEN_RUNTIME_TOKENS:
        if token in lowered:
            raise DBSqlError(
                f"{stage} generated non-executable SQL containing '{token}'. "
                "MyBatis tags/placeholders must be fully resolved before execution."
            )

    if _has_unquoted_semicolon(clean_sql):
        raise DBSqlError(f"{stage} generated multiple SQL statements; only one statement is allowed.")
    return clean_sql


def _normalize_select_row_limit(sql_text: str) -> str:
    text = sql_text.strip().rstrip(";")

    limit_match = re.search(r"\s+LIMIT\s+(\d+)\s*$", text, flags=re.IGNORECASE)
    if limit_match:
        limit = int(limit_match.group(1))
        inner = re.sub(r"\s+LIMIT\s+\d+\s*$", "", text, flags=re.IGNORECASE).strip()
        return f"SELECT * FROM ({inner}) WHERE ROWNUM <= {limit}"

    fetch_match = re.search(r"\s+FETCH\s+FIRST\s+(\d+)\s+ROWS\s+ONLY\s*$", text, flags=re.IGNORECASE)
    if fetch_match:
        limit = int(fetch_match.group(1))
        inner = re.sub(
            r"\s+FETCH\s+FIRST\s+\d+\s+ROWS\s+ONLY\s*$",
            "",
            text,
            flags=re.IGNORECASE,
        ).strip()
        return f"SELECT * FROM ({inner}) WHERE ROWNUM <= {limit}"

    return text


def _has_unquoted_semicolon(sql_text: str) -> bool:
    in_single_quote = False
    idx = 0
    length = len(sql_text)
    while idx < length:
        ch = sql_text[idx]
        if in_single_quote:
            if ch == "'":
                if idx + 1 < length and sql_text[idx + 1] == "'":
                    idx += 2
                    continue
                in_single_quote = False
            idx += 1
            continue
        if ch == "'":
            in_single_quote = True
            idx += 1
            continue
        if ch == ";":
            return True
        idx += 1
    return False
