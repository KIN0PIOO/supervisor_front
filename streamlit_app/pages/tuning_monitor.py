import streamlit as st
import pandas as pd
from utils.db import get_sql_jobs

_COLS_TABLE = ["ROW_ID", "SQL_ID", "SPACE_NM", "STATUS", "TUNED_TEST", "UPD_TS"]


def render():
    st.title("⚡ Tuning Agent Monitor")

    if st.button("🔄 새로고침"):
        st.rerun()

    try:
        all_jobs = get_sql_jobs()
    except Exception as e:
        st.error(f"DB 연결 실패: {e}")
        return

    # TUNED_SQL 또는 TUNED_TEST 가 있는 항목만
    jobs = [j for j in all_jobs if j.get("TUNED_SQL") or j.get("TUNED_TEST")]

    if not jobs:
        st.info("튜닝 대상 작업이 없습니다.")
        return

    df_all = pd.DataFrame(jobs)

    # ── 필터 ──────────────────────────────────────────────────────────────────
    with st.expander("🔍 필터", expanded=True):
        c1, c2 = st.columns(2)
        with c1:
            keyword = st.text_input("SQL_ID 검색")
        with c2:
            tune_opts = ["전체"] + sorted(df_all["TUNED_TEST"].dropna().unique().tolist())
            sel_tune = st.selectbox("TUNED_TEST 상태", tune_opts)

    df = df_all.copy()
    if keyword:
        df = df[df["SQL_ID"].astype(str).str.contains(keyword, case=False)]
    if sel_tune != "전체":
        df = df[df["TUNED_TEST"] == sel_tune]

    show_cols = [c for c in _COLS_TABLE if c in df.columns]
    st.write(f"**{len(df)}건** 조회됨")
    st.dataframe(df[show_cols], use_container_width=True, hide_index=True)

    # ── 상세 비교 ─────────────────────────────────────────────────────────────
    st.divider()
    st.subheader("튜닝 전/후 비교")

    if df.empty:
        return

    row_ids = df["ROW_ID"].tolist()
    labels = [f"{r['SQL_ID']} | TUNED_TEST={r.get('TUNED_TEST','-')}" for _, r in df.iterrows()]
    idx = st.selectbox("항목 선택", range(len(labels)), format_func=lambda i: labels[i])

    sel_row_id = row_ids[idx]
    row = next((j for j in jobs if j["ROW_ID"] == sel_row_id), None)
    if not row:
        return

    c1, c2 = st.columns(2)
    with c1:
        st.caption("📝 TO_SQL_TEXT (튜닝 전)")
        st.code(row.get("TO_SQL_TEXT") or "(없음)", language="sql")
    with c2:
        st.caption("✨ TUNED_SQL (튜닝 후)")
        st.code(row.get("TUNED_SQL") or "(없음)", language="sql")

    c_test, c_log = st.columns(2)
    with c_test:
        st.write(f"**최종 검증:** {row.get('TUNED_TEST') or '-'}")
    with c_log:
        log = row.get("LOG") or ""
        if log:
            with st.expander("실패 로그"):
                st.text(log[:2000])
