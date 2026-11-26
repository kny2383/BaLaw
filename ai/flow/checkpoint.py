"""그래프 상태 저장소.

세션 상태는 체크포인터에 thread 단위로 남는다. 대화는 thread_id가 세션 ID이고,
판례 검색은 같은 세션의 별도 thread를 쓴다 (초기화 때 대화와 동시에 실행되기 때문이다).
"""
from __future__ import annotations

from langgraph.checkpoint.memory import InMemorySaver

RAG_THREAD_PREFIX = "rag:"

# 메모리 체크포인터는 thread마다 단계별 상태 사본을 모두 보관한다. 세션당 최신 상태 하나만 두던
# 이전보다 메모리를 더 쓰고, 서비스가 재시작하면 비워진다. 저장소를 PostgreSQL로 바꿀 때
# 세션 삭제와 함께 정리 방법을 정한다.
_checkpointer = InMemorySaver()


def get_checkpointer():
    return _checkpointer


def chat_config(session_id: str) -> dict:
    return {"configurable": {"thread_id": session_id}}


def rag_config(session_id: str) -> dict:
    return {"configurable": {"thread_id": RAG_THREAD_PREFIX + session_id}}


def delete_session(session_id: str) -> None:
    """세션의 대화와 판례 검색 상태를 모두 지운다."""
    _checkpointer.delete_thread(session_id)
    _checkpointer.delete_thread(RAG_THREAD_PREFIX + session_id)


def session_ids() -> list[str]:
    """저장된 대화 세션 ID 목록."""
    seen: list[str] = []
    for item in _checkpointer.list(None):
        tid = item.config["configurable"]["thread_id"]
        if not tid.startswith(RAG_THREAD_PREFIX) and tid not in seen:
            seen.append(tid)
    return seen
