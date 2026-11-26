"""AI 서비스 API의 요청·응답 형식 테스트.

서버와 평가기가 기대는 형식만 검사한다. 대화 흐름을 어떻게 구현하는지는 보지 않으므로,
구조를 바꾼 뒤에도 이 테스트가 그대로 통과해야 한다.
"""
import pytest

import baroai

NARRATIVE = "중고거래 앱에서 아이폰을 30만원에 판다는 글을 보고 송금했는데 물건이 오지 않았습니다."
KICKOFF = "위 사건 개요를 기반으로, 이어서 질문을 해 주세요."


def _init(client, text=NARRATIVE, offense="fraud"):
    r = client.post("/chat/init", json={"text": text, "offense": offense})
    assert r.status_code == 200
    return r.json()


def _assert_items(group: dict):
    assert group, "항목이 비어 있다"
    for rec in group.values():
        assert rec["status"] in ("satisfied", "missing", "unclear")
        assert isinstance(rec["slots"], dict) and rec["slots"]
        assert all(v in ("present", "missing", "unclear", "unknown") for v in rec["slots"].values())


def _assert_send(body: dict, session_id: str):
    assert body["session_id"] == session_id
    assert isinstance(body["reply"], str) and body["reply"].strip()
    assert isinstance(body["caution"], bool)
    progress = body["progress"]
    assert isinstance(progress["complete"], bool)
    _assert_items(progress["elements"])
    _assert_items(progress["details"])


# ---------- 상태 확인 ----------
def test_health(client):
    body = client.get("/").json()
    assert body["ok"] is True
    assert isinstance(body["service"], str) and isinstance(body["model"], str)


# ---------- /chat/init ----------
def test_init_returns_session(client):
    body = _init(client)
    assert isinstance(body["session_id"], str) and body["session_id"]
    assert body["offense"] == "fraud"
    assert body["rag_status"] in ("pending", "ready", "failed")
    assert "rag_keyword" in body and isinstance(body["rag_cases"], list)


def test_init_offense_names(client):
    assert _init(client, offense="사이버사기")["offense"] == "fraud"
    assert _init(client, offense="모욕")["offense"] == "insult"
    assert _init(client, offense=None)["offense"] in ("fraud", "insult")


@pytest.mark.parametrize("offense", ["횡령", "폭행", "명예훼손", "embezzlement", "아무 말"])
def test_init_unsupported_offense_is_not_turned_into_fraud(client, fake, session_ids, offense):
    """지원하지 않는 죄목은 사기 양식으로 진행하지 않는다. 세션을 만들지 않고 LLM도 부르지 않는다 (M5)."""
    r = client.post("/chat/init", json={"text": NARRATIVE, "offense": offense})
    assert r.status_code == 200
    assert r.json() == {"session_id": None, "offense": "unsupported", "rag_status": "skipped",
                        "rag_keyword": None, "rag_cases": []}
    assert session_ids() == [] and fake.requests == []


def test_init_requires_text(client):
    assert client.post("/chat/init", json={"offense": "fraud"}).status_code == 422


# ---------- /chat/rag/{session_id} ----------
def test_rag_ready_after_init(client):
    sid = _init(client)["session_id"]
    body = client.get(f"/chat/rag/{sid}").json()
    assert body["session_id"] == sid
    assert body["rag_status"] == "ready"
    assert body["rag_keyword"] == "사기"
    assert 1 <= len(body["rag_cases"]) <= 2
    for case in body["rag_cases"]:
        assert {"case_no", "label", "summary", "result", "similarity"} <= set(case)
        assert "사기" in case["label"]


def _assert_rag_failed(client, sid):
    body = client.get(f"/chat/rag/{sid}").json()
    assert body["rag_status"] == "failed"
    assert body["rag_keyword"] is None and body["rag_cases"] == []
    # 판례 검색이 실패해도 대화는 이어진다.
    assert client.post("/chat/send", json={"session_id": sid, "message": KICKOFF}).status_code == 200


def test_rag_failure_at_keyword_is_reported(client, fake):
    fake.fail_keyword = True
    _assert_rag_failed(client, _init(client)["session_id"])


