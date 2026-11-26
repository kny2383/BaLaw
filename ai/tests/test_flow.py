"""대화 그래프의 노드와 상태 저장 테스트. LLM은 가짜 서버가 대신한다."""
import copy
import typing

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from flow.chat_graph import DONE_REPLY, build_chat_graph, route_request, select_question
from loaders.detail_loader import get_detail_schema
from loaders.offense_loader import get_offense_meta
from services.llm import StructuredOutputError

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
    assert out["review"] == {"status": "passed", "rewrites": 0, "rechecked": False, "unsupported": [], "removed": [], "confirmed": []}
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


# ---------- 사용자 확인 (interrupt) ----------
OTHER = "금원을"  # 가짜 초안에 들어 있는 다른 표현
SENTENCE = "고소인은 피고소인에게 금원을 송금하였습니다."  # BAD와 OTHER가 든 초안의 문장


def _compose_with_confirm(fake, monkeypatch, found, max_rewrites=1, confirm_max=5):
    """확인을 켠 채 작성을 요청한다. 그래프와 멈춘 뒤의 결과를 돌려준다."""
    from cfg import settings
    monkeypatch.setattr(settings, "DRAFT_MAX_REWRITES", max_rewrites)
    monkeypatch.setattr(settings, "DRAFT_CONFIRM", True)
    monkeypatch.setattr(settings, "DRAFT_CONFIRM_MAX", confirm_max)
    fake.verify_results = found
    saver = InMemorySaver()
    graph = build_chat_graph(saver)
    graph.invoke(INIT, CONFIG)
    graph.invoke({"request": {"action": "message", "message": "네"}}, CONFIG)
    fake.requests.clear()
    return saver, graph, graph.invoke({"request": {"action": "compose"}}, CONFIG)


def test_confirm_stops_before_rewriting(fake, monkeypatch):
    _, graph, out = _compose_with_confirm(fake, monkeypatch, [[BAD]])
    assert _kinds(fake) == ["compose", "verify"], "답을 받기 전에는 고쳐 쓰지 않는다"
    assert graph.get_state(CONFIG).next == ("confirm",)
    assert out["review"]["status"] == "flagged" and BAD in out["draft"]["sections"]["criminal_facts"]
    # 멈출 때 넘기는 값에는 대화 글이 없다.
    assert [i.value for i in out["__interrupt__"]] == [{"count": 1}]


def test_confirm_is_skipped_when_nothing_is_found(fake, monkeypatch):
    _, graph, out = _compose_with_confirm(fake, monkeypatch, [])
    assert graph.get_state(CONFIG).next == () and out["review"]["status"] == "passed"


def test_denied_claim_is_rewritten(fake, monkeypatch):
    _, graph, _ = _compose_with_confirm(fake, monkeypatch, [[BAD]])
    out = graph.invoke(Command(resume=[False]), CONFIG)
    assert _kinds(fake) == ["compose", "verify", "rewrite"]
    assert out["review"]["status"] == "rewritten" and out["review"]["confirmed"] == []
    assert [c["quote"] for c in out["review"]["removed"]] == [BAD]
    assert BAD not in out["draft"]["sections"]["criminal_facts"]
    assert graph.get_state(CONFIG).next == ()


def test_confirmed_claim_stays_and_becomes_what_the_user_said(fake, monkeypatch):
    _, graph, before = _compose_with_confirm(fake, monkeypatch, [[BAD]])
    out = graph.invoke(Command(resume=[True]), CONFIG)
    assert _kinds(fake) == ["compose", "verify"], "모두 사실이면 고쳐 쓰지 않는다"
    assert out["review"]["status"] == "confirmed" and out["review"]["unsupported"] == []
    assert [c["quote"] for c in out["review"]["confirmed"]] == [BAD]
    assert out["draft"] == before["draft"]
    assert out["history"][-1]["role"] == "user" and BAD in out["history"][-1]["content"]


def test_only_denied_claims_go_to_rewrite(fake, monkeypatch):
    _, graph, _ = _compose_with_confirm(fake, monkeypatch, [[BAD, OTHER]])
    out = graph.invoke(Command(resume=[True, False]), CONFIG)
    prompt = fake.requests[-1]["body"]["messages"][-1]["content"]
    assert f'"{OTHER}"' in prompt and f'"{BAD}"' not in prompt
    assert [c["quote"] for c in out["review"]["confirmed"]] == [BAD]
    assert [c["quote"] for c in out["review"]["removed"]] == [OTHER]


