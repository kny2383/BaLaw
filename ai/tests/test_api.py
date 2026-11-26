"""AI 서비스 API의 요청·응답 형식 테스트.

서버와 평가기가 기대는 형식만 검사한다. 대화 흐름을 어떻게 구현하는지는 보지 않으므로,
구조를 바꾼 뒤에도 이 테스트가 그대로 통과해야 한다.
"""
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
