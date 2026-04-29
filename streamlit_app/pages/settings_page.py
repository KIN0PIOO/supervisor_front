import streamlit as st
from utils.env_manager import read_env, write_env_key

_LLM_MODELS = [
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gpt-4o-mini",
    "gpt-4o",
    "claude-haiku-4-5-20251001",
    "claude-sonnet-4-6",
]


def render():
    st.title("⚙️ Settings")

    env = read_env()

    # ── LLM 설정 ──────────────────────────────────────────────────────────────
    st.subheader("🤖 LLM 설정")

    current_model = env.get("LLM_MODEL", "")
    model_options = sorted(set(_LLM_MODELS + ([current_model] if current_model else [])))

    col1, col2 = st.columns(2)
    with col1:
        sel_model = st.selectbox(
            "모델 선택",
            model_options,
            index=model_options.index(current_model) if current_model in model_options else 0,
        )
        custom_model = st.text_input("직접 입력 (우선 적용)", placeholder="예) gemini-2.5-pro")
    with col2:
        api_key = st.text_input(
            "API Key (OPEN_API_KEY)",
            value=env.get("OPEN_API_KEY", ""),
            type="password",
        )
        base_url = st.text_input(
            "LLM_BASE_URL",
            value=env.get("LLM_BASE_URL", ""),
        )

    if st.button("LLM 설정 저장", type="primary"):
        final_model = custom_model.strip() if custom_model.strip() else sel_model
        write_env_key("LLM_MODEL", final_model)
        if api_key:
            write_env_key("OPEN_API_KEY", api_key)
        if base_url:
            write_env_key("LLM_BASE_URL", base_url)
        st.success(f"저장 완료 → LLM_MODEL={final_model}")

    st.divider()

    # ── 튜닝 강도 설정 ────────────────────────────────────────────────────────
    st.subheader("🎛️ 튜닝 강도 설정")

    st.caption("튜닝 강도가 높을수록 더 많은 룰을 참고하고 반복적으로 개선합니다. "
               "하지만 추론 시간이 증가하고 비용이 늘어날 수 있습니다.")

    current_topk = int(env.get("TOBE_SQL_TUNING_TOP_K", "3"))
    current_iter = int(env.get("TOBE_SQL_TUNING_MAX_ITERATIONS", "1"))

    col_k, col_i = st.columns(2)
    with col_k:
        top_k = st.slider(
            "Top-K (참고할 룰 수)",
            min_value=1, max_value=20, value=current_topk, step=1,
        )
        st.caption(f"현재: {current_topk} → 변경: {top_k}")
    with col_i:
        max_iter = st.slider(
            "Retry Count (반복 튜닝 횟수)",
            min_value=1, max_value=10, value=current_iter, step=1,
        )
        st.caption(f"현재: {current_iter} → 변경: {max_iter}")

    if st.button("튜닝 설정 저장", type="primary"):
        write_env_key("TOBE_SQL_TUNING_TOP_K", str(top_k))
        write_env_key("TOBE_SQL_TUNING_MAX_ITERATIONS", str(max_iter))
        st.success(f"저장 완료 → Top-K={top_k}, MaxIter={max_iter}")

    st.divider()

    # ── DB 설정 ───────────────────────────────────────────────────────────────
    with st.expander("🗄️ Oracle DB 설정"):
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            db_host = st.text_input("DB_HOST", value=env.get("DB_HOST", "localhost"))
        with c2:
            db_port = st.text_input("DB_PORT", value=env.get("DB_PORT", "1521"))
        with c3:
            db_sid = st.text_input("DB_SID", value=env.get("DB_SID", "xe"))
        with c4:
            db_user = st.text_input("DB_USER", value=env.get("DB_USER", "scott"))
        db_pass = st.text_input("DB_PASS", value=env.get("DB_PASS", ""), type="password")

        if st.button("DB 설정 저장"):
            for k, v in [("DB_HOST", db_host), ("DB_PORT", db_port),
                         ("DB_SID", db_sid), ("DB_USER", db_user)]:
                if v:
                    write_env_key(k, v)
            if db_pass:
                write_env_key("DB_PASS", db_pass)
            st.success("DB 설정 저장 완료 (재시작 후 적용)")
