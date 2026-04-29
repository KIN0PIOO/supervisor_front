import time
import os
from agents.data_migration.core.logger import logger
from agents.data_migration.agent.graph import migration_graph, BIZ_MAX_ATTEMPTS
from agents.data_migration.domain.mapping.repository import increment_batch_count
from agents.data_migration.core.exceptions import BatchAbortError

class MigrationOrchestrator:
    def __init__(self):
        self.mig_kind = os.getenv("MIG_KIND", "DB_MIG")

    def process_job(self, NEXT_SQL_INFO):
        logger.info(f"\n==========================================")
        logger.info(f"[JOB_START] 대상 작업(map_id={NEXT_SQL_INFO.map_id}) 프로세스 시작 (LangGraph)")

        increment_batch_count(NEXT_SQL_INFO.map_id)

        initial_state = {
            "next_sql_info": NEXT_SQL_INFO,
            "source_ddl": None,
            "target_ddl": None,
            "last_error": None,
            "last_sql": None,
            "db_attempts": 1,
            "max_attempts": BIZ_MAX_ATTEMPTS,
            "llm_retry_count": 0,
            "current_ddl_sql": None,
            "current_migration_sql": None,
            "current_v_sql": None,
            "error_type": None,
            "status": "RUNNING",
            "elapsed_time": 0,
            "job_start_time": time.time()
        }

        try:
            logger.info(f"[Orchestrator] map_id={NEXT_SQL_INFO.map_id} | 시작")
            final_state = migration_graph.invoke(initial_state)

            status = final_state.get("status", "UNKNOWN")
            elapsed = final_state.get("elapsed_time", 0)
            logger.info(f"[JOB_DONE] map_id={NEXT_SQL_INFO.map_id} | 최종 상태: {status} | 소요시간: {elapsed}초")

        except BatchAbortError as abort_err:
            logger.critical(f"[Orchestrator] map_id={NEXT_SQL_INFO.map_id} | 치명적 배치 중단 요청 접수: {abort_err}")
            raise abort_err
        except Exception as e:
            logger.error(f"[Orchestrator] map_id={NEXT_SQL_INFO.map_id} | 치명적 크래시 발생: {str(e)}", exc_info=True)

            from agents.data_migration.domain.mapping.repository import update_job_status
            update_job_status(NEXT_SQL_INFO.map_id, "FAIL", 0, 0)

            logger.warning(f"[Orchestrator] map_id={NEXT_SQL_INFO.map_id} | 크래시로 인한 강제 FAIL 처리 완료.")
