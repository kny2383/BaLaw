import os

from dotenv import load_dotenv


load_dotenv()


REASONING_EFFORTS = ("minimal", "low", "medium", "high")


def _reasoning_effort(name: str) -> str:
    """추론 강도 설정을 읽는다. 비어 있으면 요청에 넣지 않아 모델 기본값으로 동작한다.

    잘못된 값은 시작할 때 막는다. 그대로 보내면 호출이 실패하고, 지금 호출 계층은
    실패를 빈 문자열로 돌려주기 때문에 모든 항목이 조용히 '없음'으로 처리된다.
    """
    value = os.getenv(name, "").strip().lower()
    if value and value not in REASONING_EFFORTS:
        raise ValueError(f"{name}={value!r}: {', '.join(REASONING_EFFORTS)} 중 하나이거나 비어 있어야 합니다.")
    return value


class Settings:
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_COMPOSE_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-5")
    OPENAI_CHAT_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-5-mini")
    # 정보 추출 호출의 추론 강도. 비어 있으면 모델 기본값.
    OPENAI_EXTRACT_REASONING_EFFORT: str = _reasoning_effort("OPENAI_EXTRACT_REASONING_EFFORT")
    RAG_DB_URL: str = os.getenv("RAG_DB_URL", "")
    REDIS_URL: str = os.getenv("REDIS_URL", "")
    RAG_CASE_CACHE_TTL_SECONDS: int = int(os.getenv("RAG_CASE_CACHE_TTL_SECONDS", "604800"))
    RAG_CASE_SUMMARY_VERSION: str = os.getenv("RAG_CASE_SUMMARY_VERSION", "v1")

settings = Settings()
