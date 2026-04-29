"""마이그레이션 agent와 coordinator."""

import os
import random
import time

from agents.sql_pipeline.core.exceptions import LLMRateLimitError
from agents.sql_pipeline.core.logger import logger
from agents.sql_pipeline.repositories.mapper_repository import get_all_mapping_rules, get_unready_target_tables
from agents.sql_pipeline.repositories.result_repository import (
    reset_tuning_state,
    update_block_rag_content,
    update_cycle_result,
    update_job_skip,
)
from agents.sql_pipeline.services.binding_service import bind_sets_to_json, build_bind_sets, extract_bind_param_names
from agents.sql_pipeline.services.llm_service import (
    generate_bind_sql,
    generate_sql_comparison_test_sql,
    generate_test_sql,
    generate_test_sql_no_bind,
    generate_tobe_sql,
    serialize_tuning_examples_for_prompt,
    tune_tobe_sql,
)
from agents.sql_pipeline.services.tobe_sql_tuning_service import tobe_sql_tuning_service
from agents.sql_pipeline.services.validation_service import (
    evaluate_status_from_test_rows,
    execute_binding_query,
    execute_test_query,
)
from agents.sql_pipeline.workflow.graph import build_migration_workflow
from agents.sql_pipeline.workflow.state import JobExecutionState


class MappingRuleProvider:
    """매핑 룰을 한 번 읽고 여러 job에서 재사용한다."""

    def get_rules(self) -> list:
        return get_all_mapping_rules()


class TobeSqlGenerationAgent:
    """baseline TO-BE SQL을 생성하고 검증한다.

    핵심 원칙:
    - tobe_rule_catalog.json 을 사용하지 않는다.
    - TO-BE 생성은 원본 SQL, 매핑 룰, 직전 오류만 기준으로 수행한다.
    """

    name = "tobe_sql_generation_agent"

    def run(self, state: JobExecutionState) -> None:
        self.generate(state)
        self.validate(state)

    def generate(self, state: JobExecutionState) -> None:
        state.tobe_sql = generate_tobe_sql(
            job=state.job,
            mapping_rules=state.mapping_rules,
            last_error=state.last_error,
        )
        logger.info(
            f"[{self.name}] ({state.job_key}) stage=GENERATE_TOBE_SQL "
            f"completed (sql_length={len(state.tobe_sql)})"
        )

    def validate(self, state: JobExecutionState) -> None:
        bind_param_names = extract_bind_param_names(state.tobe_sql) or extract_bind_param_names(state.job.source_sql)
        state.bind_param_names = bind_param_names
        if not bind_param_names:
            state.bind_sql = ""
            state.bind_set_for_db = None
            state.bind_set_json_for_test = "[]"
            logger.info(f"[{self.name}] ({state.job_key}) stage=SKIP_BIND completed (reason=no_bind_params)")
        else:
            state.bind_sql = generate_bind_sql(
                job=state.job,
                tobe_sql=state.tobe_sql,
                last_error=state.last_error,
            )
            logger.info(
                f"[{self.name}] ({state.job_key}) stage=GENERATE_BIND_SQL "
                f"completed (sql_length={len(state.bind_sql)})"
            )

            bind_query_rows = execute_binding_query(state.bind_sql, max_rows=50)
            logger.info(
                f"[{self.name}] ({state.job_key}) stage=EXECUTE_BIND_SQL "
                f"completed (rows={len(bind_query_rows)})"
            )

            bind_sets = build_bind_sets(
                tobe_sql=state.tobe_sql,
                source_sql=state.job.source_sql,
                bind_query_rows=bind_query_rows,
                max_cases=3,
            )
            state.bind_set_json_for_test = bind_sets_to_json(bind_sets)
            state.bind_set_for_db = state.bind_set_json_for_test
            logger.info(
                f"[{self.name}] ({state.job_key}) stage=BUILD_BIND_SET "
                f"completed (cases={len(bind_sets)})"
            )

        if state.bind_param_names:
            state.test_sql = generate_test_sql(
                job=state.job,
                tobe_sql=state.tobe_sql,
                bind_set_json=state.bind_set_json_for_test,
            )
        else:
            state.test_sql = generate_test_sql_no_bind(
                job=state.job,
                tobe_sql=state.tobe_sql,
            )
        logger.info(
            f"[{self.name}] ({state.job_key}) stage=GENERATE_TEST_SQL "
            f"completed (sql_length={len(state.test_sql)})"
        )

        state.test_rows = execute_test_query(state.test_sql)
        logger.info(
            f"[{self.name}] ({state.job_key}) stage=EXECUTE_TEST_SQL "
            f"completed (rows={len(state.test_rows)})"
        )

        state.status = evaluate_status_from_test_rows(state.test_rows)
        logger.info(
            f"[{self.name}] ({state.job_key}) stage=EVALUATE_STATUS "
            f"completed (status={state.status})"
        )


