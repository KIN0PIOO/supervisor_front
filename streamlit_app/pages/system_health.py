import os
import streamlit as st
from pathlib import Path
from utils.db import get_connection
from utils.env_manager import read_env
from utils.rag_manager import RAG_PATH

_REQUIRED_ENVS = [
    "DB_USER", "DB_PASS", "DB_HOST", "DB_PORT", "DB_SID",
    "LLM_MODEL", "LLM_BASE_URL",
]
_LLM_KEY_ENVS = ["OPEN_API_KEY", "LLM_API_KEY"]


def _check_oracle() -> tuple[bool, str]:
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM DUAL")
                cur.fetchone()
        return True, "연결 성공"
    except Exception as e:
        return False, str(e)


def _check_llm(env: dict) -> tuple[bool, str]:
    key = env.get("OPEN_API_KEY") or env.get("LLM_API_KEY") or ""
    model = env.get("LLM_MODEL") or ""
    base_url = env.get("LLM_BASE_URL") or ""
    if not key:
        return False, "API Key 미설정 (OPEN_API_KEY 또는 LLM_API_KEY)"
    if not model:
        return False, "LLM_MODEL 미설정"
    if not base_url:
        return False, "LLM_BASE_URL 미설정"
    return True, f"설정 확인됨 (model={model})"


def _check_rag() -> tuple[bool, str]:
    if not RAG_PATH.exists():
        return False, f"파일 없음: {RAG_PATH}"
    try:
        import json
        data = json.loads(RAG_PATH.read_text(encoding="utf-8"))
        n = len(data.get("rules", []))
        return True, f"{n}개 룰 로드됨"
    except Exception as e:
        return False, str(e)


def _missing_envs(env: dict) -> list[str]:
    missing = [k for k in _REQUIRED_ENVS if not env.get(k)]
    has_key = any(env.get(k) for k in _LLM_KEY_ENVS)
    if not has_key:
        missing.append("OPEN_API_KEY / LLM_API_KEY")
    return missing


def render():
    st.title("🏥 System Health")

    if st.button("🔄 재검사"):
        st.rerun()

    env = read_env()

    checks = {
        "Oracle DB": _check_oracle,
        "LLM API": lambda: _check_llm(env),
        "RAG Rule Catalog": _check_rag,
    }

    for name, fn in checks.items():
        ok, msg = fn()
        icon = "✅" if ok else "❌"
        col1, col2 = st.columns([2, 8])
        with col1:
            st.write(f"{icon} **{name}**")
        with col2:
            if ok:
                st.success(msg)
            else:
                st.error(msg)

    st.divider()

    missing = _missing_envs(env)
    if missing:
        st.warning("누락된 환경 변수:")
        for m in missing:
            st.write(f"  - `{m}`")
    else:
        st.success("필수 환경 변수 모두 설정됨 ✓")

    with st.expander("현재 .env 값 보기 (민감 정보 마스킹)"):
        for k, v in sorted(env.items()):
            if any(kw in k.upper() for kw in ("KEY", "PASS", "SECRET", "TOKEN")):
                v = v[:4] + "****" if len(v) > 4 else "****"
            st.write(f"`{k}` = `{v}`")
