"""NEXT_SQL_INFO ?? ??/?? ?? repository."""

from agents.sql_pipeline.core.logger import logger
from agents.sql_pipeline.domain.models import SqlInfoJob
from agents.sql_pipeline.services.db_runtime import get_connection, get_result_table, split_table_owner_and_name

_COLUMN_LENGTH_CACHE: dict[str, dict[str, int]] = {}
_AVAILABLE_COLUMNS_CACHE: dict[str, set[str]] = {}
_CORRECT_COLUMN_MAP = {
    "TOBE": "TOBE_CORRECT_SQL",
    "BIND": "BIND_CORRECT_SQL",
    "TEST": "TEST_CORRECT_SQL",
}
_LEGACY_CORRECT_COLUMN = "CORRECT_SQL"


def _to_text(value, default: str = "") -> str:
    if value is None:
        return default
    if hasattr(value, "read"):
        value = value.read()
    if value is None:
        return default
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="ignore")
    return str(value)


def _to_optional_text(value) -> str | None:
    if value is None:
        return None
    return _to_text(value)


def _get_column_data_lengths(table: str) -> dict[str, int]:
    owner, normalized_table = split_table_owner_and_name(table)
    cache_key = f"{owner or ''}.{normalized_table}"
    if cache_key in _COLUMN_LENGTH_CACHE:
        return _COLUMN_LENGTH_CACHE[cache_key]

    if owner:
        query = """
            SELECT COLUMN_NAME, DATA_TYPE, DATA_LENGTH
            FROM ALL_TAB_COLUMNS
            WHERE OWNER = :1
              AND TABLE_NAME = :2
        """
        params = [owner, normalized_table]
    else:
        query = """
            SELECT COLUMN_NAME, DATA_TYPE, DATA_LENGTH
            FROM USER_TAB_COLUMNS
            WHERE TABLE_NAME = :1
        """
        params = [normalized_table]
    lengths: dict[str, int] = {}
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        for col_name, data_type, data_length in cursor.fetchall():
            col = _to_text(col_name).upper()
            dtype = _to_text(data_type).upper()
            if "CLOB" in dtype:
                continue
            try:
                lengths[col] = int(data_length)
            except Exception:
                continue

    _COLUMN_LENGTH_CACHE[cache_key] = lengths
    return lengths


def _get_available_columns(table: str) -> set[str]:
    owner, normalized_table = split_table_owner_and_name(table)
    cache_key = f"{owner or ''}.{normalized_table}"
    if cache_key in _AVAILABLE_COLUMNS_CACHE:
        return _AVAILABLE_COLUMNS_CACHE[cache_key]

    if owner:
        query = """
            SELECT COLUMN_NAME
            FROM ALL_TAB_COLUMNS
            WHERE OWNER = :1
              AND TABLE_NAME = :2
        """
        params = [owner, normalized_table]
    else:
        query = """
            SELECT COLUMN_NAME
            FROM USER_TAB_COLUMNS
            WHERE TABLE_NAME = :1
        """
        params = [normalized_table]
    columns: set[str] = set()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        for (col_name,) in cursor.fetchall():
            columns.add(_to_text(col_name).upper())

    _AVAILABLE_COLUMNS_CACHE[cache_key] = columns
    return columns


def _can_select_column(table: str, column_name: str) -> bool:
    query = f"SELECT {column_name} FROM {table} WHERE 1 = 0"
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query)
        return True
    except Exception:
        return False


def _row_to_sql_info_job(row) -> SqlInfoJob:
    return SqlInfoJob(
        row_id=row[0],
        tag_kind=_to_text(row[1]),
        space_nm=_to_text(row[2]),
        sql_id=_to_text(row[3]),
        fr_sql_text=_to_text(row[4]),
        target_table=_to_optional_text(row[5]),
        edit_fr_sql=_to_optional_text(row[6]),
        to_sql_text=_to_optional_text(row[7]),
        tuned_sql=_to_optional_text(row[8]),
        tuned_test=_to_optional_text(row[9]),
        bind_sql=_to_optional_text(row[10]),
        bind_set=_to_optional_text(row[11]),
        test_sql=_to_optional_text(row[12]),
        status=_to_optional_text(row[13]),
        log_text=_to_optional_text(row[14]),
        upd_ts=row[15],
        edited_yn=_to_optional_text(row[16]),
        tobe_correct_sql=_to_optional_text(row[17]) if len(row) > 17 else None,
        bind_correct_sql=_to_optional_text(row[18]) if len(row) > 18 else None,
        test_correct_sql=_to_optional_text(row[19]) if len(row) > 19 else None,
    )


