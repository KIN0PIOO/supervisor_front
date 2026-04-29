# Unified Multi-Agent Migration Pipeline

Oracle 데이터 마이그레이션, MyBatis SQL 변환, SQL 튜닝을 LangGraph Supervisor 패턴으로 통합 관리하는 배치 프레임워크입니다. Supervisor가 3개의 작업 에이전트를 병렬로 오케스트레이션합니다.

## Architecture

```text
Supervisor (Parallel Orchestrator)
  - Mig Agent    : 데이터 이관 및 NEXT_SQL_INFO 작업 생성
  - SQL Agent    : MyBatis SQL -> TO-BE SQL 변환 및 기본 검증
  - Tuning Agent : RAG 기반 SQL 튜닝 및 튜닝 SQL 검증
```

## Agent Responsibilities

### 1. Mig Agent

- `NEXT_MIG_INFO`의 대기 작업을 처리합니다.
- 데이터 이관 성공 후 `NEXT_SQL_INFO`에 SQL 변환 작업을 생성합니다.
- 생성된 SQL 작업은 `STATUS='READY'` 상태로 SQL Agent가 처리합니다.

### 2. SQL Agent

- `NEXT_SQL_INFO`에서 `STATUS IN ('READY', 'PENDING', 'FAIL')` 또는 `STATUS IS NULL`인 작업을 처리합니다.
- `FR_SQL_TEXT` 또는 `EDIT_FR_SQL`을 기준으로 `TO_SQL_TEXT`를 생성합니다.
- SQL Agent 검증은 원본 SQL과 `TO_SQL_TEXT`의 row count를 비교합니다.
- 검증 성공 시 `STATUS='PASS'`를 저장하고, Tuning Agent가 처리할 수 있도록 `TUNED_TEST='READY'`를 저장합니다.
- SQL Agent는 튜닝 룰 RAG를 사용하지 않습니다.

### 3. Tuning Agent

- `NEXT_SQL_INFO.TUNED_TEST IN ('READY', 'FAIL')`인 작업을 처리합니다.
- `BATCH_CNT` 컬럼이 있으면 `BATCH_CNT < 30`인 작업만 재시도합니다.
- `TUNED_SQL` 값이 이미 있어도 재시도 시작 SQL은 항상 `TO_SQL_TEXT`입니다.
- `TOBE_SQL_TUNING_MAX_ITERATIONS`가 2 이상이면 같은 실행 안에서 직전 튜닝 결과를 다음 반복 입력으로 사용합니다.
- 튜닝 프롬프트의 `tuning_rule_block_rag_json`에 들어간 JSON 값을 `BLOCK_RAG_CONTENT`에 저장합니다.
- 최종 후보 SQL은 변경 여부와 관계없이 `TUNED_SQL`에 저장합니다.
- 튜닝 검증은 `TO_SQL_TEXT`와 `TUNED_SQL`의 row count 비교로 수행합니다.
- 검증 성공 시 `TUNED_TEST='PASS'`, 검증 실패 또는 예외 발생 시 `TUNED_TEST='FAIL'`을 저장합니다.
- `TUNED_TEST='FAIL'` 작업은 `BATCH_CNT < 30` 동안 다음 cycle에서 다시 튜닝됩니다.
- Supervisor는 Tuning Agent 작업을 한 cycle에 1건만 dispatch해 여러 row가 동시에 튜닝을 시작하지 않도록 합니다.

## Project Structure

```text
supervisor-main/
  main.py
  agents/
    supervisor/             # LangGraph supervisor loop and fan-out
    data_migration/         # Mig Agent
    sql_pipeline/           # SQL Agent and Tuning Agent
      prompts/
        tobe_sql_prompt.json
        bind_sql_prompt.json
        tobe_sql_tuning_prompt.json
      services/
      repositories/
      workflow/
  data/
    rag/
      tobe_rule_catalog.json
  tools/
    init_db.py
    list_mapping_rules.py
  requirements.txt
```

## Key DB Columns

- `STATUS`: SQL Agent의 `TO_SQL_TEXT` 기본 검증 결과입니다.
- `TO_SQL_TEXT`: SQL Agent가 생성한 TO-BE SQL입니다.
- `BLOCK_RAG_CONTENT`: Tuning Agent가 프롬프트에 넣은 RAG tuning rule JSON입니다.
- `TUNED_SQL`: Tuning Agent가 생성한 최종 튜닝 SQL입니다.
- `TUNED_TEST`: Tuning Agent 상태 및 검증 결과입니다. `READY`, `FAIL`, `PASS`를 사용합니다.
- `BATCH_CNT`: SQL 변환 및 튜닝 처리 시 증가하며, 튜닝 재시도는 30회 미만으로 제한됩니다.

## Environment

```env
ORACLE_USER=
ORACLE_PASSWORD=
ORACLE_DSN=
ORACLE_CLIENT_LIB_DIR=
ORACLE_SCHEMA=
MAPPING_RULE_TABLE=NEXT_MIG_INFO
MAPPING_RULE_DETAIL_TABLE=NEXT_MIG_INFO_DTL
RESULT_TABLE=NEXT_SQL_INFO

LLM_API_KEY=
LLM_MODEL=
LLM_BASE_URL=
LLM_PROVIDER=openai
LLM_MAX_TOKENS=4096

RAG_EMBED_BASE_URL=
RAG_EMBED_API_KEY=
RAG_EMBED_MODEL=BAAI/bge-m3
RAG_EMBED_TIMEOUT_SEC=30
TOBE_RULE_CATALOG_PATH=data/rag/tobe_rule_catalog.json
TOBE_SQL_TUNING_TOP_K=3
TOBE_SQL_TUNING_MAX_ITERATIONS=1
```

`LLM_PROVIDER`는 `openai` 또는 `anthropic`을 사용할 수 있습니다. Anthropic을 사용할 때는 예를 들어 `LLM_PROVIDER=anthropic`, `LLM_MODEL=claude-3-5-sonnet-20241022`, `LLM_BASE_URL=https://api.anthropic.com`처럼 설정합니다.

## Run

```bash
pip install -r requirements.txt
python tools/init_db.py
python main.py
```

## Verification

```bash
python -m compileall agents main.py tools
python -c "import agents.supervisor.agent; import agents.sql_pipeline.agents; print('imports ok')"
```