def test_rag_failure_at_search_is_reported(client, monkeypatch):
    import services.rag as rag

    def broken():
        raise RuntimeError("판례 DB를 열 수 없다")

    monkeypatch.setattr(rag, "get_collection", broken)
    _assert_rag_failed(client, _init(client)["session_id"])


def test_rag_unknown_session(client):
    assert client.get("/chat/rag/none").status_code == 404


# ---------- /chat/send ----------
def test_send_asks_question_when_missing(client, fake):
    fake.slot_value, fake.item_status = "missing", "missing"
    sid = _init(client)["session_id"]
    r = client.post("/chat/send", json={"session_id": sid, "message": KICKOFF})
    assert r.status_code == 200
    body = r.json()
    _assert_send(body, sid)
    assert body["progress"]["complete"] is False
    assert not body["reply"].startswith("None")
    # 평가기는 어떤 항목을 물었는지 _asked_count로 안다.
    asked = [slot for group in ("elements", "details") for rec in body["progress"][group].values()
             for slot, n in (rec.get("_asked_count") or {}).items() if n > 0]
    assert len(asked) == 1


def test_send_finishes_even_when_nothing_is_answered(client, fake):
    fake.slot_value, fake.item_status = "missing", "missing"
    sid = _init(client)["session_id"]
    for _ in range(40):
        body = client.post("/chat/send", json={"session_id": sid, "message": "잘 모르겠어요."}).json()
        if body["progress"]["complete"]:
            break
    assert body["progress"]["complete"] is True, "모든 답이 '모름'이어도 대화는 끝나야 한다"


def test_send_completes_when_all_present(client):
    sid = _init(client)["session_id"]
    body = client.post("/chat/send", json={"session_id": sid, "message": KICKOFF}).json()
    _assert_send(body, sid)
    assert body["progress"]["complete"] is True


def test_send_caution_flag(client):
    sid = _init(client)["session_id"]
    plain = client.post("/chat/send", json={"session_id": sid, "message": KICKOFF}).json()
    risky = client.post("/chat/send", json={"session_id": sid, "message": "상대가 협박도 했습니다."}).json()
    assert plain["caution"] is False and risky["caution"] is True


def test_send_unknown_session(client):
    r = client.post("/chat/send", json={"session_id": "none", "message": "안녕하세요"})
    assert r.status_code == 404


def test_send_requires_fields(client):
    assert client.post("/chat/send", json={"session_id": "x"}).status_code == 422


def test_send_reports_extraction_failure_and_allows_retry(client, fake):
    sid = _init(client)["session_id"]
    fake.fail_extract = True
    r = client.post("/chat/send", json={"session_id": sid, "message": KICKOFF})
    assert r.status_code == 502
    assert isinstance(r.json()["detail"], str) and "fake failure" not in r.text

    fake.fail_extract = False
    fake.requests.clear()
    r = client.post("/chat/send", json={"session_id": sid, "message": KICKOFF})
    assert r.status_code == 200
    _assert_send(r.json(), sid)
    # 실패한 발화가 다음 추출 요청에 두 번 들어가지 않는다.
    prompt = fake.requests[-1]["body"]["messages"][-1]["content"]
    assert prompt.count(KICKOFF) == 1


# ---------- /chat/compose ----------
def test_compose_returns_sections(client):
    sid = _init(client)["session_id"]
    client.post("/chat/send", json={"session_id": sid, "message": KICKOFF})
    r = client.post("/chat/compose", json={"session_id": sid})
    assert r.status_code == 200
    body = r.json()
    assert body["offense"] == "fraud" and isinstance(body["title"], str) and body["title"]
    sections = body["sections"]
    assert set(sections) == {"criminal_facts", "accusation_reason"}
    assert all(isinstance(v, str) and v.strip() for v in sections.values())
    assert body["verification"] == {"status": "passed", "rewrites": 0, "rechecked": False,
                                    "unsupported": [], "removed": [], "confirmed": []}