class SqlTuningAgent:
    """baseline 검증을 통과한 뒤 TO-BE SQL 튜닝을 적용한다.

    핵심 원칙:
    - RAG/FAISS 로 block별 top-k 튜닝 룰을 검색한다.
    - TOBE_SQL_TUNING_MAX_ITERATIONS=0 이면 튜닝을 비활성화한다.
    """

    name = "sql_tuning_agent"

    def __init__(self, max_iterations: int | None = None) -> None:
        raw_max = max_iterations if max_iterations is not None else int(os.getenv("TOBE_SQL_TUNING_MAX_ITERATIONS", "1"))
        self.max_iterations = max(0, raw_max)

    def run(self, state: JobExecutionState) -> None:
        state.tuned_sql = ""
        state.tuned_test = None
        if self.max_iterations <= 0:
            return
        current_sql = state.tobe_sql or ""
        for iteration in range(1, self.max_iterations + 1):
            tuning_examples = tobe_sql_tuning_service.retrieve_tuning_examples(current_sql)
            state.tuning_examples = tuning_examples
            tuning_examples_json = serialize_tuning_examples_for_prompt(tuning_examples)
            update_block_rag_content(row_id=state.job.row_id, block_rag_content=tuning_examples_json)
            logger.info(
                f"[{self.name}] ({state.job_key}) stage=LOAD_TUNING_RULES "
                f"completed (iteration={iteration}, rule_blocks={len(tuning_examples)})"
            )
            if not tuning_examples:
                break

            tuned_sql = tune_tobe_sql(
                current_tobe_sql=current_sql,
                tuning_examples=tuning_examples,
                last_error=state.last_error,
            )
            logger.info(
                f"[{self.name}] ({state.job_key}) stage=APPLY_TUNING_RULES "
                f"completed (iteration={iteration}, sql_length={len(tuned_sql)})"
            )
            if tuned_sql.strip() == current_sql.strip():
                break
            current_sql = tuned_sql

        state.tuned_sql = current_sql
        self._run_tuned_sql_validation(state)

    def _run_tuned_sql_validation(self, state: JobExecutionState) -> None:
        comparison_test_sql = generate_sql_comparison_test_sql(
            baseline_sql=state.tobe_sql,
            candidate_sql=state.tuned_sql,
            bind_set_json=state.bind_set_for_db,
        )
        logger.info(
            f"[{self.name}] ({state.job_key}) stage=GENERATE_TUNED_TEST_SQL "
            f"completed (sql_length={len(comparison_test_sql)})"
        )

        comparison_rows = execute_test_query(comparison_test_sql)
        logger.info(
            f"[{self.name}] ({state.job_key}) stage=EXECUTE_TUNED_TEST_SQL "
            f"completed (rows={len(comparison_rows)})"
        )

        state.tuned_test = evaluate_status_from_test_rows(comparison_rows)
        logger.info(
            f"[{self.name}] ({state.job_key}) stage=EVALUATE_TUNED_TEST "
            f"completed (status={state.tuned_test})"
        )


