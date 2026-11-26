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


# ---------- 고소장 생성: 초안 검증 결과 전달 ----------
def _generate(client, db_session, user_tokens, monkeypatch, verification):
    from app.api import complaint as complaint_api

    async def fake_compose(session_id):
        body = {"offense": "fraud", "title": "사기",
                "sections": {"criminal_facts": "범죄사실 본문", "accusation_reason": "고소이유 본문"}}
        if verification is not None:
            body["verification"] = verification
        return body

    monkeypatch.setattr(complaint_api.ai_service, "chat_compose", fake_compose)
    # 관할 경찰서 조회는 이 테스트의 대상이 아니다 (테스트 DB에 경찰서 표가 없다).
    monkeypatch.setattr(complaint_api, "get_police_station_name", lambda address, db: "가상경찰서")
    cid = create_complaint(client, user_tokens)
    _with_session(db_session, cid)
    return client.post(f"/api/complaints/{cid}/generate", headers=auth_header(user_tokens))


def test_generate_passes_verification_result_to_the_client(client, db_session, user_tokens, monkeypatch):
    review = {"status": "unverified", "rewrites": 0, "rechecked": False, "unsupported": [], "removed": []}
    r = _generate(client, db_session, user_tokens, monkeypatch, review)
    assert r.status_code == 200
    assert r.json()["criminal_facts"] == "범죄사실 본문"
    assert r.json()["verification"]["status"] == "unverified"


def test_generate_works_without_verification_field(client, db_session, user_tokens, monkeypatch):
    r = _generate(client, db_session, user_tokens, monkeypatch, None)
    assert r.status_code == 200 and r.json()["verification"] is None


# ---------- 실패 응답에 내부 오류 원문을 넣지 않는다 ----------
SECRET = "http://ai:8000 내부주소 Traceback"


def test_generate_failure_hides_the_internal_error(client, db_session, user_tokens, monkeypatch):
    from app.api import complaint as complaint_api

    async def failing_compose(session_id):
        raise RuntimeError(f"Baro-AI 서버 오류 (502): {SECRET}")

    monkeypatch.setattr(complaint_api.ai_service, "chat_compose", failing_compose)
    cid = create_complaint(client, user_tokens)
    _with_session(db_session, cid)
    r = client.post(f"/api/complaints/{cid}/generate", headers=auth_header(user_tokens))
    assert r.status_code == 503
    assert "내부주소" not in r.text and "Traceback" not in r.text and r.json()["detail"]
    assert _complaint(db_session, cid).status != "completed"


def test_chat_init_failure_hides_the_internal_error(client, user_tokens, monkeypatch):
    from app.api import complaint as complaint_api

    async def failing_init(*args, **kwargs):
        raise RuntimeError(SECRET)

    monkeypatch.setattr(complaint_api.ai_service, "chat_init", failing_init)
    cid = create_complaint(client, user_tokens)
    r = client.post(f"/api/complaints/{cid}/chat/init", json={"text": "사건 개요", "offense": "사기"},
                    headers=auth_header(user_tokens))
    assert r.status_code == 503 and "내부주소" not in r.text


def test_empty_draft_is_not_saved_as_a_finished_complaint(client, db_session, user_tokens, monkeypatch):
    """AI 서비스가 본문이 빈 초안을 돌려줘도 완성된 고소장으로 저장하지 않는다 (M10)."""
    from app.api import complaint as complaint_api

    cid = create_complaint(client, user_tokens)
    _with_session(db_session, cid)
    for sections in ({"criminal_facts": " ", "accusation_reason": ""}, {"criminal_facts": None}, None):
        async def empty_compose(session_id, sections=sections):
            return {"offense": "fraud", "title": "사기", "sections": sections}

        monkeypatch.setattr(complaint_api.ai_service, "chat_compose", empty_compose)
        r = client.post(f"/api/complaints/{cid}/generate", headers=auth_header(user_tokens))
        assert r.status_code == 503, sections
    saved = _complaint(db_session, cid)
    assert saved.status != "completed" and not saved.generated_complaint_encrypted


# ---------- 미지원 죄목 (F11) ----------
def test_unsupported_offense_starts_nothing(client, db_session, user_tokens, monkeypatch):
    """AI 서비스가 미지원으로 답하면 세션도 대화 기록도 남기지 않고 사용자에게 안내한다."""
    from sqlalchemy import text

    from app.api import complaint as complaint_api

    async def unsupported_init(text, offense=None, known_pii=None):
        return {"session_id": None, "offense": "unsupported", "rag_status": "skipped", "rag_keyword": None, "rag_cases": []}

    monkeypatch.setattr(complaint_api.ai_service, "chat_init", unsupported_init)
    cid = create_complaint(client, user_tokens)
    r = client.post(f"/api/complaints/{cid}/chat/init", json={"text": "돈을 맡겼는데 돌려주지 않습니다", "offense": "횡령"},
                    headers=auth_header(user_tokens))
    assert r.status_code == 422 and "지원하지 않는" in r.json()["detail"]
    saved = _complaint(db_session, cid)
    assert saved.ai_session_id is None and saved.crime_type is None
    assert db_session.execute(text("SELECT count(*) FROM chat_messages")).scalar() == 0