def test_compose_reports_what_was_rewritten(client, fake):
    sid = _init(client)["session_id"]
    client.post("/chat/send", json={"session_id": sid, "message": KICKOFF})
    fake.verify_results = [["피고소인에게"]]
    body = client.post("/chat/compose", json={"session_id": sid}).json()
    assert body["verification"]["status"] == "rewritten"
    assert [c["quote"] for c in body["verification"]["removed"]] == ["피고소인에게"]
    assert "피고소인에게" not in body["sections"]["criminal_facts"]


@pytest.fixture
def confirm_on(monkeypatch):
    monkeypatch.setattr(baroai.settings, "DRAFT_CONFIRM", True)


def _compose_waiting(client, fake, quotes):
    sid = _init(client)["session_id"]
    client.post("/chat/send", json={"session_id": sid, "message": KICKOFF})
    fake.verify_results = [quotes]
    return sid, client.post("/chat/compose", json={"session_id": sid}).json()


def test_compose_asks_the_user_before_rewriting(client, fake, confirm_on):
    sid, body = _compose_waiting(client, fake, ["피고소인에게"])
    v = body["verification"]
    assert v["status"] == "awaiting_confirmation"
    assert [c["quote"] for c in v["to_confirm"]] == ["피고소인에게"]
    assert "피고소인에게" in body["sections"]["criminal_facts"]  # 아직 고치지 않은 초안

    r = client.post("/chat/compose/confirm", json={"session_id": sid, "answers": [False]})
    assert r.status_code == 200
    body = r.json()
    assert body["verification"]["status"] == "rewritten" and "to_confirm" not in body["verification"]
    assert "피고소인에게" not in body["sections"]["criminal_facts"]


def test_confirm_keeps_what_the_user_confirms(client, fake, confirm_on):
    sid, _ = _compose_waiting(client, fake, ["피고소인에게"])
    body = client.post("/chat/compose/confirm", json={"session_id": sid, "answers": [True]}).json()
    assert body["verification"]["status"] == "confirmed"
    assert "피고소인에게" in body["sections"]["criminal_facts"]


def test_confirm_rejects_wrong_number_of_answers(client, fake, confirm_on):
    sid, _ = _compose_waiting(client, fake, ["피고소인에게"])
    assert client.post("/chat/compose/confirm", json={"session_id": sid, "answers": []}).status_code == 400
    # 거절된 뒤에도 같은 질문에 답할 수 있다.
    assert client.post("/chat/compose/confirm", json={"session_id": sid, "answers": [False]}).status_code == 200


def test_confirm_without_a_waiting_draft(client, fake, confirm_on):
    sid = _init(client)["session_id"]
    client.post("/chat/send", json={"session_id": sid, "message": KICKOFF})
    assert client.post("/chat/compose/confirm", json={"session_id": sid, "answers": [True]}).status_code == 409
    client.post("/chat/compose", json={"session_id": sid})  # 근거 없는 표현이 없어 멈추지 않는다
    assert client.post("/chat/compose/confirm", json={"session_id": sid, "answers": [True]}).status_code == 409
    assert client.post("/chat/compose/confirm", json={"session_id": "none", "answers": [True]}).status_code == 404


def test_confirm_cannot_be_answered_twice(client, fake, confirm_on):
    sid, _ = _compose_waiting(client, fake, ["피고소인에게"])
    client.post("/chat/compose/confirm", json={"session_id": sid, "answers": [False]})
    assert client.post("/chat/compose/confirm", json={"session_id": sid, "answers": [False]}).status_code == 409


def test_confirm_question_restores_identifiers(client, fake, confirm_on):
    """확인을 묻는 표현은 표식이 아니라 사용자가 쓴 원래 값으로 보인다."""
    r = client.post("/chat/init", json={"text": "김가상에게 돈을 보냈습니다", "offense": "fraud",
                                        "known_pii": {"names": ["김가상"]}})
    sid = r.json()["session_id"]
    client.post("/chat/send", json={"session_id": sid, "message": KICKOFF})
    fake.compose_text = "=== 범죄사실 ===\n○ 고소인은 [이름1]에게 금원을 송금하였습니다.\n\n=== 고소이유 ===\n○ 수사를 요청합니다.\n"
    fake.verify_results = [["[이름1]에게"]]
    body = client.post("/chat/compose", json={"session_id": sid}).json()
    assert [c["quote"] for c in body["verification"]["to_confirm"]] == ["김가상에게"]


