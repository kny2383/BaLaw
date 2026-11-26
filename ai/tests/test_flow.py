"""대화 그래프의 노드와 상태 저장 테스트. LLM은 가짜 서버가 대신한다."""
import copy
import typing

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from flow.chat_graph import DONE_REPLY, build_chat_graph, route_request, select_question
from loaders.detail_loader import get_detail_schema
from loaders.offense_loader import get_offense_meta
from services.openai_client import StructuredOutputError

CONFIG = {"configurable": {"thread_id": "t1"}}
INIT = {"request": {"action": "init", "text": "사건 개요", "offense": "fraud", "offense_selected": True}}


def _collected(value: str) -> dict:
    """사기 양식의 모든 슬롯을 한 값으로 채운 수집 상태."""
    meta = get_offense_meta("fraud")
    status = "satisfied" if value == "present" else "missing"
    elements = {e.id: {"status": status, "summary": "요약",
                       "slots": {s: value for s in list(e.slots.must) + list(e.slots.nice_to_have)}}
                for e in meta.elements}
    details = {d["id"]: {"status": status, "summary": "요약",
                         "slots": {s: value for s in list(d["must"]) + list(d["nice"])}}
               for d in get_detail_schema("fraud")}
    return {"elements": elements, "details": details}


def _asked(collected: dict) -> int:
    return sum(n for group in collected.values() for rec in group.values()
               for n in (rec.get("_asked_count") or {}).values())


def test_route_follows_request_action():
    for action in ("init", "message", "compose"):
        assert route_request({"request": {"action": action}}) == action


def test_graph_has_expected_nodes(fake):
    nodes = set(build_chat_graph(InMemorySaver()).get_graph().nodes)
    assert {"init", "extract", "select_question", "compose"} <= nodes


def test_select_question_asks_one_missing_slot_without_touching_input():
    state = {"offense": "fraud", "collected": _collected("missing"),
             "history": [{"role": "user", "content": "사건 개요"}]}
    before = copy.deepcopy(state)
    out = select_question(state)
    assert state == before, "노드는 받은 상태를 고치지 않고 새 값을 돌려준다"
    result = out["result"]
    assert result["complete"] is False and result["reply"] != DONE_REPLY
    assert _asked(out["collected"]) == 1
    assert out["history"][-1] == {"role": "assistant", "content": result["reply"]}


def test_select_question_completes_when_everything_is_present():
    state = {"offense": "fraud", "collected": _collected("present"),
             "history": [{"role": "user", "content": "사건 개요"}]}
    out = select_question(state)
    assert out["result"]["complete"] is True and out["result"]["reply"] == DONE_REPLY
    assert _asked(out["collected"]) == 0


def test_select_question_sets_caution_from_user_messages_only():
    base = {"offense": "fraud", "collected": _collected("present")}
    user = select_question({**base, "history": [{"role": "user", "content": "협박을 당했습니다"}]})
    assistant = select_question({**base, "history": [{"role": "user", "content": "사건 개요"},
                                                     {"role": "assistant", "content": "협박이 있었나요?"}]})
    assert user["result"]["caution"] is True and assistant["result"]["caution"] is False


def test_state_survives_a_new_graph_object(fake):
    """상태는 그래프 객체가 아니라 체크포인터에 있다. 서비스가 다시 떠도 같은 저장소면 이어진다."""
    saver = InMemorySaver()
    first = build_chat_graph(saver)
    first.invoke(INIT, CONFIG)
    first.invoke({"request": {"action": "message", "message": "네"}}, CONFIG)

    second = build_chat_graph(saver)
    state = second.get_state(CONFIG).values
    assert [m["role"] for m in state["history"]] == ["user", "user", "assistant"]
    out = second.invoke({"request": {"action": "compose"}}, CONFIG)
    assert set(out["draft"]["sections"]) == {"criminal_facts", "accusation_reason"}


def test_failed_extraction_saves_nothing(fake):
    graph = build_chat_graph(InMemorySaver())
    graph.invoke(INIT, CONFIG)
    fake.fail_extract = True
    with pytest.raises(StructuredOutputError):
        graph.invoke({"request": {"action": "message", "message": "네"}}, CONFIG)
    state = graph.get_state(CONFIG).values
    assert state["history"] == [{"role": "user", "content": "사건 개요"}]
    assert state["collected"] == {}

    fake.fail_extract = False
    out = graph.invoke({"request": {"action": "message", "message": "네"}}, CONFIG)
    assert [m["content"] for m in out["history"][:2]] == ["사건 개요", "네"]


def test_sessions_do_not_share_state(fake):
    graph = build_chat_graph(InMemorySaver())
    other = {"configurable": {"thread_id": "t2"}}
    graph.invoke(INIT, CONFIG)
    graph.invoke({"request": {**INIT["request"], "text": "다른 사건", "offense": "insult"}}, other)
    graph.invoke({"request": {"action": "message", "message": "네"}}, CONFIG)
    assert graph.get_state(other).values["history"] == [{"role": "user", "content": "다른 사건"}]
    assert graph.get_state(other).values["offense"] == "insult"


