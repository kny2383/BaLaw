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
        _client = OpenAI(api_key=settings.OPENAI_API_KEY)
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

def respond(model: str, system: str, user: str, reasoning_effort: Optional[str] = None) -> str:
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
        return _extract_output_text(resp).strip()
    except Exception as e:
        print(f"Error during OpenAI API call: {e}")
        return ""


def respond_parsed(model: str, system: str, user: str, schema: Type[BaseModel],
                   reasoning_effort: Optional[str] = None) -> Optional[BaseModel]:
    """스키마에 맞는 구조화 출력을 받아 검증된 객체로 돌려준다. 실패하면 None.

    실패: 호출 오류, 모델의 거부, 출력이 잘려 스키마 검증을 통과하지 못한 경우.
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
        message = resp.choices[0].message
        if message.parsed is None:
            print(f"Structured output missing (refusal={getattr(message, 'refusal', None)!r})")
        return message.parsed
    except Exception as e:
        print(f"Error during OpenAI structured call: {e}")
        return None
