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
