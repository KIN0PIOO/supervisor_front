import oracledb
from agents.data_migration.core.db import get_connection
from agents.data_migration.core.logger import logger
from agents.data_migration.core.exceptions import DBSqlError
from agents.data_migration.agent.sql_utils import split_sql_script, clean_sql_statement

def truncate_table(table_name: str):
    """재시도 전 타겟 테이블 데이터를 초기화합니다."""
    logger.info(f"[Executor] 테이블 TRUNCATE: {table_name}")
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"TRUNCATE TABLE {table_name}")
            conn.commit()
            logger.info(f"[Executor] TRUNCATE 완료: {table_name}")
    except Exception as e:
        logger.warning(f"[Executor] TRUNCATE 실패 (무시 가능): {str(e)}")

def execute_migration(sql_script: str):
    """생성된 SQL 스크립트를 Oracle DB 엔진에 실행"""
    if not sql_script.strip():
        logger.debug("[Executor] 실행할 SQL 스크립트가 비어있습니다.")
        return

    try:
        with get_connection() as conn:
            cursor = conn.cursor()

            statements = split_sql_script(sql_script)

            for stmt in statements:
                clean_stmt = clean_sql_statement(stmt)
                if not clean_stmt:
                    continue

                is_plsql = clean_stmt.upper().startswith(('BEGIN', 'DECLARE'))

                logger.info(f"[Executor] Executing {'PL/SQL' if is_plsql else 'SQL'}: {clean_stmt[:70]}...")

                try:
                    exec_stmt = clean_stmt if not is_plsql else clean_stmt + "\n"
                    cursor.execute(exec_stmt)
                except oracledb.DatabaseError as e:
                    if "ORA-00955" in str(e):
                        logger.warning(f"[Executor] 객체가 이미 존재하여 건너뜁니다.")
                        continue
                    raise e

            conn.commit()
            logger.info(f"[Executor] All commands executed and committed successfully.")

    except Exception as e:
        logger.error(f"[Executor] SQL 실행 실패: {str(e)}")
        raise DBSqlError(f"Oracle 쿼리 실행 에러: {str(e)}")
