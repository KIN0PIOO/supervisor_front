import os
import json
from pathlib import Path
import anthropic
import openai
from anthropic import Anthropic
from openai import OpenAI
from agents.data_migration.core.exceptions import (
    LLMConnectionError, LLMAuthenticationError,
    LLMRateLimitError, LLMInvalidRequestError, LLMServerError
)
from agents.data_migration.core.logger import logger
from agents.data_migration.agent.prompt_service import build_migration_prompt
from dotenv import load_dotenv

# 프로젝트 루트 .env 로드 (unified_agent/ 기준)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
load_dotenv(_PROJECT_ROOT / ".env")


def _resolve_llm_provider() -> str:
    provider = (os.getenv("LLM_PROVIDER") or "").strip().lower()
    if provider:
        if provider not in {"anthropic", "openai"}:
            raise LLMInvalidRequestError("LLM_PROVIDER must be either 'anthropic' or 'openai'.")
        return provider

    base_url = (os.getenv("LLM_BASE_URL") or "").lower()
    model = (os.getenv("LLM_MODEL") or "").lower()
    if "anthropic" in base_url or model.startswith("claude"):
        return "anthropic"
    return "openai"


def get_client():
    """Return the configured LLM client."""
    api_key = os.getenv("LLM_API_KEY") or os.getenv("OPEN_API_KEY")
    base_url = os.getenv("LLM_BASE_URL")
    provider = _resolve_llm_provider()

    if not api_key:
        error_msg = "API Key(LLM_API_KEY)? ???? ?????."
        logger.error(f"[LLM] {error_msg}")
        raise LLMAuthenticationError(error_msg)

    if provider == "anthropic":
        return Anthropic(
            api_key=api_key,
            base_url=(base_url or "https://api.anthropic.com").rstrip("/"),
        )

    return OpenAI(
        api_key=api_key,
        base_url=base_url if base_url else None,
    )


def _extract_anthropic_text(response) -> str:
    chunks = []
    for item in getattr(response, "content", []) or []:
        text = getattr(item, "text", None)
        if text:
            chunks.append(text)
    return "".join(chunks).strip()


