"""그래프 상태 저장소.

세션 상태는 체크포인터에 thread 단위로 남는다. 대화는 thread_id가 세션 ID이고,
판례 검색은 같은 세션의 별도 thread를 쓴다 (초기화 때 대화와 동시에 실행되기 때문이다).

CHECKPOINT_DB_URL이 있으면 PostgreSQL에 암호화해서 저장한다. 없으면 메모리에 둔다.
"""
from __future__ import annotations

from langgraph.checkpoint.memory import InMemorySaver

from cfg import settings

RAG_THREAD_PREFIX = "rag:"
DEFAULT_SCHEMA = "ai_checkpoint"  # 서버의 테이블과 섞이지 않게 따로 둔다


def make_postgres_saver(db_url: str, key: bytes, schema: str = DEFAULT_SCHEMA):
    """PostgreSQL 체크포인터를 만든다. dict·list 값은 AES로 암호화되어 저장된다.

    문자열 같은 단순 값은 암호화되지 않으므로, 상태에 무엇을 어떻게 둘지는 flow/state.py의 규칙을 따른다.
    """
    import psycopg
    from langgraph.checkpoint.postgres import PostgresSaver
    from langgraph.checkpoint.serde.encrypted import EncryptedSerializer
    from psycopg import sql
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool

    if len(key) != 32:
        raise ValueError("체크포인트를 PostgreSQL에 저장하려면 CHECKPOINT_AES_KEY(32바이트)가 필요합니다.")

    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(schema)))

    pool = ConnectionPool(
        db_url,
        min_size=1,
        max_size=10,
        open=True,
        kwargs={
            "autocommit": True,
            "prepare_threshold": 0,
            "row_factory": dict_row,
            "options": f"-c search_path={schema}",
        },
    )
    saver = PostgresSaver(pool, serde=EncryptedSerializer.from_pycryptodome_aes(key=key))
    saver.setup()
    return saver


def _build():
    if not settings.CHECKPOINT_DB_URL:
        print("[CHECKPOINT] 메모리에 저장합니다. 서비스가 재시작하면 세션이 사라집니다.")
        return InMemorySaver()
    saver = make_postgres_saver(settings.CHECKPOINT_DB_URL, settings.CHECKPOINT_AES_KEY)
    print("[CHECKPOINT] PostgreSQL에 암호화해서 저장합니다.")
    return saver


_checkpointer = _build()


def get_checkpointer():
    return _checkpointer


def chat_config(session_id: str) -> dict:
    return {"configurable": {"thread_id": session_id}}


def rag_config(session_id: str) -> dict:
    return {"configurable": {"thread_id": RAG_THREAD_PREFIX + session_id}}


def delete_session(session_id: str, checkpointer=None) -> None:
    """세션의 대화와 판례 검색 상태를 모두 지운다."""
    saver = checkpointer or _checkpointer
    saver.delete_thread(session_id)
    saver.delete_thread(RAG_THREAD_PREFIX + session_id)


def prune_session(session_id: str, rag: bool = False, checkpointer=None) -> None:
    """세션의 지난 단계 사본을 지우고 최신 상태 하나만 남긴다.

    그래프는 단계마다 상태 사본을 저장한다. 그대로 두면 같은 대화가 여러 벌 쌓이므로
    요청이 끝날 때마다 정리한다. 정리에 실패해도 요청은 성공으로 둔다 (다음 요청에서 다시 정리된다).
    """
    if settings.CHECKPOINT_KEEP_HISTORY:
        return
    thread_id = (RAG_THREAD_PREFIX if rag else "") + session_id
    try:
        (checkpointer or _checkpointer).prune([thread_id], strategy="keep_latest")
    except Exception as e:
        print(f"[CHECKPOINT] 지난 단계 정리 실패 reason={type(e).__name__}")


def session_ids(checkpointer=None) -> list[str]:
    """저장된 대화 세션 ID 목록."""
    seen: list[str] = []
    for item in (checkpointer or _checkpointer).list(None):
        tid = item.config["configurable"]["thread_id"]
        if not tid.startswith(RAG_THREAD_PREFIX) and tid not in seen:
            seen.append(tid)
    return seen
