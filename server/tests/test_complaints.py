from app.models.complaint import Complaint
from tests.conftest import auth_header, login, register

COMPLAINANT = {
    "complainant_name": "김가상",
    "complainant_address": "서울특별시 종로구 가상로 1",
    "complainant_phone": "010-0000-0000",
}


def create_complaint(client, tokens) -> int:
    r = client.post("/api/complaints/info/complainant", json=COMPLAINANT, headers=auth_header(tokens))
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_create_and_list(client, user_tokens):
    cid = create_complaint(client, user_tokens)
    r = client.get("/api/complaints/", headers=auth_header(user_tokens))
    assert r.status_code == 200
    assert [c["id"] for c in r.json()] == [cid]


def test_complainant_info_is_encrypted_at_rest(client, db_session, user_tokens):
    cid = create_complaint(client, user_tokens)
    row = db_session.get(Complaint, cid)
    for col, plain in (("complainant_name", "김가상"), ("complainant_phone", "010-0000-0000")):
        value = getattr(row, col)
        assert isinstance(value, bytes)
        assert plain.encode() not in value


def test_other_user_cannot_see_or_delete(client, user_tokens):
    cid = create_complaint(client, user_tokens)
    register(client, email="user2@example.com")
    other = login(client, email="user2@example.com")

    assert client.get("/api/complaints/", headers=auth_header(other)).json() == []
    assert client.delete(f"/api/complaints/{cid}", headers=auth_header(other)).status_code == 404
    assert client.get(f"/api/complaints/{cid}/chat/history", headers=auth_header(other)).status_code == 404
    assert client.get(f"/api/complaints/{cid}/download", headers=auth_header(other)).status_code == 404


def test_owner_can_delete(client, user_tokens):
    cid = create_complaint(client, user_tokens)
    assert client.delete(f"/api/complaints/{cid}", headers=auth_header(user_tokens)).status_code == 204
    assert client.get("/api/complaints/", headers=auth_header(user_tokens)).json() == []


def test_chat_init_uses_ai_service(client, user_tokens, monkeypatch):
    from app.api import complaint as complaint_api

    calls, known = [], []

    async def fake_chat_init(text, offense=None, known_pii=None):
        calls.append((text, offense))
        known.append(known_pii)
        return {"session_id": "fake-session", "offense": offense or "fraud", "message": "질문을 시작합니다."}

    monkeypatch.setattr(complaint_api.ai_service, "chat_init", fake_chat_init)
    cid = create_complaint(client, user_tokens)
    r = client.post(f"/api/complaints/{cid}/chat/init", json={"text": "가상의 중고거래 사기 사건 개요", "offense": "사기"},
                    headers=auth_header(user_tokens))
    assert calls, "AI 서비스가 호출되지 않았다"
    assert r.status_code == 200, r.text
    # 입력 화면에서 받은 이름·주소·전화번호를 AI 서비스에 알려 준다 (서술에서 찾아 가리게 한다).
    assert known == [{"names": [COMPLAINANT["complainant_name"]],
                      "addresses": [COMPLAINANT["complainant_address"]],
                      "phones": [COMPLAINANT["complainant_phone"]]}]


def test_chat_init_ai_failure_returns_503_and_keeps_complaint(client, db_session, user_tokens, monkeypatch):
    """AI 서비스가 실패하면 503을 돌려주고 고소장 상태와 대화 기록을 바꾸지 않는다 (지금 동작 기록)."""
    from app.api import complaint as complaint_api
    from app.models.chat_message import ChatMessage

    async def failing_chat_init(text, offense=None, known_pii=None):
        raise RuntimeError("upstream down")

    monkeypatch.setattr(complaint_api.ai_service, "chat_init", failing_chat_init)
    cid = create_complaint(client, user_tokens)
    r = client.post(f"/api/complaints/{cid}/chat/init", json={"text": "가상의 사건 개요", "offense": "사기"},
                    headers=auth_header(user_tokens))
    assert r.status_code == 503
    db_session.expire_all()
    assert db_session.get(Complaint, cid).ai_session_id is None
    assert db_session.query(ChatMessage).filter(ChatMessage.complaint_id == cid).count() == 0


# ---------- 고소장을 지울 때 AI 서비스의 세션도 지운다 ----------
def _with_session(db_session, complaint_id, session_id="ai-session-1"):
    complaint = db_session.get(Complaint, complaint_id)
    complaint.ai_session_id = session_id
    db_session.commit()


def _record_ai_deletes(monkeypatch, fail=False):
    from app.services.ai_service import ai_service

    calls = []

    def fake_delete(session_id):
        calls.append(session_id)
        if fail:
            raise RuntimeError("Baro-AI 세션 삭제 실패 (ConnectError)")

    monkeypatch.setattr(ai_service, "delete_session", fake_delete)
    return calls


