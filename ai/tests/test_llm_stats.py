"""LLM 호출 기록 집계."""
import json

import services.llm as llm
from services import llm_stats
from tests.snapshot_llm_requests import collect


def rec(task="compose", ok=True, latency=1.0, cost=0.01, error=None, **more):
    return {"task": task, "model": "gpt-5-mini", "response_model": "gpt-5-mini-2025-08-07", "prompt_version": "aaaa1111",
            "input_tokens": 100, "cached_tokens": 0, "output_tokens": 50, "reasoning_tokens": 10,
            "cost_usd": cost, "latency_s": latency, "ok": ok, "error": error, **more}


def test_summary_groups_by_task():
    s = llm_stats.summarize([rec("compose", latency=1.0), rec("compose", latency=3.0), rec("verify", latency=2.0)])
    assert list(s["tasks"]) == ["compose", "verify"]
    assert s["tasks"]["compose"]["calls"] == 2 and s["total"]["calls"] == 3
    assert s["tasks"]["compose"]["input_tokens"] == 200 and s["tasks"]["compose"]["reasoning_tokens"] == 20
    assert s["tasks"]["compose"]["cost_usd"] == 0.02 and s["total"]["cost_usd"] == 0.03
    assert s["tasks"]["compose"]["models"] == ["gpt-5-mini-2025-08-07"]


def test_failures_are_counted_by_reason():
    failed = dict(ok=False, cost=None, input_tokens=None, output_tokens=None, reasoning_tokens=None)
    g = llm_stats.summarize([rec(), rec(error="APITimeoutError", **failed), rec(error="APITimeoutError", **failed),
                             rec(error="empty_output", **failed)])["tasks"]["compose"]
    assert g["failed"] == 3 and g["failure_rate"] == 0.75
    assert g["errors"] == {"APITimeoutError": 2, "empty_output": 1}


def test_calls_without_cost_are_reported_not_counted_as_free():
    g = llm_stats.summarize([rec(cost=0.01), rec(cost=None), rec(cost=None)])["total"]
    assert g["cost_usd"] == 0.01 and g["calls_without_cost"] == 2


def test_percentiles():
    g = llm_stats.summarize([rec(latency=float(i)) for i in range(1, 101)])["total"]
    assert g["latency_p50_s"] == 50.0 and g["latency_p95_s"] == 95.0
    assert llm_stats.summarize([rec(latency=7.0)])["total"]["latency_p95_s"] == 7.0


def test_mixed_prompt_versions_are_visible():
    g = llm_stats.summarize([rec(), rec(prompt_version="bbbb2222")])["tasks"]["compose"]
    assert g["prompt_versions"] == ["aaaa1111", "bbbb2222"]


def test_empty_summary():
    s = llm_stats.summarize([])
    assert s["tasks"] == {} and s["total"]["calls"] == 0 and s["total"]["failure_rate"] is None
    assert s["total"]["latency_p50_s"] is None


def test_log_lines_are_parsed_and_other_lines_skipped():
    lines = ["ai-1  | [RAG CACHE] miss version=v1\n", "ai-1  | [LLM] " + json.dumps(rec("verify")) + "\n",
             "ai-1  | [LLM] {깨진 줄\n", "[LLM] " + json.dumps(rec("compose")), "[LLM] 3\n"]
    got = llm_stats.parse_log(lines)
    assert [r["task"] for r in got] == ["verify", "compose"]
    assert "| verify | 1 | 0 |" in llm_stats.table(llm_stats.summarize(got))


def test_stats_endpoint_is_closed_unless_a_token_is_set(client, monkeypatch):
    from cfg import settings
    assert settings.LLM_STATS_TOKEN == ""
    assert client.get("/llm/stats").status_code == 404
    assert client.get("/llm/stats", headers={"Authorization": "Bearer "}).status_code == 404  # 빈 토큰끼리 맞는 일이 없다
    monkeypatch.setattr(settings, "LLM_STATS_TOKEN", "stats-secret")
    assert client.get("/llm/stats").status_code == 404
    assert client.get("/llm/stats", headers={"Authorization": "Bearer wrong"}).status_code == 404
    assert client.get("/llm/stats", headers={"Authorization": "Bearer stats-secret"}).status_code == 200


def test_stats_endpoint_reports_recent_calls_without_content(client, fake, monkeypatch):
    from cfg import settings
    monkeypatch.setattr(settings, "LLM_STATS_TOKEN", "stats-secret")
    llm.RECENT.clear()
    collect(client, fake)
    body = client.get("/llm/stats", headers={"Authorization": "Bearer stats-secret"}).json()
    assert sorted(body["tasks"]) == sorted(llm.TASKS) and body["window"] == llm.RECENT.maxlen
    assert body["total"]["calls"] == len(llm.RECENT) and body["total"]["failed"] == 0
    assert body["tasks"]["compose"]["prompt_versions"] == [llm.PROMPT_VERSIONS["compose"]]
    assert body["total"]["calls_without_cost"] == 0 and body["total"]["cost_usd"] > 0
    assert "30만원" not in json.dumps(body, ensure_ascii=False)
