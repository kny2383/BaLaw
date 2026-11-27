"""LLM 호출 계층.

서비스 코드는 작업 이름과 메시지, 출력 형식만 넘긴다. 어떤 모델을 어디로 부를지는 설정이 정한다 (결정 0002).

    text("compose", user, system=...)          글로 된 출력
    parsed("extract", system, user, Schema)    스키마에 맞는 구조화 출력

- 작업별 모델: `LLM_MODEL_<작업>` (예: LLM_MODEL_EXTRACT). 없으면 이전과 같은 기본값이다.
- 작업별 주소: `LLM_BASE_URL_<작업>`. OpenAI 호환 API를 내는 다른 서버(로컬 모델 등)로 보낼 때 쓴다.
  이때 OpenAI 키는 보내지 않는다. 그 서버의 키가 있으면 `LLM_API_KEY_<작업>`으로 준다.
- 모든 호출은 같은 형식으로 기록한다: 작업, 세션 표지, 모델, 프롬프트 판본, 토큰, 비용, 걸린 시간, 성공 여부.
  내용은 기록하지 않는다.
- 실패는 빈 값으로 바꾸지 않고 예외로 올린다 (지표 M10).

모델 객체는 LangChain의 채팅 모델 인터페이스를 쓴다 (결정 0003). 지금 연결된 공급자는 OpenAI와
OpenAI 호환 서버다. 다른 공급자는 `_PROVIDERS`에 모델을 만드는 함수를 더해 붙인다.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from collections import deque
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Optional, Type

from langchain_openai import ChatOpenAI
from openai.lib._parsing import type_to_response_format_param
from pydantic import BaseModel, ValidationError

from cfg import settings

TASKS = ("extract", "compose", "verify", "rewrite", "rag_keyword", "rag_summary")

# 최근 호출 기록. 내용 없이 수치만 담는다. 서비스가 재시작하면 비고, 그 전 기록은 로그에 남아 있다.
RECENT: deque = deque(maxlen=5000)
_recent_lock = threading.Lock()


def recent() -> list:
    """최근 호출 기록의 사본. 호출이 진행 중이어도 안전하게 읽는다."""
    with _recent_lock:
        return list(RECENT)


_session: ContextVar[Optional[str]] = ContextVar("llm_session", default=None)


def session_tag(session_id: str) -> str:
    """기록에 남기는 세션 표지. 세션 값 자체는 그 세션의 대화를 읽을 수 있는 값이라 로그에 남기지 않는다."""
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:12]


@contextmanager
def session(session_id: str):
    """이 안에서 일어난 호출의 기록에 세션 표지를 붙인다. 고소장 한 건의 호출을 묶어 보기 위해서다."""
    token = _session.set(session_tag(session_id))
    try:
        yield
    finally:
        _session.reset(token)


class LLMCallError(RuntimeError):
    """LLM에서 쓸 수 있는 결과를 받지 못했다 (다시 시도한 뒤에도 실패한 호출, 빈 출력)."""


class StructuredOutputError(LLMCallError):
    """구조화 출력을 받지 못했다 (호출 오류, 모델의 거부, 잘리거나 스키마에 맞지 않는 출력)."""


NO_KEY = "not-needed"  # 키가 필요 없는 서버에 보내는 자리 채움 값


def _openai_model(name: str, base_url: Optional[str], reasoning_effort: Optional[str], api_key: Optional[str] = None):
    # 작업별 주소를 지정했으면 OpenAI 키를 보내지 않는다. 그 서버의 키는 LLM_API_KEY_<작업>으로 따로 준다.
    # 다른 서버에 OpenAI 키가 Authorization 헤더로 실려 가는 것을 막기 위해서다.
    if base_url:
        key = api_key or NO_KEY
    else:
        key = api_key or settings.OPENAI_API_KEY
    if not key:
        raise RuntimeError("OPENAI_API_KEY가 설정되어 있지 않습니다. .env를 확인하세요.")
    # 추론 강도를 지정하지 않으면 요청에 넣지 않는다 (모델 기본값).
    options = {"reasoning_effort": reasoning_effort} if reasoning_effort else {}
    # 연결 오류, 시간 초과, 429, 5xx는 간격을 늘려 가며 다시 시도한다. 그래도 실패하면 예외가 올라온다.
    return ChatOpenAI(model=name, api_key=key, base_url=base_url or os.getenv("OPENAI_BASE_URL") or None,
                      max_retries=settings.OPENAI_MAX_RETRIES, **options)


_PROVIDERS = {"openai": _openai_model}
_models: dict = {}


def spec(task: str) -> tuple[str, str]:
    """작업에 쓰는 (공급자, 모델 이름). 설정 값이 '공급자:모델' 꼴이 아니면 OpenAI다."""
    value = settings.LLM_MODELS[task]
    provider, _, name = value.partition(":")
    return (provider, name) if name and provider in _PROVIDERS else ("openai", value)


def _model(task: str):
    if task not in _models:
        provider, name = spec(task)
        _models[task] = _PROVIDERS[provider](name, settings.LLM_BASE_URLS.get(task), settings.LLM_REASONING_EFFORTS.get(task),
                                             settings.LLM_API_KEYS.get(task))
    return _models[task]


def reset() -> None:
    """만들어 둔 모델 객체를 버린다 (설정을 바꾼 테스트용)."""
    _models.clear()


_ROOT = Path(__file__).resolve().parent.parent
# 단가표 (100만 토큰당 달러). 평가기도 같은 파일을 읽는다.
PRICES: dict = json.loads((_ROOT / "prices.json").read_text(encoding="utf-8"))
# 작업별 프롬프트 판본. 기준 요청(tests/fixtures/llm_requests.json)을 다시 만들 때 함께 만들어진다.
PROMPT_VERSIONS: dict = json.loads((_ROOT / "prompt_versions.json").read_text(encoding="utf-8"))


def prompt_version_of(body: dict) -> str:
    """요청 본문에서 프롬프트 판본을 만든다. 메시지와 출력 형식이 같으면 같은 판본이다 (모델과 추론 강도는 뺀다)."""
    core = {"messages": body.get("messages"), "response_format": body.get("response_format")}
    return hashlib.sha256(json.dumps(core, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:8]


def cost_usd(task: str, model: Optional[str], input_tokens: Optional[int], cached_tokens: Optional[int],
             output_tokens: Optional[int]) -> Optional[float]:
    """호출 한 번의 비용. 계산할 수 없으면 0이 아니라 None이다.

    토큰 수가 없거나, 단가표에 없는 모델이거나, 다른 서버로 보낸 작업(단가가 다르다)이면 계산하지 않는다.
    캐시된 입력 토큰은 캐시 단가로 계산한다. 추론 토큰은 출력 토큰에 들어 있다.
    """
    if input_tokens is None or output_tokens is None or settings.LLM_BASE_URLS.get(task):
        return None
    price = PRICES["models"].get(PRICES["aliases"].get(model, model))
    if not price:
        return None
    cached = cached_tokens or 0
    fresh = input_tokens - cached
    return round((fresh * price["input"] + cached * price.get("cached_input", price["input"])
                  + output_tokens * price["output"]) / 1e6, 8)


def _record(task: str, started: float, message=None, error: Optional[str] = None) -> None:
    provider, name = spec(task)
    usage = getattr(message, "usage_metadata", None) or {}
    response_model = (getattr(message, "response_metadata", None) or {}).get("model_name")
    cached = (usage.get("input_token_details") or {}).get("cache_read")
    rec = {
        "task": task, "session": _session.get(), "provider": provider, "model": name, "response_model": response_model,
        "prompt_version": PROMPT_VERSIONS.get(task),
        "input_tokens": usage.get("input_tokens"), "cached_tokens": cached, "output_tokens": usage.get("output_tokens"),
        "reasoning_tokens": (usage.get("output_token_details") or {}).get("reasoning"),
        "cost_usd": cost_usd(task, response_model or name, usage.get("input_tokens"), cached, usage.get("output_tokens")),
        "latency_s": round(time.time() - started, 3), "ok": error is None, "error": error,
    }
    with _recent_lock:
        RECENT.append(rec)
    print("[LLM] " + json.dumps(rec, ensure_ascii=False))


def _invoke(task: str, system: Optional[str], user: str, error_type: type, response_format: Optional[dict] = None):
    messages = ([("system", system)] if system is not None else []) + [("user", user)]
    started = time.time()
    try:
        model = _model(task)
        if response_format is not None:
            model = model.bind(response_format=response_format)
        message = model.invoke(messages)
    except Exception as e:
        # 예외 본문에는 요청 내용(사용자 서술)이 들어갈 수 있어 종류만 남긴다.
        _record(task, started, error=type(e).__name__)
        raise error_type(type(e).__name__) from e
    return message, started


def text(task: str, user: str, system: Optional[str] = None) -> str:
    """글로 된 출력을 받는다. 실패하거나 출력이 비면 LLMCallError를 던진다."""
    message, started = _invoke(task, system, user, LLMCallError)
    out = message.content.strip() if isinstance(message.content, str) else ""
    if not out:
        _record(task, started, message, error="empty_output")
        raise LLMCallError("empty_output")
    _record(task, started, message)
    return out


def parsed(task: str, system: str, user: str, schema: Type[BaseModel]) -> BaseModel:
    """스키마에 맞는 구조화 출력을 받아 검증된 객체로 돌려준다. 실패하면 StructuredOutputError를 던진다."""
    message, started = _invoke(task, system, user, StructuredOutputError, type_to_response_format_param(schema))
    content = message.content if isinstance(message.content, str) else ""
    try:
        out = schema.model_validate_json(content)
    except ValidationError:
        reason = "refusal" if (message.additional_kwargs or {}).get("refusal") else "no_parsed_output"
        _record(task, started, message, error=reason)
        raise StructuredOutputError(reason)
    _record(task, started, message)
    return out
