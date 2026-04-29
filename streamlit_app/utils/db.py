import os
import oracledb
from pathlib import Path
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(_ROOT / ".env")

oracledb.defaults.fetch_lobs = False

DB_USER = os.getenv("DB_USER", "scott")
DB_PASS = os.getenv("DB_PASS", "tiger")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "1521")
DB_SID  = os.getenv("DB_SID", "xe")
ORACLE_CLIENT_PATH = os.getenv("ORACLE_CLIENT_PATH", "")

MIG_TABLE    = os.getenv("MAPPING_RULE_TABLE", "NEXT_MIG_INFO")
MIG_DTL_TABLE = os.getenv("MAPPING_RULE_DETAIL_TABLE", "NEXT_MIG_INFO_DTL").strip()
SQL_TABLE    = os.getenv("RESULT_TABLE", "NEXT_SQL_INFO")

_thick_done = False


def get_connection():
    global _thick_done
    if ORACLE_CLIENT_PATH and os.path.exists(ORACLE_CLIENT_PATH) and not _thick_done:
        try:
            oracledb.init_oracle_client(lib_dir=ORACLE_CLIENT_PATH)
        except oracledb.ProgrammingError:
            pass
        _thick_done = True
    dsn = DB_HOST if ("/" in DB_HOST or "(" in DB_HOST) else f"{DB_HOST}:{DB_PORT}/{DB_SID}"
    conn = oracledb.connect(user=DB_USER, password=DB_PASS, dsn=dsn)
    with conn.cursor() as cur:
        cur.execute("ALTER SESSION SET NLS_DATE_FORMAT='YYYY-MM-DD HH24:MI:SS'")
    return conn


def _s(val, default="") -> str:
    if val is None:
        return default
    if hasattr(val, "read"):
        val = val.read()
    if val is None:
        return default
    if isinstance(val, bytes):
        return val.decode("utf-8", errors="ignore")
    return str(val)


def _to_dicts(cur) -> list[dict]:
    cols = [d[0] for d in cur.description]
    return [{cols[i]: _s(row[i]) for i in range(len(cols))} for row in cur.fetchall()]


# ── Mig ──────────────────────────────────────────────────────────────────────

def get_mig_jobs() -> list[dict]:
    q = f"""
        SELECT MAP_ID, MAP_TYPE, FR_TABLE, TO_TABLE,
               USE_YN, TARGET_YN, PRIORITY, STATUS,
               MIG_SQL, VERIFY_SQL,
               BATCH_CNT, ELAPSED_SECONDS, RETRY_COUNT,
               TO_CHAR(CREATED_AT) AS CREATED_AT,
               TO_CHAR(UPD_TS) AS UPD_TS
        FROM {MIG_TABLE}
        ORDER BY PRIORITY ASC, MAP_ID ASC
    """
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(q)
        return _to_dicts(cur)


def get_mig_status_summary() -> dict[str, int]:
    q = f"SELECT NVL(TO_CHAR(STATUS),'NULL'), COUNT(*) FROM {MIG_TABLE} GROUP BY STATUS"
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(q)
        return {_s(r[0]) or "NULL": r[1] for r in cur.fetchall()}


def get_mig_dtl(map_id: int) -> list[dict]:
    q = f"""
        SELECT MAP_DTL, FR_COL, TO_COL
        FROM {MIG_DTL_TABLE}
        WHERE MAP_ID = :1
        ORDER BY MAP_DTL
    """
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute(q, (map_id,))
            return _to_dicts(cur)
    except Exception:
        return []


def get_mig_logs(map_id: int) -> list[dict]:
    q = """
        SELECT LOG_ID, MIG_KIND, LOG_TYPE, LOG_LEVEL,
               STEP_NAME, STATUS, MESSAGE, RETRY_COUNT
        FROM NEXT_MIG_LOG
        WHERE MAP_ID = :1
        ORDER BY LOG_ID ASC
    """
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute(q, (map_id,))
            return _to_dicts(cur)
    except Exception:
        return []


def get_recent_fails(limit: int = 10) -> list[dict]:
    q = f"""
        SELECT * FROM (
            SELECT MAP_ID, FR_TABLE, TO_TABLE, STATUS,
                   TO_CHAR(UPD_TS) AS UPD_TS
            FROM {MIG_TABLE}
            WHERE UPPER(NVL(STATUS,'X')) = 'FAIL'
            ORDER BY UPD_TS DESC NULLS LAST
        ) WHERE ROWNUM <= {limit}
    """
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute(q)
            return _to_dicts(cur)
    except Exception:
        return []


# ── Tuning 전용 요약 ──────────────────────────────────────────────────────────

def get_tuning_status_summary() -> dict[str, int]:
    """TUNED_TEST 컬럼 기준 상태 요약 (SQL이 변환된 행만)."""
    q = f"""
        SELECT NVL(TO_CHAR(TUNED_TEST), 'NULL'), COUNT(*)
        FROM {SQL_TABLE}
        WHERE TO_SQL_TEXT IS NOT NULL
        GROUP BY TUNED_TEST
    """
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute(q)
            return {_s(r[0]) or "NULL": r[1] for r in cur.fetchall()}
    except Exception:
        return {}


# ── SQL / Tuning ──────────────────────────────────────────────────────────────

def get_sql_jobs() -> list[dict]:
    q = f"""
        SELECT ROWIDTOCHAR(ROWID) AS ROW_ID,
               TAG_KIND, SPACE_NM, SQL_ID,
               FR_SQL_TEXT, TO_SQL_TEXT, TUNED_SQL, TUNED_TEST,
               STATUS, LOG, TO_CHAR(UPD_TS) AS UPD_TS
        FROM {SQL_TABLE}
        ORDER BY UPD_TS DESC NULLS LAST
    """
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute(q)
            return _to_dicts(cur)
    except Exception:
        return []


def get_sql_status_summary() -> dict[str, int]:
    q = f"SELECT NVL(TO_CHAR(STATUS),'NULL'), COUNT(*) FROM {SQL_TABLE} GROUP BY STATUS"
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute(q)
            return {_s(r[0]) or "NULL": r[1] for r in cur.fetchall()}
    except Exception:
        return {}


def get_sql_job_full(row_id: str) -> dict | None:
    q = f"""
        SELECT ROWIDTOCHAR(ROWID) AS ROW_ID,
               TAG_KIND, SPACE_NM, SQL_ID,
               FR_SQL_TEXT, EDIT_FR_SQL, TARGET_TABLE,
               TO_SQL_TEXT, TUNED_SQL, TUNED_TEST,
               BIND_SQL, BIND_SET, TEST_SQL,
               STATUS, LOG, TO_CHAR(UPD_TS) AS UPD_TS, EDITED_YN
        FROM {SQL_TABLE}
        WHERE ROWIDTOCHAR(ROWID) = :1
    """
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute(q, (row_id,))
            row = cur.fetchone()
            if row:
                cols = [d[0] for d in cur.description]
                return {cols[i]: _s(row[i]) for i in range(len(cols))}
    except Exception:
        pass
    return None