# ---------- 고소장 생성: 사용자 확인 ----------
WAITING = {"status": "awaiting_confirmation", "rewrites": 0, "rechecked": False, "removed": [], "confirmed": [],
           "unsupported": [{"quote": "극심한 고통", "reason": "대화에 없는 내용"}],
           "to_confirm": [{"quote": "극심한 고통", "reason": "대화에 없는 내용"}]}


def _confirm(client, user_tokens, monkeypatch, cid, answers, result=None, error=None):
    from app.api import complaint as complaint_api
    calls = []

    async def fake_confirm(session_id, got):
        calls.append((session_id, got))
        if error:
            raise RuntimeError(error)
        return result

    monkeypatch.setattr(complaint_api.ai_service, "chat_compose_confirm", fake_confirm)
    r = client.post(f"/api/complaints/{cid}/generate/confirm", json={"answers": answers}, headers=auth_header(user_tokens))
    return r, calls


def _complaint(db_session, cid) -> Complaint:
    db_session.expire_all()
    return db_session.query(Complaint).filter(Complaint.id == cid).one()


def test_generate_waiting_for_confirmation_saves_nothing(client, db_session, user_tokens, monkeypatch):
    r = _generate(client, db_session, user_tokens, monkeypatch, WAITING)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "awaiting_confirmation"
    assert [c["quote"] for c in body["verification"]["to_confirm"]] == ["극심한 고통"]
    saved = _complaint(db_session, body["complaint_id"])
    assert saved.status != "completed" and not saved.generated_complaint_encrypted and not saved.crime_fact


def test_confirm_finishes_the_complaint(client, db_session, user_tokens, monkeypatch):
    cid = _generate(client, db_session, user_tokens, monkeypatch, WAITING).json()["complaint_id"]
    done = {"sections": {"criminal_facts": "고친 범죄사실", "accusation_reason": "고소이유 본문"},
            "verification": {"status": "rewritten", "rewrites": 1, "removed": WAITING["to_confirm"]}}
    r, calls = _confirm(client, user_tokens, monkeypatch, cid, [False], result=done)
    assert r.status_code == 200 and calls == [("ai-session-1", [False])]
    assert r.json()["status"] == "completed" and r.json()["criminal_facts"] == "고친 범죄사실"
    saved = _complaint(db_session, cid)
    assert saved.status == "completed" and saved.generated_complaint_encrypted


def test_confirm_without_a_waiting_draft_is_conflict(client, db_session, user_tokens, monkeypatch):
    cid = _generate(client, db_session, user_tokens, monkeypatch, WAITING).json()["complaint_id"]
    for error in ("Baro-AI 서버 오류 (409): 확인을 기다리는 초안이 없습니다.", "Baro-AI 서버 오류 (404): 세션을 찾을 수 없습니다."):
        r, _ = _confirm(client, user_tokens, monkeypatch, cid, [True], error=error)
        assert r.status_code == 409
    assert _complaint(db_session, cid).status != "completed"


def test_confirm_reports_ai_failure_without_details(client, db_session, user_tokens, monkeypatch):
    cid = _generate(client, db_session, user_tokens, monkeypatch, WAITING).json()["complaint_id"]
    r, _ = _confirm(client, user_tokens, monkeypatch, cid, [True], error="Baro-AI 서버에 연결할 수 없습니다. 내부주소")
    assert r.status_code == 503 and "내부주소" not in r.text
    r, _ = _confirm(client, user_tokens, monkeypatch, cid, [], error="Baro-AI 서버 오류 (400): 답은 1개여야 합니다.")
    assert r.status_code == 400


def test_other_user_cannot_confirm(client, db_session, user_tokens, monkeypatch):
    cid = _generate(client, db_session, user_tokens, monkeypatch, WAITING).json()["complaint_id"]
    register(client, email="other2@example.com")
    other = login(client, email="other2@example.com")
    r, calls = _confirm(client, other, monkeypatch, cid, [True], result={})
    assert r.status_code == 404 and calls == []


def test_ai_client_sends_confirmation_answers(monkeypatch):
    import asyncio
    import json

    import httpx

    from app.services.ai_service import BaroAIService

    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"], seen["body"] = request.url.path, json.loads(request.content)
        return httpx.Response(409, json={"detail": "확인을 기다리는 초안이 없습니다."})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    service = BaroAIService()
    try:
        asyncio.run(service.chat_compose_confirm("sid", [True, False]))
        raise AssertionError("409는 오류로 올라와야 한다")
    except RuntimeError as e:
        assert service.is_no_pending_confirmation_error(e) and not service.is_session_missing_error(e)
    assert seen == {"path": "/chat/compose/confirm", "body": {"session_id": "sid", "answers": [True, False]}}


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


# ---------- 채팅 기록 암호화 (S03) ----------
KICKOFF = "위 사건 개요를 기반으로, 이어서 질문을 해 주세요."
NARRATIVE = "표식서술 중고거래로 삼십만원을 보냈습니다"
ANSWER = "표식답변 오월 삼일입니다"
QUESTION = "표식질문 언제 송금하셨나요?"


