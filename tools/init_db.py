"""Oracle / LLM 연결 health check 도구.

실행:
  python tools/init_db.py
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools._bootstrap import ROOT_DIR  # noqa: F401
from dotenv import load_dotenv
load_dotenv(ROOT_DIR / ".env")

import requests
from agents.sql_pipeline.services.db_runtime import (
    get_connection,
    get_mapping_rule_detail_table,
    get_mapping_rule_table,
    get_result_table,
)
from agents.sql_pipeline.core.logger import logger


@dataclass
class HealthResult:
    name: str
    ok: bool
    detail: str


def _join_url(base_url: str, suffix: str) -> str:
    return f"{base_url.rstrip('/')}/{suffix.lstrip('/')}"


def check_oracle_connection() -> HealthResult:
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM DUAL")
            row = cursor.fetchone()
            if row and row[0] == 1:
                return HealthResult("Oracle DB", True, "SELECT 1 FROM DUAL → OK")
            return HealthResult("Oracle DB", False, f"Unexpected result: {row}")
    except Exception as exc:
        return HealthResult("Oracle DB", False, str(exc))


def check_tables() -> list[HealthResult]:
    results = []
    tables = {
        "mapping_rule_table": get_mapping_rule_table(),
        "mapping_rule_detail_table": get_mapping_rule_detail_table(),
        "result_table": get_result_table(),
    }
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            for alias, table in tables.items():
                try:
                    cursor.execute(f"SELECT COUNT(*) FROM {table} WHERE ROWNUM <= 1")
                    count = cursor.fetchone()[0]
                    results.append(HealthResult(f"Table:{alias}", True, f"{table} → {count} row(s) accessible"))
                except Exception as exc:
                    results.append(HealthResult(f"Table:{alias}", False, f"{table} → {exc}"))
    except Exception as exc:
        results.append(HealthResult("Tables", False, f"Connection failed: {exc}"))
    return results


def check_llm_connection() -> HealthResult:
    api_key = os.getenv("LLM_API_KEY") or os.getenv("OPEN_API_KEY")
    base_url = os.getenv("LLM_BASE_URL", "")
    model = os.getenv("LLM_MODEL", "")
    provider = (os.getenv("LLM_PROVIDER") or "").strip().lower()

    if not api_key:
        return HealthResult("LLM", False, "LLM_API_KEY / OPEN_API_KEY is not set")

    try:
        if provider == "anthropic" or "anthropic" in base_url.lower() or model.lower().startswith("claude"):
            anthropic_base = (base_url or "https://api.anthropic.com").rstrip("/")
            if anthropic_base.endswith("/v1"):
                models_url = _join_url(anthropic_base, "models")
            else:
                models_url = _join_url(anthropic_base, "v1/models")
            headers = {
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            }
        else:
            models_url = _join_url(base_url, "models") if base_url else "https://api.openai.com/v1/models"
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

        resp = requests.get(models_url, headers=headers, timeout=10)
        if resp.status_code == 200:
            return HealthResult("LLM", True, f"Connected to {models_url} | model={model}")
        return HealthResult("LLM", False, f"HTTP {resp.status_code}: {resp.text[:200]}")
    except Exception as exc:
        return HealthResult("LLM", False, str(exc))


def run_all_checks() -> None:
    checks: list[HealthResult] = []
    checks.append(check_oracle_connection())
    checks.extend(check_tables())
    checks.append(check_llm_connection())

    print("\n=== Health Check Results ===")
    all_ok = True
    for result in checks:
        icon = "✓" if result.ok else "✗"
        print(f"  [{icon}] {result.name:<35} {result.detail}")
        if not result.ok:
            all_ok = False
    print()
    if all_ok:
        print("All checks passed. System is ready.")
    else:
        print("One or more checks failed. Please review the configuration.")


if __name__ == "__main__":
    run_all_checks()
