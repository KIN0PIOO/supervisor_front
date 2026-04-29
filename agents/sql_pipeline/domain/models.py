from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class SqlInfoJob:
    """NEXT_SQL_INFO 한 row를 애플리케이션 내부에서 다루기 위한 모델."""

    row_id: str
    tag_kind: str
    space_nm: str
    sql_id: str
    fr_sql_text: str
    target_table: Optional[str] = None
    edit_fr_sql: Optional[str] = None
    to_sql_text: Optional[str] = None
    tuned_sql: Optional[str] = None
    tuned_test: Optional[str] = None
    bind_sql: Optional[str] = None
    bind_set: Optional[str] = None
    test_sql: Optional[str] = None
    status: Optional[str] = None
    log_text: Optional[str] = None
    upd_ts: Optional[datetime] = None
    edited_yn: Optional[str] = None
    tobe_correct_sql: Optional[str] = None
    bind_correct_sql: Optional[str] = None
    test_correct_sql: Optional[str] = None

    @property
    def source_sql(self) -> str:
        """사용자가 수정한 SQL이 있으면 우선 사용하고, 없으면 원본 SQL을 반환한다."""
        edited = (self.edit_fr_sql or "").strip()
        return edited if edited else (self.fr_sql_text or "")


@dataclass
class MappingRuleItem:
    """FROM/TO 테이블과 컬럼 매핑 룰 한 건을 표현하는 모델."""

    map_type: str
    fr_table: str
    fr_col: str
    to_table: str
    to_col: str
