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
os.environ["OPENAI_MODEL"] = "gpt-5-mini"  # 요청 기준 파일이 실행 환경의 모델 설정에 따라 달라지지 않게 고정한다
os.environ["REDIS_URL"] = ""
os.environ["OPENAI_EXTRACT_REASONING_EFFORT"] = "low"
os.environ["DRAFT_MAX_REWRITES"] = "1"
os.environ["PII_MASKING"] = "1"
os.environ["DRAFT_CONFIRM"] = "0"
# 실행 환경에 토큰이 설정돼 있어도 테스트는 토큰 없는 구성에서 시작한다. 필요한 테스트가 직접 넣는다.
os.environ["BARO_AI_TOKEN"] = ""
os.environ["LLM_STATS_TOKEN"] = ""

from fastapi.testclient import TestClient  # noqa: E402

import baroai  # noqa: E402
import services.llm as llm  # noqa: E402
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
    for task in llm.TASKS:
        assert str(llm._model(task).root_client.base_url).startswith("http://127.0.0.1:"), task
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
