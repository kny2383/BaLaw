"""저장된 실행 기록의 추출 결과로 초안 작성만 다시 한다.

대화와 정보 추출은 다시 하지 않는다. 작성 프롬프트를 바꾼 뒤 같은 추출 결과에서 초안이 어떻게 달라지는지 볼 때 쓴다.
작성 입력(항목별 판정과 요약)은 호출 기록(llm_calls.jsonl)의 원래 작성 요청에서 꺼낸다.
서비스 코드의 작성 함수를 그대로 부르므로 AI 이미지 안에서 실행한다.

  docker compose -f compose.yaml -f compose.eval.yaml run --rm --no-deps \\
      -e CHECKPOINT_DB_URL= -v "$PWD/ai":/app -v "$PWD/eval":/eval ai \\
      python /eval/recompose.py --from extract-structured-dev10 --run-id compose-prompt-dev10-drafts

그다음 새 초안을 판정한다:

  python3 eval/rejudge.py --from compose-prompt-dev10-drafts --run-id compose-prompt-dev10

결과: eval/runs/<run-id>/cases/ (git 제외). 원래 초안과 판정은 draft_before, judge_before로 옮겨 둔다.
"""
import argparse
import difflib
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, "/app")

ELEMENTS, DETAILS, EVIDENCE = "[사건 요소(JSON)]\n", "[사건 디테일(JSON)]\n", "[증거 메모]\n"


def proxy_control(body: dict) -> None:
    base = os.environ.get("OPENAI_BASE_URL", "")
    if "llm-proxy" not in base:
        raise SystemExit(f"기록 장치를 거치지 않는다 (OPENAI_BASE_URL={base!r}). compose.eval.yaml을 덧붙여 실행한다.")
    req = urllib.request.Request(base.rsplit("/v1", 1)[0] + "/_control", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    urllib.request.urlopen(req, timeout=5).read()


def compose_calls(run_id: str) -> list[dict]:
    calls = []
    for line in (ROOT / "runs" / "llm_calls.jsonl").read_text(encoding="utf-8").splitlines():
        if run_id not in line:
            continue
        c = json.loads(line)
        if c.get("run_id") != run_id or not c.get("path", "").endswith("/chat/completions"):
            continue
        if ELEMENTS in c["request"]["messages"][-1]["content"]:
            calls.append(c)
    return calls


def collected_of(call: dict) -> dict:
    text, dec = call["request"]["messages"][-1]["content"], json.JSONDecoder()
    elements, _ = dec.raw_decode(text[text.rfind(ELEMENTS) + len(ELEMENTS):])
    details, _ = dec.raw_decode(text[text.rfind(DETAILS) + len(DETAILS):])
    return {"elements": elements, "details": details}


def evidence_of(call: dict) -> list:
    text, dec = call["request"]["messages"][-1]["content"], json.JSONDecoder()
    memo, _ = dec.raw_decode(text[text.rfind(EVIDENCE) + len(EVIDENCE):])
    return memo


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="src", required=True)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--only", nargs="*")
    args = ap.parse_args()

    from loaders.offense_loader import get_offense_meta
    from services.pipelines import compose_complaint  # 서비스의 작성 함수를 그대로 쓴다

    calls = compose_calls(args.src)
    out_dir = ROOT / "runs" / args.run_id / "cases"
    out_dir.mkdir(parents=True, exist_ok=True)
    proxy_control({"run_id": args.run_id, "case_id": ""})
    failed: list[str] = []
    try:
        run(args, calls, out_dir, failed, get_offense_meta, compose_complaint)
    finally:
        proxy_control({"run_id": "", "case_id": ""})  # 중간에 멈춰도 다음 호출이 이 실행 이름으로 기록되지 않게 한다
    if failed:
        print(f"실패 {len(failed)}건: {', '.join(failed)}", flush=True)
        return 1
    return 0


def run(args, calls, out_dir, failed, get_offense_meta, compose_complaint) -> None:
    for f in sorted((ROOT / "runs" / args.src / "cases").glob("*.json")):
        r = json.loads(f.read_text(encoding="utf-8"))
        if (args.only and r["id"] not in args.only) or not r.get("draft") or (out_dir / f.name).exists():
            continue
        body = r["compose"]["body"]
        # 원래 작성 요청을 그 응답과 저장된 초안의 닮은 정도로 찾는다 (기록에 사례 이름이 없는 실행이 있다).
        def score(c):
            return difflib.SequenceMatcher(None, (c.get("response_text") or "")[:400], r["draft"][:400]).ratio()
        call = max(calls, key=score)
        if score(call) < 0.5:
            print(f"{r['id']}: 원래 작성 요청을 찾지 못함", flush=True)
            failed.append(r["id"])
            continue
        proxy_control({"case_id": r["id"]})
        t0 = time.time()
        try:
            # 증거 메모는 원래 요청과 같은 값을 넘긴다 (서비스는 항상 빈 목록을 넘긴다).
            new = compose_complaint(meta=get_offense_meta(body["offense"]), collected=collected_of(call),
                                    evidence=evidence_of(call))
            sections = new["sections"]
        except Exception as e:
            print(f"{r['id']}: 작성 실패 ({type(e).__name__})", flush=True)
            failed.append(r["id"])
            continue
        draft = "\n\n".join(f"[{k}]\n{v}" for k, v in sections.items() if isinstance(v, str) and v.strip())
        if not draft:
            print(f"{r['id']}: 작성 실패 (빈 결과)", flush=True)
            failed.append(r["id"])
            continue
        r["judge_before"], r["draft_before"] = r.pop("judge", None), r["draft"]
        r["draft"] = draft
        r["compose"] = {"status": 200, "latency_s": round(time.time() - t0, 1), "body": new}
        (out_dir / f.name).write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"{r['id']}: {len(r['draft_before'])}자 → {len(draft)}자 ({r['compose']['latency_s']}초)", flush=True)


if __name__ == "__main__":
    sys.exit(main())
