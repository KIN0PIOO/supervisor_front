import streamlit as st
import pandas as pd
from utils.rag_db import (
    get_all_rules, add_rule, update_rule, delete_rule,
    rule_id_exists, get_next_rule_id,
)


def render():
    st.title("📚 RAG Rule Manager")
    st.caption("Oracle DB (NEXT_SQL_RULES) 기반 튜닝 룰 관리")

    col_title, col_refresh = st.columns([9, 1])
    with col_refresh:
        if st.button("🔄"):
            st.rerun()

    # ── 룰 목록 조회 ──────────────────────────────────────────────────────────
    try:
        rules = get_all_rules()
    except Exception as e:
        st.error(f"DB 연결 실패: {e}")
        return

    st.write(f"**총 {len(rules)}개** 룰 등록됨")

    keyword = st.text_input("🔍 검색", placeholder="RULE_ID 또는 guidance 키워드")

    filtered = rules
    if keyword:
        kw = keyword.lower()
        filtered = [
            r for r in rules
            if kw in r.get("RULE_ID", "").lower()
            or kw in r.get("GUIDANCE", "").lower()
        ]

    # 테이블로 목록 표시
    if filtered:
        table_rows = [
            {
                "RULE_ID": r["RULE_ID"],
                "guidance (preview)": (r.get("GUIDANCE") or "")[:80],
                "CREATED_AT": r.get("CREATED_AT", ""),
                "UPDATED_AT": r.get("UPDATED_AT", ""),
            }
            for r in filtered
        ]
        st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)
    else:
        st.info("검색 결과 없음")

    st.divider()

    # ── 상세 조회 / 수정 / 삭제 ───────────────────────────────────────────────
    if filtered:
        st.subheader("📋 상세 조회 / 수정 / 삭제")
        rule_ids = [r["RULE_ID"] for r in filtered]
        sel_id = st.selectbox("룰 선택", rule_ids, key="sel_rule")
        sel = next((r for r in filtered if r["RULE_ID"] == sel_id), None)

        if sel:
            with st.expander(f"🔍 {sel_id} 상세", expanded=True):
                tab_view, tab_edit = st.tabs(["조회", "수정"])

                with tab_view:
                    st.write("**guidance:**")
                    for line in (sel.get("GUIDANCE") or "").splitlines():
                        if line.strip():
                            st.write(f"- {line.strip()}")
                    st.write("**example_bad_sql:**")
                    st.code(sel.get("EXAMPLE_BAD_SQL") or "(없음)", language="sql")
                    if sel.get("EXAMPLE_TUNED_SQL"):
                        st.write("**example_tuned_sql:**")
                        st.code(sel["EXAMPLE_TUNED_SQL"], language="sql")
                    st.caption(
                        f"생성: {sel.get('CREATED_AT','')}  |  수정: {sel.get('UPDATED_AT','')}"
                    )

                with tab_edit:
                    with st.form(f"edit_form_{sel_id}"):
                        new_guidance = st.text_area(
                            "guidance", value=sel.get("GUIDANCE") or "", height=120
                        )
                        new_bad_sql = st.text_area(
                            "example_bad_sql",
                            value=sel.get("EXAMPLE_BAD_SQL") or "",
                            height=100,
                        )
                        new_tuned_sql = st.text_area(
                            "example_tuned_sql",
                            value=sel.get("EXAMPLE_TUNED_SQL") or "",
                            height=100,
                        )
                        if st.form_submit_button("💾 수정 저장", type="primary"):
                            try:
                                update_rule(sel_id, new_guidance, new_bad_sql, new_tuned_sql)
                                st.success(f"{sel_id} 수정 완료")
                                st.rerun()
                            except Exception as e:
                                st.error(f"수정 실패: {e}")

            # 삭제 버튼 (expander 밖)
            if st.button(f"🗑️ {sel_id} 삭제", type="secondary", key=f"del_{sel_id}"):
                st.session_state["confirm_delete"] = sel_id

            if st.session_state.get("confirm_delete") == sel_id:
                st.warning(f"**{sel_id}** 를 삭제하시겠습니까?")
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("✅ 확인 삭제", type="primary", key="do_delete"):
                        try:
                            ok = delete_rule(sel_id)
                            if ok:
                                st.success(f"{sel_id} 삭제 완료")
                                st.session_state.pop("confirm_delete", None)
                                st.rerun()
                            else:
                                st.error("삭제할 항목을 찾지 못했습니다.")
                        except Exception as e:
                            st.error(f"삭제 실패: {e}")
                with c2:
                    if st.button("❌ 취소", key="cancel_delete"):
                        st.session_state.pop("confirm_delete", None)
                        st.rerun()

    st.divider()

    # ── 새 룰 생성 ────────────────────────────────────────────────────────────
    st.subheader("➕ 새 룰 생성")

    auto_id = ""
    try:
        auto_id = get_next_rule_id()
    except Exception:
        pass

    with st.form("new_rule_form", clear_on_submit=True):
        col_id, col_hint = st.columns([3, 7])
        with col_id:
            new_id = st.text_input("RULE_ID", value=auto_id, placeholder="예) USER_RULE_006")
        with col_hint:
            st.write("")
            st.caption(f"자동 제안: `{auto_id}`  (직접 입력 가능)")

        new_guidance = st.text_area(
            "guidance (줄바꿈으로 여러 항목)",
            placeholder="불필요한 SELECT * 제거\n인라인뷰를 직접 조인으로 변환",
            height=100,
        )
        new_bad_sql = st.text_area(
            "example_bad_sql",
            placeholder="SELECT * FROM EMP WHERE ...",
            height=80,
        )
        new_tuned_sql = st.text_area(
            "example_tuned_sql (선택)",
            placeholder="SELECT EMP_ID, EMP_NM FROM EMP WHERE ...",
            height=80,
        )
        submitted = st.form_submit_button("💾 저장", type="primary")

    if submitted:
        if not new_id.strip():
            st.error("RULE_ID를 입력하세요.")
        elif not new_guidance.strip():
            st.error("guidance를 입력하세요.")
        elif not new_bad_sql.strip():
            st.error("example_bad_sql을 입력하세요.")
        else:
            try:
                if rule_id_exists(new_id.strip()):
                    st.error(f"RULE_ID '{new_id.strip()}' 이 이미 존재합니다.")
                else:
                    add_rule(new_id.strip(), new_guidance.strip(),
                             new_bad_sql.strip(), new_tuned_sql.strip())
                    st.success(f"룰 생성 완료: **{new_id.strip()}**")
                    st.rerun()
            except Exception as e:
                st.error(f"저장 실패: {e}")
