from agents.data_migration.core.db import get_connection
from agents.data_migration.core.logger import logger
from agents.data_migration.agent.sql_utils import split_sql_script, clean_sql_statement

def execute_verification(sql: str) -> tuple[bool, str]:
    """양 DB의 정합성을 대조하는 검증 SQL 실행"""
    if not sql.strip():
        return True, "No verification SQL provided"

    logger.debug(f"[Verifier] 실제 검증 쿼리 실행 시작: {sql[:50]}...")

    try:
        statements = split_sql_script(sql)
        if not statements:
            return True, "No valid SQL statements found"

        last_rows = []
        with get_connection() as conn:
            cursor = conn.cursor()
            for stmt in statements:
                clean_stmt = clean_sql_statement(stmt)
                if not clean_stmt:
                    continue

                logger.debug(f"[Verifier] Executing: {clean_stmt[:70]}...")
                cursor.execute(clean_stmt)

                if cursor.description:
                    last_rows = cursor.fetchall()

            if not last_rows:
                return True, "No mismatch found (Empty ResultSet)"

            for row in last_rows:
                for col_val in row:
                    if col_val is None or str(col_val) != "0":
                        return False, f"Mismatch found (NULL or non-zero DIFF): {row}"

            return True, "All Verification Passed"

    except Exception as e:
        logger.error(f"[Verifier] 검증 쿼리 실행 에러: {str(e)}")
        return False, f"Verification Query Error: {str(e)}"
