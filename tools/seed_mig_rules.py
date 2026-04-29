"""HR DB 기반 샘플 매핑 룰 5개를 NEXT_MIG_INFO / NEXT_MIG_INFO_DTL에 삽입합니다.

실행:
  python tools/seed_mig_rules.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools._bootstrap import ROOT_DIR  # noqa
from dotenv import load_dotenv
load_dotenv(ROOT_DIR / ".env")

from agents.data_migration.core.db import get_connection

# ── 매핑 룰 정의 ─────────────────────────────────────────────────────────────
#
# (map_type, fr_table, to_table, priority, columns: [(fr_col, to_col), ...])
#
RULES = [
    # 1. Simple: DEPARTMENTS → TGT_DEPT
    (
        "SIMPLE",
        "DEPARTMENTS",
        "TGT_DEPT",
        10,
        [
            ("DEPARTMENT_ID",   "DEPT_ID"),
            ("DEPARTMENT_NAME", "DEPT_NM"),
            ("MANAGER_ID",      "MGR_ID"),
        ],
    ),
    # 2. Simple: JOBS → TGT_JOB
    (
        "SIMPLE",
        "JOBS",
        "TGT_JOB",
        20,
        [
            ("JOB_ID",      "JOB_CD"),
            ("JOB_TITLE",   "JOB_NM"),
            ("MIN_SALARY",  "SAL_MIN"),
            ("MAX_SALARY",  "SAL_MAX"),
        ],
    ),
    # 3. Simple: LOCATIONS → TGT_LOCATION
    (
        "SIMPLE",
        "LOCATIONS",
        "TGT_LOCATION",
        30,
        [
            ("LOCATION_ID",    "LOC_ID"),
            ("CITY",           "CITY_NM"),
            ("STATE_PROVINCE", "STATE_NM"),
            ("COUNTRY_ID",     "CNTRY_CD"),
        ],
    ),
    # 4. Complex: EMPLOYEES JOIN DEPARTMENTS → TGT_EMP_DEPT
    (
        "COMPLEX",
        "EMPLOYEES JOIN DEPARTMENTS ON EMPLOYEES.DEPARTMENT_ID = DEPARTMENTS.DEPARTMENT_ID",
        "TGT_EMP_DEPT",
        40,
        [
            ("EMPLOYEES.EMPLOYEE_ID",      "EMP_ID"),
            ("EMPLOYEES.FIRST_NAME",       "FIRST_NM"),
            ("EMPLOYEES.LAST_NAME",        "LAST_NM"),
            ("DEPARTMENTS.DEPARTMENT_NAME","DEPT_NM"),
            ("EMPLOYEES.SALARY",           "SAL_AMT"),
        ],
    ),
    # 5. Complex: EMPLOYEES JOIN JOBS → TGT_EMP_JOB
    (
        "COMPLEX",
        "EMPLOYEES JOIN JOBS ON EMPLOYEES.JOB_ID = JOBS.JOB_ID",
        "TGT_EMP_JOB",
        50,
        [
            ("EMPLOYEES.EMPLOYEE_ID", "EMP_ID"),
            ("EMPLOYEES.FIRST_NAME",  "FIRST_NM"),
            ("EMPLOYEES.LAST_NAME",   "LAST_NM"),
            ("JOBS.JOB_TITLE",        "JOB_NM"),
            ("EMPLOYEES.SALARY",      "CURR_SAL"),
            ("JOBS.MIN_SALARY",       "SAL_MIN"),
            ("JOBS.MAX_SALARY",       "SAL_MAX"),
        ],
    ),
]


def main():
    with get_connection() as conn:
        cur = conn.cursor()

        # MAP_ID / MAP_DTL 시작값 계산 (기존 데이터와 충돌 방지)
        cur.execute("SELECT NVL(MAX(MAP_ID), 0) FROM NEXT_MIG_INFO")
        base_id = max(cur.fetchone()[0], 99)

        cur.execute("SELECT NVL(MAX(MAP_DTL), 0) FROM NEXT_MIG_INFO_DTL")
        base_dtl = cur.fetchone()[0]

        print(f"MAP_ID 시작: {base_id + 1}, MAP_DTL 시작: {base_dtl + 1}")

        dtl_counter = base_dtl

        for i, (map_type, fr_table, to_table, priority, cols) in enumerate(RULES, start=1):
            map_id = base_id + i

            # NEXT_MIG_INFO 삽입
            cur.execute(
                """
                INSERT INTO NEXT_MIG_INFO
                    (MAP_ID, MAP_TYPE, FR_TABLE, TO_TABLE,
                     USE_YN, TARGET_YN, PRIORITY, STATUS,
                     CREATED_AT, UPD_TS)
                VALUES
                    (:1, :2, :3, :4,
                     'Y', 'Y', :5, NULL,
                     SYSDATE, SYSDATE)
                """,
                (map_id, map_type, fr_table, to_table, priority),
            )

            # NEXT_MIG_INFO_DTL 삽입 (MAP_DTL은 전역 시퀀스)
            for fr_col, to_col in cols:
                dtl_counter += 1
                cur.execute(
                    """
                    INSERT INTO NEXT_MIG_INFO_DTL
                        (MAP_DTL, MAP_ID, FR_COL, TO_COL)
                    VALUES
                        (:1, :2, :3, :4)
                    """,
                    (dtl_counter, map_id, fr_col, to_col),
                )

            print(f"  ✓ MAP_ID={map_id} | {map_type:<8} | {fr_table.split()[0]:<11} → {to_table} ({len(cols)}컬럼)")

        conn.commit()
        print("\n✅ 5개 매핑 룰 삽입 완료")


if __name__ == "__main__":
    main()
