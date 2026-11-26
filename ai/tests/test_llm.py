"""LLM 호출 계층: 요청이 이전과 같은가, 작업별 설정, 호출 기록, 실패 처리."""
import json
from pathlib import Path

import pytest
from pydantic import BaseModel

import services.llm as llm
from cfg import settings
from tests.snapshot_llm_requests import collect

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
        assert set(rec) == {"task", "provider", "model", "response_model", "input_tokens", "output_tokens",
                            "reasoning_tokens", "latency_s", "ok", "error"}
    assert "30만원" not in json.dumps(list(llm.RECENT), ensure_ascii=False)


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
    def change(models=None, base_urls=None):
        monkeypatch.setattr(settings, "LLM_MODELS", {**settings.LLM_MODELS, **(models or {})})
        monkeypatch.setattr(settings, "LLM_BASE_URLS", {**settings.LLM_BASE_URLS, **(base_urls or {})})
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
    finally:
        other.close()


def test_per_task_settings_are_read_from_the_environment(monkeypatch):
    import cfg
    monkeypatch.setenv("LLM_MODEL_EXTRACT", "small-model")
    got = cfg._per_task("LLM_MODEL", {"extract": "default", "compose": "default"})
    assert got == {"extract": "small-model", "compose": "default"}
    assert cfg._per_task("LLM_BASE_URL", {}) == {}
