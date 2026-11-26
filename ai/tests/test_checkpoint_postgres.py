"""PostgreSQL 체크포인터 테스트: 대화가 평문으로 남지 않는지, 다시 떠도 이어지는지, 지워지는지.

TEST_CHECKPOINT_DB_URL이 가리키는 테스트 전용 DB에 테스트마다 새 스키마를 만들고 끝나면 지운다.
주소가 없으면 건너뛴다. CI는 REQUIRE_DB_TESTS=1이라 건너뛰지 않고 실패한다.
"""
import json
import os
import uuid

import pytest

from flow import checkpoint
from flow.chat_graph import build_chat_graph
from flow.rag_graph import build_rag_graph
from tests.fake_openai import COMPOSE_TEXT, FakeCollection

DB_URL = os.environ.get("TEST_CHECKPOINT_DB_URL", "")
if not DB_URL:
    if os.environ.get("REQUIRE_DB_TESTS") == "1":
        raise RuntimeError("REQUIRE_DB_TESTS=1인데 TEST_CHECKPOINT_DB_URL이 없습니다.")
    pytestmark = pytest.mark.skip(reason="TEST_CHECKPOINT_DB_URL이 없어 PostgreSQL 테스트를 건너뜁니다.")

KEY = os.urandom(32)
SID = "session-1"
NARRATIVE = "표식서술 중고거래로 삼십만원을 보냈습니다"
MESSAGE = "표식발화 오월 삼일입니다"
# 저장소에서 찾으면 안 되는 글. 사용자가 쓴 글과 LLM이 만든 글(요약, 초안, 키워드, 판례)이 모두 들어 있다.
PHONE = "010-9999-8888"  # 치환 상태(표식 → 원래 값)에 들어가는 값
SECRETS = [NARRATIVE, MESSAGE, PHONE, "확인된 내용을 정리했습니다", "고소인은 피고소인에게", "표식키워드", "판례 요약 1", "2020고단1"]


@pytest.fixture
def schema():
    import psycopg
    from psycopg import sql

    name = "t_" + uuid.uuid4().hex[:12]
    yield name
    with psycopg.connect(DB_URL, autocommit=True) as conn:
        conn.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(name)))


def _saver(schema, key=KEY):
    return checkpoint.make_postgres_saver(DB_URL, key, schema=schema)


def _close(saver):
    saver.conn.close()


def _run_conversation(saver, fake, monkeypatch):
    import services.rag as rag

    monkeypatch.setattr(rag, "get_collection", lambda: FakeCollection())
    fake.keyword = "표식키워드"
    fake.slot_value, fake.item_status = "missing", "missing"
    chat, rag_graph = build_chat_graph(saver), build_rag_graph(saver)
    cfg = checkpoint.chat_config(SID)
    chat.invoke({"request": {"action": "init", "text": NARRATIVE, "offense": "fraud", "offense_selected": True,
                             "pii": {"known": {}, "tokens": {"[전화번호1]": PHONE}}}}, cfg)
    monkeypatch.setattr(rag, "search_similar_cases_filtered", lambda text, keyword, k=2: FakeCollection().query([text], 3)["metadatas"][0][:k])
    rag_graph.invoke({"request": {"text": NARRATIVE}}, checkpoint.rag_config(SID))
    out = chat.invoke({"request": {"action": "message", "message": MESSAGE}}, cfg)
    chat.invoke({"request": {"action": "compose"}}, cfg)
    return chat, out