def get_pending_jobs() -> list[SqlInfoJob]:
    table = get_result_table()
    available_columns = _get_available_columns(table)
    select_correct_cols = ", ".join(
        column
        if column in available_columns
        else f"CAST(NULL AS VARCHAR2(4000)) AS {column}"
        for column in ("TOBE_CORRECT_SQL", "BIND_CORRECT_SQL", "TEST_CORRECT_SQL")
    )
    tuned_sql_column = "TUNED_SQL" if "TUNED_SQL" in available_columns else "CAST(NULL AS VARCHAR2(4000)) AS TUNED_SQL"
    tuned_test_column = "TUNED_TEST" if "TUNED_TEST" in available_columns else "CAST(NULL AS VARCHAR2(4000)) AS TUNED_TEST"
    tuning_job_exclusion_clause = (
        "AND NOT (UPPER(TRIM(STATUS)) = 'PASS' AND TO_SQL_TEXT IS NOT NULL AND UPPER(TRIM(TUNED_TEST)) IN ('READY', 'FAIL'))"
        if "TUNED_TEST" in available_columns
        else ""
    )

    query = f"""
        SELECT ROWIDTOCHAR(ROWID) AS RID,
               TAG_KIND, SPACE_NM, SQL_ID, FR_SQL_TEXT, TARGET_TABLE, EDIT_FR_SQL,
               TO_SQL_TEXT, {tuned_sql_column}, {tuned_test_column}, BIND_SQL, BIND_SET, TEST_SQL, STATUS, LOG,
               UPD_TS, EDITED_YN, {select_correct_cols}
        FROM {table}
        WHERE (UPPER(TRIM(STATUS)) IN ('FAIL', 'READY', 'PENDING', 'SKIP') OR STATUS IS NULL)
          {tuning_job_exclusion_clause}
        ORDER BY UPD_TS NULLS FIRST, TO_CHAR(SPACE_NM), TO_CHAR(SQL_ID)
    """

    jobs: list[SqlInfoJob] = []
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query)
            for row in cursor.fetchall():
                jobs.append(_row_to_sql_info_job(row))
    except Exception as e:
        logger.error(f"[Repo] SqlPipeline 대기 작업 조회 중 오류: {e}")
    return jobs

def get_tuning_jobs() -> list:
    """Return tuning jobs with TUNED_TEST READY/FAIL under the retry limit."""
    table = get_result_table()
    available_columns = _get_available_columns(table)
    if "TUNED_TEST" not in available_columns:
        return []

    select_correct_cols = ", ".join(
        column
        if column in available_columns
        else f"CAST(NULL AS VARCHAR2(4000)) AS {column}"
        for column in ("TOBE_CORRECT_SQL", "BIND_CORRECT_SQL", "TEST_CORRECT_SQL")
    )
    tuned_sql_column = "TUNED_SQL" if "TUNED_SQL" in available_columns else "CAST(NULL AS VARCHAR2(4000)) AS TUNED_SQL"
    batch_limit_clause = "AND NVL(BATCH_CNT, 0) < 30" if "BATCH_CNT" in available_columns else ""

    query = f"""
        SELECT ROWIDTOCHAR(ROWID) AS RID,
               TAG_KIND, SPACE_NM, SQL_ID, FR_SQL_TEXT, TARGET_TABLE, EDIT_FR_SQL,
               TO_SQL_TEXT, {tuned_sql_column}, TUNED_TEST, BIND_SQL, BIND_SET, TEST_SQL, STATUS, LOG,
               UPD_TS, EDITED_YN, {select_correct_cols}
        FROM {table}
        WHERE UPPER(TRIM(TUNED_TEST)) IN ('READY', 'FAIL')
          AND TO_SQL_TEXT IS NOT NULL
          AND UPPER(TRIM(STATUS)) = 'PASS'
          {batch_limit_clause}
        ORDER BY UPD_TS NULLS FIRST, TO_CHAR(SPACE_NM), TO_CHAR(SQL_ID)
    """

    jobs = []
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query)
            rows = cursor.fetchall()
            if rows:
                logger.info(f"[Repo] SqlTuning pending jobs found: {len(rows)}")

            for row in rows:
                jobs.append(_row_to_sql_info_job(row))
    except Exception as e:
        logger.error(f"[Repo] SqlTuning pending job lookup failed: {e}")
    return jobs


