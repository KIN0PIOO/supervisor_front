"""PlannerAgent — Stage 1: LLM 기반 동적 작업 선택.

역할:
  - DB에서 폴링된 전체 대기 작업을 분석
  - LLM이 이번 사이클에 실행할 작업을 동적으로 결정
  - 각 에이전트 내부 워크플로우는 절대 변경하지 않음

위치: Supervisor 폴링 → [Planner 판단] → 에이전트 Fan-out
"""
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from config.settings import (
    LLM_API_KEY, LLM_BASE_URL, LLM_MODEL,
    PLANNER_MAX_MIG_PER_CYCLE,
)

logger = logging.getLogger("migration_agent")

_PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "planner_prompt.json"


# ── 플래너 결정 결과 ───────────────────────────────────────────────────────────
@dataclass
class PlannerDecision:
    mig_jobs:     list = field(default_factory=list)
    sql_jobs:     list = field(default_factory=list)
    tuning_jobs:  list = field(default_factory=list)
    skip_reasons: dict = field(default_factory=dict)
    reasoning:    str  = ""


# ── 플래너 에이전트 ────────────────────────────────────────────────────────────
class PlannerAgent:
    """Stage 1: LLM이 이번 사이클에 실행할 작업을 동적으로 결정."""

    def __init__(self):
        self._prompt = json.loads(_PROMPT_PATH.read_text(encoding="utf-8"))

    # ── 공개 API ──────────────────────────────────────────────────────────────
    def plan(
        self,
        mig_jobs:    list,
        sql_jobs:    list,
        tuning_jobs: list,
    ) -> PlannerDecision:
        """대기 작업 목록을 받아 실행할 작업 목록을 반환."""
        if not mig_jobs and not sql_jobs and not tuning_jobs:
            return PlannerDecision()

        context = self._build_context(mig_jobs, sql_jobs, tuning_jobs)
        logger.info("[Planner] LLM 플래닝 시작...")

        try:
            raw      = self._call_llm(context)
            decision = self._parse(raw, mig_jobs, sql_jobs, tuning_jobs)
            self._log_decision(decision)
            return decision

        except Exception as exc:
            # Fallback: 기존 하드코딩 동작과 동일 (전체 실행)
            logger.warning(f"[Planner] LLM 실패 → 전체 작업 실행으로 폴백 ({exc})")
            return PlannerDecision(
                mig_jobs=mig_jobs,
                sql_jobs=sql_jobs,
                tuning_jobs=tuning_jobs,
                reasoning="폴백: Planner LLM 호출 실패",
            )

    # ── 컨텍스트 구성 ─────────────────────────────────────────────────────────
    def _build_context(self, mig_jobs, sql_jobs, tuning_jobs) -> str:
        lines = []

        if mig_jobs:
            lines.append(f"[이관 작업 — 총 {len(mig_jobs)}건]")
            for job in mig_jobs:
                retry = getattr(job, "retry_count", 0) or 0
                lines.append(
                    f"  MAP_ID={job.map_id} | {job.fr_table} → {job.to_table}"
                    f" | PRIORITY={job.priority} | RETRY={retry}회"
                )

        if sql_jobs:
            lines.append(f"\n[SQL 변환 작업 — 총 {len(sql_jobs)}건]")
            for job in sql_jobs[:20]:
                lines.append(
                    f"  ROW_ID={job.row_id} | SQL_ID={job.sql_id}"
                    f" | SPACE={job.space_nm} | STATUS={job.status or 'NULL'}"
                )
            if len(sql_jobs) > 20:
                lines.append(f"  ... 외 {len(sql_jobs) - 20}건")

        if tuning_jobs:
            lines.append(f"\n[SQL 튜닝 작업 — 총 {len(tuning_jobs)}건]")
            for job in tuning_jobs[:10]:
                lines.append(
                    f"  ROW_ID={job.row_id} | SQL_ID={job.sql_id}"
                    f" | TUNED_TEST={job.tuned_test or 'NULL'}"
                )
            if len(tuning_jobs) > 10:
                lines.append(f"  ... 외 {len(tuning_jobs) - 10}건")

        return "\n".join(lines)

    # ── LLM 호출 ─────────────────────────────────────────────────────────────
    def _call_llm(self, context: str) -> str:
        from openai import OpenAI

        client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)
        system = self._prompt["system"].format(
            max_mig_per_cycle=PLANNER_MAX_MIG_PER_CYCLE
        )
        user = self._prompt["user_template"].format(context=context)

        resp = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
            temperature=0,
            max_tokens=800,
        )
        return resp.choices[0].message.content.strip()

    # ── 응답 파싱 ─────────────────────────────────────────────────────────────
    def _parse(self, raw: str, mig_jobs, sql_jobs, tuning_jobs) -> PlannerDecision:
        text = raw.strip()
        if text.startswith("```"):
            text = text.strip("`").strip()
            if text.lower().startswith("json"):
                text = text[4:].strip()

        data = json.loads(text)

        run_mig_ids  = set(int(x) for x in data.get("run_mig_jobs",  [j.map_id  for j in mig_jobs]))
        run_sql_ids  = set(str(x) for x in data.get("run_sql_jobs",  [j.row_id  for j in sql_jobs]))
        run_tune_ids = set(str(x) for x in data.get("run_tuning_jobs",[j.row_id for j in tuning_jobs]))

        return PlannerDecision(
            mig_jobs    = [j for j in mig_jobs    if j.map_id  in run_mig_ids],
            sql_jobs    = [j for j in sql_jobs    if j.row_id  in run_sql_ids],
            tuning_jobs = [j for j in tuning_jobs if j.row_id  in run_tune_ids],
            skip_reasons= data.get("skip_reasons", {}),
            reasoning   = data.get("reasoning",    ""),
        )

    # ── 로깅 ─────────────────────────────────────────────────────────────────
    @staticmethod
    def _log_decision(d: PlannerDecision):
        logger.info(
            f"[Planner] 결정 → "
            f"Mig {len(d.mig_jobs)}건 | "
            f"SQL {len(d.sql_jobs)}건 | "
            f"Tuning {len(d.tuning_jobs)}건"
        )
        if d.skip_reasons:
            for job_id, reason in d.skip_reasons.items():
                logger.info(f"[Planner] SKIP {job_id}: {reason}")
        if d.reasoning:
            logger.info(f"[Planner] 판단 근거: {d.reasoning}")
