"""실패 주입 측정 (M10: 실패 은폐 건수).

기록 장치가 호출 종류 하나에만 실패를 돌려주게 하고, 서비스의 응답이 그 실패를 드러내는지 본다.

    python3 eval/fail_inject.py --run-id fail-1

호출 종류(판례 키워드, 판례 요약, 정보 추출, 초안 작성, 검증, 재작성)와 실패 방식(http, garbage)의 조합마다
가상 사례 하나로 그 호출이 일어나는 단계까지만 진행한다.

  http     500 오류 응답. 호출 계층이 다시 시도한 뒤에도 실패한다.
  garbage  200 응답이지만 내용이 요청한 형식이 아닌 한 문장 ("죄송합니다. 지금은 답변할 수 없습니다.")

판정:
  드러남  실패가 주입된 단계의 응답이 실패를 알린다 (2xx가 아닌 상태, 판례 검색 failed, 판례의 summarized=false,
          검증 상태 unverified·rewrite_failed)
  은폐    실패가 주입됐는데 응답이 정상과 구분되지 않는다  → M10에 센다
  미발생  그 호출이 일어나지 않아 주입되지 않았다 (예: 검증이 고칠 표현을 찾지 못해 재작성이 없었다)
  측정 불가  주입은 됐는데 그 단계의 결과를 받지 못했다 (판례 검색이 시간 안에 끝나지 않음 등). M10에 세지 않는다

AI 서비스는 compose.eval.yaml로 띄워 기록 장치를 거쳐야 한다. 주입 대상이 아닌 호출은 실제 모델로 간다 (비용이 든다).
"""
import argparse
import json
import subprocess
import time

import run_eval as ev

# 호출 종류를 가르는 문구. 그 호출의 메시지에만 들어 있다 (ai/tests/fixtures/llm_requests.json으로 확인).
MARKERS = {
    "rag_keyword": "죄목 리스트",
    "rag_summary": "[후보 판례]",
    "extract": "법적 구성요건(elements)",
    "compose": "[사건 요소(JSON)]",
    "verify": "근거가 없는 사실 서술",
    "rewrite": "[근거 없는 표현]",
}
FAILED_REVIEW = ("unverified", "rewrite_failed")
SUMMARY_KEYS = "baro:rag:case-summary:*"  # ai/services/rag.py의 _case_summary_cache_key


def flush_cache() -> None:
    """판례 요약 캐시만 지운다. 같은 Redis에 다른 것이 있어도 건드리지 않는다."""
    subprocess.run(["docker", "compose", "-f", "compose.yaml", "-f", "compose.eval.yaml", "exec", "-T", "redis", "sh", "-c",
                    f"redis-cli --scan --pattern '{SUMMARY_KEYS}' | xargs -r redis-cli del"],
                   cwd=ev.REPO, check=True, capture_output=True)


def wait_rag(ai: str, sid: str, timeout: float) -> dict:
    rag, deadline = {}, time.time() + timeout
    while time.time() < deadline:
        _, rag, _ = ev.http("GET", f"{ai}/chat/rag/{sid}")
        if (rag or {}).get("rag_status") != "pending":
            break
        time.sleep(2)
    return rag or {}


def rag_step(rag: dict) -> dict:
    cases = rag.get("rag_cases") or []
    not_summarized = sum(1 for c in cases if c.get("summarized") is False)
    return {"step": "rag", "rag_status": rag.get("rag_status"), "keyword": rag.get("rag_keyword"), "cases": len(cases),
            "not_summarized": not_summarized,
            "signal": rag.get("rag_status") == "failed" or not_summarized > 0,
            # 끝나지 않았거나(시간 초과) 조회하지 못했으면 드러났는지 은폐됐는지 말할 수 없다.
            "unmeasured": rag.get("rag_status") not in ("ready", "failed")}


def compose_step(name: str, status: int, body: dict | None) -> dict:
    review = ((body or {}).get("verification") or {}).get("status")
    draft = (body or {}).get("criminal_facts") or ""
    return {"step": name, "status": status, "verification": review, "draft_chars": len(draft), "draft_head": draft[:60],
            "signal": status != 200 or review in FAILED_REVIEW}


def run_scenario(kind: str, mode: str, case: dict, args) -> dict:
    ai, tag = args.ai_url, f"{kind}-{mode}"
    out = {"kind": kind, "mode": mode, "steps": []}
    if kind == "rag_summary":
        flush_cache()  # 저장된 요약이 있으면 요약 호출이 일어나지 않는다
    inject = {"run_id": args.run_id, "case_id": tag, "fail_rate": 1.0, "fail_mode": mode, "fail_status": 500,
              "fail_contains": MARKERS[kind]}
    off = {"fail_rate": 0, "fail_contains": ""}
    ev.proxy_control(args.proxy_url, inject)
    sid = None
    try:
        known = {k: (case.get("pii") or {}).get(k) or [] for k in ("names", "addresses")}
        st, init, _ = ev.http("POST", f"{ai}/chat/init",
                              {"text": case["narrative"], "offense": case["offense_selected"], "known_pii": known})
        if st != 200 or not (init or {}).get("session_id"):
            out["steps"].append({"step": "init", "status": st, "signal": True})
            return out
        sid = init["session_id"]
        out["steps"].append(rag_step(wait_rag(ai, sid, args.rag_timeout)))
        if kind in ("rag_keyword", "rag_summary"):
            return out

        st, _, _ = ev.http("POST", f"{ai}/chat/send", {"session_id": sid, "message": ev.KICKOFF})
        out["steps"].append({"step": "send", "status": st, "signal": st != 200})
        if kind == "extract":
            # 실패를 끄고 같은 발화를 다시 보낸다. 받아들여지면 사용자는 다시 시도해 이어 갈 수 있다.
            ev.proxy_control(args.proxy_url, off)
            st, _, _ = ev.http("POST", f"{ai}/chat/send", {"session_id": sid, "message": ev.KICKOFF})
            out["retry_after_failure"] = st
            return out
        if st != 200:
            return out

        st, comp, _ = ev.http("POST", f"{ai}/chat/compose", {"session_id": sid})
        out["steps"].append(compose_step("compose", st, comp))
        review = (comp or {}).get("verification") or {}
        if st == 200 and review.get("status") == "awaiting_confirmation":
            # 모두 사실이 아니라고 답해 재작성 호출이 일어나게 한다.
            answers = [False] * len(review.get("to_confirm") or [])
            st, comp, _ = ev.http("POST", f"{ai}/chat/compose/confirm", {"session_id": sid, "answers": answers})
            out["steps"].append(compose_step("confirm", st, comp))
        if kind == "compose":
            ev.proxy_control(args.proxy_url, off)
            st, comp, _ = ev.http("POST", f"{ai}/chat/compose", {"session_id": sid})
            out["retry_after_failure"] = st
        return out
    finally:
        ev.proxy_control(args.proxy_url, off)
        if sid:
            ev.http("DELETE", f"{ai}/chat/{sid}")


