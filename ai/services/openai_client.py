# services/openai_client.py
from typing import Optional, Type
from pydantic import BaseModel
from openai import OpenAI
from cfg import settings

_client: Optional[OpenAI] = None

def client() -> OpenAI:
    global _client
    if _client is None:
        if not settings.OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY가 설정되어 있지 않습니다. .env를 확인하세요.")
        # 연결 오류, 시간 초과, 429, 5xx는 SDK가 간격을 늘려 가며 다시 시도한다. 그래도 실패하면 예외가 올라온다.
        _client = OpenAI(api_key=settings.OPENAI_API_KEY, max_retries=settings.OPENAI_MAX_RETRIES)
    return _client

def _extract_output_text(resp) -> str:
    """
    Responses API와 Chat Completions API를 모두 커버하는 출력 파서.
    """
    # Responses API (신규): resp.output_text 속성 제공
    txt = getattr(resp, "output_text", None)
    if isinstance(txt, str) and txt.strip():
        return txt

    # Responses API (수동 파싱)
    try:
        parts = resp.output[0].content
        if parts and hasattr(parts[0], "text"):
            return parts[0].text.value
    except Exception:
        pass

    # Chat Completions
    try:
        return resp.choices[0].message.content
    except Exception:
        pass

    return ""

class LLMCallError(RuntimeError):
    """LLM에서 쓸 수 있는 결과를 받지 못했다 (다시 시도한 뒤에도 실패한 호출, 빈 출력)."""


def respond(model: str, system: str, user: str, reasoning_effort: Optional[str] = None) -> str:
    """글로 된 출력을 받는다. 실패하거나 출력이 비면 LLMCallError를 던진다.

    예전에는 실패를 빈 문자열로 돌려줬고, 그 빈 문자열이 빈 초안으로 저장됐다 (지표 M10).
    """
    c = client()
    # 추론 강도를 지정하지 않으면 요청에 넣지 않는다 (모델 기본값).
    options = {"reasoning_effort": reasoning_effort} if reasoning_effort else {}

    try:
        resp = c.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            **options,
        )
    except Exception as e:
        # 예외 본문에는 요청 내용(사용자 서술)이 들어갈 수 있어 종류만 남긴다.
        print(f"[LLM] 호출 실패: {type(e).__name__}")
        raise LLMCallError(type(e).__name__) from e
    text = (_extract_output_text(resp) or "").strip()
    if not text:
        print("[LLM] 빈 출력")
        raise LLMCallError("empty_output")
    return text


class StructuredOutputError(LLMCallError):
    """구조화 출력을 받지 못했다 (호출 오류, 모델의 거부, 잘리거나 스키마에 맞지 않는 출력)."""


def respond_parsed(model: str, system: str, user: str, schema: Type[BaseModel],
                   reasoning_effort: Optional[str] = None) -> BaseModel:
    """스키마에 맞는 구조화 출력을 받아 검증된 객체로 돌려준다.

    실패하면 StructuredOutputError를 던진다. 빈 결과로 바꿔 돌려주지 않는다.
    """
    c = client()
    options = {"reasoning_effort": reasoning_effort} if reasoning_effort else {}

    try:
        resp = c.chat.completions.parse(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format=schema,
            **options,
        )
    except Exception as e:
        # 예외 본문에는 모델 출력(사용자 서술 인용)이 들어갈 수 있어 종류만 남긴다.
        print(f"[LLM] 구조화 출력 호출 실패: {type(e).__name__}")
        raise StructuredOutputError(f"{type(e).__name__}") from e

    message = resp.choices[0].message
    if message.parsed is None:
        reason = "refusal" if getattr(message, "refusal", None) else "no_parsed_output"
        print(f"[LLM] 구조화 출력 없음: {reason}")
        raise StructuredOutputError(reason)
    return message.parsed