def test_claims_over_the_limit_are_rewritten_without_asking(fake, monkeypatch):
    _, graph, out = _compose_with_confirm(fake, monkeypatch, [[BAD, OTHER]], confirm_max=1)
    assert [i.value for i in out["__interrupt__"]] == [{"count": 1}]
    out = graph.invoke(Command(resume=[True]), CONFIG)
    assert [c["quote"] for c in out["review"]["confirmed"]] == [BAD]
    assert [c["quote"] for c in out["review"]["removed"]] == [OTHER]


def test_wrong_answer_shape_is_rejected_and_the_question_stays(fake, monkeypatch):
    _, graph, _ = _compose_with_confirm(fake, monkeypatch, [[BAD]])
    for wrong in ([True, False], "yes", [1]):
        out = graph.invoke(Command(resume=wrong), CONFIG)
        assert graph.get_state(CONFIG).next == ("confirm",) and out["review"]["status"] == "flagged"
    assert _kinds(fake) == ["compose", "verify"]
    assert graph.invoke(Command(resume=[False]), CONFIG)["review"]["status"] == "rewritten"


def test_waiting_confirmation_survives_a_new_graph_object(fake, monkeypatch):
    """멈춘 상태는 체크포인터에 있다. 서비스가 재시작해도 답을 받아 이어 간다."""
    saver, _, _ = _compose_with_confirm(fake, monkeypatch, [[BAD]])
    graph = build_chat_graph(saver)
    assert graph.get_state(CONFIG).next == ("confirm",)
    assert graph.invoke(Command(resume=[False]), CONFIG)["review"]["status"] == "rewritten"


def test_second_verify_uses_the_confirmation(fake, monkeypatch):
    """다시 검증할 때 사용자가 사실이라고 답한 내용이 대화에 들어 있다."""
    _, graph, _ = _compose_with_confirm(fake, monkeypatch, [[BAD, OTHER], []], max_rewrites=2)
    out = graph.invoke(Command(resume=[True, False]), CONFIG)
    assert _kinds(fake) == ["compose", "verify", "rewrite", "verify"]
    prompt = fake.requests[-1]["body"]["messages"][-1]["content"]
    # 사용자가 확인한 범위는 구절이다. 문장은 뜻을 정하는 문맥으로만 적는다.
    assert f'사실이 맞습니다: "{SENTENCE}"에서 "{BAD}" 부분' in prompt
    assert out["review"]["status"] == "rewritten" and out["review"]["rechecked"] is True


def test_new_request_discards_a_waiting_confirmation(fake, monkeypatch):
    _, graph, _ = _compose_with_confirm(fake, monkeypatch, [[BAD]])
    graph.invoke({"request": {"action": "message", "message": "추가로 말씀드립니다"}}, CONFIG)
    assert graph.get_state(CONFIG).next == ()


def test_confirm_limit_must_be_at_least_one(monkeypatch):
    import cfg
    monkeypatch.setenv("DRAFT_CONFIRM_MAX", "0")
    with pytest.raises(ValueError):
        cfg._at_least_one("DRAFT_CONFIRM_MAX", 5)
    monkeypatch.setenv("DRAFT_CONFIRM_MAX", "")
    assert cfg._at_least_one("DRAFT_CONFIRM_MAX", 5) == 5


def test_claim_carries_the_sentence_it_sits_in(fake, monkeypatch):
    """검증은 근거 없는 구절만 인용한다. 사용자에게 물을 때 보여 줄 문장은 초안에서 찾아 붙인다."""
    _, _, out = _compose_with_confirm(fake, monkeypatch, [[BAD]])
    assert out["review"]["unsupported"] == [{"quote": BAD, "reason": "대화에 없는 내용", "sentence": SENTENCE}]


def test_rewrite_is_told_which_sentence_the_phrase_is_in(fake, monkeypatch):
    fake.verify_results = [[BAD]]
    _compose(fake, monkeypatch)
    prompt = fake.requests[-1]["body"]["messages"][-1]["content"]
    assert f'- "{BAD}" — 문장: "{SENTENCE}"' in prompt


def test_whole_sentence_quote_is_not_repeated(fake, monkeypatch):
    fake.verify_results = [[SENTENCE]]
    out = _compose(fake, monkeypatch)
    prompt = fake.requests[-1]["body"]["messages"][-1]["content"]
    assert f'- "{SENTENCE}" (' in prompt and "— 문장:" not in prompt
    assert out["review"]["removed"][0]["sentence"] == SENTENCE


