"""공유 로거 — 모든 에이전트가 동일한 logger 인스턴스를 사용한다."""

import logging
import sys


def _setup_logger() -> logging.Logger:
    logger = logging.getLogger("migration_agent")
    if not logger.handlers:
        logger.setLevel(logging.DEBUG)
        # Windows 환경 UTF-8 인코딩 보정
        try:
            import io
            sys.stdout = io.TextIOWrapper(
                sys.stdout.detach(), encoding="utf-8", line_buffering=True
            )
        except Exception:
            pass
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(
            logging.Formatter("%(asctime)s - [%(name)s] [%(levelname)s] - %(message)s")
        )
        logger.addHandler(handler)
    return logger


logger = _setup_logger()