def _chat(client, db_session, user_tokens, monkeypatch) -> int:
    """대화 한 건: 서술 → 고정 문장(저장하지 않음) → 질문 → 답 → 질문."""
    from app.api import complaint as complaint_api

    async def fake_init(text, offense=None, known_pii=None):
        return {"session_id": "ai-session-1", "offense": "fraud", "rag_status": "pending", "rag_keyword": None, "rag_cases": []}

    async def fake_send(session_id, message):
        return {"reply": QUESTION, "session_id": session_id}

    monkeypatch.setattr(complaint_api.ai_service, "chat_init", fake_init)
    monkeypatch.setattr(complaint_api.ai_service, "chat_send", fake_send)
    cid = create_complaint(client, user_tokens)
    h = auth_header(user_tokens)
    assert client.post(f"/api/complaints/{cid}/chat/init", json={"text": NARRATIVE, "offense": "사기"}, headers=h).status_code == 200
    for message in (KICKOFF, ANSWER):
        assert client.post(f"/api/complaints/{cid}/chat/ai-session-1", json={"message": message}, headers=h).status_code == 200
    return cid


def _raw_chat_rows(db_session):
    from sqlalchemy import text
    return db_session.execute(text("SELECT role, content, reason, is_internal FROM chat_messages ORDER BY id")).fetchall()


def test_chat_text_is_not_stored_in_plain(client, db_session, user_tokens, monkeypatch):
    _chat(client, db_session, user_tokens, monkeypatch)
    rows = _raw_chat_rows(db_session)
    assert len(rows) == 4
    stored = " ".join(str(v) for row in rows for v in row)
    for secret in (NARRATIVE, ANSWER, QUESTION, KICKOFF, "표식"):
        assert secret not in stored
    assert all(row.content.startswith("enc:v1:") for row in rows)


def test_chat_history_reads_back_and_hides_the_bootstrap_message(client, db_session, user_tokens, monkeypatch):
    cid = _chat(client, db_session, user_tokens, monkeypatch)
    h = auth_header(user_tokens)
    for query in ("", "?limit=50"):  # 전체 조회와 쪽 단위 조회는 거르는 경로가 다르다
        messages = client.get(f"/api/complaints/{cid}/chat/history{query}", headers=h).json()["messages"]
        assert [m["content"] for m in messages] == [NARRATIVE, QUESTION, ANSWER, QUESTION], query
    assert not any(r.is_internal for r in _raw_chat_rows(db_session))


def test_restore_history_skips_the_bootstrap_message(client, db_session, user_tokens, monkeypatch):
    from app.api.complaint import get_restore_history
    cid = _chat(client, db_session, user_tokens, monkeypatch)
    assert [m["content"] for m in get_restore_history(db_session, cid)] == [NARRATIVE, ANSWER]


def _migration():
    import importlib.util
    from pathlib import Path
    path = next((Path(__file__).resolve().parents[1] / "alembic" / "versions").glob("a7c3e9d1f052_*.py"))
    spec = importlib.util.spec_from_file_location("encrypt_chat_messages", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_encrypts_rows_stored_before_and_can_be_rerun(client, db_session, user_tokens, monkeypatch):
    """암호화 전에 평문으로 저장된 행: 암호화되고, 고정 문장에 표시가 남고, 화면에는 같은 내용이 보인다."""
    from sqlalchemy import text
    cid = create_complaint(client, user_tokens)
    for role, content in (("user", NARRATIVE), ("user", KICKOFF), ("assistant", QUESTION), ("user", ANSWER)):
        db_session.execute(text("INSERT INTO chat_messages (complaint_id, role, content, is_internal) VALUES (:c, :r, :t, 0)"),
                           {"c": cid, "r": role, "t": content})
    db_session.commit()
    h = auth_header(user_tokens)
    # 마이그레이션 전의 평문 행도 읽힌다.
    before = client.get(f"/api/complaints/{cid}/chat/history", headers=h).json()["messages"]
    assert [m["content"] for m in before] == [NARRATIVE, QUESTION, ANSWER]

    migration = _migration()
    assert migration.encrypt_rows(db_session.connection()) == 4
    assert migration.encrypt_rows(db_session.connection()) == 0, "다시 실행해도 이미 암호화된 행은 그대로다"
    db_session.commit()
    rows = _raw_chat_rows(db_session)
    assert all(r.content.startswith("enc:v1:") for r in rows) and "표식" not in " ".join(r.content for r in rows)
    assert [bool(r.is_internal) for r in rows] == [False, True, False, False]
    for query in ("", "?limit=50"):
        after = client.get(f"/api/complaints/{cid}/chat/history{query}", headers=h).json()["messages"]
        assert [m["content"] for m in after] == [NARRATIVE, QUESTION, ANSWER]

    assert migration.decrypt_rows(db_session.connection()) == 4
    db_session.commit()
    assert [r.content for r in _raw_chat_rows(db_session)] == [NARRATIVE, KICKOFF, QUESTION, ANSWER]
