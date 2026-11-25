"""OpenAI 요청 기록 장치.

AI 서비스의 OpenAI 호출을 그대로 전달하면서 호출마다 모델, 토큰, 지연,
요청 본문을 JSONL로 기록한다. 서비스 코드는 바꾸지 않고 AI 컨테이너에
OPENAI_BASE_URL=http://llm-proxy:8080/v1 만 지정해서 쓴다.

제어 (평가기가 사용):
  GET  /_control            현재 설정 확인
  POST /_control  {...}     설정 변경
    run_id       로그에 붙일 실행 이름
    case_id      로그에 붙일 사례 이름 (사례마다 바꿔 준다)
    fail_rate    0~1. 이 비율로 채팅 호출에 실패를 주입한다 (지표 M10)
    fail_mode    "http"    : fail_status 상태 코드로 오류 응답
                 "garbage" : 200 응답이지만 내용이 JSON이 아닌 문장
    fail_status  http 모드의 상태 코드 (기본 500)
    seed         실패 주입 난수 시드

표준 라이브러리만 사용한다.
"""

import json
import os
import random
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UPSTREAM = os.environ.get("UPSTREAM_BASE", "https://api.openai.com").rstrip("/")
LOG_PATH = os.environ.get("LLM_LOG_PATH", "/logs/llm_calls.jsonl")
PORT = int(os.environ.get("PORT", "8080"))
TIMEOUT = float(os.environ.get("UPSTREAM_TIMEOUT", "300"))

FORWARD_HEADERS = {"authorization", "content-type", "openai-organization", "openai-project", "openai-beta"}

_lock = threading.Lock()
_control = {"run_id": "", "case_id": "", "fail_rate": 0.0, "fail_mode": "http", "fail_status": 500, "seed": None}
_rng = random.Random()


def _write_log(record: dict) -> None:
    line = json.dumps(record, ensure_ascii=False)
    with _lock:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def _usage(body: dict) -> dict:
    u = body.get("usage") or {}
    details = u.get("completion_tokens_details") or u.get("output_tokens_details") or {}
    prompt_details = u.get("prompt_tokens_details") or u.get("input_tokens_details") or {}
    return {
        "cached_tokens": prompt_details.get("cached_tokens"),
        "prompt_tokens": u.get("prompt_tokens", u.get("input_tokens")),
        "completion_tokens": u.get("completion_tokens", u.get("output_tokens")),
        "reasoning_tokens": details.get("reasoning_tokens"),
        "total_tokens": u.get("total_tokens"),
    }


def _should_inject(path: str):
    with _lock:
        rate = float(_control.get("fail_rate") or 0)
        mode = _control.get("fail_mode", "http")
        status = int(_control.get("fail_status") or 500)
        hit = rate > 0 and path.endswith("/chat/completions") and _rng.random() < rate
    return (mode, status) if hit else None


def _garbage_completion(model: str) -> bytes:
    return json.dumps({
        "id": "chatcmpl-injected",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model or "injected",
        "choices": [{"index": 0, "finish_reason": "stop",
                     "message": {"role": "assistant", "content": "죄송합니다. 지금은 답변할 수 없습니다."}}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }, ensure_ascii=False).encode()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # 기본 접근 로그는 끄고 JSONL만 남긴다
        pass

    def _send(self, status: int, body: bytes, content_type: str = "application/json", extra=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> bytes:
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def do_GET(self):
        if self.path == "/_control":
            with _lock:
                body = json.dumps(_control, ensure_ascii=False).encode()
            return self._send(200, body)
        if self.path == "/_health":
            return self._send(200, b'{"ok":true}')
        return self._proxy("GET", b"")

    def do_POST(self):
        raw = self._read_body()
        if self.path == "/_control":
            try:
                update = json.loads(raw or b"{}")
            except json.JSONDecodeError:
                return self._send(400, b'{"error":"invalid json"}')
            with _lock:
                for k in ("run_id", "case_id", "fail_rate", "fail_mode", "fail_status", "seed"):
                    if k in update:
                        _control[k] = update[k]
                if "seed" in update and update["seed"] is not None:
                    _rng.seed(update["seed"])
                body = json.dumps(_control, ensure_ascii=False).encode()
            return self._send(200, body)
        return self._proxy("POST", raw)

    def _proxy(self, method: str, raw: bytes):
        started = time.time()
        try:
            req_json = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            req_json = None
        model = (req_json or {}).get("model") if isinstance(req_json, dict) else None
        with _lock:
            run_id, case_id = _control.get("run_id", ""), _control.get("case_id", "")
        record = {
            "ts": started, "run_id": run_id, "case_id": case_id,
            "method": method, "path": self.path, "model": model,
            "request": req_json,
        }

        injected = _should_inject(self.path)
        if injected:
            mode, status = injected
            if mode == "garbage":
                body = _garbage_completion(model)
                self._send(200, body)
                record.update(status=200, injected="garbage", latency_s=round(time.time() - started, 3))
            else:
                body = json.dumps({"error": {"message": "injected failure", "type": "server_error"}}).encode()
                self._send(status, body)
                record.update(status=status, injected="http", latency_s=round(time.time() - started, 3))
            _write_log(record)
            return

        headers = {k: v for k, v in self.headers.items() if k.lower() in FORWARD_HEADERS}
        headers["Accept-Encoding"] = "identity"
        upstream_req = urllib.request.Request(UPSTREAM + self.path, data=raw if method == "POST" else None,
                                              headers=headers, method=method)
        status, body, ctype, req_id = 502, b"", "application/json", ""
        try:
            with urllib.request.urlopen(upstream_req, timeout=TIMEOUT) as resp:
                status, body = resp.status, resp.read()
                ctype = resp.headers.get("Content-Type", ctype)
                req_id = resp.headers.get("x-request-id", "")
        except urllib.error.HTTPError as e:
            status, body = e.code, e.read()
            ctype = e.headers.get("Content-Type", ctype)
            req_id = e.headers.get("x-request-id", "")
        except Exception as e:  # 연결 실패 등
            body = json.dumps({"error": {"message": f"proxy upstream error: {e}", "type": "proxy_error"}}).encode()

        latency = time.time() - started
        self._send(status, body, ctype, {"x-request-id": req_id} if req_id else None)

        try:
            resp_json = json.loads(body)
        except Exception:
            resp_json = None
        record.update(status=status, latency_s=round(latency, 3), request_id=req_id)
        if isinstance(resp_json, dict):
            record["usage"] = _usage(resp_json)
            record["response_model"] = resp_json.get("model")
            if "/chat/completions" in self.path:
                try:
                    record["response_text"] = resp_json["choices"][0]["message"]["content"]
                except Exception:
                    pass
            if status >= 400:
                record["error"] = resp_json.get("error")
        _write_log(record)


if __name__ == "__main__":
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    print(f"llm-proxy listening on :{PORT}, upstream={UPSTREAM}, log={LOG_PATH}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
