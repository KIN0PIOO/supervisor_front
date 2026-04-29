import streamlit as st
import pandas as pd
from utils.db import get_mig_jobs, get_mig_logs, get_mig_dtl, get_sql_job_full


def render():
    st.title("🔎 Job Detail")

    tab_mig, tab_sql = st.tabs(["Mig Job", "SQL Job"])

    # ── Mig Job 상세 ──────────────────────────────────────────────────────────
    with tab_mig:
        try:
            jobs = get_mig_jobs()
        except Exception as e:
            st.error(f"DB 연결 실패: {e}")
            return

        if not jobs:
            st.info("데이터 없음")
            return

        df = pd.DataFrame(jobs)
        labels = [f"MAP_ID={r['MAP_ID']} | {r['FR_TABLE']} → {r['TO_TABLE']} | {r['STATUS']}"
                  for _, r in df.iterrows()]
        idx = st.selectbox("Mig Job 선택", range(len(labels)), format_func=lambda i: labels[i],
                           key="mig_sel")

        row = jobs[idx]
        map_id = int(row["MAP_ID"])

        # 기본 정보
        st.subheader("기본 정보")
        c1, c2, c3 = st.columns(3)
        with c1:
            st.metric("MAP_ID", row["MAP_ID"])
            st.write(f"**FR_TABLE:** {row.get('FR_TABLE')}")
            st.write(f"**TO_TABLE:** {row.get('TO_TABLE')}")
        with c2:
            st.metric("STATUS", row.get("STATUS") or "-")
            st.write(f"**PRIORITY:** {row.get('PRIORITY')}")
            st.write(f"**MAP_TYPE:** {row.get('MAP_TYPE')}")
        with c3:
            st.metric("ELAPSED", f"{row.get('ELAPSED_SECONDS') or 0}s")
            st.write(f"**RETRY_COUNT:** {row.get('RETRY_COUNT')}")
            st.write(f"**BATCH_CNT:** {row.get('BATCH_CNT')}")

        st.divider()

        # SQL 흐름
        st.subheader("SQL 전체 흐름")
        t1, t2 = st.tabs(["MIG_SQL", "VERIFY_SQL"])
        with t1:
            st.code(row.get("MIG_SQL") or "(없음)", language="sql")
        with t2:
            st.code(row.get("VERIFY_SQL") or "(없음)", language="sql")

        # 컬럼 매핑
        with st.expander("컬럼 매핑 (NEXT_MIG_INFO_DTL)"):
            dtl = get_mig_dtl(map_id)
            st.dataframe(pd.DataFrame(dtl) if dtl else pd.DataFrame(), use_container_width=True)

        # 로그
        st.subheader("실행 로그")
        logs = get_mig_logs(map_id)
        if logs:
            st.dataframe(pd.DataFrame(logs), use_container_width=True, hide_index=True)
        else:
            st.info("로그 없음")

    # ── SQL Job 상세 ──────────────────────────────────────────────────────────
    with tab_sql:
        row_id_input = st.text_input("ROW_ID 입력 (ROWIDTOCHAR)", placeholder="예) AAABBBCCCDDDEEEF")

        if not row_id_input:
            st.info("ROW_ID를 입력하면 SQL Job 상세를 조회합니다.")
            return

        job = get_sql_job_full(row_id_input.strip())
        if not job:
            st.warning("해당 ROW_ID의 데이터를 찾을 수 없습니다.")
            return

        c1, c2, c3 = st.columns(3)
        with c1:
            st.write(f"**SQL_ID:** {job.get('SQL_ID')}")
            st.write(f"**SPACE_NM:** {job.get('SPACE_NM')}")
        with c2:
            st.metric("STATUS", job.get("STATUS") or "-")
            st.write(f"**EDITED_YN:** {job.get('EDITED_YN')}")
        with c3:
            st.write(f"**TARGET_TABLE:** {job.get('TARGET_TABLE')}")
            st.write(f"**UPD_TS:** {job.get('UPD_TS')}")

        st.divider()
        st.subheader("SQL 전체 흐름")
        t1, t2, t3 = st.tabs(["AS-IS SQL", "TO-BE SQL", "TUNED SQL"])
        with t1:
            st.code(job.get("FR_SQL_TEXT") or "(없음)", language="sql")
        with t2:
            st.code(job.get("TO_SQL_TEXT") or "(없음)", language="sql")
        with t3:
            st.code(job.get("TUNED_SQL") or "(없음)", language="sql")

        log = job.get("LOG") or ""
        if log:
            with st.expander("LOG"):
                st.text(log)
