"""서버 테스트 공통 설정.

실제 Postgres·AI 서비스 없이 돌린다. DB는 테스트마다 새 SQLite 메모리 DB,
AI 서비스 호출은 테스트에서 직접 가짜로 바꾼다. 키와 비밀값은 테스트 전용 값이다.
"""

import os

from cryptography.fernet import Fernet

# app을 불러오기 전에 설정값을 채운다 (app.config가 import 시점에 읽는다)
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())
os.environ.setdefault("OPENAI_API_KEY", "test-not-used")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture
def db_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def client(db_session):
    def _get_db():
        yield db_session

    app.dependency_overrides[get_db] = _get_db
    # with 블록을 쓰지 않으므로 lifespan(스케줄러)은 시작하지 않는다
    yield TestClient(app)
    app.dependency_overrides.clear()


def register(client, email="user1@example.com", password="password123", name="홍길동"):
    return client.post("/api/auth/register", json={"email": email, "password": password, "name": name})


def login(client, email="user1@example.com", password="password123") -> dict:
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


def auth_header(tokens: dict) -> dict:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


@pytest.fixture
def user_tokens(client):
    register(client)
    return login(client)
