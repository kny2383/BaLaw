import base64
import os

from dotenv import load_dotenv


load_dotenv()


REASONING_EFFORTS = ("minimal", "low", "medium", "high")


def _reasoning_effort(name: str, default: str) -> str:
    """추론 강도 설정을 읽는다. 값이 없거나 비어 있으면 default를 쓴다.

    잘못된 값은 시작할 때 막는다. 그대로 보내면 호출이 실패하고, 지금 호출 계층은
    실패를 빈 문자열로 돌려주기 때문에 모든 항목이 조용히 '없음'으로 처리된다.
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


class Settings:
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_COMPOSE_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-5")
    OPENAI_CHAT_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-5-mini")
    # 정보 추출 호출의 추론 강도. 기본값 low의 근거는 eval/results/extract-low-dev10.md.
    # 지정하지 않던 이전 동작(모델 기본값)과 비교하려면 medium으로 둔다.
    OPENAI_EXTRACT_REASONING_EFFORT: str = _reasoning_effort("OPENAI_EXTRACT_REASONING_EFFORT", "low")
    # 초안을 대화와 대조해 근거 없는 표현을 고쳐 다시 쓰는 횟수의 상한. 0이면 검증하지 않는다.
    DRAFT_MAX_REWRITES: int = int(os.getenv("DRAFT_MAX_REWRITES", "").strip() or "1")
    # 검증이 찾은 표현을 고치기 전에 사용자에게 사실인지 묻는다. 꺼 두면(기본) 묻지 않고 고친다.
    DRAFT_CONFIRM: bool = os.getenv("DRAFT_CONFIRM", "").strip() == "1"
    # 한 번에 묻는 표현 개수의 상한. 넘는 것은 묻지 않고 고친다.
    DRAFT_CONFIRM_MAX: int = int(os.getenv("DRAFT_CONFIRM_MAX", "").strip() or "5")
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