def test_bullet_mark_is_not_part_of_the_quote(fake, monkeypatch):
    fake.verify_results = [["○ " + SENTENCE]]
    out = _compose(fake, monkeypatch)
    assert out["review"]["removed"] == [{"quote": SENTENCE, "reason": "대화에 없는 내용", "sentence": SENTENCE}]


def test_confirmation_records_only_the_confirmed_phrase_as_said(fake, monkeypatch):
    _, graph, _ = _compose_with_confirm(fake, monkeypatch, [[BAD, OTHER]])
    out = graph.invoke(Command(resume=[True, True]), CONFIG)
    assert out["history"][-1]["content"].endswith(
        f'사실이 맞습니다: "{SENTENCE}"에서 "{BAD}" 부분 / "{SENTENCE}"에서 "{OTHER}" 부분')


def test_whole_sentence_confirmation_is_recorded_as_is(fake, monkeypatch):
    _, graph, _ = _compose_with_confirm(fake, monkeypatch, [[SENTENCE]])
    out = graph.invoke(Command(resume=[True]), CONFIG)
    assert out["history"][-1]["content"].endswith(f'사실이 맞습니다: "{SENTENCE}"')


def test_phrase_found_in_several_sentences_gets_no_sentence(fake, monkeypatch):
    """같은 구절이 여러 문장에 있으면 어느 문장인지 정할 수 없다. 엉뚱한 문장을 붙이지 않는다."""
    from services.verify import sentence_of
    draft = "○ 고소인은 금원을 보냈습니다.\n○ 피고소인은 금원을 받았습니다."
    assert sentence_of("금원을", draft) == "금원을"
    assert sentence_of("보냈습니다", draft) == "고소인은 금원을 보냈습니다."


# ---------- 추출에 넣는 사용자 발화 ----------
def _old_window(history, max_chars):
    """고치기 전의 구현. 짧은 대화에서 결과가 같다는 것을 보이려고 남긴다."""
    buf, used = [], 0
    for m in reversed(history):
        if m["role"] != "user":
            continue
        c = m["content"]
        if used + len(c) > max_chars and buf:
            break
        buf.append(c)
        used += len(c)
        if used >= max_chars:
            break
    return "\n".join(reversed(buf))


def _hist(*users):
    out = []
    for u in users:
        out += [{"role": "user", "content": u}, {"role": "assistant", "content": "질문"}]
    return out


def test_short_dialogue_window_is_unchanged():
    """예전 상한(1,800자) 안의 대화는 추출 입력이 글자까지 같다. 평가 사례는 모두 여기에 든다."""
    from services.pipelines import _user_window
    history = _hist("서술 " * 100, "위 사건 개요를 기반으로, 이어서 질문을 해 주세요.", "답 " * 200, "잘 모르겠어요.")
    assert sum(len(m["content"]) for m in history if m["role"] == "user") < 1800
    assert _user_window(history, max_chars=6000) == _old_window(history, 1800)


def test_long_narrative_is_not_dropped():
    """서술이 길면 예전에는 서술이 통째로 빠지고 고정 문장만 추출에 들어갔다."""
    from services.pipelines import _user_window
    narrative, kickoff = "가" * 2000, "위 사건 개요를 기반으로, 이어서 질문을 해 주세요."
    history = _hist(narrative, kickoff)
    assert _old_window(history, 1800) == kickoff, "고치기 전의 동작"
    assert _user_window(history, max_chars=6000) == narrative + "\n" + kickoff


def test_window_keeps_the_narrative_and_recent_answers_when_over_the_limit():
    from services.pipelines import _user_window
    narrative = "서술" * 100                      # 200자
    answers = [f"답{i:02d}" + "x" * 97 for i in range(10)]  # 100자씩
    out = _user_window(_hist(narrative, *answers), max_chars=500)
    assert out.split("\n") == [narrative] + answers[-3:]  # 처음 서술과 최근 답 3개
    assert len(out.replace("\n", "")) <= 500


def test_very_long_narrative_is_cut_but_recent_answers_stay():
    from services.pipelines import _user_window
    out = _user_window(_hist("가" * 5000, "최근 답"), max_chars=900)
    assert out == "가" * (900 - len("최근 답")) + "\n최근 답"
    assert _user_window(_hist("가" * 5000), max_chars=900) == "가" * 900
