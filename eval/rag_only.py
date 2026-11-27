"""판례 검색만 재는 도구 (M4, M6).

사례마다 대화 시작(/chat/init)만 하고 판례 검색이 끝나면 세션을 지운다. 대화와 초안 작성은 하지 않으므로
사례당 LLM 호출은 죄명 키워드 1회와, 처음 보는 판례의 요약(판례당 1회, 캐시됨)뿐이다.

    python3 eval/rag_only.py --run-id rag-dev --split dev
"""
import argparse
import json
import time
from pathlib import Path

import run_eval as ev


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--split", default="dev", choices=["dev"])  # 보류 세트는 최종 측정에서만 연다
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--ai-url", default="http://localhost:8001")
    ap.add_argument("--proxy-url", default="http://localhost:8090")
    ap.add_argument("--rag-timeout", type=float, default=180)
    args = ap.parse_args()

    cases = [c for c in ev.load_cases(args.split, args.only) if c["expected_offense"] != "unsupported"]
    out_dir = ev.ROOT / "runs" / args.run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    ev.use_ai(args.ai_url)
    ev.proxy_control(args.proxy_url, {"run_id": args.run_id, "case_id": "", "fail_rate": 0})
    rows, failed = [], 0
    try:
        for case in cases:
            ev.proxy_control(args.proxy_url, {"case_id": case["id"]})
            known = {k: (case.get("pii") or {}).get(k) or [] for k in ("names", "addresses")}
            st, init, _ = ev.http("POST", f"{args.ai_url}/chat/init",
                                  {"text": case["narrative"], "offense": case["offense_selected"], "known_pii": known})
            sid = (init or {}).get("session_id")
            if st != 200 or not sid:
                failed += 1
                rows.append({"id": case["id"], "error": f"init {st}"})
                continue
            rag, deadline = {}, time.time() + args.rag_timeout
            while time.time() < deadline:
                _, rag, _ = ev.http("GET", f"{args.ai_url}/chat/rag/{sid}")
                if (rag or {}).get("rag_status") != "pending":
                    break
                time.sleep(2)
            ev.http("DELETE", f"{args.ai_url}/chat/{sid}")
            status = (rag or {}).get("rag_status")
            failed += status != "ready"
            labels = [c.get("label") for c in (rag or {}).get("rag_cases") or []]
            gold = case["gold_crime_label"]
            rows.append({"id": case["id"], "gold": gold, "status": status, "keyword": (rag or {}).get("rag_keyword"),
                         "labels": labels,
                         "primary_match": [ev.label_match(ev.primary_label(label), gold) for label in labels]})
            print(case["id"], status, (rag or {}).get("rag_keyword"), labels, flush=True)
    finally:
        ev.proxy_control(args.proxy_url, {"run_id": "", "case_id": ""})

    ok = [r for r in rows if "error" not in r]
    shown = [m for r in ok for m in r["primary_match"]]
    summary = {
        "cases": len(rows), "failed": failed,
        "M4_keyword_accuracy": ev.pct(sum(ev.label_match(r["keyword"], r["gold"]) for r in ok), len(ok)),
        "M6_primary_label_match": ev.pct(sum(shown), len(shown)), "M6_cases_shown": len(shown),
        "cases_with_no_precedent": sum(1 for r in ok if not r["labels"]),
    }
    (out_dir / "rag_only.json").write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=1),
                                           encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 1 if failed else 0


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    raise SystemExit(main())
