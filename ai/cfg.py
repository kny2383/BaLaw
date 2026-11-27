import base64
import os

from dotenv import load_dotenv


load_dotenv()


# 모델 세대마다 받는 값이 다르다. gpt-5 계열은 minimal~high, gpt-6 계열은 none·low~max다 (minimal 없음).
# 여기서는 오타만 막는다. 모델이 받지 않는 값을 주면 호출이 오류로 올라온다.
REASONING_EFFORTS = ("none", "minimal", "low", "medium", "high", "xhigh", "max")


def _reasoning_effort(name: str, default: str) -> str:
    """추론 강도 설정을 읽는다. 값이 없거나 비어 있으면 default를 쓴다.

    목록에 없는 값(오타)은 시작할 때 막는다. 목록에는 있지만 그 모델이 받지 않는 값은 여기서 걸리지 않고,
    첫 호출이 오류로 올라온다 (호출 계층은 실패를 빈 값으로 바꾸지 않는다).
    """
    value = os.getenv(name, "").strip().lower() or default
    if value not in REASONING_EFFORTS:
        raise ValueError(f"{name}={value!r}: {', '.join(REASONING_EFFORTS)} 중 하나여야 합니다.")
    return value


def _checkpoint_key(name: str) -> bytes:
    """체크포인트 암호화 키(base64로 적은 32바이트)를 읽는다. 값이 없으면 빈 바이트."""
    raw = os.getenv(name, "").strip()
    if not raw:
        return b""
    try:
        key = base64.b64decode(raw, validate=True)
    except Exception:
        raise ValueError(f"{name}: base64로 적은 값이어야 합니다.")
    if len(key) != 32:
        raise ValueError(f"{name}: 32바이트 키여야 합니다 (지금 {len(key)}바이트).")
    return key


def _at_least_one(name: str, default: int) -> int:
    """1 이상의 정수 설정을 읽는다. 0 이하는 시작할 때 막는다."""
    value = int(os.getenv(name, "").strip() or default)
    if value < 1:
        raise ValueError(f"{name}={value}: 1 이상이어야 합니다.")
    return value


LLM_TASKS = ("extract", "compose", "verify", "rewrite", "rag_keyword", "rag_summary")


def _per_task(prefix: str, defaults: dict) -> dict:
    """작업별 설정을 읽는다. `<prefix>_<작업>` 환경 변수가 있으면 그 값, 없으면 기본값. 값이 없는 작업은 뺀다."""
    out = {}
    for task in LLM_TASKS:
        value = os.getenv(f"{prefix}_{task.upper()}", "").strip() or defaults.get(task)
        if value:
            out[task] = value
    return out