def test_delete_also_deletes_ai_session(client, db_session, user_tokens, monkeypatch):
    calls = _record_ai_deletes(monkeypatch)
    cid = create_complaint(client, user_tokens)
    _with_session(db_session, cid)
    assert client.delete(f"/api/complaints/{cid}", headers=auth_header(user_tokens)).status_code == 204
    assert calls == ["ai-session-1"]


def test_delete_without_ai_session_does_not_call_ai(client, user_tokens, monkeypatch):
    calls = _record_ai_deletes(monkeypatch)
    cid = create_complaint(client, user_tokens)
    assert client.delete(f"/api/complaints/{cid}", headers=auth_header(user_tokens)).status_code == 204
    assert calls == []


def test_delete_is_refused_when_ai_session_cannot_be_deleted(client, db_session, user_tokens, monkeypatch):
    """AI 쪽을 지우지 못하면 고소장도 남긴다. 고소장만 지우면 세션 ID를 잃어 다시 지울 방법이 없다."""
    _record_ai_deletes(monkeypatch, fail=True)
    cid = create_complaint(client, user_tokens)
    _with_session(db_session, cid)
    r = client.delete(f"/api/complaints/{cid}", headers=auth_header(user_tokens))
    assert r.status_code == 503
    assert "ConnectError" not in r.text, "내부 오류 문구를 그대로 내보내지 않는다"
    db_session.expire_all()
    assert db_session.get(Complaint, cid) is not None


def test_other_user_delete_does_not_touch_ai_session(client, db_session, user_tokens, monkeypatch):
    calls = _record_ai_deletes(monkeypatch)
    cid = create_complaint(client, user_tokens)
    _with_session(db_session, cid)
    register(client, email="user2@example.com")
    other = login(client, email="user2@example.com")
    assert client.delete(f"/api/complaints/{cid}", headers=auth_header(other)).status_code == 404
    assert calls == []


def _expire(db_session, complaint_id, session_id=None):
    from datetime import datetime, timedelta, timezone

    complaint = db_session.get(Complaint, complaint_id)
    complaint.downloaded_at = datetime.now(timezone.utc) - timedelta(days=2)
    complaint.ai_session_id = session_id
    db_session.commit()


def _run_scheduler(db_session, monkeypatch):
    from app.services import scheduler_service as module

    monkeypatch.setattr(module, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(db_session, "close", lambda: None)
    module.scheduler_service.delete_old_complaints()
    db_session.expire_all()


def test_scheduler_deletes_ai_session_with_old_complaint(client, db_session, user_tokens, monkeypatch):
    calls = _record_ai_deletes(monkeypatch)
    old, fresh = create_complaint(client, user_tokens), create_complaint(client, user_tokens)
    _expire(db_session, old, "ai-old")
    _with_session(db_session, fresh, "ai-fresh")
    _run_scheduler(db_session, monkeypatch)
    assert calls == ["ai-old"]
    assert db_session.get(Complaint, old) is None and db_session.get(Complaint, fresh) is not None


def test_scheduler_keeps_complaint_when_ai_session_delete_fails(client, db_session, user_tokens, monkeypatch):
    _record_ai_deletes(monkeypatch, fail=True)
    with_session, without_session = create_complaint(client, user_tokens), create_complaint(client, user_tokens)
    _expire(db_session, with_session, "ai-old")
    _expire(db_session, without_session)
    _run_scheduler(db_session, monkeypatch)
    assert db_session.get(Complaint, with_session) is not None, "AI 쪽을 지우지 못한 건은 다음 실행까지 남긴다"
    assert db_session.get(Complaint, without_session) is None


def test_ai_client_delete_session(monkeypatch):
    """AI 클라이언트가 올바른 주소로 DELETE를 보내고, 실패를 RuntimeError로 올린다."""
    import httpx
    import pytest

    from app.services.ai_service import ai_service

    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        return httpx.Response(204 if request.url.path.endswith("/ok") else 500)

    real_client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    ai_service.delete_session("ok")
    with pytest.raises(RuntimeError):
        ai_service.delete_session("broken")
    assert seen == [("DELETE", "/chat/ok"), ("DELETE", "/chat/broken")]


def test_known_pii_skips_placeholder_names(client, db_session, user_tokens):
    """이름 칸에 '성명불상'처럼 값 대신 적은 말은 넘기지 않는다."""
    from app.api.complaint import known_pii_of
    from app.services.encryption_service import encryption_service

    cid = create_complaint(client, user_tokens)
    complaint = db_session.get(Complaint, cid)
    complaint.accused_name = encryption_service.encrypt_field("성명 불상(추정)")
    complaint.accused_address = encryption_service.encrypt_field("부산광역시 가상구 가상로 9")
    db_session.commit()
    known = known_pii_of(db_session.get(Complaint, cid))
    assert known["names"] == [COMPLAINANT["complainant_name"]]
    assert known["addresses"] == [COMPLAINANT["complainant_address"], "부산광역시 가상구 가상로 9"]