def _stored_bytes(schema) -> bytes:
    """스키마의 모든 테이블, 모든 열의 값을 바이트로 이어 붙인다."""
    import psycopg
    from psycopg import sql

    chunks = []
    with psycopg.connect(DB_URL, autocommit=True) as conn:
        tables = [r[0] for r in conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = %s", (schema,))]
        assert {"checkpoints", "checkpoint_blobs", "checkpoint_writes"} <= set(tables)
        for table in tables:
            for row in conn.execute(sql.SQL("SELECT * FROM {}.{}").format(sql.Identifier(schema), sql.Identifier(table))):
                for value in row:
                    if isinstance(value, (bytes, memoryview)):
                        chunks.append(bytes(value))
                    else:
                        chunks.append(json.dumps(value, ensure_ascii=False, default=str).encode("utf-8"))
    return b"\n".join(chunks)


def _rows(schema, table, thread_id) -> int:
    import psycopg
    from psycopg import sql

    with psycopg.connect(DB_URL, autocommit=True) as conn:
        q = sql.SQL("SELECT count(*) FROM {}.{} WHERE thread_id = %s").format(sql.Identifier(schema), sql.Identifier(table))
        return conn.execute(q, (thread_id,)).fetchone()[0]


def test_no_conversation_text_is_stored_in_plain(schema, fake, monkeypatch):
    saver = _saver(schema)
    _, out = _run_conversation(saver, fake, monkeypatch)
    assert COMPOSE_TEXT.split("○ ")[1].strip()[:10] in "고소인은 피고소인에게 금원을 송금하였습니다."
    assert "확인된 내용을 정리했습니다" in out["result"]["reply"]  # 질문 문장에 LLM 요약이 들어 있다

    stored = _stored_bytes(schema)
    assert len(stored) > 1000
    leaked = [s for s in SECRETS if s.encode("utf-8") in stored]
    assert leaked == [], f"암호화되지 않은 채 저장된 글: {leaked}"
    _close(saver)


def test_the_scan_finds_text_when_encryption_is_off(schema, fake, monkeypatch):
    """위 테스트의 검사가 실제로 평문을 찾아낼 수 있는지 확인한다 (암호화를 뺀 저장소로)."""
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

    saver = _saver(schema)
    saver.serde = JsonPlusSerializer()
    _run_conversation(saver, fake, monkeypatch)
    stored = _stored_bytes(schema)
    assert all(s.encode("utf-8") in stored for s in (NARRATIVE, MESSAGE))
    _close(saver)


def test_session_survives_restart(schema, fake, monkeypatch):
    first = _saver(schema)
    _run_conversation(first, fake, monkeypatch)
    _close(first)

    second = _saver(schema)  # 서비스가 다시 뜬 상황: 새 연결, 같은 키
    chat = build_chat_graph(second)
    state = chat.get_state(checkpoint.chat_config(SID)).values
    assert [m["content"] for m in state["history"][:2]] == [NARRATIVE, MESSAGE]
    out = chat.invoke({"request": {"action": "message", "message": "네"}}, checkpoint.chat_config(SID))
    assert out["history"][-2] == {"role": "user", "content": "네"}
    assert checkpoint.session_ids(second) == [SID]
    _close(second)


def test_wrong_key_cannot_read(schema, fake, monkeypatch):
    saver = _saver(schema)
    _run_conversation(saver, fake, monkeypatch)
    _close(saver)

    other = _saver(schema, key=os.urandom(32))
    with pytest.raises(Exception):
        build_chat_graph(other).get_state(checkpoint.chat_config(SID)).values["history"]
    _close(other)


def test_prune_keeps_only_latest_state(schema, fake, monkeypatch):
    saver = _saver(schema)
    chat, _ = _run_conversation(saver, fake, monkeypatch)
    assert _rows(schema, "checkpoints", SID) > 1

    checkpoint.prune_session(SID, checkpointer=saver)
    checkpoint.prune_session(SID, rag=True, checkpointer=saver)
    assert _rows(schema, "checkpoints", SID) == 1
    assert _rows(schema, "checkpoints", checkpoint.RAG_THREAD_PREFIX + SID) == 1
    state = chat.get_state(checkpoint.chat_config(SID)).values
    assert state["history"][0]["content"] == NARRATIVE and state["draft"]["sections"]
    out = chat.invoke({"request": {"action": "message", "message": "네"}}, checkpoint.chat_config(SID))
    assert out["result"]["reply"]
    _close(saver)


def test_delete_removes_every_row_of_the_session(schema, fake, monkeypatch):
    saver = _saver(schema)
    _run_conversation(saver, fake, monkeypatch)
    checkpoint.delete_session(SID, checkpointer=saver)
    for table in ("checkpoints", "checkpoint_blobs", "checkpoint_writes"):
        assert _rows(schema, table, SID) == 0
        assert _rows(schema, table, checkpoint.RAG_THREAD_PREFIX + SID) == 0
    assert checkpoint.session_ids(saver) == []
    _close(saver)


def test_key_is_required():
    with pytest.raises(ValueError):
        checkpoint.make_postgres_saver(DB_URL, b"", schema="unused")
