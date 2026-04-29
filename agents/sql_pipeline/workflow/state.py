"""마이그레이션 워크플로우에서 공유하는 상태 객체."""

from dataclasses import dataclass, field
from typing import TypedDict


@dataclass
class JobExecutionState:
    """SQL 마이그레이션 job 하나에 대한 변경 가능한 실행 상태."""

    job: object
    job_key: str
    mapping_rules: list
    last_error: str | None = None
    tuning_examples: list[dict] = field(default_factory=list)
    tobe_sql: str = ""
    tuned_sql: str = ""
    tuned_test: str | None = None
    bind_sql: str = ""
    bind_set_for_db: str | None = None
    bind_set_json_for_test: str = "[]"
    bind_param_names: list[str] = field(default_factory=list)
    test_sql: str = ""
    test_rows: list[dict] = field(default_factory=list)
    status: str | None = None


class MigrationGraphState(TypedDict):
    """LangGraph 전용 상태 wrapper."""

    execution: JobExecutionState
    terminal_action: str | None
