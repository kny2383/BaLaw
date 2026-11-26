"""AI 서비스 API 동작 테스트의 공통 준비.

외부 의존을 모두 대역으로 바꾼다: OpenAI는 로컬 가짜 서버, 판례 DB는 가짜 컬렉션,
Redis는 끈다. 실제 OpenAI로는 요청이 나가지 않는다 (비용 없음).
"""
import os

import pytest

from tests.fake_openai import FakeCollection, FakeOpenAI

_fake = FakeOpenAI()

# 앱을 불러오기 전에 정해야 한다. cfg의 .env 읽기는 이미 있는 환경변수를 덮어쓰지 않는다.
os.environ["OPENAI_API_KEY"] = "test-key"
os.environ["OPENAI_BASE_URL"] = _fake.base_url
os.environ["REDIS_URL"] = ""
os.environ["OPENAI_EXTRACT_REASONING_EFFORT"] = "low"
os.environ["DRAFT_MAX_REWRITES"] = "1"
os.environ["PII_MASKING"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

import baroai  # noqa: E402
import services.openai_client as openai_client  # noqa: E402
import services.rag as rag  # noqa: E402
from flow import checkpoint  # noqa: E402


def _clear_sessions():
    for sid in checkpoint.session_ids():
        checkpoint.delete_session(sid)


@pytest.fixture
def session_ids():
    """지금 저장된 세션 ID 목록을 돌려주는 함수."""
    return checkpoint.session_ids


@pytest.fixture(autouse=True)
def _no_real_openai():
    """모든 OpenAI 클라이언트가 가짜 서버를 보고 있는지 테스트마다 확인한다."""
    assert str(openai_client.client().base_url).startswith("http://127.0.0.1:")
    assert str(rag.openai_client.base_url).startswith("http://127.0.0.1:")
    yield


@pytest.fixture
def fake(monkeypatch):
    _fake.reset()
    monkeypatch.setattr(rag, "get_collection", lambda: FakeCollection())
    _clear_sessions()
    yield _fake
    _clear_sessions()


@pytest.fixture
def client(fake):
    # with 없이 만들면 시작 이벤트(판례 DB 내려받기)가 실행되지 않는다.
    return TestClient(baroai.app)
