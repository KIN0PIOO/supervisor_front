from typing import TypedDict, Optional, Dict, Any

class MigrationState(TypedDict):
    """
    마이그레이션 에이전트의 상태를 관리하는 객체.
    모든 노드(Node)는 이 상태를 읽고 업데이트하여 흐름을 제어합니다.
    """
    next_sql_info: Any

    source_ddl: Optional[Dict[str, Any]]
    target_ddl: Optional[list]

    last_error: Optional[str]
    last_sql: Optional[str]

    db_attempts: int
    max_attempts: int
    llm_retry_count: int

    current_ddl_sql: Optional[str]
    current_migration_sql: Optional[str]
    current_v_sql: Optional[str]
    error_type: Optional[str]

    status: str
    elapsed_time: int
    job_start_time: float