def test_only_fixed_codes_are_plain_state_fields():
    """문자열·숫자·불리언 값은 암호화 없이 저장된다. 대화에서 나온 글이 그런 자리에 놓이지 않게 막는다."""
    from flow.state import PLAIN_FIELDS, ChatState, RagState

    for schema in (ChatState, RagState):
        for name, annotation in typing.get_type_hints(schema).items():
            if name in PLAIN_FIELDS:
                continue
            container = typing.get_origin(annotation) or annotation
            assert container in (dict, list), f"{schema.__name__}.{name}: {annotation}는 암호화되지 않는다"


# ---------- 작성 → 검증 → 재작성 ----------
BAD = "피고소인에게"  # 가짜 초안(COMPOSE_TEXT)에 들어 있는 표현


def _compose(fake, monkeypatch, max_rewrites=1):
    from cfg import settings
    monkeypatch.setattr(settings, "DRAFT_MAX_REWRITES", max_rewrites)
    graph = build_chat_graph(InMemorySaver())
    graph.invoke(INIT, CONFIG)
    graph.invoke({"request": {"action": "message", "message": "네"}}, CONFIG)
    fake.requests.clear()
    return graph.invoke({"request": {"action": "compose"}}, CONFIG)


def _kinds(fake) -> list[str]:
    """작성 요청 동안 나간 LLM 호출의 종류를 순서대로."""
    kinds = []
    for r in fake.requests:
        body = r["body"]
        if body.get("response_format"):
            kinds.append("verify")
        elif "revise a draft" in body["messages"][0]["content"]:
            kinds.append("rewrite")
        else:
            kinds.append("compose")
    return kinds


def test_graph_has_verify_and_rewrite_nodes():
    assert {"verify", "rewrite"} <= set(build_chat_graph(InMemorySaver()).get_graph().nodes)


def test_clean_draft_is_not_rewritten(fake, monkeypatch):
    out = _compose(fake, monkeypatch)
    assert _kinds(fake) == ["compose", "verify"]
    assert out["review"] == {"status": "passed", "rewrites": 0, "rechecked": False, "unsupported": [], "removed": []}
    assert BAD in out["draft"]["sections"]["criminal_facts"]


def test_unsupported_claim_is_rewritten_once(fake, monkeypatch):
    fake.verify_results = [[BAD]]
    out = _compose(fake, monkeypatch)
    assert _kinds(fake) == ["compose", "verify", "rewrite"]
    assert out["review"]["status"] == "rewritten" and out["review"]["rewrites"] == 1
    assert out["review"]["rechecked"] is False  # 상한 1에서는 고쳐 쓴 초안을 다시 검증하지 않는다
    assert [c["quote"] for c in out["review"]["removed"]] == [BAD]
    assert BAD not in out["draft"]["sections"]["criminal_facts"]
    # 재작성 요청에는 지적된 표현과 초안이 들어간다.
    prompt = fake.requests[-1]["body"]["messages"][-1]["content"]
    assert f'"{BAD}"' in prompt and "=== 범죄사실 ===" in prompt


def test_verify_sees_questions_and_answers(fake, monkeypatch):
    _compose(fake, monkeypatch)
    prompt = fake.requests[1]["body"]["messages"][-1]["content"]
    assert "사용자: 사건 개요" in prompt and "사용자: 네" in prompt and "질문: " in prompt


def test_rewrite_loop_stops_at_the_limit(fake, monkeypatch):
    """계속 근거 없는 표현이 나와도 상한에서 멈춘다."""
    fake.verify_results = [[BAD], ["금원을"], ["금원을"]]
    out = _compose(fake, monkeypatch, max_rewrites=2)
    assert _kinds(fake) == ["compose", "verify", "rewrite", "verify", "rewrite"]
    assert out["review"]["rewrites"] == 2
    assert out["review"]["rechecked"] is False  # 마지막으로 고쳐 쓴 초안은 다시 검증하지 않았다


def test_second_verify_can_pass(fake, monkeypatch):
    fake.verify_results = [[BAD], []]
    out = _compose(fake, monkeypatch, max_rewrites=2)
    assert _kinds(fake) == ["compose", "verify", "rewrite", "verify"]
    assert out["review"]["status"] == "rewritten" and out["review"]["rewrites"] == 1
    assert out["review"]["rechecked"] is True


def test_verification_can_be_turned_off(fake, monkeypatch):
    out = _compose(fake, monkeypatch, max_rewrites=0)
    assert _kinds(fake) == ["compose"]
    assert out["review"]["status"] == "off"


def test_failed_verification_is_reported_not_hidden(fake, monkeypatch):
    fake.fail_verify = True
    out = _compose(fake, monkeypatch)
    assert out["review"]["status"] == "unverified"
    assert BAD in out["draft"]["sections"]["criminal_facts"]  # 초안은 그대로


def test_failed_rewrite_keeps_the_draft_and_says_so(fake, monkeypatch):
    fake.verify_results = [[BAD]]
    fake.rewrite_text = ""
    out = _compose(fake, monkeypatch)
    assert out["review"]["status"] == "rewrite_failed"
    assert [c["quote"] for c in out["review"]["unsupported"]] == [BAD]
    assert BAD in out["draft"]["sections"]["criminal_facts"]


def test_quote_not_in_the_draft_is_ignored(fake, monkeypatch):
    fake.verify_results = [["초안에 없는 문장"]]
    out = _compose(fake, monkeypatch)
    assert _kinds(fake) == ["compose", "verify"]
    assert out["review"]["status"] == "passed"
