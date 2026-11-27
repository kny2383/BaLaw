"""LLM 호출 계층: 요청이 이전과 같은가, 작업별 설정, 호출 기록, 실패 처리."""
import json
from pathlib import Path

import pytest
from pydantic import BaseModel

import services.llm as llm
from cfg import settings
from tests.snapshot_llm_requests import OFFENSES, collect, versions_of

FIXTURE = Path(__file__).parent / "fixtures" / "llm_requests.json"


def test_requests_are_the_same_as_before_the_call_layer(client, fake):
    """구조 변경의 기준: 호출 종류 여섯 가지의 요청 본문이 계층을 바꾸기 전에 저장한 것과 같다.

    하나만 다르다. 예전 SDK 호출은 글로 받는 요청에 stream을 넣지 않았고, 지금은 stream=false를 넣는다.
    둘 다 "한 번에 받는다"는 같은 뜻이다.
    """
    before = json.loads(FIXTURE.read_text(encoding="utf-8"))
    now = collect(client, fake)
    assert sorted(now) == sorted(before) == sorted(llm.TASKS)
    for task in llm.TASKS:
        body = dict(now[task])
        if "stream" not in before[task]:
            assert body.pop("stream") is False, task
        assert body == before[task], task


def test_every_call_is_recorded_without_content(client, fake):
    llm.RECENT.clear()
    collect(client, fake)
    tasks = [r["task"] for r in llm.RECENT]
    assert set(tasks) == set(llm.TASKS)
    for rec in llm.RECENT:
        assert rec["ok"] is True and rec["provider"] == "openai" and rec["model"] == "gpt-5-mini"
        assert rec["input_tokens"] == 1 and rec["output_tokens"] == 1 and rec["latency_s"] >= 0
        assert set(rec) == {"task", "session", "provider", "model", "response_model", "prompt_version", "input_tokens",
                            "cached_tokens", "output_tokens", "reasoning_tokens", "cost_usd", "latency_s", "ok", "error"}
        assert rec["prompt_version"] == llm.PROMPT_VERSIONS[rec["task"]]
        assert rec["cost_usd"] == pytest.approx((0.25 + 2.00) / 1e6)  # gpt-5-mini 입력 1토큰 + 출력 1토큰
    assert "30만원" not in json.dumps(list(llm.RECENT), ensure_ascii=False)


def test_calls_of_one_session_share_a_tag_that_is_not_the_session_id(client, fake, capsys):
    """작성 한 건의 호출을 묶어 볼 수 있다. 세션 값 자체는 기록과 로그에 남지 않는다."""
    llm.RECENT.clear()
    collect(client, fake)
    tags = {r["session"] for r in llm.RECENT}
    assert len(tags) == 1 and None not in tags  # 대화, 작성, 검증, 재작성, 판례 검색 모두 같은 표지
    sid = fake_session_id(client)  # 다른 세션은 다른 표지
    assert llm.RECENT[-1]["session"] == llm.session_tag(sid) and llm.session_tag(sid) not in tags
    assert len(llm.session_tag(sid)) == 12 and sid not in capsys.readouterr().out
    llm.text("compose", "본문", system="You are a drafting assistant")  # 세션 밖의 호출
    assert llm.RECENT[-1]["session"] is None


def fake_session_id(client) -> str:
    return client.post("/chat/init", json={"text": "중고거래로 30만원을 보냈는데 물건이 오지 않았습니다.", "offense": "사기"}).json()["session_id"]


def test_failure_logs_carry_the_tag_not_the_session_id(client, fake, capsys):
    sid = fake_session_id(client)
    fake.fail_compose = True
    assert client.post("/chat/compose", json={"session_id": sid}).status_code == 502
    out = capsys.readouterr().out
    assert sid not in out and f"session={llm.session_tag(sid)}" in out


def test_prompt_versions_match_the_stored_requests():
    """판본은 죄목별 기준 요청에서 나온다. 프롬프트를 바꿔 기준 요청을 다시 만들면 판본도 함께 바뀌어야 한다."""
    stored = [json.loads((FIXTURE.parent / name).read_text(encoding="utf-8")) for name, _, _ in OFFENSES]
    assert llm.PROMPT_VERSIONS == versions_of(stored)
    assert len(set(llm.PROMPT_VERSIONS.values())) == len(llm.TASKS)


def test_requests_of_every_offense_match_the_stored_ones(client, fake):
    """프롬프트를 따로 가진 죄목마다 지금 코드의 요청이 기준 요청과 같다. 다르면 기준 요청과 판본을 다시 만든다."""
    for name, offense, text in OFFENSES[1:]:  # 첫 죄목(사기)은 위의 계층 변경 전 기준으로 비교한다
        stored = json.loads((FIXTURE.parent / name).read_text(encoding="utf-8"))
        assert collect(client, fake, offense, text) == stored, name
        assert sorted(stored) == sorted(llm.TASKS), name


def test_a_prompt_change_in_any_offense_changes_the_version():
    fraud = {"messages": [{"role": "user", "content": "사기 규칙"}]}
    insult = {"messages": [{"role": "user", "content": "모욕 규칙"}]}
    both = llm.prompt_version_of(fraud, insult)
    assert both != llm.prompt_version_of(fraud, {"messages": [{"role": "user", "content": "모욕 규칙 2"}]})
    assert both != llm.prompt_version_of(fraud)


def test_prompt_version_follows_the_prompt_not_the_model():
    body = {"model": "a", "messages": [{"role": "user", "content": "규칙 1"}]}
    assert llm.prompt_version_of(body) == llm.prompt_version_of({**body, "model": "b", "reasoning_effort": "low"})
    assert llm.prompt_version_of(body) != llm.prompt_version_of({**body, "messages": [{"role": "user", "content": "규칙 2"}]})
    assert llm.prompt_version_of(body) != llm.prompt_version_of({**body, "response_format": {"type": "json_object"}})


