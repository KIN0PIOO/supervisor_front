"""Supervisor 전역 상태 정의.

LangGraph 노드들이 공유하는 불변 상태 컨테이너.
에이전트는 이 상태를 읽고 부분 업데이트만 반환한다.
"""

import operator
from typing import Annotated, Any, List
from typing_extensions import TypedDict


class SupervisorState(TypedDict):
    """멀티 에이전트 폴링 사이클 상태."""

    # 이번 사이클에서 수집된 DataMigration 대기 작업 목록
    pending_mig_jobs: list[Any]

    # 이번 사이클에서 수집된 SqlPipeline 대기 작업 목록
    pending_sql_jobs: list[Any]

    # 이번 사이클에서 수집된 SQL Tuning 전용 대기 작업 목록 (STATUS=PASS 건)
    pending_tuning_jobs: list[Any]

    # SqlPipeline 마지막 폴링 시각 (epoch seconds)
    last_sql_poll_at: float

    # 완료된 폴링 사이클 수 (로깅용)
    cycle: int

    # SIGINT/SIGTERM 수신 시 True 로 설정 → Supervisor 루프 종료
    stop_requested: bool

    # 에이전트 작업 결과 수집 (LangGraph 상태 변화 인지 목적)
    agent_outcomes: Annotated[List[str], operator.add]
