"""서비스가 LLM에 보내는 요청 본문을 호출 종류별로 모은다.

호출 계층을 바꾸는 구조 변경에서 "요청이 이전과 같다"를 확인하는 기준이다.
기준 파일을 다시 만들 때:  python -m tests.snapshot_llm_requests tests/fixtures/llm_requests.json
이때 작업별 프롬프트 판본(prompt_versions.json)도 함께 다시 만든다. 프롬프트나 출력 형식을 바꾸면 판본이 바뀐다.
"""
from __future__ import annotations

import json


def kind_of(body: dict) -> str:
    rf = body.get("response_format") or {}
    text = "\n".join(str(m.get("content", "")) for m in body.get("messages", []))
    if rf.get("type") == "json_schema":
        return "verify" if "unsupported" in rf["json_schema"]["schema"].get("properties", {}) else "extract"
    if "revise a draft" in text:
        return "rewrite"
    if "drafting assistant" in text:
        return "compose"
    if "죄목 리스트" in text:
        return "rag_keyword"
    return "rag_summary"


def collect(client, fake) -> dict:
    """대화 한 건을 끝까지 진행하며 호출 종류마다 첫 요청 본문을 모은다."""
    fake.verify_results = [["피고소인에게"]]  # 재작성 호출까지 나오게 한다
    sid = client.post("/chat/init", json={"text": "중고거래로 30만원을 보냈는데 물건이 오지 않았습니다.", "offense": "사기"}).json()["session_id"]
    client.post("/chat/send", json={"session_id": sid, "message": "위 사건 개요를 기반으로, 이어서 질문을 해 주세요."})
    client.post("/chat/compose", json={"session_id": sid})
    out: dict = {}
    for r in fake.requests:
        if r["path"].endswith("/chat/completions"):
            out.setdefault(kind_of(r["body"]), r["body"])
    return dict(sorted(out.items()))


if __name__ == "__main__":
    import tests.conftest as c  # 가짜 서버와 환경 변수를 준비한다
    from fastapi.testclient import TestClient
    import baroai
    import services.rag as rag
    from tests.fake_openai import FakeCollection

    rag.get_collection = lambda: FakeCollection()
    c._fake.reset()
    import sys
    from pathlib import Path

    data = collect(TestClient(baroai.app), c._fake)
    Path(sys.argv[1]).write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    import services.llm as llm
    versions = {task: llm.prompt_version_of(body) for task, body in data.items()}
    (Path(llm.__file__).resolve().parent.parent / "prompt_versions.json").write_text(
        json.dumps(versions, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print("저장:", sys.argv[1], versions)
