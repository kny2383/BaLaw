"""저장된 실행 기록으로 판정(M1, M8)만 다시 한다.

서비스 대화와 초안은 다시 만들지 않는다. 판정 기준(run_eval.JUDGE_VERSION)을 바꾼 뒤
같은 초안에 새 기준을 적용해 이전 판정과 비교할 때 쓴다. 판정 모델 비용만 든다.

  python3 eval/rejudge.py --from baseline-1 --run-id baseline-1-judge-v2
  python3 eval/rejudge.py --from baseline-1 --run-id try-v2 --only insult-02 insult-04

같은 --run-id와 같은 판정 모델로 다시 실행하면 판정에 성공한 사례는 건너뛰고 실패한 사례만 다시 판정한다.

결과: eval/runs/<run-id>/ (사례별 기록, git 제외), eval/results/<run-id>.md (요약, 커밋).
"""

import argparse
import copy
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import run_eval as ev  # noqa: E402


def m1_summary(results: list[dict], prices: dict) -> dict:
    judged = [r for r in results if "judge" in r]
    missing: set = set()
    cost = sum(ev.price_cost(r["judge"]["model"], r["judge"]["usage"], prices, missing) or 0 for r in judged)
    return {
        "judged_cases": len(judged),
        "judge_failed": sum(1 for r in results if r.get("draft") and "judge" not in r),
        "M1_judge_fabricated_total": sum(len(r["judge"]["fabricated"]) for r in judged),
        "M1_cases_with_fabrication": sum(1 for r in judged if r["judge"]["fabricated"]),
        "M8_judge_assertions": sum(len(r["judge"]["assertions"]) for r in judged),
        "judge_cost_usd": round(cost, 4),
        "models_missing_price": sorted(missing),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="src", required=True, help="판정을 다시 할 원래 실행 이름")
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--only", nargs="*", help="이 사례 id만 다시 판정")
    ap.add_argument("--concurrency", type=int, default=5)
    ap.add_argument("--judge-provider", default="openai")
    ap.add_argument("--judge-model", default="gpt-5-2025-08-07")
    args = ap.parse_args()

    src_dir = ROOT / "runs" / args.src / "cases"
    if not src_dir.is_dir():
        raise SystemExit(f"원래 실행 기록이 없다: {src_dir}")
    sources = [json.loads(f.read_text(encoding="utf-8")) for f in sorted(src_dir.glob("*.json"))]
    sources = [r for r in sources if r.get("draft") and (not args.only or r["id"] in args.only)]
    if not sources:
        raise SystemExit("다시 판정할 사례가 없다 (초안이 있는 사례만 대상)")

    ev.load_openai_key()
    prices = json.loads((ROOT.parent / "ai" / "prices.json").read_text(encoding="utf-8"))
    before = m1_summary(sources, prices)
    print(f"[{args.run_id}] {args.src}의 {len(sources)}건 다시 판정. 이전 판정 비용 {before['judge_cost_usd']}달러", flush=True)

    out_dir = ROOT / "runs" / args.run_id / "cases"
    out_dir.mkdir(parents=True, exist_ok=True)
    cfg = {"provider": args.judge_provider, "model": args.judge_model}
    started = time.time()
    results = []

    def one(src: dict) -> dict:
        # 같은 실행 이름·판정 판본·판정 모델로 이미 성공한 사례는 다시 부르지 않는다 (실패한 사례만 다시)
        done = out_dir / f"{src['id']}.json"
        if done.exists():
            prev = json.loads(done.read_text(encoding="utf-8"))
            j = prev.get("judge", {})
            if (j.get("version"), j.get("provider"), j.get("model")) == (ev.JUDGE_VERSION, cfg["provider"], cfg["model"]):
                return prev
        r = copy.deepcopy(src)
        r.pop("judge", None)
        r["errors"] = [e for e in r.get("errors", []) if not e.startswith("판정 실패")]
        r["rejudged_from"] = args.src
        try:
            ev.judge_case(r, cfg)
        except Exception as e:  # 판정 외 예외도 사례 결과에 남기고 나머지를 계속한다
            r["errors"].append(f"판정 실패: 평가기 예외 {e!r}")
        return r

    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futs = {pool.submit(one, s): s for s in sources}
        for f in as_completed(futs):
            r = f.result()
            results.append(r)
            (out_dir / f"{r['id']}.json").write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
            n = len(r["judge"]["fabricated"]) if "judge" in r else "실패"
            print(f"  {r['id']:32s} 지어낸 사실 {n}", flush=True)

    after = m1_summary(results, prices)
    meta = {
        "run_id": args.run_id, "rejudged_from": args.src,
        "date_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"), "git_head": ev.git_head(),
        "cases": len(results), "judge": f"{cfg['provider']}/{cfg['model']}", "judge_version": ev.JUDGE_VERSION,
        "prices_as_of": prices["as_of"], "wall_min": round((time.time() - started) / 60, 1),
    }
    (ROOT / "runs" / args.run_id / "summary.json").write_text(
        json.dumps({"meta": meta, "before": before, "after": after}, ensure_ascii=False, indent=1), encoding="utf-8")
    meta_rows = "\n".join(f"| {k} | {v} |" for k, v in meta.items())
    rows = "\n".join(f"| {k} | {before[k]} | {after[k]} |" for k in after)
    (ROOT / "results").mkdir(exist_ok=True)
    (ROOT / "results" / f"{args.run_id}.md").write_text(
        f"# 다시 판정 {args.run_id}\n\n## 실행 조건\n\n| 항목 | 값 |\n|---|---|\n{meta_rows}\n\n"
        f"## 판정 지표 (같은 초안, 같은 사례)\n\n| 지표 | {args.src} | {args.run_id} |\n|---|---|---|\n{rows}\n",
        encoding="utf-8")
    print(json.dumps({"before": before, "after": after}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