def _extract_json_object(text: str) -> dict:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`").strip()
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            return json.loads(raw[start : end + 1])
        raise

def _format_ddl_info(ddl_rows: list) -> str:
    if not ddl_rows:
        return "  (조회된 컬럼 정보 없음)"
    lines = []
    for col_name, data_type, data_length, data_precision, data_scale, nullable in ddl_rows:
        if data_type == "NUMBER":
            if data_precision is not None and data_scale not in (None, 0):
                type_str = f"NUMBER({data_precision},{data_scale})"
            elif data_precision is not None:
                type_str = f"NUMBER({data_precision})"
            else:
                type_str = "NUMBER"
        elif data_type in ("VARCHAR2", "CHAR", "NVARCHAR2", "NCHAR") and data_length:
            type_str = f"{data_type}({data_length})"
        else:
            type_str = data_type
        null_str = "NULL" if nullable == "Y" else "NOT NULL"
        lines.append(f"  {col_name:<30} {type_str:<25} {null_str}")
    return "\n".join(lines)


def generate_sqls(NEXT_SQL_INFO, last_error=None, last_sql=None, source_ddl=None, target_ddl=None, is_append=False):
    """
    OpenAI 호환 API를 호출하여 Oracle 21c 마이그레이션 SQL들을 생성합니다.
    (DDL, Migration, Verification 분리)
    """
    client = get_client()
    model_name = os.getenv("LLM_MODEL") or "gpt-4o-mini"

    from_table = NEXT_SQL_INFO.fr_table
    to_table = NEXT_SQL_INFO.to_table

    details = NEXT_SQL_INFO.details
    mapping_info = "\n".join([f"  - {d.fr_col} -> {d.to_col}" for d in details])

    ddl_info_block = ""
    if source_ddl and isinstance(source_ddl, dict):
        table_blocks = []
        for tbl_name, rows in source_ddl.items():
            formatted = _format_ddl_info(rows)
            table_blocks.append(
                f"    테이블: {tbl_name}\n"
                f"    {'컬럼명':<30} {'데이터타입':<25} {'NULL여부'}\n"
                f"    {'-'*70}\n"
                f"{formatted}"
            )
        ddl_info_block += f"""
    [소스 테이블 실제 DDL 정보] (ALL_TAB_COLUMNS 읽기 전용 조회 결과)
{chr(10).join(table_blocks)}

    ※ 소스 타입을 참고하여 이관 SQL의 타입 변환 표현식을 작성하십시오.
"""

    if target_ddl:
        formatted_target = _format_ddl_info(target_ddl)
        ddl_info_block += f"""
    [타겟 테이블 실제 DDL 정보] (사전 생성된 테이블, ALL_TAB_COLUMNS 읽기 전용 조회 결과)
    테이블: {to_table}
    {'컬럼명':<30} {'데이터타입':<25} {'NULL여부'}
    {'-'*70}
{formatted_target}

    ※ INSERT INTO 절의 컬럼명과 타입은 위 타겟 DDL 정보를 반드시 따르십시오.
"""

    if NEXT_SQL_INFO.correct_sql:
        logger.info(f"[LLM] map_id={NEXT_SQL_INFO.map_id} | 인간 전문가의 정답 SQL을 프롬프트에 반영합니다.")

    system_anthropic, system_openai, prompt = build_migration_prompt(
        from_table=from_table,
        to_table=to_table,
        mapping_info=mapping_info,
        ddl_info_block=ddl_info_block,
        is_append=is_append,
        correct_sql=NEXT_SQL_INFO.correct_sql or None,
        last_error=last_error,
        last_sql=last_sql,
    )

    try:
        logger.debug(f"[LLM_PROMPT] map_id={NEXT_SQL_INFO.map_id}\n{'='*60}\n{prompt}\n{'='*60}")
        if _resolve_llm_provider() == "anthropic":
            response = client.messages.create(
                model=model_name,
                max_tokens=int(os.getenv("LLM_MAX_TOKENS", "4096")),
                temperature=0,
                system=system_anthropic,
                messages=[{"role": "user", "content": prompt}],
            )
            result = _extract_json_object(_extract_anthropic_text(response))
        else:
            response = client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_openai},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"}
            )
            result = json.loads(response.choices[0].message.content)

        ddl_sql = result.get("ddl_sql", "")
        migration_sql = result.get("migration_sql", "")
        verification_sql = result.get("verification_sql", "")

        def merge_list(val):
            if isinstance(val, list):
                # 리스트 요소가 문자열이 아닌 경우(예: dict) 문자열로 변환하여 join
                str_list = [str(x) if not isinstance(x, dict) else (x.get("sql") or str(x)) for x in val]
                return "\n/\n".join(str_list)
            return val

        logger.info(f"[LLM] SQL 생성 완료 (Model: {model_name})")
        return (
            merge_list(ddl_sql),
            merge_list(migration_sql),
            merge_list(verification_sql)
        )

    except anthropic.AuthenticationError as e:
        logger.error(f"[LLM] Anthropic authentication failed: {e}")
        raise LLMAuthenticationError(f"Anthropic authentication failed: {str(e)}")
    except anthropic.RateLimitError as e:
        logger.error(f"[LLM] Anthropic rate limit exceeded: {e}")
        raise LLMRateLimitError(f"Anthropic rate limit exceeded: {str(e)}")
    except anthropic.BadRequestError as e:
        logger.error(f"[LLM] Anthropic bad request: {e}")
        raise LLMInvalidRequestError(f"Anthropic bad request: {str(e)}")
    except anthropic.APIStatusError as e:
        if e.status_code >= 500:
            logger.error(f"[LLM] Anthropic server error ({e.status_code}): {e}")
            raise LLMServerError(f"Anthropic server error: {str(e)}")
        logger.error(f"[LLM] Anthropic API error ({e.status_code}): {e}")
        raise LLMConnectionError(f"Anthropic API error: {str(e)}")
    except (anthropic.APIConnectionError, anthropic.APITimeoutError) as e:
        logger.error(f"[LLM] Anthropic connection/timeout error: {e}")
        raise LLMConnectionError(f"Anthropic connection failed: {str(e)}")
    except openai.AuthenticationError as e:
        logger.error(f"[LLM] 인증 실패 (API Key 확인 필요): {e}")
        raise LLMAuthenticationError(f"API Key 인증 실패: {str(e)}")
    except openai.RateLimitError as e:
        logger.error(f"[LLM] 호출 한도 초과 (429): {e}")
        raise LLMRateLimitError(f"API 호출 한도 초과: {str(e)}")
    except openai.BadRequestError as e:
        logger.error(f"[LLM] 잘못된 요청 (400): {e}")
        raise LLMInvalidRequestError(f"잘못된 요청 형식: {str(e)}")
    except openai.APIStatusError as e:
        if e.status_code >= 500:
            logger.error(f"[LLM] 서버 에러 ({e.status_code}): {e}")
            raise LLMServerError(f"LLM 서버 에러: {str(e)}")
        logger.error(f"[LLM] API 에러 ({e.status_code}): {e}")
        raise LLMConnectionError(f"LLM API 에러: {str(e)}")
    except (openai.APIConnectionError, openai.APITimeoutError) as e:
        logger.error(f"[LLM] 연결/타임아웃 에러: {e}")
        raise LLMConnectionError(f"LLM 연결 실패: {str(e)}")
    except Exception as e:
        logger.error(f"[LLM] 예상치 못한 에러: {e}")
        raise LLMConnectionError(f"LLM 호출 중 알 수 없는 에러: {str(e)}")