# 주입한 호출이 일어나는 단계. 그 단계의 응답이 실패를 알려야 한다.
TARGET_STEPS = {"rag_keyword": ("rag",), "rag_summary": ("rag",), "extract": ("send",),
                "compose": ("compose",), "verify": ("compose", "confirm"), "rewrite": ("compose", "confirm")}


def judge(scenario: dict, injected: int) -> str:
    if injected == 0:
        return "미발생"
    steps = [s for s in scenario["steps"] if s["step"] in TARGET_STEPS[scenario["kind"]] or s["step"] == "init"]
    if any(s["signal"] for s in steps):
        return "드러남"
    # 대상 단계에 이르지 못했거나 그 단계의 결과를 받지 못했으면 은폐로 세지 않는다.
    if not steps or any(s.get("unmeasured") for s in steps):
        return "측정 불가"
    return "은폐"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--case", help="쓸 사례 id. 비우면 개발 세트에서 대화를 진행하는 첫 사례")
    ap.add_argument("--kinds", nargs="*", default=list(MARKERS), choices=list(MARKERS))
    ap.add_argument("--modes", nargs="*", default=["http", "garbage"], choices=["http", "garbage"])
    ap.add_argument("--ai-url", default="http://localhost:8001")
    ap.add_argument("--proxy-url", default="http://localhost:8090")
    ap.add_argument("--rag-timeout", type=float, default=180)
    args = ap.parse_args()

    cases = [c for c in ev.load_cases("dev", [args.case] if args.case else None)
             if c.get("run_conversation") and c["expected_offense"] != "unsupported" and c["split"] == "dev"]
    if not cases:
        raise SystemExit("쓸 사례가 없다 (개발 세트의 대화 진행 사례여야 한다)")
    case = cases[0]
    ev.use_ai(args.ai_url)
    st, _, _ = ev.http("GET", f"{args.ai_url}/")
    if st != 200:
        raise SystemExit(f"AI 서비스에 연결하지 못했다: {st}")

    started = time.time()
    scenarios = []
    out_dir = ev.ROOT / "runs" / args.run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    for kind in args.kinds:
        for mode in args.modes:
            s = run_scenario(kind, mode, case, args)
            scenarios.append(s)
            # 조합이 끝날 때마다 저장한다. 중간에 멈춰도 그때까지의 응답이 남는다 (판정과 비용은 끝에서 계산한다).
            (out_dir / "fail_inject.partial.json").write_text(
                json.dumps({"scenarios": scenarios}, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"[{args.run_id}] {kind}/{mode} 끝", flush=True)

    calls = ev.load_calls(args.run_id, started)
    prices = json.loads((ev.ROOT.parent / "ai" / "prices.json").read_text(encoding="utf-8"))
    missing: set = set()
    for s in scenarios:
        mine = [r for r in calls if r.get("case_id") == f"{s['kind']}-{s['mode']}"]
        s["injected_calls"] = sum(1 for r in mine if r.get("injected"))
        s["real_calls"] = sum(1 for r in mine if not r.get("injected") and ev.call_kind(r) != "embedding")
        s["verdict"] = judge(s, s["injected_calls"])
    cost = sum(ev.cost_of(r, prices, missing) or 0 for r in calls if not r.get("injected"))
    summary = {
        "run_id": args.run_id, "case": case["id"], "git_head": ev.git_head(), "scenarios": len(scenarios),
        "M10_concealed": sum(1 for s in scenarios if s["verdict"] == "은폐"),
        "revealed": sum(1 for s in scenarios if s["verdict"] == "드러남"),
        "not_exercised": sum(1 for s in scenarios if s["verdict"] == "미발생"),
        "unmeasured": sum(1 for s in scenarios if s["verdict"] == "측정 불가"),
        "cost_usd": round(cost, 4), "models_missing_price": sorted(missing),
        "wall_min": round((time.time() - started) / 60, 1),
    }
    (out_dir / "fail_inject.json").write_text(
        json.dumps({"summary": summary, "scenarios": scenarios}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    print("| 호출 | 방식 | 주입 | 판정 | 응답 |\n|---|---|---|---|---|")
    for s in scenarios:
        shown = "; ".join(" ".join(f"{k}={v}" for k, v in step.items() if k not in ("signal", "draft_head", "unmeasured")) for step in s["steps"])
        print(f"| {s['kind']} | {s['mode']} | {s['injected_calls']} | {s['verdict']} | {shown} |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
