"""대화 그래프: 추출 → 질문 선택, 그리고 작성.

요청 하나가 그래프 실행 한 번이다. 상태는 체크포인터가 세션(thread)별로 이어 준다.

    요청 ─┬─ init ─────────────────────────▶ 끝
          ├─ message ─▶ extract ─▶ select_question ─▶ 끝
          └─ compose ─▶ compose ───────────▶ 끝
"""
from __future__ import annotations

import copy

from langgraph.graph import END, START, StateGraph

from flow.checkpoint import get_checkpointer
from flow.state import ChatState
from loaders.offense_loader import get_offense_meta
from services.pipelines import (
    _user_window,
    classify_need_caution,
    compose_complaint,
    enforce_details,
    enforce_elements,
    extract_all,
    pick_detail_followup,
    pick_element_followup,
)

DONE_REPLY = "필수 정보가 충족되었습니다. 고소장을 작성해드릴게요."
EXTRACT_WINDOW_CHARS = 1800


def route_request(state: ChatState) -> str:
    return state["request"]["action"]


def init_session(state: ChatState) -> dict:
    """새 세션의 처음 상태. 첫 서술은 대화 기록에만 넣고 추출은 첫 발화 때 한다."""
    req = state["request"]
    return {
        "offense": req["offense"],
        "offense_selected": req["offense_selected"],
        "history": [{"role": "user", "content": req["text"]}],
        "collected": {},
        "pii": req.get("pii") or {},
    }


def _current_offense(state: ChatState) -> str:
    # 죄목을 직접 고르지 않은 세션은 판례 검색이 끝나면 그 결과로 양식을 정한다.
    return state["request"].get("offense") or state["offense"]


def extract(state: ChatState) -> dict:
    """사용자 발화를 받아 항목별 수집 상태를 다시 판정한다 (LLM 호출).

    실패하면 예외가 올라가고 이 노드의 결과는 저장되지 않는다.
    발화는 기록에 남지 않으므로 다시 보내면 같은 상태에서 이어진다.
    """
    offense = _current_offense(state)
    meta = get_offense_meta(offense)
    history = state["history"] + [{"role": "user", "content": state["request"]["message"]}]
    user_text = _user_window(history, max_chars=EXTRACT_WINDOW_CHARS)

    parsed = extract_all(user_text, offense)
    elements = enforce_elements(meta, parsed.get("elements", {}), user_text)
    details = enforce_details(parsed.get("details", {}), offense)

    # 질문 횟수는 추출 결과가 아니라 대화가 쌓아 온 값이므로 이어받는다.
    old = state.get("collected") or {}
    for eid, old_rec in (old.get("elements") or {}).items():
        if "_asked_count" in old_rec:
            elements.setdefault(eid, {})["_asked_count"] = copy.deepcopy(old_rec["_asked_count"])
    for did, old_rec in (old.get("details") or {}).items():
        if "_asked_count" in old_rec:
            details.setdefault(did, {})["_asked_count"] = copy.deepcopy(old_rec["_asked_count"])

    return {
        "offense": offense,
        "history": history,
        "collected": {"elements": elements, "details": details},
        # 이번 발화에서 새로 생긴 표식. 추출이 실패하면 발화와 함께 저장되지 않는다.
        "pii": state["request"].get("pii") or state.get("pii") or {},
    }


def select_question(state: ChatState) -> dict:
    """아직 비어 있는 항목 중 다음에 물을 것을 규칙으로 고른다 (LLM 호출 없음)."""
    offense = state["offense"]
    meta = get_offense_meta(offense)
    collected = copy.deepcopy(state["collected"])  # 질문 선택이 질문 횟수를 올린다
    elements, details = collected["elements"], collected["details"]
    history = list(state["history"])

    reply = pick_detail_followup(details, offense) or pick_element_followup(elements, meta) or DONE_REPLY
    complete = reply.startswith("필수 정보가 충족")

    # 중복 질문 방지
    last_assistant = next((m for m in reversed(history) if m["role"] == "assistant"), None)
    if last_assistant and last_assistant["content"].strip() == reply.strip() and not complete:
        alt = pick_element_followup(elements, meta) if reply == pick_detail_followup(details, offense) \
            else pick_detail_followup(details, offense)
        if alt and alt.strip() != reply.strip():
            reply = alt

    history.append({"role": "assistant", "content": reply})

    # 위험요소 정규식판별
    caution_msg = classify_need_caution("\n".join(m["content"] for m in history if m["role"] == "user"))

    return {
        "collected": collected,
        "history": history,
        "result": {"reply": reply, "complete": complete, "caution": bool(caution_msg)},
    }


def compose(state: ChatState) -> dict:
    """모은 정보로 초안을 쓴다 (LLM 호출)."""
    offense = _current_offense(state)
    meta = get_offense_meta(offense)
    draft = compose_complaint(meta=meta, collected=state.get("collected", {}), evidence=[])
    return {"offense": offense, "draft": draft}


def build_chat_graph(checkpointer=None):
    g = StateGraph(ChatState)
    g.add_node("init", init_session)
    g.add_node("extract", extract)
    g.add_node("select_question", select_question)
    g.add_node("compose", compose)
    g.add_conditional_edges(START, route_request, {"init": "init", "message": "extract", "compose": "compose"})
    g.add_edge("init", END)
    g.add_edge("extract", "select_question")
    g.add_edge("select_question", END)
    g.add_edge("compose", END)
    return g.compile(checkpointer=checkpointer or get_checkpointer())
