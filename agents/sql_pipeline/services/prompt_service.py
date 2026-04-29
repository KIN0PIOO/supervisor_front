import json
from pathlib import Path
from typing import Any


# sql_pipeline/prompts/ 디렉토리
PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


def load_prompt_template(filename: str) -> dict[str, Any]:
    prompt_path = PROMPTS_DIR / filename
    return json.loads(prompt_path.read_text(encoding="utf-8"))


def render_prompt_template(filename: str, **kwargs) -> dict[str, Any]:
    template = load_prompt_template(filename)
    return _render_value(template, kwargs)


def build_prompt_messages(filename: str, **kwargs) -> list[dict[str, str]]:
    payload = render_prompt_template(filename, **kwargs)
    user_instruction = payload.pop("user_instruction", "Generate one executable Oracle SQL statement only.")
    return [
        {"role": "system", "content": json.dumps(payload, ensure_ascii=False, indent=2)},
        {"role": "user", "content": str(user_instruction)},
    ]


def _render_value(value: Any, context: dict[str, Any]) -> Any:
    if isinstance(value, dict):
        return {key: _render_value(item, context) for key, item in value.items()}
    if isinstance(value, list):
        return [_render_value(item, context) for item in value]
    if isinstance(value, str):
        return value.format(**context)
    return value
