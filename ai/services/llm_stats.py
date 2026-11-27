"""LLM 호출 기록을 작업별로 모은다.

기록(`services.llm`의 `[LLM] {...}` 줄)에는 내용이 없고 수치만 있으므로, 집계에도 내용이 들어가지 않는다.

    GET /llm/stats                                  실행 중인 서비스의 최근 호출 (LLM_STATS_TOKEN을 설정해야 열린다)
    docker compose logs ai | python -m services.llm_stats    로그에 남은 호출 (재시작 전 것도 포함)
"""
from __future__ import annotations

import json
import math
import sys
from typing import Iterable, Optional

MARK = "[LLM] "


def _percentile(values: list[float], q: float) -> Optional[float]:
    """가장 가까운 순위 방식. 값이 없으면 None."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(q * len(ordered)) - 1)]


def _group(records: list[dict]) -> dict:
    failed = [r for r in records if not r.get("ok")]
    errors: dict = {}
    for r in failed:
        key = r.get("error") or "unknown"
        errors[key] = errors.get(key, 0) + 1
    latency = [r["latency_s"] for r in records if r.get("latency_s") is not None]
    priced = [r["cost_usd"] for r in records if r.get("cost_usd") is not None]

    def total(field: str) -> int:
        return sum(r.get(field) or 0 for r in records)

    return {
        "calls": len(records), "failed": len(failed),
        "failure_rate": round(len(failed) / len(records), 4) if records else None,
        "errors": dict(sorted(errors.items())),
        "latency_p50_s": _percentile(latency, 0.5), "latency_p95_s": _percentile(latency, 0.95),
        "input_tokens": total("input_tokens"), "cached_tokens": total("cached_tokens"),
        "output_tokens": total("output_tokens"), "reasoning_tokens": total("reasoning_tokens"),
        # 비용을 계산하지 못한 호출이 있으면 cost_usd는 실제보다 작다. 그 수를 함께 낸다.
        "cost_usd": round(sum(priced), 6), "calls_without_cost": len(records) - len(priced),
        "models": sorted({str(r.get("response_model") or r.get("model")) for r in records}),
        "prompt_versions": sorted({str(r.get("prompt_version")) for r in records}),
    }


def summarize(records: Iterable[dict]) -> dict:
    """전체와 작업별 집계. 작업 안에서 모델이나 프롬프트 판본이 섞였으면 목록에 둘 이상이 나온다."""
    records = list(records)
    tasks = sorted({r["task"] for r in records})
    return {"total": _group(records), "tasks": {t: _group([r for r in records if r["task"] == t]) for t in tasks}}


def parse_log(lines: Iterable[str]) -> list[dict]:
    """로그에서 호출 기록 줄만 읽는다. 다른 줄과 깨진 줄은 건너뛴다."""
    out = []
    for line in lines:
        _, mark, rest = line.partition(MARK)
        if not mark:
            continue
        try:
            rec = json.loads(rest)
        except ValueError:
            continue
        if isinstance(rec, dict) and "task" in rec:
            out.append(rec)
    return out


def table(summary: dict) -> str:
    head = "| 작업 | 호출 | 실패 | p50(초) | p95(초) | 입력 토큰 | 출력 토큰 | 추론 토큰 | 비용(달러) | 비용 모름 | 프롬프트 판본 |"
    rows = [head, "|" + "---|" * 11]
    for name, g in [*summary["tasks"].items(), ("전체", summary["total"])]:
        rows.append(f"| {name} | {g['calls']} | {g['failed']} | {g['latency_p50_s']} | {g['latency_p95_s']} | {g['input_tokens']} "
                    f"| {g['output_tokens']} | {g['reasoning_tokens']} | {g['cost_usd']} | {g['calls_without_cost']} "
                    f"| {', '.join(g['prompt_versions']) if name != '전체' else ''} |")
    return "\n".join(rows)


if __name__ == "__main__":
    print(table(summarize(parse_log(sys.stdin))))
