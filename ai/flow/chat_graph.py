"""대화 그래프: 추출 → 질문 선택, 그리고 작성 → 검증 → (사용자 확인) → 재작성.

요청 하나가 그래프 실행 한 번이다. 상태는 체크포인터가 세션(thread)별로 이어 준다.

    요청 ─┬─ init ─────────────────────────▶ 끝
          ├─ message ─▶ extract ─▶ select_question ─▶ 끝
          └─ compose ─▶ compose ─▶ verify ─┬─ 근거 없는 표현 없음 ─▶ 끝
                                  ▲        └─ 있음 ─▶ rewrite ─┬─ 횟수 남음 ─▶ verify
                                  └────────────────────────────┘└─ 상한 ─▶ 끝

DRAFT_CONFIRM이 켜져 있으면(기본) verify와 rewrite 사이에 confirm이 들어간다. confirm은 실행을 멈추고
(interrupt) 사용자의 답을 기다린다. 답이 오면 멈춘 자리에서 이어서, 사용자가 사실이 아니라고 한
표현만 rewrite로 보낸다. 멈춘 상태는 체크포인터에 남으므로 서비스가 재시작해도 이어 갈 수 있다.

    verify ─ 있음 ─▶ confirm ─(멈춤, 답을 받음)─┬─ 사실이 아닌 표현 있음 ─▶ rewrite
                                                └─ 모두 사실 ─▶ 끝
"""
from __future__ import annotations

import copy

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from cfg import settings
from flow.checkpoint import get_checkpointer
from flow.state import ChatState
from loaders.offense_loader import get_offense_meta
from services.llm import StructuredOutputError
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
from services.verify import rewrite_draft, verify_draft

DONE_REPLY = "필수 정보가 충족되었습니다. 고소장을 작성해드릴게요."
# 추출에 넣는 사용자 발화의 상한(글자 수). 넘으면 처음 서술을 지키고 최근 발화부터 채운다.
# 평가 사례는 가장 긴 것도 600자를 넘지 않아 이 상한에 닿지 않는다.
EXTRACT_WINDOW_CHARS = 6000


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
    status = "pending" if settings.DRAFT_MAX_REWRITES > 0 else "off"
    return {"offense": offense, "draft": draft,
            "review": {"status": status, "rewrites": 0, "rechecked": False, "unsupported": [], "removed": [],
                       "confirmed": []}}


def verify(state: ChatState) -> dict:
    """초안을 대화와 대조해 근거 없는 표현을 찾는다 (LLM 호출).

    검증 호출이 실패하면 초안은 그대로 두고 '검증하지 못함'으로 남긴다. 검증된 것처럼 돌려주지 않는다.
    """
    review = dict(state["review"])
    try:
        found = verify_draft(state["history"], state["draft"]["sections"])
    except StructuredOutputError as e:
        print(f"[VERIFY] 초안 검증 실패 reason={e}")
        return {"review": {**review, "status": "unverified"}}
    if found:
        return {"review": {**review, "status": "flagged", "rechecked": bool(review["rewrites"]), "unsupported": found}}
    if review["rewrites"]:
        return {"review": {**review, "status": "rewritten", "rechecked": True, "unsupported": []}}
    return {"review": {**review, "status": "passed", "unsupported": []}}


def rewrite(state: ChatState) -> dict:
    """검증이 찾은 표현만 고쳐 다시 쓴다 (LLM 호출). 다시 쓰지 못하면 초안을 그대로 두고 그 사실을 남긴다."""
    review = dict(state["review"])
    sections = rewrite_draft(state["draft"]["sections"], review["unsupported"])
    if sections is None:
        print("[VERIFY] 재작성 실패: 쓸 수 있는 결과가 없음")
        return {"review": {**review, "status": "rewrite_failed"}}
    return {
        "draft": {**state["draft"], "sections": sections},
        # 고쳐 쓴 초안은 아직 다시 검증하지 않았다. 다시 검증하면 verify가 rechecked를 True로 바꾼다.
        "review": {**review, "status": "rewritten", "rewrites": review["rewrites"] + 1, "rechecked": False,
                   "unsupported": [], "removed": review["removed"] + review["unsupported"]},
    }


