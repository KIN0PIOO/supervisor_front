"""공유 예외 계층 — 두 에이전트의 예외를 통합한 단일 계층.

DataMigration 과 SqlPipeline 이 공통으로 사용하는 최상위 예외부터
각 에이전트 전용 예외까지 한 곳에서 관리한다.
"""


class AgentBaseException(Exception):
    """모든 에이전트 예외의 최상위 클래스."""


# ── 배치 제어 ──────────────────────────────────────────────────────────────

class BatchAbortError(AgentBaseException):
    """배치 전체를 즉시 중단해야 할 때 (LLM 인증 실패, 할당량 초과 등)."""


# ── LLM 호출 ──────────────────────────────────────────────────────────────

class LLMBaseError(AgentBaseException):
    """LLM API 호출 관련 모든 에러의 상위 예외."""


class LLMRateLimitError(LLMBaseError):
    """Rate limit / timeout — 재시도 가능."""


class LLMConnectionError(LLMBaseError):
    """네트워크 연결·타임아웃 문제."""


class LLMAuthenticationError(LLMBaseError):
    """API 키 오류 등 인증 실패 — BatchAbortError 트리거."""


class LLMTokenLimitError(LLMBaseError):
    """프롬프트 최대 토큰 초과."""


class LLMInvalidRequestError(LLMBaseError):
    """잘못된 요청 형식 (4xx)."""


class LLMServerError(LLMBaseError):
    """서버 측 오류 (5xx)."""


# ── DB 실행 ───────────────────────────────────────────────────────────────

class DBSqlError(AgentBaseException):
    """생성된 SQL 실행 중 DB 오류 — 재시도용."""


class VerificationFailError(AgentBaseException):
    """데이터 정합성 검증 실패."""
