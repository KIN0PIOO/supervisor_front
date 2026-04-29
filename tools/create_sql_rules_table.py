"""NEXT_SQL_RULES 테이블 생성 + tobe_rule_catalog.json 데이터 마이그레이션.

실행:
  python tools/create_sql_rules_table.py
"""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools._bootstrap import ROOT_DIR
from dotenv import load_dotenv
load_dotenv(ROOT_DIR / ".env")

from agents.data_migration.core.db import get_connection

DDL = """
CREATE TABLE NEXT_SQL_RULES (
    RULE_ID           VARCHAR2(100)  NOT NULL,
    GUIDANCE          VARCHAR2(4000) NOT NULL,
    EXAMPLE_BAD_SQL   CLOB,
    EXAMPLE_TUNED_SQL CLOB,
    CREATED_AT        TIMESTAMP DEFAULT SYSTIMESTAMP NOT NULL,
    UPDATED_AT        TIMESTAMP DEFAULT SYSTIMESTAMP NOT NULL,
    CONSTRAINT PK_NEXT_SQL_RULES PRIMARY KEY (RULE_ID)
)
"""

RAG_PATH = (
    ROOT_DIR / "agents" / "sql_pipeline" / "data" / "rag" / "tobe_rule_catalog.json"
)


def table_exists(cur, table_name: str) -> bool:
    cur.execute(
        "SELECT COUNT(*) FROM USER_TABLES WHERE TABLE_NAME = :1",
        (table_name.upper(),),
    )
    return cur.fetchone()[0] > 0


def main():
    rules = json.loads(RAG_PATH.read_text(encoding="utf-8")).get("rules", [])

    with get_connection() as conn:
        cur = conn.cursor()

        # ── 테이블 생성 ───────────────────────────────────────────────────────
        if table_exists(cur, "NEXT_SQL_RULES"):
            print("⚠️  NEXT_SQL_RULES 테이블이 이미 존재합니다. 데이터만 업서트합니다.")
        else:
            cur.execute(DDL)
            print("✅ NEXT_SQL_RULES 테이블 생성 완료")

        # ── 데이터 삽입 ───────────────────────────────────────────────────────
        inserted = 0
        skipped = 0
        for r in rules:
            rule_id = r.get("rule_id", "")
            guidance_lines = r.get("guidance", [])
            guidance = "\n".join(guidance_lines) if isinstance(guidance_lines, list) else str(guidance_lines)
            bad_sql = r.get("example_bad_sql", "") or ""
            tuned_sql = r.get("example_tuned_sql", "") or ""

            # 이미 존재하면 UPDATE, 없으면 INSERT
            cur.execute(
                "SELECT COUNT(*) FROM NEXT_SQL_RULES WHERE RULE_ID = :1",
                (rule_id,),
            )
            exists = cur.fetchone()[0] > 0

            if exists:
                cur.execute(
                    """UPDATE NEXT_SQL_RULES
                       SET GUIDANCE = :1, EXAMPLE_BAD_SQL = :2,
                           EXAMPLE_TUNED_SQL = :3, UPDATED_AT = SYSTIMESTAMP
                       WHERE RULE_ID = :4""",
                    (guidance, bad_sql, tuned_sql, rule_id),
                )
                skipped += 1
                print(f"  ↻ UPDATED  {rule_id}")
            else:
                cur.execute(
                    """INSERT INTO NEXT_SQL_RULES
                           (RULE_ID, GUIDANCE, EXAMPLE_BAD_SQL, EXAMPLE_TUNED_SQL)
                       VALUES (:1, :2, :3, :4)""",
                    (rule_id, guidance, bad_sql, tuned_sql),
                )
                inserted += 1
                print(f"  ✓ INSERTED {rule_id}")

        conn.commit()
        print(f"\n완료 — 삽입: {inserted}건, 업데이트: {skipped}건 (총 {len(rules)}건)")


if __name__ == "__main__":
    main()