CONFIRM_PREFIX = "고소장 초안의 다음 내용은 사실이 맞습니다: "


def confirmed_text(claim: dict) -> str:
    """사용자가 사실이라고 답한 내용을 대화 기록에 남길 글.

    사용자가 확인한 것은 구절이다. 구절만으로는 뜻이 정해지지 않아 문장을 함께 적되,
    확인한 범위가 그 구절이라는 것을 밝힌다. 문장의 나머지까지 사용자의 말로 만들지 않기 위해서다.
    """
    quote, sentence = claim["quote"], claim.get("sentence") or claim["quote"]
    if sentence == quote:
        return f'"{quote}"'
    return f'"{sentence}"에서 "{quote}" 부분'


def claims_to_confirm(review: dict) -> list[dict]:
    """사용자에게 물을 표현. 한 번에 묻는 개수에 상한을 두고, 넘는 것은 묻지 않고 고친다."""
    return review["unsupported"][:settings.DRAFT_CONFIRM_MAX]


def confirm(state: ChatState) -> dict:
    """검증이 찾은 표현이 사실인지 사용자에게 묻는다 (LLM 호출 없음).

    interrupt에서 실행이 멈추고, 답이 오면 이 노드가 처음부터 다시 실행되어 interrupt가 그 답을 돌려준다.
    답은 묻는 표현과 같은 순서의 참/거짓 목록이다 (참 = 사용자가 겪은 사실이 맞다).
    멈출 때 넘기는 값에는 대화 글을 넣지 않는다. 물을 표현은 상태(review)에서 읽는다.
    """
    review = dict(state["review"])
    asked = claims_to_confirm(review)
    # 형식이 틀린 답은 받지 않고 다시 멈춘다. 여기서 예외를 내면 틀린 답이 저장된 채 남아 다음 답을 가린다.
    while True:
        answers = interrupt({"count": len(asked)})
        if isinstance(answers, list) and len(answers) == len(asked) and all(isinstance(a, bool) for a in answers):
            break

    kept = [c for c, yes in zip(asked, answers) if yes]
    denied = [c for c, yes in zip(asked, answers) if not yes] + review["unsupported"][len(asked):]
    update: dict = {"review": {**review, "status": "flagged" if denied else "confirmed",
                               "unsupported": denied, "confirmed": review["confirmed"] + kept}}
    if kept:
        # 사용자가 사실이라고 답한 내용은 사용자의 말이므로 대화 기록에 남긴다. 다시 검증할 때 근거가 된다.
        update["history"] = state["history"] + [{"role": "user", "content": CONFIRM_PREFIX + " / ".join(
            confirmed_text(c) for c in kept)}]
    return update


def route_after_compose(state: ChatState) -> str:
    return "verify" if state["review"]["status"] == "pending" else END


def route_after_verify(state: ChatState) -> str:
    review = state["review"]
    if review["status"] != "flagged" or review["rewrites"] >= settings.DRAFT_MAX_REWRITES:
        return END
    return "confirm" if settings.DRAFT_CONFIRM else "rewrite"


def route_after_confirm(state: ChatState) -> str:
    return "rewrite" if state["review"]["unsupported"] else END


def route_after_rewrite(state: ChatState) -> str:
    # 상한까지 고쳤으면 다시 검증하지 않고 끝낸다 (검증 호출을 한 번 아낀다).
    review = state["review"]
    return "verify" if review["status"] == "rewritten" and review["rewrites"] < settings.DRAFT_MAX_REWRITES else END


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
    g.add_node("verify", verify)
    g.add_node("rewrite", rewrite)
    g.add_conditional_edges("compose", route_after_compose, {"verify": "verify", END: END})
    g.add_node("confirm", confirm)
    g.add_conditional_edges("verify", route_after_verify, {"confirm": "confirm", "rewrite": "rewrite", END: END})
    g.add_conditional_edges("confirm", route_after_confirm, {"rewrite": "rewrite", END: END})
    g.add_conditional_edges("rewrite", route_after_rewrite, {"verify": "verify", END: END})
    return g.compile(checkpointer=checkpointer or get_checkpointer())