def update_tuning_error(row_id: str, error_msg: str) -> None:
    """Record a tuning error and mark the row as retryable FAIL."""
    table = get_result_table()
    available_columns = _get_available_columns(table)
    tuned_test_clause = "TUNED_TEST = 'FAIL'," if "TUNED_TEST" in available_columns else ""
    query = f"""
        UPDATE {table}
        SET {tuned_test_clause}
            LOG = SUBSTR(NVL(LOG, '') || CHR(10) || '[TUNING_ERROR] ' || :err, 1, 4000),
            UPD_TS = SYSDATE
        WHERE ROWID = CHARTOROWID(:rid)
    """
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, {"err": error_msg, "rid": row_id})
            conn.commit()
    except Exception as e:
        logger.error(f"[Repo] Tuning error update failed: {e}")


def update_job_skip(row_id: str, reason: str) -> None:
    table = get_result_table()
    payload = _fit_payload_to_column_limits(
        table=table,
        values={
            "STATUS": "SKIP",
            "LOG": f"SKIP reason={reason}",
        },
    )
    query = f"""
        UPDATE {table}
        SET STATUS = :1,
            LOG = :2,
            UPD_TS = CURRENT_TIMESTAMP
        WHERE ROWID = CHARTOROWID(:3)
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, [payload["STATUS"], payload["LOG"], row_id])
        conn.commit()


def reset_tuning_state(row_id: str) -> None:
    table = get_result_table()
    available_columns = _get_available_columns(table)
    set_clauses = ["UPD_TS = CURRENT_TIMESTAMP"]
    if "TUNED_SQL" in available_columns:
        set_clauses.append("TUNED_SQL = NULL")
    if "TUNED_TEST" in available_columns:
        set_clauses.append("TUNED_TEST = NULL")
    if "BLOCK_RAG_CONTENT" in available_columns:
        set_clauses.append("BLOCK_RAG_CONTENT = NULL")

    if len(set_clauses) == 1:
        return

    query = f"""
        UPDATE {table}
        SET {", ".join(set_clauses)}
        WHERE ROWID = CHARTOROWID(:1)
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, [row_id])
        conn.commit()

def increment_batch_count(row_id: str) -> None:
    table = get_result_table()
    lengths = _get_column_data_lengths(table)
    if "BATCH_CNT" in lengths:
        query = f"""
            UPDATE {table}
            SET BATCH_CNT = NVL(BATCH_CNT, 0) + 1,
                UPD_TS = CURRENT_TIMESTAMP
            WHERE ROWID = CHARTOROWID(:1)
        """
    else:
        query = f"""
            UPDATE {table}
            SET UPD_TS = CURRENT_TIMESTAMP
            WHERE ROWID = CHARTOROWID(:1)
        """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, [row_id])
        conn.commit()


def update_block_rag_content(row_id: str, block_rag_content: str) -> None:
    table = get_result_table()
    available_columns = _get_available_columns(table)
    if "BLOCK_RAG_CONTENT" not in available_columns:
        return

    payload = _fit_payload_to_column_limits(
        table=table,
        values={"BLOCK_RAG_CONTENT": block_rag_content},
    )
    query = f"""
        UPDATE {table}
        SET BLOCK_RAG_CONTENT = :1,
            UPD_TS = CURRENT_TIMESTAMP
        WHERE ROWID = CHARTOROWID(:2)
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, [payload["BLOCK_RAG_CONTENT"], row_id])
        conn.commit()


def update_cycle_result(
    row_id: str,
    tobe_sql: str,
    tuned_sql: str | None,
    tuned_test: str | None,
    bind_sql: str,
    bind_set: str | None,
    test_sql: str,
    status: str,
    final_log: str,
):
    table = get_result_table()
    available_columns = _get_available_columns(table)
    payload = _fit_payload_to_column_limits(
        table=table,
        values={
            "TO_SQL_TEXT": tobe_sql,
            "TUNED_SQL": tuned_sql if "TUNED_SQL" in available_columns else None,
            "TUNED_TEST": tuned_test if "TUNED_TEST" in available_columns else None,
            "BIND_SQL": bind_sql,
            "BIND_SET": bind_set,
            "TEST_SQL": test_sql,
            "STATUS": status,
            "LOG": final_log,
        },
    )
    set_clauses = ["TO_SQL_TEXT = :1"]
    params: list[str | None] = [payload["TO_SQL_TEXT"]]
    if "TUNED_SQL" in available_columns:
        set_clauses.append("TUNED_SQL = :2")
        params.append(payload["TUNED_SQL"])
        next_index = 3
    else:
        next_index = 2
    if "TUNED_TEST" in available_columns:
        set_clauses.append(f"TUNED_TEST = :{next_index}")
        params.append(payload["TUNED_TEST"])
        next_index += 1
    set_clauses.extend(
        [
            f"BIND_SQL = :{next_index}",
            f"BIND_SET = :{next_index + 1}",
            f"TEST_SQL = :{next_index + 2}",
            f"STATUS = :{next_index + 3}",
            f"LOG = :{next_index + 4}",
            "UPD_TS = CURRENT_TIMESTAMP",
        ]
    )
    params.extend(
        [
            payload["BIND_SQL"],
            payload["BIND_SET"],
            payload["TEST_SQL"],
            payload["STATUS"],
            payload["LOG"],
            row_id,
        ]
    )
    query = f"""
        UPDATE {table}
        SET {", ".join(set_clauses)}
        WHERE ROWID = CHARTOROWID(:{next_index + 5})
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        conn.commit()


