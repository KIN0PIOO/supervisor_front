"""LangGraph Supervisor 그래프.

그래프 흐름 (Planner 추가):
  START
    → supervisor_node  : DB 폴링, 전체 대기 작업 수집
    → planner_node     : LLM이 이번 사이클에 실행할 작업 동적 선택
                         (PLANNER_ENABLED=false 시 전체 작업 통과)
    → [조건부]
        jobs 있음 → Send() 로 에이전트 fan-out (내부 로직 완전 불변)
        jobs 없음 → wait_node
        stop      → END
    wait_node → supervisor_node (루프)

Stage 1 (유연): supervisor_node + planner_node — 어떤 작업 실행할지 LLM 판단
Stage 2 (안정): 각 에이전트 내부 워크플로우 — 절대 변경 없음
"""

import threading
import time
from pathlib import Path
from typing import Literal

from langgraph.graph import END, StateGraph
from langgraph.types import Send

from agents.supervisor.state import SupervisorState
from agents.planner.agent import PlannerAgent
from config.settings import PLANNER_ENABLED

# ── 폴링 주기 상수 (원본 시스템 그대로 유지) ──────────────────────────────
DM_POLL_INTERVAL_SEC  = 5    # DataMigration: 5초
SQL_POLL_INTERVAL_SEC = 5    # SqlPipeline  : 5초

# ── 런타임 제어 파일 경로 ────────────────────────────────────────────────
_RUNTIME_DIR = Path(__file__).resolve().parent.parent.parent / "runtime"
PAUSE_FLAG   = _RUNTIME_DIR / "agent.pause"

# ── 종료 신호 (signal handler → wait_node 감지) ─────────────────────────
_stop_event = threading.Event()


def request_stop() -> None:
    _stop_event.set()


