"""저장된 실행 기록의 초안에 검증·재작성만 다시 돌린다.

대화와 초안 작성은 다시 하지 않는다. 같은 초안의 검증 전후를 비교해 검증·재작성의 효과만 볼 때 쓴다
(작성 호출의 흔들림이 빠진다). 서비스 코드의 그래프 노드를 그대로 부르므로 AI 이미지 안에서 실행한다.

  docker compose -f compose.yaml -f compose.eval.yaml run --rm --no-deps \\
      -e CHECKPOINT_DB_URL= -v "$PWD/ai":/app -v "$PWD/eval":/eval ai \\
      python /eval/verify_drafts.py --from extract-structured-dev10 --run-id verify-rewrite-dev10-drafts

그다음 고친 초안을 판정한다:

  python3 eval/rejudge.py --from verify-rewrite-dev10-drafts --run-id verify-rewrite-dev10

결과: eval/runs/<run-id>/cases/ (git 제외). 원래 판정은 judge_before로 옮겨 둔다.
"""
import argparse
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, "/app")


def proxy_control(body: dict) -> None:
    base = os.environ.get("OPENAI_BASE_URL", "")
    if "llm-proxy" not in base:
        raise SystemExit(f"기록 장치를 거치지 않는다 (OPENAI_BASE_URL={base!r}). compose.eval.yaml을 덧붙여 실행한다.")
    req = urllib.request.Request(base.rsplit("/v1", 1)[0] + "/_control", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    urllib.request.urlopen(req, timeout=5).read()


def history_of(r: dict) -> list[dict]:
    """서비스가 세션에 쌓는 대화 기록과 같은 모양으로 되살린다."""
    history = [{"role": "user", "content": r["user_inputs"][0]}]
    for t in r["turns"]:
        history.append({"role": "user", "content": t["sent"]})
        if t.get("reply"):
            history.append({"role": "assistant", "content": t["reply"]})
    return history


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="src", required=True)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--only", nargs="*")
    args = ap.parse_args()

    from flow.chat_graph import rewrite, route_after_verify, verify  # 서비스의 노드를 그대로 쓴다

    src_dir = ROOT / "runs" / args.src / "cases"
    out_dir = ROOT / "runs" / args.run_id / "cases"
    out_dir.mkdir(parents=True, exist_ok=True)
    proxy_control({"run_id": args.run_id, "case_id": ""})
    failed: list[str] = []
    try:
        run(args, src_dir, out_dir, failed, verify, rewrite, route_after_verify)
    finally:
        proxy_control({"run_id": "", "case_id": ""})  # 중간에 멈춰도 다음 호출이 이 실행 이름으로 기록되지 않게 한다
    if failed:
        print(f"검증하지 못했거나 다시 쓰지 못한 사례 {len(failed)}건: {', '.join(failed)}", flush=True)
        return 1
    return 0


def run(args, src_dir, out_dir, failed, verify, rewrite, route_after_verify) -> None:
    for f in sorted(src_dir.glob("*.json")):
        r = json.loads(f.read_text(encoding="utf-8"))
        if args.only and r["id"] not in args.only:
            continue
        if (out_dir / f.name).exists():
            print(f"{r['id']}: 이미 있음, 건너뜀", flush=True)
            continue
        body = (r.get("compose") or {}).get("body") or {}
        if not r.get("draft") or not isinstance(body.get("sections"), dict):
            continue
        proxy_control({"case_id": r["id"]})
        state = {"history": history_of(r), "draft": {k: body[k] for k in ("offense", "title", "sections")},
                 "review": {"status": "pending", "rewrites": 0, "unsupported": [], "removed": []}}
        t0 = time.time()
        state.update(verify(state))
        while route_after_verify(state) == "rewrite":
            state.update(rewrite(state))
            break  # 상한 1과 같은 흐름: 고친 뒤 다시 검증하지 않는다
        sections = state["draft"]["sections"]
        r["judge_before"] = r.pop("judge", None)
        r["draft_before"] = r["draft"]
        r["draft"] = "\n\n".join(f"[{k}]\n{v}" for k, v in sections.items() if isinstance(v, str) and v.strip())
        r["compose"]["body"] = {**body, "sections": sections, "verification": state["review"]}
        r["verify_rewrite_s"] = round(time.time() - t0, 1)
        (out_dir / f.name).write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
        rv = state["review"]
        print(f"{r['id']}: {rv['status']} 찾음 {len(rv['removed']) + len(rv['unsupported'])} "
              f"({r['verify_rewrite_s']}초)", flush=True)
        if rv["status"] in ("unverified", "rewrite_failed"):
            failed.append(r["id"])


if __name__ == "__main__":
    sys.exit(main())
