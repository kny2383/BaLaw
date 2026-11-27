"""AI 서비스 접근 제한: 토큰을 설정하면 /chat/* 주소가 그 토큰을 요구한다."""
import pytest

from cfg import settings

NARRATIVE = "중고거래로 30만원을 보냈는데 물건이 오지 않았습니다."
GOOD = {"Authorization": "Bearer service-secret"}


@pytest.fixture
def token(monkeypatch):
    monkeypatch.setattr(settings, "BARO_AI_TOKEN", "service-secret")


def test_without_a_configured_token_calls_need_no_header(client, fake):
    assert settings.BARO_AI_TOKEN == ""
    assert client.post("/chat/init", json={"text": NARRATIVE, "offense": "사기"}).status_code == 200


@pytest.mark.parametrize("method,path,body", [
    ("post", "/chat/init", {"text": NARRATIVE, "offense": "사기"}),
    ("get", "/chat/rag/some-session", None),
    ("post", "/chat/send", {"session_id": "some-session", "message": "답"}),
    ("post", "/chat/restore", {"history": [{"role": "user", "content": NARRATIVE}]}),
    ("post", "/chat/compose", {"session_id": "some-session"}),
    ("post", "/chat/compose/confirm", {"session_id": "some-session", "answers": [True]}),
    ("delete", "/chat/some-session", None),
])
def test_every_chat_route_refuses_calls_without_the_token(client, fake, token, method, path, body):
    kwargs = {"json": body} if body is not None else {}
    for headers in ({}, {"Authorization": "Bearer wrong"}, {"Authorization": "Bearer "}, {"Authorization": "service-secret-x"}):
        r = getattr(client, method)(path, headers=headers, **kwargs)
        assert r.status_code == 401 and r.headers["www-authenticate"] == "Bearer", (path, headers)
    assert fake.requests == []  # 거부된 요청은 LLM을 부르지 않는다


def test_calls_with_the_token_work(client, fake, token):
    r = client.post("/chat/init", json={"text": NARRATIVE, "offense": "사기"}, headers=GOOD)
    assert r.status_code == 200
    sid = r.json()["session_id"]
    assert client.get(f"/chat/rag/{sid}", headers=GOOD).status_code == 200
    assert client.get(f"/chat/rag/{sid}").status_code == 401
    assert client.delete(f"/chat/{sid}", headers=GOOD).status_code == 204


def test_refusal_does_not_reveal_whether_a_session_exists(client, fake, token):
    sid = client.post("/chat/init", json={"text": NARRATIVE, "offense": "사기"}, headers=GOOD).json()["session_id"]
    assert client.get(f"/chat/rag/{sid}").status_code == client.get("/chat/rag/no-such-session").status_code == 401


def test_health_stays_open_and_stats_keeps_its_own_token(client, token, monkeypatch):
    assert client.get("/").status_code == 200  # 컨테이너 상태 확인은 토큰 없이 한다
    # 호출 기록 집계는 서비스 토큰으로 열리지 않는다. 자기 토큰만 본다.
    assert client.get("/llm/stats", headers=GOOD).status_code == 404
    monkeypatch.setattr(settings, "LLM_STATS_TOKEN", "stats-secret")
    assert client.get("/llm/stats", headers=GOOD).status_code == 404
    assert client.get("/llm/stats", headers={"Authorization": "Bearer stats-secret"}).status_code == 200
