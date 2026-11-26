"""LLM 호출 계층.

서비스 코드는 작업 이름과 메시지, 출력 형식만 넘긴다. 어떤 모델을 어디로 부를지는 설정이 정한다 (결정 0002).

    text("compose", user, system=...)          글로 된 출력
    parsed("extract", system, user, Schema)    스키마에 맞는 구조화 출력

- 작업별 모델: `LLM_MODEL_<작업>` (예: LLM_MODEL_EXTRACT). 없으면 이전과 같은 기본값이다.
- 작업별 주소: `LLM_BASE_URL_<작업>`. OpenAI 호환 API를 내는 다른 서버(로컬 모델 등)로 보낼 때 쓴다.
- 모든 호출은 같은 형식으로 기록한다: 작업, 모델, 토큰, 걸린 시간, 성공 여부. 내용은 기록하지 않는다.
- 실패는 빈 값으로 바꾸지 않고 예외로 올린다 (지표 M10).

모델 객체는 LangChain의 채팅 모델 인터페이스를 쓴다 (결정 0003). 지금 연결된 공급자는 OpenAI와
OpenAI 호환 서버다. 다른 공급자는 `_PROVIDERS`에 모델을 만드는 함수를 더해 붙인다.
"""
from __future__ import annotations

import json
import os
import time
from collections import deque
from typing import Optional, Type

from langchain_openai import ChatOpenAI
from openai.lib._parsing import type_to_response_format_param
from pydantic import BaseModel, ValidationError

from cfg import settings

TASKS = ("extract", "compose", "verify", "rewrite", "rag_keyword", "rag_summary")

# 최근 호출 기록 (테스트와 점검용). 내용 없이 수치만 담는다.
RECENT: deque = deque(maxlen=200)


class LLMCallError(RuntimeError):
    """LLM에서 쓸 수 있는 결과를 받지 못했다 (다시 시도한 뒤에도 실패한 호출, 빈 출력)."""


class StructuredOutputError(LLMCallError):
    """구조화 출력을 받지 못했다 (호출 오류, 모델의 거부, 잘리거나 스키마에 맞지 않는 출력)."""


def _openai_model(name: str, base_url: Optional[str], reasoning_effort: Optional[str]):
    if not settings.OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY가 설정되어 있지 않습니다. .env를 확인하세요.")
    # 추론 강도를 지정하지 않으면 요청에 넣지 않는다 (모델 기본값).
    options = {"reasoning_effort": reasoning_effort} if reasoning_effort else {}
    # 연결 오류, 시간 초과, 429, 5xx는 간격을 늘려 가며 다시 시도한다. 그래도 실패하면 예외가 올라온다.
    return ChatOpenAI(model=name, api_key=settings.OPENAI_API_KEY, base_url=base_url or os.getenv("OPENAI_BASE_URL") or None,
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
        _models[task] = _PROVIDERS[provider](name, settings.LLM_BASE_URLS.get(task), settings.LLM_REASONING_EFFORTS.get(task))
    return _models[task]


def reset() -> None:
    """만들어 둔 모델 객체를 버린다 (설정을 바꾼 테스트용)."""
    _models.clear()


def _record(task: str, started: float, message=None, error: Optional[str] = None) -> None:
    provider, name = spec(task)
    usage = getattr(message, "usage_metadata", None) or {}
    rec = {
        "task": task, "provider": provider, "model": name,
        "response_model": (getattr(message, "response_metadata", None) or {}).get("model_name"),
        "input_tokens": usage.get("input_tokens"), "output_tokens": usage.get("output_tokens"),
        "reasoning_tokens": (usage.get("output_token_details") or {}).get("reasoning"),
        "latency_s": round(time.time() - started, 3), "ok": error is None, "error": error,
    }
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
