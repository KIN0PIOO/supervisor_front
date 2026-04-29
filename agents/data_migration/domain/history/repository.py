from agents.data_migration.core.logger import logger
from agents.data_migration.core.db import get_connection

def log_generated_sql(map_id: int, migration_sql: str, verification_sql: str):
    def ensure_string(val):
        if isinstance(val, list):
            return "\n".join(map(str, val))
        return str(val) if val is not None else ""

    safe_mig_sql = ensure_string(migration_sql)
    safe_v_sql = ensure_string(verification_sql)

    logger.info(f"[HistoryRepo] map_id={map_id} | 마이그레이션 SQL(DML/VERIFY) DB 기록 진행")

    query = """
        UPDATE NEXT_MIG_INFO
        SET MIG_SQL = :1, VERIFY_SQL = :2, UPD_TS = CURRENT_TIMESTAMP
        WHERE MAP_ID = :3
    """

    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, (safe_mig_sql, safe_v_sql, map_id))
            conn.commit()
    except Exception as e:
        logger.error(f"[HistoryRepo] SQL 생성 내역 기록 중 오류: {e}")

def log_business_history(map_id: int, log_type: str, log_level: str, step_name: str, status: str, message: str, retry_count: int = 0, mig_kind: str = "DB_MIG"):
    msg_str = str(message)
    if len(msg_str) > 4000:
        msg_str = msg_str[:3996] + "..."

    logger.info(f"[HistoryRepo] map_id={map_id} | Business Log 저장 -> [{step_name}][{status}] : {msg_str[:50]}")

    query = """
        INSERT INTO NEXT_MIG_LOG (
            LOG_ID, MAP_ID, MIG_KIND, LOG_TYPE, LOG_LEVEL, STEP_NAME, STATUS, MESSAGE, RETRY_COUNT
        ) VALUES (MIGRATION_LOG_SEQ.NEXTVAL, :1, :2, :3, :4, :5, :6, :7, :8)
    """

    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, (map_id, mig_kind, log_type, log_level, step_name, status, msg_str, retry_count))
            conn.commit()
    except Exception as e:
        logger.error(f"[HistoryRepo] 비즈니스 이력 기록 중 오류: {e}")
