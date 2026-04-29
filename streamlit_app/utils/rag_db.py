"""NEXT_SQL_RULES 테이블 CRUD."""
from utils.db import get_connection, _s


def get_all_rules() -> list[dict]:
    q = """
        SELECT RULE_ID, GUIDANCE, EXAMPLE_BAD_SQL, EXAMPLE_TUNED_SQL,
               TO_CHAR(CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT,
               TO_CHAR(UPDATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS UPDATED_AT
        FROM NEXT_SQL_RULES
        ORDER BY CREATED_AT ASC
    """
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(q)
        cols = [d[0] for d in cur.description]
        return [{cols[i]: _s(row[i]) for i in range(len(cols))} for row in cur.fetchall()]


def add_rule(rule_id: str, guidance: str, bad_sql: str, tuned_sql: str = "") -> None:
    q = """
        INSERT INTO NEXT_SQL_RULES
            (RULE_ID, GUIDANCE, EXAMPLE_BAD_SQL, EXAMPLE_TUNED_SQL)
        VALUES (:1, :2, :3, :4)
    """
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(q, (rule_id, guidance, bad_sql, tuned_sql))
        conn.commit()


def update_rule(rule_id: str, guidance: str, bad_sql: str, tuned_sql: str = "") -> None:
    q = """
        UPDATE NEXT_SQL_RULES
        SET GUIDANCE = :1, EXAMPLE_BAD_SQL = :2,
            EXAMPLE_TUNED_SQL = :3, UPDATED_AT = SYSTIMESTAMP
        WHERE RULE_ID = :4
    """
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(q, (guidance, bad_sql, tuned_sql, rule_id))
        conn.commit()


def delete_rule(rule_id: str) -> bool:
    q = "DELETE FROM NEXT_SQL_RULES WHERE RULE_ID = :1"
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(q, (rule_id,))
        deleted = cur.rowcount
        conn.commit()
    return deleted > 0


def rule_id_exists(rule_id: str) -> bool:
    q = "SELECT COUNT(*) FROM NEXT_SQL_RULES WHERE RULE_ID = :1"
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(q, (rule_id,))
        return cur.fetchone()[0] > 0


def get_next_rule_id() -> str:
    """USER_RULE_NNN 형식으로 다음 ID 생성."""
    q = """
        SELECT NVL(MAX(TO_NUMBER(REGEXP_SUBSTR(RULE_ID, '\\d+$'))), 0)
        FROM NEXT_SQL_RULES
        WHERE REGEXP_LIKE(RULE_ID, '^USER_RULE_\\d+$')
    """
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(q)
        n = cur.fetchone()[0] or 0
    return f"USER_RULE_{int(n) + 1:03d}"