class TobeMultiAgentCoordinator:
    """재시도, 그래프 호출, DB 저장을 조율한다."""

    def __init__(
        self,
        mapping_rule_provider: MappingRuleProvider | None = None,
        generation_agent: TobeSqlGenerationAgent | None = None,
        tuning_agent: SqlTuningAgent | None = None,
    ) -> None:
        self.mapping_rule_provider = mapping_rule_provider or MappingRuleProvider()
        self.generation_agent = generation_agent or TobeSqlGenerationAgent()
        self.tuning_agent = tuning_agent or SqlTuningAgent()
        self.graph = build_migration_workflow(
            generation_agent=self.generation_agent,
            tuning_agent=self.tuning_agent,
        )

    def process_job(self, job) -> None:
        logger.info("\n==========================================")
        logger.info(f"[TobeMultiAgentCoordinator] Starting job ({job.space_nm}.{job.sql_id})")
        job_key = f"{job.space_nm}.{job.sql_id}"

        retry_count = 0
        max_retries = 3
        stage = "INIT"
        state = self._build_state(job=job, last_error=None)

        if (job.status or "").strip().upper() == "FAIL":
            reset_tuning_state(job.row_id)
            job.tuned_sql = None
            job.tuned_test = None

        unready_target_tables = get_unready_target_tables(job.target_table)
        if unready_target_tables:
            reason = "TARGET_MAPPING_NOT_READY: " + ",".join(unready_target_tables)
            update_job_skip(row_id=job.row_id, reason=reason)
            logger.warning(f"[TobeMultiAgentCoordinator] ({job_key}) skipped: {reason}")
            return

        while retry_count <= max_retries:
            state = self._build_state(job=job, last_error=state.last_error)
            try:
                graph_result = self.graph.invoke({"execution": state, "terminal_action": None})
                state = graph_result["execution"]
                terminal_action = graph_result.get("terminal_action")
                stage = terminal_action or stage

                tag_kind = (job.tag_kind or "").strip().upper()
                if terminal_action == "persist_non_select" or tag_kind != "SELECT":
                    self._complete_non_select_job(state, tag_kind)
                    return

                if state.status != "PASS":
                    retry_count += 1
                    state.last_error = "TEST_VALIDATION_FAIL: " + self._summarize_test_rows_for_retry(state.test_rows)
                    logger.warning(
                        f"[TobeMultiAgentCoordinator] ({job_key}) stage={stage} status=FAIL "
                        f"(retry={retry_count}/{max_retries}): {state.last_error}"
                    )
                    if retry_count <= max_retries:
                        self._sleep_with_backoff(retry_count)
                        continue
                    break

                self._persist_success(state)
                return

            except LLMRateLimitError as exc:
                retry_count += 1
                stage = "LLM_CALL"
                state.last_error = str(exc)
                logger.warning(
                    f"[TobeMultiAgentCoordinator] ({job_key}) stage={stage} LLM rate limit "
                    f"(retry={retry_count}/{max_retries}): {state.last_error}"
                )
                self._sleep_with_backoff(retry_count)

            except Exception as exc:
                retry_count += 1
                state.last_error = str(exc)
                logger.error(
                    f"[TobeMultiAgentCoordinator] ({job_key}) stage={stage} error "
                    f"(retry={retry_count}/{max_retries}): {state.last_error}"
                )
                self._sleep_with_backoff(retry_count)

        self._persist_failure(state=state, stage=stage, retry_count=retry_count)

    def _build_state(self, job, last_error: str | None) -> JobExecutionState:
        return JobExecutionState(
            job=job,
            job_key=f"{job.space_nm}.{job.sql_id}",
            mapping_rules=self.mapping_rule_provider.get_rules(),
            last_error=last_error,
        )

    @staticmethod
    def _persist_success(state: JobExecutionState) -> None:
        final_log = f"FINAL SUCCESS stage=COMPLETED status={state.status} job={state.job_key}"
        update_cycle_result(
            row_id=state.job.row_id,
            tobe_sql=state.tobe_sql,
            tuned_sql=state.tuned_sql or None,
            tuned_test=state.tuned_test or "READY",
            bind_sql=state.bind_sql,
            bind_set=state.bind_set_for_db,
            test_sql=state.test_sql,
            status=state.status or "FAIL",
            final_log=final_log,
        )
        logger.info(f"[TobeMultiAgentCoordinator] ({state.job_key}) completed successfully.")

    @staticmethod
    def _persist_failure(state: JobExecutionState, stage: str, retry_count: int) -> None:
        final_log = (
            f"FINAL FAIL stage={stage} retry_count={retry_count} "
            f"job={state.job_key} error={state.last_error or 'UNKNOWN'}"
        )
        update_cycle_result(
            row_id=state.job.row_id,
            tobe_sql=state.tobe_sql,
            tuned_sql=state.tuned_sql or None,
            tuned_test=state.tuned_test,
            bind_sql=state.bind_sql,
            bind_set=state.bind_set_for_db,
            test_sql=state.test_sql,
            status="FAIL",
            final_log=final_log,
        )
        logger.error(f"[TobeMultiAgentCoordinator] ({state.job_key}) failed after retries: {state.last_error}")

    @staticmethod
    def _complete_non_select_job(state: JobExecutionState, tag_kind: str) -> None:
        final_log = (
            f"FINAL SUCCESS stage=COMPLETED status=PASS "
            f"job={state.job_key} reason=TAG_KIND:{tag_kind or 'UNKNOWN'}"
        )
        update_cycle_result(
            row_id=state.job.row_id,
            tobe_sql=state.tobe_sql,
            tuned_sql=state.tuned_sql or None,
            tuned_test=state.tuned_test,
            bind_sql="",
            bind_set=None,
            test_sql="",
            status="PASS",
            final_log=final_log,
        )
        logger.info(
            f"[TobeMultiAgentCoordinator] ({state.job_key}) stage=SKIP_TEST_FOR_NON_SELECT "
            f"completed (tag_kind={tag_kind or 'UNKNOWN'})"
        )

    @staticmethod
    def _sleep_with_backoff(retry_count: int) -> None:
        base = min(8, 2 ** max(0, retry_count - 1))
        jitter = random.uniform(0.0, 0.7)
        time.sleep(base + jitter)

    @staticmethod
    def _get_case_insensitive_value(row: dict, key: str):
        lowered = key.lower()
        for existing_key, value in row.items():
            if str(existing_key).lower() == lowered:
                return value
        return None

    @classmethod
    def _summarize_test_rows_for_retry(cls, rows: list[dict]) -> str:
        if not rows:
            return "no_rows_returned"

        samples: list[str] = []
        for row in rows[:5]:
            case_no = cls._get_case_insensitive_value(row, "case_no")
            from_count = cls._get_case_insensitive_value(row, "from_count")
            to_count = cls._get_case_insensitive_value(row, "to_count")
            samples.append(f"CASE_NO={case_no},FROM_COUNT={from_count},TO_COUNT={to_count}")
        return " ; ".join(samples)
