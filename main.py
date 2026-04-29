"""멀티 에이전트 시스템 진입점.

세 개의 에이전트를 LangGraph Supervisor 패턴으로 통합 구동한다.

아키텍처:

  SupervisorAgent (LangGraph state machine)
    │
    ├─ supervisor_node     : DB 폴링 + 라우팅 결정
    │
    ├─ dispatch_node       : Send 로 작업 fan-out
    │     ├── Send → data_migration_agent 노드 (tool)
    │     │         MappingRule 1건 → MigrationOrchestrator
    │     └── Send → sql_pipeline_agent 노드 (tool)
    │                SqlInfoJob 1건 → TobeMultiAgentCoordinator
    │                                 (TobeSqlGenerationAgent + SqlTuningAgent)
    └─ wait_node           : 10초 대기 후 supervisor_node 로 복귀

폴링 주기:
  Mig Agent     : 매 사이클 (10초)
  SQL Agent     : 60초마다
  Tuning Agent  : 60초마다

실행:
  python main.py
"""

import sys
import os
from pathlib import Path
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent
ENV_PATH = ROOT_DIR / ".env"

if ENV_PATH.exists():
    load_dotenv(ENV_PATH, override=True)
else:
    print(f"ERROR: {ENV_PATH} 파일을 찾을 수 없습니다. 실행을 중단합니다.")
    sys.exit(1)

from agents.supervisor.agent import SupervisorAgent
from tools.init_db import run_all_checks

def startup_check():
    """실행 전 DB 및 LLM 연결 상태를 점검합니다."""
    print("\n[Startup] 연결 상태를 점검 중...")
    try:
        from tools.init_db import check_oracle_connection, check_llm_connection, check_tables
        checks = [
            check_oracle_connection(),
            check_llm_connection(),
            *check_tables()
        ]
        
        all_ok = True
        for res in checks:
            icon = "✓" if res.ok else "✗"
            print(f"  [{icon}] {res.name:<35} {res.detail}")
            if not res.ok:
                all_ok = False
        
        if not all_ok:
            print("\nERROR: 연결 상태 점검이 실패하였습니다. .env 설정을 확인해주세요.")
            sys.exit(1)
        print("SUCCESS: 모든 연결이 확인되었습니다.\n")
    except Exception as e:
        print(f"\nERROR: 점검 도중 예상치 못한 오류가 발생했습니다: {e}")
        sys.exit(1)

if __name__ == "__main__":
    startup_check()
    SupervisorAgent().run()
