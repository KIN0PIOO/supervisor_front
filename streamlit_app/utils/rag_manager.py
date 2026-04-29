import json
import re
from datetime import date
from pathlib import Path
from dotenv import load_dotenv
import os

_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(_ROOT / ".env")

_catalog_env = os.getenv("TOBE_RULE_CATALOG_PATH", "")
RAG_PATH = (
    (_ROOT / _catalog_env)
    if _catalog_env
    else _ROOT / "agents" / "sql_pipeline" / "data" / "rag" / "tobe_rule_catalog.json"
)


def load_rules() -> list[dict]:
    return json.loads(RAG_PATH.read_text(encoding="utf-8")).get("rules", [])


def save_rules(rules: list[dict]):
    RAG_PATH.write_text(
        json.dumps({"rules": rules}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def add_rule(guidance_text: str, bad_sql: str) -> dict:
    rules = load_rules()
    nums = [
        int(n)
        for r in rules
        for n in re.findall(r"\d+", str(r.get("rule_id", "")))
    ]
    next_num = max(nums, default=0) + 1
    new_rule = {
        "rule_id": f"USER_RULE_{next_num:03d}",
        "guidance": [g.strip() for g in guidance_text.strip().splitlines() if g.strip()],
        "example_bad_sql": bad_sql.strip(),
        "example_tuned_sql": "",
        "created_at": str(date.today()),
    }
    rules.append(new_rule)
    save_rules(rules)
    return new_rule


def delete_rule(rule_id: str) -> bool:
    rules = load_rules()
    new_rules = [r for r in rules if r.get("rule_id") != rule_id]
    if len(new_rules) == len(rules):
        return False
    save_rules(new_rules)
    return True