def test_cost_uses_the_price_table():
    # gpt-5-mini: 입력 0.25, 캐시된 입력 0.025, 출력 2.00 (100만 토큰당 달러)
    assert llm.cost_usd("compose", "gpt-5-mini", 1000, 0, 500) == pytest.approx((1000 * 0.25 + 500 * 2.00) / 1e6)
    assert llm.cost_usd("compose", "gpt-5-mini-2025-08-07", 1000, 400, 500) == pytest.approx(
        (600 * 0.25 + 400 * 0.025 + 500 * 2.00) / 1e6)


def test_cost_is_unknown_rather_than_zero_when_it_cannot_be_computed(fake, task_settings):
    assert llm.cost_usd("compose", "model-without-price", 1000, 0, 500) is None
    assert llm.cost_usd("compose", "gpt-5-mini", None, None, None) is None
    # 실패한 호출은 토큰 수가 없다.
    fake.fail_compose = True
    with pytest.raises(llm.LLMCallError):
        llm.text("compose", "본문", system="You are a drafting assistant")
    assert llm.RECENT[-1]["cost_usd"] is None and llm.RECENT[-1]["prompt_version"] == llm.PROMPT_VERSIONS["compose"]
    # 다른 서버로 보낸 작업은 모델 이름이 같아도 단가가 다르므로 계산하지 않는다.
    fake.fail_compose = False
    task_settings(base_urls={"compose": fake.base_url})
    llm.text("compose", "본문", system="You are a drafting assistant")
    assert llm.RECENT[-1]["ok"] is True and llm.RECENT[-1]["cost_usd"] is None


def test_failed_call_is_recorded_and_raised(fake):
    llm.RECENT.clear()
    fake.fail_compose = True
    with pytest.raises(llm.LLMCallError):
        llm.text("compose", "본문", system="You are a drafting assistant")
    assert llm.RECENT[-1]["ok"] is False and llm.RECENT[-1]["error"].endswith("Error")  # 예외의 종류만 남는다
    assert "fake failure" not in json.dumps(llm.RECENT[-1])


def test_empty_text_output_is_an_error(fake):
    fake.compose_text = "  "
    with pytest.raises(llm.LLMCallError, match="empty_output"):
        llm.text("compose", "본문", system="You are a drafting assistant")
    assert llm.RECENT[-1]["error"] == "empty_output"


def test_output_that_does_not_fit_the_schema_is_an_error(fake):
    class Strict(BaseModel):
        must_be_number: int

    with pytest.raises(llm.StructuredOutputError, match="no_parsed_output"):
        llm.parsed("verify", "system", "user", Strict)  # 가짜 서버는 문자열로 채운다


@pytest.fixture
def task_settings(monkeypatch):
    """작업별 설정을 바꾸고, 끝나면 만들어 둔 모델 객체를 버린다."""
    def change(models=None, base_urls=None, api_keys=None):
        monkeypatch.setattr(settings, "LLM_MODELS", {**settings.LLM_MODELS, **(models or {})})
        monkeypatch.setattr(settings, "LLM_BASE_URLS", {**settings.LLM_BASE_URLS, **(base_urls or {})})
        monkeypatch.setattr(settings, "LLM_API_KEYS", {**settings.LLM_API_KEYS, **(api_keys or {})})
        llm.reset()
    yield change
    monkeypatch.undo()
    llm.reset()


def test_model_can_be_changed_for_one_task_only(fake, task_settings):
    task_settings(models={"compose": "another-model"})
    llm.text("compose", "본문", system="You are a drafting assistant")
    assert fake.requests[-1]["body"]["model"] == "another-model"
    llm.text("rewrite", "본문", system="You revise a draft")
    assert fake.requests[-1]["body"]["model"] == "gpt-5-mini"
    assert llm.RECENT[-2]["model"] == "another-model"


def test_one_task_can_be_sent_to_another_openai_compatible_server(fake, task_settings):
    """로컬 모델 서버처럼 OpenAI 호환 API를 내는 다른 주소로 한 작업만 보낸다."""
    from tests.fake_openai import FakeOpenAI
    other = FakeOpenAI()
    try:
        task_settings(models={"rag_keyword": "local-model"}, base_urls={"rag_keyword": other.base_url})
        assert llm.text("rag_keyword", "죄목 리스트 ...") == "사기"
        assert [r["body"]["model"] for r in other.requests] == ["local-model"] and fake.requests == []
        llm.text("compose", "본문", system="You are a drafting assistant")
        assert len(fake.requests) == 1 and len(other.requests) == 1
        # 다른 서버에는 OpenAI 키를 보내지 않는다. 기본 주소로 가는 호출에만 보낸다.
        assert other.auth == ["Bearer not-needed"] and fake.auth == ["Bearer test-key"]
        # 그 서버의 키를 따로 주면 그 키를 보낸다.
        task_settings(models={"rag_keyword": "local-model"}, base_urls={"rag_keyword": other.base_url},
                      api_keys={"rag_keyword": "local-key"})
        llm.text("rag_keyword", "죄목 리스트 ...")
        assert other.auth[-1] == "Bearer local-key" and "test-key" not in " ".join(other.auth)
    finally:
        other.close()


def test_per_task_settings_are_read_from_the_environment(monkeypatch):
    import cfg
    monkeypatch.setenv("LLM_MODEL_EXTRACT", "small-model")
    got = cfg._per_task("LLM_MODEL", {"extract": "default", "compose": "default"})
    assert got == {"extract": "small-model", "compose": "default"}
    assert cfg._per_task("LLM_BASE_URL", {}) == {}
