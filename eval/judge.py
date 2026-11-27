"""평가 판정 모델 호출 계층 (결정 0002).

평가기는 judge(provider, model, system, user, schema)만 부른다. 공급자를 추가할 때는
이 파일에 어댑터 함수 하나를 더하고 PROVIDERS에 등록한다. 지금은 OpenAI만 구현했다.

표준 라이브러리만 쓴다 (urllib).
"""

import json
import os
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field


@dataclass
class JudgeResult:
    data: dict
    provider: str
    model: str
    response_model: str | None
    usage: dict = field(default_factory=dict)
    latency_s: float = 0.0


class JudgeError(RuntimeError):
    """판정 호출 실패. 빈 결과로 바꾸지 않고 사례 결과에 오류로 남긴다."""


def _ssl_context() -> ssl.SSLContext:
    """python.org 설치본은 시스템 인증서를 쓰지 않으므로 certifi 또는 macOS 인증서 묶음을 쓴다."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        pem = "/etc/ssl/cert.pem"
        return ssl.create_default_context(cafile=pem) if os.path.exists(pem) else ssl.create_default_context()


_CTX = _ssl_context()


def _post_json(url: str, headers: dict, body: dict, timeout: float = 300) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_CTX) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        raise JudgeError(f"HTTP {e.code}: {e.read()[:300]!r}") from e
    except Exception as e:
        raise JudgeError(str(e)) from e


def _openai(model: str, system: str, user: str, schema: dict, reasoning_effort: str | None = None) -> JudgeResult:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise JudgeError("OPENAI_API_KEY가 없다")
    started = time.time()
    resp = _post_json(
        "https://api.openai.com/v1/chat/completions",
        {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        {
            "model": model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {"type": "json_schema", "json_schema": {"name": "judgement", "strict": True, "schema": schema}},
            # 추론 강도를 지정하지 않으면 요청에 넣지 않는다 (모델 기본값).
            **({"reasoning_effort": reasoning_effort} if reasoning_effort else {}),
        },
    )
    try:
        data = json.loads(resp["choices"][0]["message"]["content"])
    except Exception as e:
        raise JudgeError(f"판정 결과를 JSON으로 읽지 못했다: {e}") from e
    u = resp.get("usage") or {}
    details = u.get("completion_tokens_details") or {}
    cached = (u.get("prompt_tokens_details") or {}).get("cached_tokens")
    return JudgeResult(
        data=data, provider="openai", model=model, response_model=resp.get("model"),
        usage={"prompt_tokens": u.get("prompt_tokens"), "completion_tokens": u.get("completion_tokens"),
               "reasoning_tokens": details.get("reasoning_tokens"), "cached_tokens": cached},
        latency_s=round(time.time() - started, 3),
    )


PROVIDERS = {"openai": _openai}


def judge(provider: str, model: str, system: str, user: str, schema: dict,
          reasoning_effort: str | None = None) -> JudgeResult:
    if provider not in PROVIDERS:
        raise JudgeError(f"아직 구현하지 않은 판정 공급자: {provider} (가능: {sorted(PROVIDERS)})")
    return PROVIDERS[provider](model, system, user, schema, reasoning_effort)
