from app.models.user import User
from tests.conftest import auth_header, login, register


def test_register_login_me(client):
    r = register(client)
    assert r.status_code == 201
    assert r.json()["name"] == "홍길동"

    tokens = login(client)
    me = client.get("/api/auth/me", headers=auth_header(tokens))
    assert me.status_code == 200
    assert me.json()["email"] == "user1@example.com"


def test_personal_info_is_encrypted_at_rest(client, db_session):
    register(client)
    user = db_session.query(User).filter(User.email == "user1@example.com").one()
    assert isinstance(user.name, bytes)
    assert "홍길동".encode() not in user.name
    assert user.password_hash != "password123"


def test_duplicate_email_rejected(client):
    register(client)
    r = register(client)
    assert r.status_code == 400


def test_check_email(client):
    assert client.get("/api/auth/check-email/user1@example.com").json()["available"] is True
    register(client)
    assert client.get("/api/auth/check-email/user1@example.com").json()["available"] is False


def test_short_password_rejected(client):
    r = register(client, password="short")
    assert r.status_code == 422


def test_wrong_password(client):
    register(client)
    r = client.post("/api/auth/login", json={"email": "user1@example.com", "password": "wrong-password"})
    assert r.status_code == 401


def test_me_requires_token(client):
    assert client.get("/api/auth/me").status_code in (401, 403)
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_refresh_issues_new_tokens(client, user_tokens):
    r = client.post("/api/auth/refresh", json={"refresh_token": user_tokens["refresh_token"]})
    assert r.status_code == 200
    assert client.get("/api/auth/me", headers=auth_header(r.json())).status_code == 200


def test_refresh_token_cannot_be_used_as_access_token(client, user_tokens):
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {user_tokens['refresh_token']}"})
    assert r.status_code == 401


def test_access_token_cannot_be_used_to_refresh(client, user_tokens):
    r = client.post("/api/auth/refresh", json={"refresh_token": user_tokens["access_token"]})
    assert r.status_code == 401


def test_tokens_issued_by_refresh_keep_their_types(client, user_tokens):
    new = client.post("/api/auth/refresh", json={"refresh_token": user_tokens["refresh_token"]}).json()
    assert client.get("/api/auth/me", headers=auth_header(new)).status_code == 200
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {new['refresh_token']}"}).status_code == 401
    assert client.post("/api/auth/refresh", json={"refresh_token": new["refresh_token"]}).status_code == 200


def test_token_without_a_type_is_refused(client, user_tokens):
    """종류가 적히지 않은 토큰(검사를 넣기 전에 발급된 형식)은 서명이 맞아도 받지 않는다."""
    from datetime import datetime, timedelta

    from jose import jwt

    from app.config import settings

    old = jwt.encode({"sub": "user1@example.com", "exp": datetime.utcnow() + timedelta(minutes=5)},
                     settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {old}"}).status_code == 401
    assert client.post("/api/auth/refresh", json={"refresh_token": old}).status_code == 401
