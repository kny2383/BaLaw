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

    calls = []

    async def fake_chat_init(text, offense=None):
        calls.append((text, offense))
        return {"session_id": "fake-session", "offense": offense or "fraud", "message": "질문을 시작합니다."}

    monkeypatch.setattr(complaint_api.ai_service, "chat_init", fake_chat_init)
    cid = create_complaint(client, user_tokens)
    r = client.post(f"/api/complaints/{cid}/chat/init", json={"text": "가상의 중고거래 사기 사건 개요", "offense": "사기"},
                    headers=auth_header(user_tokens))
    assert calls, "AI 서비스가 호출되지 않았다"
    assert r.status_code == 200, r.text
