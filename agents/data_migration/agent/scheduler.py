"""DataMigration 스케줄러.

APScheduler 없이 단순 루프로 10초 주기 폴링을 구현한다.
SupervisorAgent 에서 daemon thread 로 실행되므로 BlockingScheduler 대신
threading.Event 를 이용한 인터럽트 가능한 sleep 을 사용한다.
직접 실행(python -m agents.data_migration.agent.scheduler)도 지원한다.
"""

import threading
import time
import traceback
from apscheduler.schedulers.blocking import BlockingScheduler

from agents.data_migration.core.logger import logger
from agents.data_migration.agent.orchestrator import MigrationOrchestrator
from agents.data_migration.domain.mapping.repository import get_pending_jobs
from agents.data_migration.core.exceptions import BatchAbortError

_orchestrator = MigrationOrchestrator()
_stop_event = threading.Event()


def poll_database():
    try:
        logger.info("\n--- [DataMigration:Scheduler] DB 작업 대상 스캔 ---")

        jobs = get_pending_jobs()

        if not jobs:
            logger.info("[DataMigration:Scheduler] 현재 대기 중인 작업 대상 없음")
            return

        logger.info(f"[DataMigration:Scheduler] 처리 대상 작업 발견: {len(jobs)}건")

        for job in jobs:
            if _stop_event.is_set():
                break
            try:
                _orchestrator.process_job(job)
            except BatchAbortError as abort_err:
                logger.critical(f"[DataMigration:BATCH_ABORT] 스케줄러가 배치를 심각한 오류로 조기 중단합니다: {abort_err}")
                logger.critical("시스템 설정을 확인한 후 에이전트를 재가동하십시오.")
                import os as _os
                _os._exit(1)

    except Exception as e:
        logger.error(f"[DataMigration:Scheduler] 시스템 에러 발생: {str(e)}")
        logger.error(traceback.format_exc())


class DataMigrationScheduler:
    """Supervisor 에서 호출하는 DataMigration 스케줄러 래퍼."""

    def run(self) -> None:
        """BlockingScheduler 로 10초 주기 폴링을 시작한다."""
        logger.info("====================================")
        logger.info(" DataMigration Agent 가동")
        logger.info("====================================")
        logger.info("APScheduler 가동 시작. (10초 주기로 작업 대기열 스캔)")

        scheduler = BlockingScheduler()
        scheduler.add_job(poll_database, 'interval', seconds=10)

        try:
            scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            logger.info("[DataMigration] 에이전트가 종료되었습니다.")
        finally:
            _stop_event.set()


# 단독 실행 지원
if __name__ == "__main__":
    DataMigrationScheduler().run()
