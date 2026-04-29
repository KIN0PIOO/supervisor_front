import sys
from pathlib import Path

# streamlit_app/ 를 import 경로에 추가
sys.path.insert(0, str(Path(__file__).parent))

import streamlit as st

st.set_page_config(
    page_title="Migration Pipeline Console",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded",
)

from utils.agent_control import get_status, start, stop, pause, resume
from pages.dashboard        import render as render_dashboard
from pages.mig_monitor      import render as render_mig
from pages.sql_monitor      import render as render_sql
from pages.tuning_monitor   import render as render_tuning
from pages.job_detail       import render as render_job_detail
from pages.rag_manager_page import render as render_rag
from pages.system_health    import render as render_health
from pages.settings_page    import render as render_settings

_MENU = {
    "📊 Dashboard":            render_dashboard,
    "📦 Mig Agent Monitor":    render_mig,
    "🔄 SQL Agent Monitor":    render_sql,
    "⚡ Tuning Agent Monitor": render_tuning,
    "🔎 Job Detail":           render_job_detail,
    "📚 RAG Rule Manager":     render_rag,
    "🏥 System Health":        render_health,
    "⚙️ Settings":             render_settings,
}

# Streamlit 자동 페이지 목록 완전 숨김
st.markdown("""
<style>
[data-testid="stSidebarNav"],
[data-testid="stSidebarNavItems"],
[data-testid="stSidebarNavSeparator"],
section[data-testid="stSidebar"] ul { display: none !important; }
</style>
""", unsafe_allow_html=True)

with st.sidebar:
    st.image("https://img.icons8.com/color/96/database.png", width=60)
    st.markdown("## Migration Console")
    st.markdown("---")
    selected = st.radio("메뉴", list(_MENU.keys()), label_visibility="collapsed")

    # ── Agent 컨트롤 패널 ────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("#### ⚙️ Agent 제어")

    status = get_status()
    st.markdown(f"**{status['label']}**" + (f"  `PID {status['pid']}`" if status["pid"] else ""))

    if not status["running"]:
        if st.button("▶ 시작", use_container_width=True, type="primary"):
            msg = start()
            st.toast(msg)
            st.rerun()
    else:
        c1, c2 = st.columns(2)
        if status["paused"]:
            with c1:
                if st.button("▶ 재개", use_container_width=True, type="primary"):
                    st.toast(resume())
                    st.rerun()
        else:
            with c1:
                if st.button("⏸ 일시정지", use_container_width=True):
                    st.toast(pause())
                    st.rerun()
        with c2:
            if st.button("■ 중지", use_container_width=True, type="secondary"):
                st.toast(stop())
                st.rerun()

    st.markdown("---")
    st.caption("Unified Multi-Agent Pipeline")

_MENU[selected]()
