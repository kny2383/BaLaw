"""테스트용 가짜 OpenAI 서버.

AI 서비스가 OpenAI로 보내는 HTTP 요청을 로컬에서 받아 정해진 응답을 돌려준다.
서비스 코드를 건드리지 않고 OPENAI_BASE_URL만 바꿔 쓰므로, 호출 계층을 바꾸거나
(SDK → 다른 클라이언트) 흐름 제어를 옮겨도 그대로 쓸 수 있다.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

COMPOSE_TEXT = (
    "=== 범죄사실 ===\n"
    "○ 고소인은 피고소인에게 금원을 송금하였습니다.\n\n"
    "=== 고소이유 ===\n"
    "○ 위 사실에 관하여 수사를 요청합니다.\n"
)


class FakeOpenAI:
    """응답을 바꿔 가며 쓰는 가짜 서버. 받은 요청은 requests에 쌓인다."""

    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.reset()
        handler = self._handler()
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}/v1"

    def reset(self) -> None:
        self.requests.clear()
        self.slot_value = "present"   # 추출 응답의 모든 슬롯 값
        self.item_status = "satisfied"
        self.fail_extract = False     # True면 추출 요청에 400을 돌려준다
        self.keyword = "사기"
        self.fail_keyword = False     # True면 죄명 키워드 요청에 400을 돌려준다
        self.compose_text = COMPOSE_TEXT

    def close(self) -> None:
        self._server.shutdown()

    # --- 응답 만들기 ---
    def _fill(self, node: dict, defs: dict, key: str = ""):
        if "$ref" in node:
            node = defs[node["$ref"].split("/")[-1]]
        if "properties" in node:
            return {k: self._fill(v, defs, k) for k, v in node["properties"].items()}
        if "enum" in node:
            if key == "status":
                return self.item_status
            return self.slot_value if self.slot_value in node["enum"] else node["enum"][0]
        return "확인된 내용을 정리했습니다." if key == "summary" else ""

    def _chat(self, body: dict) -> tuple[int, dict]:
        rf = body.get("response_format") or {}
        if rf.get("type") == "json_schema":
            if self.fail_extract:
                return 400, {"error": {"message": "fake failure", "type": "invalid_request_error"}}
            schema = rf["json_schema"]["schema"]
            content = json.dumps(self._fill(schema, schema.get("$defs", {})), ensure_ascii=False)
        else:
            text = "\n".join(str(m.get("content", "")) for m in body.get("messages", []))
            if "drafting assistant" in text:
                content = self.compose_text
            elif "죄목 리스트" in text:
                if self.fail_keyword:
                    return 400, {"error": {"message": "fake failure", "type": "invalid_request_error"}}
                content = self.keyword
            else:  # 판례 요약
                content = json.dumps({"case_no": "2020고단1", "label": "사기",
                                      "summary": "요약", "result": "유죄"}, ensure_ascii=False)
        return 200, {
            "id": "fake", "object": "chat.completion", "created": 0, "model": body.get("model", "fake"),
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }

    def _handler(self):
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):
                pass

            def do_POST(self):
                raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                body = json.loads(raw or b"{}")
                fake.requests.append({"path": self.path, "body": body})
                if self.path.endswith("/chat/completions"):
                    status, payload = fake._chat(body)
                else:
                    status, payload = 404, {"error": {"message": f"fake: {self.path}", "type": "not_found"}}
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        return Handler


class FakeCollection:
    """Chroma 컬렉션 대역. 판례 DB 파일 없이 검색 결과 형식만 돌려준다."""

    def query(self, query_texts, n_results):
        metas = [
            {"case_no": "2020고단1", "label": "사기", "summary": "판례 요약 1", "facts": "사실관계 1"},
            {"case_no": "2021고단2", "label": "사기", "summary": "판례 요약 2", "facts": "사실관계 2"},
            {"case_no": "2022고단3", "label": "횡령", "summary": "판례 요약 3", "facts": "사실관계 3"},
        ]
        return {"ids": [[m["case_no"] for m in metas]], "metadatas": [metas], "distances": [[0.1, 0.2, 0.3]]}
