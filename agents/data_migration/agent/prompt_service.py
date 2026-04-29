import json
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


def _load(filename: str) -> dict:
    return json.loads((PROMPTS_DIR / filename).read_text(encoding="utf-8"))


def build_migration_prompt(
    from_table: str,
    to_table: str,
    mapping_info: str,
    ddl_info_block: str,
    is_append: bool,
    correct_sql: str | None = None,
    last_error: str | None = None,
    last_sql: str | None = None,
) -> tuple[str, str, str]:
    """Returns (system_anthropic, system_openai, user_prompt)."""
    t = _load("migration_prompt.json")

    # ── 조건부 섹션 선택 및 렌더링 ──────────────────────────────────────────
    verification_key = "verification_append" if is_append else "verification_regular"
    verification_instruction = t[verification_key].format(
        from_table=from_table, to_table=to_table
    )

    prompt = t["main_prompt"].format(
        from_table=from_table,
        to_table=to_table,
        mapping_info=mapping_info,
        ddl_info_block=ddl_info_block,
        verification_instruction=verification_instruction,
    )

    if correct_sql:
        prompt += t["correct_sql_suffix"].format(correct_sql=correct_sql)

    if last_error:
        prompt += t["error_suffix"].format(last_sql=last_sql, last_error=last_error)

    if is_append:
        prompt += t["append_mode_suffix"].format(to_table=to_table)

    return t["system_anthropic"], t["system_openai"], prompt
