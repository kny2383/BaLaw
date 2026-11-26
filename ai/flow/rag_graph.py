"""판례 그래프: 죄명 키워드 → 판례 검색 → 판례 요약.

초기화 때 백그라운드로 한 번 실행한다. 대화와 동시에 돌 수 있어 별도 thread에 저장한다.
"""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from flow.checkpoint import get_checkpointer
from flow.state import RagState
from services import rag

PREVIEW_CASES = 2


def predict_keyword(state: RagState) -> dict:
    return {"found": {"keyword": rag.predict_crime_keyword(state["request"]["text"])}}


def search_cases(state: RagState) -> dict:
    found = state["found"]
    raw = rag.search_similar_cases_filtered(state["request"]["text"], found["keyword"], k=PREVIEW_CASES)
    return {"found": {**found, "raw_cases": raw}}


def summarize_cases(state: RagState) -> dict:
    found = state["found"]
    cases = rag.summarize_cases_for_ui(state["request"]["text"], found["raw_cases"])
    return {"result": {"status": "ready", "keyword": found["keyword"], "cases": cases, "error": None}}


def failed_result(error: Exception) -> dict:
    """어느 단계에서 실패했든 남기는 결과. 키워드와 판례는 비운다."""
    return {"result": {"status": "failed", "keyword": None, "cases": [], "error": str(error)}}


def build_rag_graph(checkpointer=None):
    g = StateGraph(RagState)
    g.add_node("predict_keyword", predict_keyword)
    g.add_node("search_cases", search_cases)
    g.add_node("summarize_cases", summarize_cases)
    g.add_edge(START, "predict_keyword")
    g.add_edge("predict_keyword", "search_cases")
    g.add_edge("search_cases", "summarize_cases")
    g.add_edge("summarize_cases", END)
    return g.compile(checkpointer=checkpointer or get_checkpointer())
