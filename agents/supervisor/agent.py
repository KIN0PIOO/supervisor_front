"""Supervisor Agent.

각 서브 에이전트를 LangGraph 노드(tool)로 등록하고
Supervisor 그래프를 통해 전체 수명 주기를 관리한다.

역할 분담:
  SupervisorAgent          : DB 폴링 + 라우팅 (LangGraph state machine)
  data_migration_agent 노드: MappingRule 작업 1건 처리 (tool)
  sql_pipeline_agent 노드  : SqlInfoJob 작업 1건 처리 (tool)
"""

import logging
import os
import signal

from agents.supervisor.graph import build_supervisor_graph, request_stop
from agents.supervisor.state import SupervisorState

logger = logging.getLogger("migration_agent")


class SupervisorAgent:
    """멀티 에이전트 시스템의 최상위 오케스트레이터."""

    def __init__(self) -> None:
        # 각 서브 에이전트의 처리 함수를 지연 임포트하여 순환 의존 방지
        from agents.data_migration.domain.mapping.repository import (
            get_pending_jobs as get_mig_jobs,
            increment_batch_count as mig_inc,
        )
        from agents.data_migration.agent.orchestrator import MigrationOrchestrator

        from agents.sql_pipeline.repositories.result_repository import (
            get_pending_jobs as get_sql_jobs,
            get_tuning_jobs as get_tuning_jobs_func,
            increment_batch_count as sql_inc,
        )
        from agents.sql_pipeline.agents import TobeMultiAgentCoordinator, TobeSqlGenerationAgent, SqlTuningAgent
        
        dm  = MigrationOrchestrator()
        
        # 1. SQL 변환 전용 에이전트 (튜닝 반복 횟수 0으로 설정하여 변환만 수행)
        conversion_coordinator = TobeMultiAgentCoordinator(
            generation_agent=TobeSqlGenerationAgent(),
            tuning_agent=SqlTuningAgent(max_iterations=0)
        )
        
        # 2. SQL 튜닝 전용 에이전트 처리 함수
        def tune_proc(job):
            from agents.sql_pipeline.agents import SqlTuningAgent
            from agents.sql_pipeline.workflow.state import JobExecutionState
            from agents.sql_pipeline.repositories.mapper_repository import get_all_mapping_rules
            from agents.sql_pipeline.repositories.result_repository import update_cycle_result, update_tuning_error
            from agents.sql_pipeline.core.logger import logger as sql_logger

            tuning_agent = SqlTuningAgent()
            job_key = f"{job.space_nm}.{job.sql_id}"
            
            try:
                state = JobExecutionState(
                    job=job,
                    job_key=job_key,
                    mapping_rules=get_all_mapping_rules(),
                    last_error=None
                )
                # 원본 튜닝 프로세스와 동일하게 필드 주입
                state.tobe_sql = job.to_sql_text
                state.bind_set_for_db = job.bind_set # <<-- 이 부분이 누락되었었습니다!
                
                # 튜닝 실행 (내부 RAG 및 블록 튜닝 로직 가동)
                tuning_agent.run(state)
                
                # 튜닝 결과가 없더라도(이미 최적화된 경우 등), 완료 표시를 위해 tuned_test를 설정
                final_status = state.tuned_test if state.tuned_test else "FAIL"
                
                final_log = f"TUNING COMPLETED status={final_status} job={job_key} (changed={bool(state.tuned_sql)})"
                update_cycle_result(
                    row_id=job.row_id,
                    tobe_sql=state.tobe_sql,
                    tuned_sql=state.tuned_sql if state.tuned_sql else None,
                    tuned_test=final_status, # <--- 튜닝 변화 없어도 PASS로 기록하여 완료 처리
                    bind_sql=job.bind_sql,
                    bind_set=job.bind_set,
                    test_sql=job.test_sql,
                    status=job.status, 
                    final_log=final_log
                )
                sql_logger.info(f"[TuningAgent] {job_key} 튜닝 프로세스 완료 (Status: {final_status})")
                
            except Exception as exc:
                sql_logger.error(f"[TuningAgent] {job_key} 처리 중 치명적 오류: {exc}")
                # 튜닝 단계에서 에러 발생 시 로그만 남기고 다음 주기에 재시도할 수 있게 상태 유지
                update_tuning_error(job.row_id, str(exc))

        self._graph = build_supervisor_graph(
            get_migration_jobs  = get_mig_jobs,
            get_sql_jobs        = get_sql_jobs,
            get_tuning_jobs     = get_tuning_jobs_func,
            mig_increment_batch = mig_inc,
            mig_process_job     = dm.process_job,
            sql_increment_batch = sql_inc,
            sql_process_job     = conversion_coordinator.process_job,
            tune_process_job    = tune_proc,
            logger              = logger,
        )

    def run(self) -> None:
        """SIGINT/SIGTERM 을 등록하고 Supervisor 그래프를 실행한다."""
        logger.info("============================================================")
        logger.info(" Multi-Agent Supervisor 시작 (3 Agent Parallel Mode)")
        logger.info("  ├─ Mig Agent    : 데이터 이관 및 튜닝 대상(READY) 생성")
        logger.info("  ├─ SQL Agent    : To-be SQL 변환 및 기본 검증(PASS)")
        logger.info("  └─ Tuning Agent : 튜닝 룰 적용 및 최종 검증(TUNED_TEST)")
        logger.info("============================================================")

        self._register_signal_handlers()

        initial_state: SupervisorState = {
            "pending_mig_jobs":  [],
            "pending_sql_jobs":  [],
            "pending_tuning_jobs": [],
            "last_sql_poll_at":  0.0,
            "cycle":             0,
            "stop_requested":    False,
            "agent_outcomes":    [],
        }

        try:
            self._graph.invoke(initial_state)
        except (KeyboardInterrupt, SystemExit):
            pass
        finally:
            logger.info("[Supervisor] 모든 에이전트가 종료되었습니다.")

    @staticmethod
    def _register_signal_handlers() -> None:
        signal_count = {"n": 0}

        def _handle(_signum, _frame):
            signal_count["n"] += 1
            request_stop()
            if signal_count["n"] == 1:
                try:
                    msg = "[Supervisor] Stop signal received. Finishing current job...\n"
                    os.write(2, msg.encode("utf-8", errors="ignore"))
                except OSError:
                    pass
            else:
                os._exit(130)

        signal.signal(signal.SIGINT, _handle)
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, _handle)
