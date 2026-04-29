"""SQL 파이프라인 배치 스케줄러.

APScheduler 로 1분 주기 폴링을 담당한다.
SupervisorAgent 에서 daemon thread 로 호출된다.
"""

import logging
import os
import signal
import traceback
from datetime import datetime

from apscheduler.schedulers.blocking import BlockingScheduler

from agents.sql_pipeline.agents import TobeMultiAgentCoordinator
from agents.sql_pipeline.core.logger import logger
from agents.sql_pipeline.core.runtime import clear_stop, is_stop_requested, request_stop
from agents.sql_pipeline.repositories.result_repository import get_pending_jobs, increment_batch_count


class _SkipMaxInstancesLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return "maximum number of running instances reached" not in record.getMessage().lower()


class MigrationBatchScheduler:
    """SQL 변환 + 튜닝 배치 스케줄러."""

    def __init__(self, coordinator: TobeMultiAgentCoordinator | None = None) -> None:
        self.coordinator = coordinator or TobeMultiAgentCoordinator()

    def process_job(self, job) -> None:
        self.coordinator.process_job(job)

    def poll_database(self) -> None:
        try:
            if is_stop_requested():
                logger.info("[SqlPipeline] Stop requested. Skipping polling cycle.")
                return

            logger.info("\n--- [SqlPipeline:Scheduler] Polling NEXT_SQL_INFO for pending jobs ---")
            jobs = get_pending_jobs()
            if not jobs:
                logger.info("[SqlPipeline:Scheduler] No pending jobs found.")
                return

            logger.info(f"[SqlPipeline:Scheduler] Found {len(jobs)} pending job(s).")

            for job in jobs:
                if is_stop_requested():
                    logger.info("[SqlPipeline:Scheduler] Stop requested. Aborting remaining jobs.")
                    break
                increment_batch_count(job.row_id)
                self.process_job(job)
        except Exception as exc:
            logger.error(f"[SqlPipeline:Scheduler] Unexpected error while polling database: {exc}")
            logger.error(traceback.format_exc())

    def run(self) -> None:
        logger.info("====================================")
        logger.info(" Oracle SQL Migration Main Agent ")
        logger.info("====================================")

        self._attach_scheduler_log_filters()
        clear_stop()
        scheduler = BlockingScheduler()
        scheduler.add_job(
            self.poll_database,
            "interval",
            minutes=1,
            next_run_time=datetime.now(),
            id="poll_database",
            max_instances=1,
            coalesce=True,
        )

        logger.info("APScheduler started. Polling Oracle every 1 minute.")
        logger.info("Press Ctrl+C to stop.")

        signal_count = {"count": 0}

        def _safe_signal_print(message: str) -> None:
            try:
                os.write(2, (message + "\n").encode("utf-8", errors="ignore"))
            except Exception:
                pass

        def _handle_stop_signal(signum, _frame):
            signal_count["count"] += 1
            request_stop()
            if signal_count["count"] == 1:
                _safe_signal_print(f"Received signal {signum}. Stopping scheduler (wait=False).")
                _safe_signal_print("If shutdown hangs, press Ctrl+C again to force exit.")
                try:
                    scheduler.shutdown(wait=False)
                except Exception:
                    pass
                return
            _safe_signal_print("Forced termination requested.")
            os._exit(130)

        signal.signal(signal.SIGINT, _handle_stop_signal)
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, _handle_stop_signal)

        try:
            scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            logger.info("SqlPipeline agent stopped gracefully.")
        finally:
            request_stop()

    @staticmethod
    def _attach_scheduler_log_filters() -> None:
        skip_filter = _SkipMaxInstancesLogFilter()
        for logger_name in ("apscheduler", "apscheduler.scheduler", "apscheduler.executors.default"):
            target = logging.getLogger(logger_name)
            target.addFilter(skip_filter)
            for handler in target.handlers:
                handler.addFilter(skip_filter)
        for handler in logging.getLogger().handlers:
            handler.addFilter(skip_filter)


# 단독 실행 지원
if __name__ == "__main__":
    MigrationBatchScheduler().run()
