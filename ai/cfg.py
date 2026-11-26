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


class Settings:
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_COMPOSE_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-5")
    OPENAI_CHAT_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-5-mini")
    # 정보 추출 호출의 추론 강도. 기본값 low의 근거는 eval/results/extract-low-dev10.md.
    # 지정하지 않던 이전 동작(모델 기본값)과 비교하려면 medium으로 둔다.
    OPENAI_EXTRACT_REASONING_EFFORT: str = _reasoning_effort("OPENAI_EXTRACT_REASONING_EFFORT", "low")
    RAG_DB_URL: str = os.getenv("RAG_DB_URL", "")
    REDIS_URL: str = os.getenv("REDIS_URL", "")
    RAG_CASE_CACHE_TTL_SECONDS: int = int(os.getenv("RAG_CASE_CACHE_TTL_SECONDS", "604800"))
    RAG_CASE_SUMMARY_VERSION: str = os.getenv("RAG_CASE_SUMMARY_VERSION", "v1")

settings = Settings()