@pytest.mark.parametrize("broken", ["call_fails", "empty_output", "no_text_at_all", "no_criminal_facts"])
def test_compose_failure_is_an_error_not_an_empty_draft(client, fake, broken):
    """작성 호출이 실패하거나 쓸 수 있는 글이 없으면 빈 초안을 200으로 돌려주지 않는다 (M10)."""
    sid = _init(client)["session_id"]
    client.post("/chat/send", json={"session_id": sid, "message": KICKOFF})
    if broken == "call_fails":
        fake.fail_compose = True
    else:
        fake.compose_text = {"empty_output": "", "no_text_at_all": "   \n  ",
                             "no_criminal_facts": "=== 고소이유 ===\n○ 수사를 요청합니다.\n"}[broken]
    r = client.post("/chat/compose", json={"session_id": sid})
    assert r.status_code == 502
    assert "fake failure" not in r.text
    # 실패한 뒤 다시 요청하면 작성된다.
    fake.reset()
    assert client.post("/chat/compose", json={"session_id": sid}).status_code == 200


def test_rewrite_call_failure_keeps_the_draft_and_says_so(client, fake):
    sid = _init(client)["session_id"]
    client.post("/chat/send", json={"session_id": sid, "message": KICKOFF})
    fake.verify_results = [["피고소인에게"]]
    fake.fail_rewrite = True
    body = client.post("/chat/compose", json={"session_id": sid}).json()
    assert body["verification"]["status"] == "rewrite_failed"
    assert "피고소인에게" in body["sections"]["criminal_facts"]


def test_compose_unknown_session(client):
    assert client.post("/chat/compose", json={"session_id": "none"}).status_code == 404


# ---------- /chat/restore ----------
def test_restore_rebuilds_session(client, fake):
    fake.slot_value, fake.item_status = "missing", "missing"
    history = [
        {"role": "user", "content": NARRATIVE},
        {"role": "assistant", "content": "사건이 언제 발생했나요?"},
        {"role": "user", "content": "2026년 5월 3일입니다."},
    ]
    r = client.post("/chat/restore", json={"history": history})
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["session_id"], str) and body["session_id"]
    assert body["offense"] in ("fraud", "insult")
    assert body["rag_status"] in ("pending", "ready", "failed")
    assert isinstance(body["rag_cases"], list)
    assert isinstance(body["progress"]["complete"], bool)
    _assert_items(body["progress"]["elements"])
    _assert_items(body["progress"]["details"])

    # 복원한 세션으로 대화를 이어갈 수 있다.
    nxt = client.post("/chat/send", json={"session_id": body["session_id"], "message": "카카오뱅크로 보냈습니다."})
    assert nxt.status_code == 200
    _assert_send(nxt.json(), body["session_id"])


def test_restore_single_message(client):
    r = client.post("/chat/restore", json={"history": [{"role": "user", "content": NARRATIVE}]})
    assert r.status_code == 200
    progress = r.json()["progress"]
    assert progress["complete"] is False
    assert isinstance(progress["elements"], dict) and isinstance(progress["details"], dict)


def test_restore_without_user_message(client):
    r = client.post("/chat/restore", json={"history": [{"role": "assistant", "content": "안녕하세요"}]})
    assert r.status_code == 400


def test_restore_failure_leaves_no_session(client, fake, session_ids):
    fake.fail_extract = True
    history = [{"role": "user", "content": NARRATIVE}, {"role": "user", "content": "네"}]
    assert client.post("/chat/restore", json={"history": history}).status_code == 502
    assert session_ids() == []


# ---------- DELETE /chat/{session_id} ----------
def test_delete_session(client, session_ids):
    sid = _init(client)["session_id"]
    client.post("/chat/send", json={"session_id": sid, "message": KICKOFF})
    assert client.delete(f"/chat/{sid}").status_code == 204
    assert session_ids() == []
    assert client.post("/chat/send", json={"session_id": sid, "message": KICKOFF}).status_code == 404
    assert client.get(f"/chat/rag/{sid}").status_code == 404


def test_delete_unknown_session_is_ok(client):
    assert client.delete("/chat/none").status_code == 204
