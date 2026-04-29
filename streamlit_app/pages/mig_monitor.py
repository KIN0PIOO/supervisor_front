import streamlit as st
import pandas as pd
from utils.db import get_mig_jobs, get_mig_dtl, get_mig_logs

_COLS_TABLE = ["MAP_ID", "STATUS", "FR_TABLE", "TO_TABLE", "USE_YN", "TARGET_YN",
               "PRIORITY", "RETRY_COUNT", "ELAPSED_SECONDS", "UPD_TS"]


def render():
    st.title("📦 Mig Agent Monitor")

    if st.button("🔄 새로고침"):
        st.rerun()

    try:
        jobs = get_mig_jobs()
    except Exception as e:
        st.error(f"DB 연결 실패: {e}")
        return

    if not jobs:
        st.info("조회된 작업이 없습니다.")
        return

    df_all = pd.DataFrame(jobs)

    # ── 필터 ──────────────────────────────────────────────────────────────────
    with st.expander("🔍 검색 / 필터", expanded=True):
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            keyword = st.text_input("MAP_ID 검색", placeholder="예) 1")
        with c2:
            statuses = ["전체"] + sorted(df_all["STATUS"].dropna().unique().tolist())
            sel_status = st.selectbox("STATUS", statuses)
        with c3:
            use_opts = ["전체"] + sorted(df_all["USE_YN"].dropna().unique().tolist())
            sel_use = st.selectbox("USE_YN", use_opts)
        with c4:
            tgt_opts = ["전체"] + sorted(df_all["TARGET_YN"].dropna().unique().tolist())
            sel_tgt = st.selectbox("TARGET_YN", tgt_opts)

    df = df_all.copy()
    if keyword:
        df = df[df["MAP_ID"].astype(str).str.contains(keyword, case=False)]
    if sel_status != "전체":
        df = df[df["STATUS"] == sel_status]
    if sel_use != "전체":
        df = df[df["USE_YN"] == sel_use]
    if sel_tgt != "전체":
        df = df[df["TARGET_YN"] == sel_tgt]

    show_cols = [c for c in _COLS_TABLE if c in df.columns]
    st.write(f"**{len(df)}건** 조회됨")
    st.dataframe(df[show_cols], use_container_width=True, hide_index=True)

    # ── 상세 조회 ─────────────────────────────────────────────────────────────
    st.divider()
    st.subheader("작업 상세 조회")

    map_ids = df["MAP_ID"].astype(str).tolist()
    if not map_ids:
        return

    selected = st.selectbox("MAP_ID 선택", map_ids)
    if not selected:
        return

    row = next((j for j in jobs if str(j.get("MAP_ID")) == str(selected)), None)
    if not row:
        return

    map_id = int(selected)

    c1, c2 = st.columns(2)
    with c1:
        st.write(f"**FR_TABLE:** {row.get('FR_TABLE')}")
        st.write(f"**TO_TABLE:** {row.get('TO_TABLE')}")
        st.write(f"**STATUS:** {row.get('STATUS')}")
    with c2:
        st.write(f"**PRIORITY:** {row.get('PRIORITY')}")
        st.write(f"**RETRY_COUNT:** {row.get('RETRY_COUNT')}")
        st.write(f"**ELAPSED_SECONDS:** {row.get('ELAPSED_SECONDS')}s")

    tab1, tab2, tab3 = st.tabs(["MIG SQL", "VERIFY SQL", "로그"])

    with tab1:
        st.code(row.get("MIG_SQL") or "(없음)", language="sql")

    with tab2:
        st.code(row.get("VERIFY_SQL") or "(없음)", language="sql")

    with tab3:
        logs = get_mig_logs(map_id)
        if logs:
            st.dataframe(pd.DataFrame(logs), use_container_width=True, hide_index=True)
        else:
            st.info("로그 없음")

    with st.expander("컬럼 매핑 정보"):
        dtl = get_mig_dtl(map_id)
        if dtl:
            st.dataframe(pd.DataFrame(dtl), use_container_width=True, hide_index=True)
        else:
            st.info("매핑 정보 없음")
