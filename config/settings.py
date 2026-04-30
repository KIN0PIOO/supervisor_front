"""전역 설정 중앙화.

모든 에이전트/서비스는 각자 os.getenv() 대신 이 모듈을 import해서 씁니다.
기존 에이전트 코드는 그대로 두고, 신규 코드(Planner 등)부터 이 모듈을 사용합니다.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env")


# ── Oracle DB ────────────────────────────────────────────────────────────────
DB_USER             = os.getenv("DB_USER", "scott")
DB_PASS             = os.getenv("DB_PASS", "tiger")
DB_HOST             = os.getenv("DB_HOST", "localhost")
DB_PORT             = os.getenv("DB_PORT", "1521")
DB_SID              = os.getenv("DB_SID", "xe")
ORACLE_CLIENT_PATH  = os.getenv("ORACLE_CLIENT_PATH", "")

# ── LLM ──────────────────────────────────────────────────────────────────────
LLM_PROVIDER    = os.getenv("LLM_PROVIDER", "openai").strip().lower()
LLM_API_KEY     = (os.getenv("OPEN_API_KEY") or os.getenv("LLM_API_KEY") or "")
LLM_BASE_URL    = os.getenv("LLM_BASE_URL", "")
LLM_MODEL       = os.getenv("LLM_MODEL", "gpt-4o-mini")
LLM_MAX_TOKENS  = int(os.getenv("LLM_MAX_TOKENS", "4096"))

# ── DB 테이블명 ───────────────────────────────────────────────────────────────
MIG_TABLE       = os.getenv("MAPPING_RULE_TABLE",        "NEXT_MIG_INFO")
MIG_DTL_TABLE   = os.getenv("MAPPING_RULE_DETAIL_TABLE", "NEXT_MIG_INFO_DTL").strip()
SQL_TABLE       = os.getenv("RESULT_TABLE",              "NEXT_SQL_INFO")
SQL_RULES_TABLE = "NEXT_SQL_RULES"

# ── RAG / Tuning ─────────────────────────────────────────────────────────────
RAG_EMBED_BASE_URL   = os.getenv("RAG_EMBED_BASE_URL", "").strip()
RAG_EMBED_API_KEY    = os.getenv("RAG_EMBED_API_KEY", "").strip()
RAG_EMBED_MODEL      = os.getenv("RAG_EMBED_MODEL", "BAAI/bge-m3").strip()
TUNING_TOP_K         = int(os.getenv("TOBE_SQL_TUNING_TOP_K", "3"))
TUNING_MAX_ITER      = int(os.getenv("TOBE_SQL_TUNING_MAX_ITERATIONS", "1"))

# ── Planner ──────────────────────────────────────────────────────────────────
PLANNER_ENABLED          = os.getenv("PLANNER_ENABLED", "true").lower() == "true"
PLANNER_MAX_MIG_PER_CYCLE = int(os.getenv("PLANNER_MAX_MIG_PER_CYCLE", "5"))

# ── Runtime ───────────────────────────────────────────────────────────────────
RUNTIME_DIR  = _ROOT / "runtime"
MIG_KIND     = os.getenv("MIG_KIND", "DB_MIG")
