import streamlit as st
import pandas as pd
from utils.db import get_sql_jobs

_COLS_TABLE = ["ROW_ID", "SQL_ID", "SPACE_NM", "TAG_KIND", "STATUS", "UPD_TS"]


def render():
    st.title("🔄 SQL Agent Monitor")

    if st.button("🔄 새로고침"):
        st.rerun()

    try:
        jobs = get_sql_jobs()
    except Exception as e:
        st.error(f"DB 연결 실패: {e}")
        return

    if not jobs:
        st.info("조회된 작업이 없습니다.")
        return

    df_all = pd.DataFrame(jobs)

    # ── 필터 ──────────────────────────────────────────────────────────────────
    with st.expander("🔍 검색 / 필터", expanded=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            keyword = st.text_input("SQL_ID 검색", placeholder="예) SEL_001")
        with c2:
            statuses = ["전체"] + sorted(df_all["STATUS"].dropna().unique().tolist())
            sel_status = st.selectbox("STATUS", statuses)
        with c3:
            spaces = ["전체"] + sorted(df_all["SPACE_NM"].dropna().unique().tolist())
            sel_space = st.selectbox("SPACE_NM", spaces)

    df = df_all.copy()
    if keyword:
        df = df[df["SQL_ID"].astype(str).str.contains(keyword, case=False)]
    if sel_status != "전체":
        df = df[df["STATUS"] == sel_status]
    if sel_space != "전체":
        df = df[df["SPACE_NM"] == sel_space]

    show_cols = [c for c in _COLS_TABLE if c in df.columns]
    st.write(f"**{len(df)}건** 조회됨")
    st.dataframe(df[show_cols], use_container_width=True, hide_index=True)

    # ── 상세 조회 ─────────────────────────────────────────────────────────────
    st.divider()
    st.subheader("SQL 상세 조회")

    row_ids = df["ROW_ID"].tolist()
    if not row_ids:
        return

    labels = [f"{r['SQL_ID']} ({r['STATUS']})" for _, r in df.iterrows()]
    idx = st.selectbox("항목 선택", range(len(labels)), format_func=lambda i: labels[i])

    sel_row_id = row_ids[idx]
    row = next((j for j in jobs if j["ROW_ID"] == sel_row_id), None)
    if not row:
        return

    tab1, tab2, tab3 = st.tabs(["원본 SQL (AS-IS)", "변환 SQL (TO-BE)", "로그"])

    with tab1:
        st.code(row.get("FR_SQL_TEXT") or "(없음)", language="sql")

    with tab2:
        c1, c2 = st.columns(2)
        with c1:
            st.caption("TO_SQL_TEXT")
            st.code(row.get("TO_SQL_TEXT") or "(없음)", language="sql")
        with c2:
            verify = row.get("TUNED_TEST") or ""
            st.caption(f"건수 검증 결과: **{verify or '-'}**")

    with tab3:
        log = row.get("LOG") or ""
        if log:
            st.text_area("LOG", log, height=200)
        else:
            st.info("로그 없음")
