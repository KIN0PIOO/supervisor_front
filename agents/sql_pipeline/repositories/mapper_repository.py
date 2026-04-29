"""매핑 룰 조회 리포지토리."""

import json
import re

from agents.sql_pipeline.services.db_runtime import (
    get_connection,
    get_mapping_rule_detail_table,
    get_mapping_rule_table,
)
from agents.sql_pipeline.domain.models import MappingRuleItem


def _to_text(value, default: str = "") -> str:
    if value is None:
        return default
    if hasattr(value, "read"):
        value = value.read()
    if value is None:
        return default
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="ignore")
    return str(value)


def get_all_mapping_rules() -> list[MappingRuleItem]:
    """NEXT_MIG_INFO + DTL 조인으로 전체 매핑 룰을 읽어온다."""
    map_table = get_mapping_rule_table()
    detail_table = get_mapping_rule_detail_table()
    query = f"""
        SELECT M.FR_TABLE, D.FR_COL, M.TO_TABLE, D.TO_COL
        FROM {map_table} M
        JOIN {detail_table} D
          ON M.MAP_ID = D.MAP_ID
        WHERE UPPER(TRIM(M.TARGET_YN)) = 'Y'
          AND UPPER(TRIM(M.STATUS)) = 'PASS'
        ORDER BY M.MAP_ID, D.MAP_DTL
    """

    rules: list[MappingRuleItem] = []
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query)
        for row in cursor.fetchall():
            rules.append(
                MappingRuleItem(
                    map_type="",
                    fr_table=_to_text(row[0]),
                    fr_col=_to_text(row[1]),
                    to_table=_to_text(row[2]),
                    to_col=_to_text(row[3]),
                )
            )
    return rules


def get_unready_target_tables(target_table_value: str | None) -> list[str]:
    target_tables = _parse_target_tables(target_table_value)
    if not target_tables:
        return []

    map_table = get_mapping_rule_table()
    query = f"""
        SELECT M.FR_TABLE, M.STATUS
        FROM {map_table} M
        WHERE UPPER(TRIM(M.TARGET_YN)) = 'Y'
    """

    rows: list[tuple[str, str]] = []
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query)
        for fr_table, status in cursor.fetchall():
            rows.append((_to_text(fr_table).upper(), _to_text(status).strip().upper()))

    unready: list[str] = []
    for target_table in sorted(target_tables):
        matched_statuses = [
            status
            for fr_table, status in rows
            if _fr_table_contains_target(fr_table, target_table)
        ]
        if not matched_statuses or any(status != "PASS" for status in matched_statuses):
            unready.append(target_table)
    return unready


def _parse_target_tables(raw_value: str | None) -> set[str]:
    raw = _to_text(raw_value).strip()
    if not raw:
        return set()

    tokens: list[str] = []
    if raw.startswith("[") or raw.startswith("{"):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                tokens = [str(item) for item in parsed]
            elif isinstance(parsed, str):
                tokens = [parsed]
        except Exception:
            tokens = []

    if not tokens:
        tokens = re.split(r"[,\s;|]+", raw)

    return {normalized for token in tokens if (normalized := _normalize_table_token(token))}


def _normalize_table_token(token: str) -> str:
    value = (token or "").strip().strip("[]").strip().strip('"').strip("'").strip()
    if not value:
        return ""
    if "." in value:
        value = value.split(".")[-1]
    return value.strip("[]").strip().strip('"').strip("'").upper()


def _fr_table_contains_target(fr_table: str, target_table: str) -> bool:
    if not fr_table or not target_table:
        return False
    pattern = rf"(?<![A-Z0-9_$#]){re.escape(target_table)}(?![A-Z0-9_$#])"
    return bool(re.search(pattern, fr_table.upper()))