def get_feedback_corpus_rows(correct_kind: str, limit: int = 2000) -> list[dict[str, str]]:
    table = get_result_table()
    safe_limit = max(1, min(limit, 20000))
    normalized_kind = (correct_kind or "").strip().upper()
    preferred_correct_column = _CORRECT_COLUMN_MAP.get(normalized_kind)
    if not preferred_correct_column:
        raise ValueError(f"Unsupported correct SQL kind: {correct_kind}")

    available_columns = _get_available_columns(table)
    if preferred_correct_column.upper() in available_columns:
        correct_column = preferred_correct_column
    elif _LEGACY_CORRECT_COLUMN in available_columns:
        correct_column = _LEGACY_CORRECT_COLUMN
    else:
        return []

    if not _can_select_column(table, correct_column):
        if correct_column != _LEGACY_CORRECT_COLUMN and _LEGACY_CORRECT_COLUMN in available_columns:
            if _can_select_column(table, _LEGACY_CORRECT_COLUMN):
                correct_column = _LEGACY_CORRECT_COLUMN
            else:
                return []
        else:
            return []

    query = f"""
        SELECT ROWIDTOCHAR(ROWID) AS RID,
               TO_CHAR(SPACE_NM),
               TO_CHAR(SQL_ID),
               FR_SQL_TEXT,
               EDIT_FR_SQL,
               TO_SQL_TEXT,
               CORRECT_SQL,
               EDITED_YN,
               UPD_TS
        FROM (
            SELECT ROWIDTOCHAR(ROWID) AS RID,
                   SPACE_NM, SQL_ID, FR_SQL_TEXT, EDIT_FR_SQL, TO_SQL_TEXT,
                   {correct_column} AS CORRECT_SQL, EDITED_YN, UPD_TS
            FROM {table}
            WHERE (EDITED_YN = 'Y' OR {correct_column} IS NOT NULL)
              AND {correct_column} IS NOT NULL
            ORDER BY UPD_TS DESC
        )
        WHERE ROWNUM <= {safe_limit}
    """

    rows: list[dict[str, str]] = []
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query)
        for row in cursor.fetchall():
            rows.append(
                {
                    "row_id": _to_text(row[0]),
                    "space_nm": _to_text(row[1]),
                    "sql_id": _to_text(row[2]),
                    "fr_sql_text": _to_text(row[3]),
                    "edit_fr_sql": _to_optional_text(row[4]) or "",
                    "to_sql_text": _to_optional_text(row[5]) or "",
                    "correct_sql": _to_text(row[6]),
                    "correct_kind": normalized_kind,
                    "edited_yn": _to_text(row[7]),
                    "upd_ts": _to_text(row[8]),
                }
            )
    return rows


def _fit_payload_to_column_limits(
    table: str,
    values: dict[str, str | None],
) -> dict[str, str | None]:
    lengths = _get_column_data_lengths(table)
    fitted: dict[str, str | None] = {}
    for column, value in values.items():
        if value is None:
            fitted[column] = None
            continue
        limit = lengths.get(column.upper())
        text = _to_text(value, default="")
        fitted[column] = _truncate_utf8_by_bytes(text, limit) if limit else text
    return fitted


def _truncate_utf8_by_bytes(text: str, byte_limit: int) -> str:
    if byte_limit <= 0:
        return ""
    encoded = text.encode("utf-8", errors="ignore")
    if len(encoded) <= byte_limit:
        return text
    return encoded[:byte_limit].decode("utf-8", errors="ignore")