def build_supervisor_graph(
    get_migration_jobs,     # () -> list[MappingRule]
    get_sql_jobs,           # () -> list[SqlInfoJob]
    get_tuning_jobs,        # () -> list[SqlInfoJob]
    mig_increment_batch,    # (map_id: int) -> None
    mig_process_job,        # (job: MappingRule) -> None
    sql_increment_batch,    # (row_id: str) -> None
    sql_process_job,        # (job: SqlInfoJob) -> None
    tune_process_job,       # (job: SqlInfoJob) -> None
    logger,
):
    # ── 노드 정의 ──────────────────────────────────────────────────────────

    def supervisor_node(state: SupervisorState) -> dict:
        """DB 를 폴링하여 대기 작업을 수집한다. 종료 신호도 여기서 감지한다."""
        if _stop_event.is_set():
            logger.info("[Supervisor] 종료 신호 감지 → 루프 종료")
            return {"stop_requested": True}

        now = time.time()
        last_sql = state.get("last_sql_poll_at", 0.0)
        poll_sql  = (now - last_sql) >= SQL_POLL_INTERVAL_SEC

        logger.info(f"\n{'='*50}")
        logger.info(f"[Supervisor] Cycle {state.get('cycle', 0) + 1} 시작")

        # ① DataMigration 작업 폴링 (매 사이클)
        mig_jobs = []
        try:
            mig_jobs = get_migration_jobs()
        except Exception as exc:
            logger.error(f"[Supervisor] DataMigration 폴링 오류: {exc}")

        # ② SQL 변환 및 튜닝 작업 폴링 (60초마다)
        sql_jobs = []
        tuning_jobs = []
        if poll_sql:
            try:
                sql_jobs = get_sql_jobs()
                tuning_jobs = get_tuning_jobs()
            except Exception as exc:
                logger.error(f"[Supervisor] SQL/Tuning 폴링 오류: {exc}")

        if mig_jobs:
            logger.info(f"[Supervisor] DataMigration 대기 작업: {len(mig_jobs)}건")
        if poll_sql:
            if sql_jobs:
                logger.info(f"[Supervisor] SqlConversion 대기 작업: {len(sql_jobs)}건")
            if tuning_jobs:
                logger.info(f"[Supervisor] SqlTuning 대기 작업: {len(tuning_jobs)}건")
        
        if not mig_jobs and not sql_jobs and not tuning_jobs:
            logger.info("[Supervisor] 대기 중인 작업 없음")

        return {
            "pending_mig_jobs":    mig_jobs,
            "pending_sql_jobs":    sql_jobs,
            "pending_tuning_jobs": tuning_jobs,
            "last_sql_poll_at":    now if poll_sql else last_sql,
            "stop_requested":      False,
            "agent_outcomes":      [],
            "planner_reasoning":   "",
        }

    # ── Planner Node (Stage 1: 동적 작업 선택) ─────────────────────────────
    _planner = PlannerAgent()

    def planner_node(state: SupervisorState) -> dict:
        """LLM이 이번 사이클에 실행할 작업을 동적으로 선택한다.
        PLANNER_ENABLED=false 이면 폴링된 작업 전체를 그대로 통과시킨다.
        LLM 호출 실패 시 전체 실행으로 자동 폴백한다."""
        mig_jobs    = state.get("pending_mig_jobs",    [])
        sql_jobs    = state.get("pending_sql_jobs",    [])
        tuning_jobs = state.get("pending_tuning_jobs", [])

        if not PLANNER_ENABLED:
            logger.debug("[Planner] PLANNER_ENABLED=false → 전체 작업 통과")
            return {}   # 상태 변경 없음

        if not mig_jobs and not sql_jobs and not tuning_jobs:
            return {}

        decision = _planner.plan(mig_jobs, sql_jobs, tuning_jobs)
        return {
            "pending_mig_jobs":    decision.mig_jobs,
            "pending_sql_jobs":    decision.sql_jobs,
            "pending_tuning_jobs": decision.tuning_jobs,
            "planner_reasoning":   decision.reasoning,
        }

    def data_migration_agent(state: dict) -> dict:
        """DataMigration 작업 하나를 처리하는 에이전트 노드."""
        job = state["job"]
        logger.info(f"[DataMigrationAgent] map_id={job.map_id} 처리 시작")
        try:
            mig_increment_batch(job.map_id)
            mig_process_job(job)
        except SystemExit:
            raise
        except Exception as exc:
            logger.error(f"[DataMigrationAgent] map_id={job.map_id} 오류: {exc}")
            return {"agent_outcomes": [f"mig_{job.map_id}_fail"]}
        
        return {"agent_outcomes": [f"mig_{job.map_id}_success"]}

    def sql_conversion_agent(state: dict) -> dict:
        """MyBatis SQL 을 To-be SQL 로 변환하고 검증하는 에이전트 노드."""
        job = state["job"]
        logger.info(f"[SqlConversionAgent] {job.space_nm}.{job.sql_id} 처리 시작")
        try:
            sql_increment_batch(job.row_id)
            sql_process_job(job)
        except Exception as exc:
            logger.error(f"[SqlConversionAgent] {job.space_nm}.{job.sql_id} 오류: {exc}")
            return {"agent_outcomes": [f"sql_{job.sql_id}_fail"]}
            
        return {"agent_outcomes": [f"sql_{job.sql_id}_success"]}

    def sql_tuning_agent(state: dict) -> dict:
        """Process tuning jobs sequentially inside one supervisor cycle."""
        jobs = state.get("jobs") or [state["job"]]
        outcomes = []
        logger.info(f"[SqlTuningAgent] sequential tuning start (jobs={len(jobs)})")
        for job in jobs:
            logger.info(f"[SqlTuningAgent] {job.space_nm}.{job.sql_id} tuning start")
            try:
                sql_increment_batch(job.row_id)
                tune_process_job(job)
                outcomes.append(f"tune_{job.sql_id}_success")
            except Exception as exc:
                logger.error(f"[SqlTuningAgent] {job.space_nm}.{job.sql_id} error: {exc}")
                outcomes.append(f"tune_{job.sql_id}_fail")

        return {"agent_outcomes": outcomes}

    def wait_node(state: SupervisorState) -> dict:
        """폴링 주기만큼 대기. PAUSE_FLAG 파일이 있으면 재개 신호까지 무한 대기."""
        # ── pause 진입 로그 (최초 1회) ──────────────────────────────────────
        paused_logged = False
        while PAUSE_FLAG.exists():
            if _stop_event.is_set():
                return {"cycle": state.get("cycle", 0) + 1}
            if not paused_logged:
                logger.info("[Supervisor] ⏸  일시정지 중... (runtime/agent.pause 파일 감지)")
                paused_logged = True
            time.sleep(0.5)
        if paused_logged:
            logger.info("[Supervisor] ▶  일시정지 해제, 재개합니다.")

        # ── 일반 폴링 대기 ──────────────────────────────────────────────────
        elapsed = 0.0
        step    = 0.2
        while elapsed < DM_POLL_INTERVAL_SEC:
            if _stop_event.is_set():
                break
            if PAUSE_FLAG.exists():   # 대기 중 pause 요청 시 즉시 반응
                break
            time.sleep(step)
            elapsed += step
        return {"cycle": state.get("cycle", 0) + 1}

    # ── 라우팅 함수 ────────────────────────────────────────────────────────

    def route_after_supervisor(
        state: SupervisorState,
    ) -> list[Send] | Literal["wait", "__end__"]:
        """작업이 있으면 Send 로 fan-out 하고, 없으면 wait 로 보냅니다."""
        if state.get("stop_requested"):
            return END

        mig_jobs = state.get("pending_mig_jobs", [])
        sql_jobs = state.get("pending_sql_jobs", [])
        tuning_jobs = state.get("pending_tuning_jobs", [])

        if not mig_jobs and not sql_jobs and not tuning_jobs:
            return "wait"

        sends = []
        for job in mig_jobs:
            sends.append(Send("data_migration_agent", {"job": job}))
        for job in sql_jobs:
            sends.append(Send("sql_conversion_agent", {"job": job}))
        if tuning_jobs:
            sends.append(Send("sql_tuning_agent", {"jobs": tuning_jobs}))

        return sends

    def route_after_agent(state: dict) -> Literal["wait"]:
        """에이전트 노드가 완료된 후 wait 노드로 집결합니다."""
        return "wait"

    def route_after_wait(
        state: SupervisorState,
    ) -> Literal["supervisor", "__end__"]:
        if _stop_event.is_set() or state.get("stop_requested"):
            return END
        return "supervisor"

    # ── 그래프 조립 ────────────────────────────────────────────────────────
    #
    #  supervisor → planner → [conditional] → agents (fan-out) → wait → supervisor
    #
    workflow = StateGraph(SupervisorState)

    workflow.add_node("supervisor",           supervisor_node)
    workflow.add_node("planner",              planner_node)        # ← NEW
    workflow.add_node("data_migration_agent", data_migration_agent)
    workflow.add_node("sql_conversion_agent", sql_conversion_agent)
    workflow.add_node("sql_tuning_agent",     sql_tuning_agent)
    workflow.add_node("wait",                 wait_node)

    workflow.set_entry_point("supervisor")

    # supervisor → planner (항상)
    workflow.add_edge("supervisor", "planner")

    # planner → 조건부 분기 (기존 supervisor 조건부 엣지와 동일)
    workflow.add_conditional_edges(
        "planner",
        route_after_supervisor,          # planner가 갱신한 state 기준으로 라우팅
        {
            "data_migration_agent": "data_migration_agent",
            "sql_conversion_agent": "sql_conversion_agent",
            "sql_tuning_agent":     "sql_tuning_agent",
            "wait":                 "wait",
            END:                    END,
        }
    )

    workflow.add_conditional_edges("data_migration_agent", route_after_agent, {"wait": "wait"})
    workflow.add_conditional_edges("sql_conversion_agent", route_after_agent, {"wait": "wait"})
    workflow.add_conditional_edges("sql_tuning_agent",     route_after_agent, {"wait": "wait"})

    workflow.add_conditional_edges(
        "wait",
        route_after_wait,
        {"supervisor": "supervisor", END: END},
    )

    return workflow.compile()