class Settings:
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_COMPOSE_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-5")
    OPENAI_CHAT_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-5-mini")
    # 작업별 모델. LLM_MODEL_<작업>으로 바꾼다 (예: LLM_MODEL_EXTRACT). 기본값은 위의 두 모델로, 이전과 같다.
    LLM_MODELS: dict = _per_task("LLM_MODEL", {
        "extract": OPENAI_CHAT_MODEL, "verify": OPENAI_CHAT_MODEL,
        "compose": OPENAI_COMPOSE_MODEL, "rewrite": OPENAI_COMPOSE_MODEL,
        "rag_keyword": OPENAI_COMPOSE_MODEL, "rag_summary": OPENAI_COMPOSE_MODEL,
    })
    # 작업별 주소. OpenAI 호환 API를 내는 다른 서버로 보낼 때만 LLM_BASE_URL_<작업>으로 지정한다.
    LLM_BASE_URLS: dict = _per_task("LLM_BASE_URL", {})
    # 작업별 주소를 쓰는 서버의 키. 주소를 지정한 작업에는 OPENAI_API_KEY를 보내지 않는다.
    LLM_API_KEYS: dict = _per_task("LLM_API_KEY", {})
    # 이 서비스를 부르는 쪽(서버)이 보내야 하는 토큰. 값을 넣으면 /chat/* 주소가 이 토큰을 요구한다.
    # 비우면 요구하지 않는다 (누구나 부를 수 있다). 운영 구성은 값이 없으면 뜨지 않는다.
    BARO_AI_TOKEN: str = os.getenv("BARO_AI_TOKEN", "").strip()
    # 호출 기록 집계(GET /llm/stats)를 읽는 토큰. 비워 두면 그 주소는 닫혀 있다 (404).
    LLM_STATS_TOKEN: str = os.getenv("LLM_STATS_TOKEN", "").strip()
    # LLM 호출이 일시적 오류(연결, 시간 초과, 429, 5xx)로 실패했을 때 다시 시도하는 횟수.
    OPENAI_MAX_RETRIES: int = int(os.getenv("OPENAI_MAX_RETRIES", "").strip() or "2")
    # 정보 추출 호출의 추론 강도. 기본값 low의 근거는 eval/results/extract-low-dev10.md.
    # 지정하지 않던 이전 동작(모델 기본값)과 비교하려면 medium으로 둔다.
    OPENAI_EXTRACT_REASONING_EFFORT: str = _reasoning_effort("OPENAI_EXTRACT_REASONING_EFFORT", "low")
    # 작업별 추론 강도. 지정하지 않은 작업은 요청에 넣지 않는다 (모델 기본값).
    LLM_REASONING_EFFORTS: dict = {"extract": OPENAI_EXTRACT_REASONING_EFFORT}
    # 초안을 대화와 대조해 근거 없는 표현을 고쳐 다시 쓰는 횟수의 상한. 0이면 검증하지 않는다.
    DRAFT_MAX_REWRITES: int = int(os.getenv("DRAFT_MAX_REWRITES", "").strip() or "1")
    # 검증이 찾은 표현을 고치기 전에 사용자에게 사실인지 묻는다 (기본 켜짐). 0이면 묻지 않고 고친다.
    # 켜 두려면 호출하는 쪽이 awaiting_confirmation 응답을 다뤄야 한다 (서버의 /generate/confirm, 화면의 확인 창).
    DRAFT_CONFIRM: bool = os.getenv("DRAFT_CONFIRM", "").strip() != "0"
    # 한 번에 묻는 표현 개수의 상한. 넘는 것은 묻지 않고 고친다.
    DRAFT_CONFIRM_MAX: int = _at_least_one("DRAFT_CONFIRM_MAX", 5)
    # 사용자 서술의 식별정보를 표식으로 바꿔 LLM에 보낸다 (S05). 0이면 끈다 (전후 비교용).
    PII_MASKING: bool = os.getenv("PII_MASKING", "").strip() != "0"
    # 대화 상태(체크포인트) 저장소. 비우면 메모리에 두고 서비스가 재시작하면 사라진다.
    # 값을 넣으면 PostgreSQL에 저장하며, 이때 암호화 키가 없으면 서비스가 뜨지 않는다.
    CHECKPOINT_DB_URL: str = os.getenv("CHECKPOINT_DB_URL", "").strip()
    CHECKPOINT_AES_KEY: bytes = _checkpoint_key("CHECKPOINT_AES_KEY")
    # 기본은 세션마다 최신 상태 하나만 남긴다. 단계별 기록을 남기려면 1로 둔다 (가상 사례 분석용).
    CHECKPOINT_KEEP_HISTORY: bool = os.getenv("CHECKPOINT_KEEP_HISTORY", "").strip() == "1"
    RAG_DB_URL: str = os.getenv("RAG_DB_URL", "")
    REDIS_URL: str = os.getenv("REDIS_URL", "")
    RAG_CASE_CACHE_TTL_SECONDS: int = int(os.getenv("RAG_CASE_CACHE_TTL_SECONDS", "604800"))
    RAG_CASE_SUMMARY_VERSION: str = os.getenv("RAG_CASE_SUMMARY_VERSION", "v1")

settings = Settings()
