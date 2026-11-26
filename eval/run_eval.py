"""바로 AI 평가기 (경로 A: AI 서비스 직접 호출).

    docker compose -f compose.yaml -f compose.eval.yaml up -d
    python eval/run_eval.py --run-id baseline-1 --split dev --flush-cache

사례마다 실제 프론트와 같은 순서로 대화를 진행한다.
  1. /chat/init (사건 서술 + 사용자가 고른 죄목)
  2. 판례 검색 완료까지 /chat/rag 확인
  3. 프론트가 보내는 고정 문장으로 첫 질문 요청
  4. AI가 물은 항목을 _asked_count 변화로 알아내 모의 사용자가 정답의 답을 돌려줌
  5. 완료되면 /chat/compose로 초안 생성
  6. 판정 모델로 지어낸 사실(M1)과 성립 단정 표현(M8)을 판정

지표 정의는 docs/metrics.md, 판정 공급자 구조는 결정 0002를 따른다.

가상 사례 전용이다. 사건 서술과 답변 원문이 서비스와 판정 모델(외부 API)로 그대로 전송되므로
실제 사용자 서술을 eval/cases에 넣거나 --only로 실행하지 않는다 (요구사항 S05).
결과는 eval/runs/<run-id>/ (git 제외)와 eval/results/<run-id>.md (커밋용 요약)에 남긴다.
"""

import argparse
import json
import math
import os
import re
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))
from judge import JudgeError, judge  # noqa: E402

KICKOFF = "위 사건 개요를 기반으로, 이어서 질문을 해 주세요."  # web ChatWindowSection.tsx와 같은 문장
DONE_PREFIX = "필수 정보가 충족"
UNKNOWN_ANSWER = "잘 모르겠어요."
ASSERTION_RE = re.compile(r"(성립한다|성립합니다|성립된다|성립됩니다|성립함|명백한 범죄|유죄)")

# 판정 기준 판본. 바꾸면 이전 판본의 M1·M8과 비교할 수 없다.
#   1: 사용자 입력만 전달 (baseline-1)
#   2: AI 질문과 사용자 답을 짝지어 전달, 넣을 것·넣지 않을 것 명시 (baseline-1 M1 사람 검수 반영)
JUDGE_VERSION = "2"
JUDGE_SYSTEM = (
    "당신은 고소장 초안의 사실 정확성을 검수하는 검토자다. "
    "대화에서 사용자가 실제로 말한 내용에 근거가 없는 구체적 사실이 초안에 있는지, "
    "초안이 범죄 성립을 단정하는지만 판단한다. 문체나 법리 수준은 평가하지 않는다."
)
JUDGE_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["fabricated", "assertions"],
    "properties": {
        "fabricated": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["fact", "reason"],
            "properties": {"fact": {"type": "string"}, "reason": {"type": "string"}}}},
        "assertions": {"type": "array", "items": {"type": "string"}},
    },
}


# ---------------------------------------------------------------- HTTP

def http(method: str, url: str, body: dict | None = None, timeout: float = 300) -> tuple[int, dict | None, float]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    started = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            status = resp.status
    except urllib.error.HTTPError as e:
        raw, status = e.read(), e.code
    elapsed = time.time() - started
    try:
        return status, json.loads(raw), elapsed
    except Exception:
        return status, {"_raw": raw[:500].decode("utf-8", "replace")}, elapsed


# ---------------------------------------------------------------- 사례·정답

def load_cases(split: str, only: list[str] | None) -> list[dict]:
    cases = []
    for p in sorted((ROOT / "cases").glob("*.yaml")):
        if p.name.startswith("_"):
            continue
        c = yaml.safe_load(p.read_text(encoding="utf-8"))
        if only and c["id"] not in only:
            continue
        if not only and split != "all" and c["split"] != split:
            continue
        cases.append(c)
    return cases


def cases_lock() -> str:
    lock = (ROOT / "cases" / "LOCK.sha256").read_text(encoding="utf-8").strip().splitlines()[-1]
    return lock.split()[0]


def flatten_slots(progress: dict) -> dict:
    """progress의 elements·details에서 slot별 상태와 질문 횟수를 모은다."""
    status, asked = {}, {}
    for group in ("elements", "details"):
        for rec in (progress.get(group) or {}).values():
            if not isinstance(rec, dict):
                continue
            for s, v in (rec.get("slots") or {}).items():
                status[s] = v
            for s, n in (rec.get("_asked_count") or {}).items():
                asked[s] = asked.get(s, 0) + int(n)
    return {"status": status, "asked": asked}


# ---------------------------------------------------------------- 사례 하나 진행

def judge_transcript(r: dict) -> str:
    """판정 모델에 줄 대화 기록. 사용자 답은 바로 앞 AI 질문과 짝지어야 뜻이 정해진다
    ("잘 모르겠어요"가 무엇을 모른다는 것인지). 판본 1은 사용자 입력만 줘서 이 짝이 없었다."""
    inputs = r.get("user_inputs") or []
    lines = [f"[처음 서술] {inputs[0]}"] if inputs else []
    turns = r.get("turns") or []
    for k, t in enumerate(turns):
        if t.get("reply"):
            lines.append(f"[AI 질문 {k + 1}] {t['reply']}")
        if k + 1 < len(turns) and turns[k + 1].get("sent"):
            lines.append(f"[사용자 답 {k + 1}] {turns[k + 1]['sent']}")
    return "\n".join(lines)


def judge_prompt(r: dict) -> str:
    return ("[대화 기록]\n" + judge_transcript(r) +
            "\n\n[고소장 초안]\n" + r["draft"] +
            "\n\n[판정 기준]\n"
            "대화 기록은 처음 서술, AI 질문, 사용자 답 전체다. 사용자 답은 바로 앞 AI 질문에 대한 답으로 읽는다. "
            "AI 질문 안의 요약이나 예시는 사용자가 한 말이 아니다.\n"
            "fabricated: 사용자가 한 말(처음 서술과 사용자 답) 어디에도 근거가 없는 구체적 사실만 넣는다. "
            "날짜, 시각, 금액, 이름·닉네임, 계좌, 장소, 연락처, 행위, 발언, 피해 내용, 증거 보유 여부가 대상이다. "
            "사용자가 한 말과 반대되는 내용도 넣는다. 특히 다음은 넣는다:\n"
            "- 사용자가 말하지 않은 피해의 정도나 감정 (예: 정신적 고통, 극심한 피해)\n"
            "- 사용자가 모른다고 답한 것을 있다 또는 없다로 단정한 것 (예: 증거를 묻자 모르겠다고 답했는데 "
            "'캡처본을 보관하고 있다' 또는 '증거가 없다'고 쓴 것)\n"
            "- 사용자가 말하지 않은 구체적 세부 (날짜, 금액, 경로, 횟수, 상대의 말 등)\n"
            "다음은 넣지 않는다:\n"
            "- 여러 답에 흩어진 사실을 합치거나 시간 순서로 이은 문장\n"
            "- 사용자가 말한 사실을 고소장의 법률 문장(기망, 착오, 처분행위 등)으로 옮긴 것\n"
            "- 사용자가 모른다고 답한 것을 '확인하지 못했다', '알 수 없다'처럼 모른다는 뜻 그대로 적은 것\n"
            "- 대화에서 바로 따라 나오는 관계나 사실, 사용자가 한 말을 다른 말로 표현한 것, 고소장 형식 문구\n"
            "assertions: 범죄가 성립한다거나 피고소인이 유죄라고 결론을 단정한 문장만 넣는다 "
            "(예: '사기죄가 성립한다', '피고소인의 행위는 명백한 사기죄에 해당한다'). "
            "사실을 기망·착오·처분행위 같은 법률 용어로 서술한 문장, 처벌을 요청하는 문장('엄벌에 처해 주시기 바랍니다'), "
            "수사를 요청하는 문장은 넣지 않는다.")


def judge_case(r: dict, judge_cfg: dict) -> None:
    """r["judge"]를 채운다. 실패하면 r["errors"]에 남긴다 (빈 결과로 바꾸지 않는다)."""
    try:
        j = judge(judge_cfg["provider"], judge_cfg["model"], JUDGE_SYSTEM, judge_prompt(r), JUDGE_SCHEMA)
        r["judge"] = {"provider": j.provider, "model": j.model, "response_model": j.response_model,
                      "version": JUDGE_VERSION, "usage": j.usage, "latency_s": j.latency_s, **j.data}
    except JudgeError as e:
        r["errors"].append(f"판정 실패: {e}")


def run_case(case: dict, ai: str, max_turns: int, judge_cfg: dict, rag_timeout: float) -> dict:
    out = {"id": case["id"], "group": case["group"], "split": case["split"],
           "expected_offense": case["expected_offense"], "errors": [], "turns": []}
    t0 = time.time()

    st, init, lat = http("POST", f"{ai}/chat/init", {"text": case["narrative"], "offense": case["offense_selected"]})
    out["init"] = {"status": st, "latency_s": round(lat, 3), "offense": (init or {}).get("offense")}
    if st != 200 or not init or "session_id" not in init:
        out["errors"].append(f"init 실패: {st} {init}")
        return out
    sid = init["session_id"]

    # 판례 검색 (비동기) 완료 대기
    rag = {}
    deadline = time.time() + rag_timeout
    while time.time() < deadline:
        _, rag, _ = http("GET", f"{ai}/chat/rag/{sid}")
        if (rag or {}).get("rag_status") != "pending":
            break
        time.sleep(2)
    out["rag"] = {"status": (rag or {}).get("rag_status"), "keyword": (rag or {}).get("rag_keyword"),
                  "cases": [{"case_no": c.get("case_no"), "label": c.get("label")} for c in (rag or {}).get("rag_cases") or []]}

    if not case.get("run_conversation"):
        out["wall_s"] = round(time.time() - t0, 3)
        return out

    gold = case["slots"]
    answered: set[str] = set()
    user_inputs = [case["narrative"]]
    prev_asked: dict = {}
    message = KICKOFF
    complete = False
    first_status = None

    for turn in range(max_turns):
        st, resp, lat = http("POST", f"{ai}/chat/send", {"session_id": sid, "message": message})
        rec = {"turn": turn, "sent": message, "status": st, "latency_s": round(lat, 3)}
        if st != 200 or not resp:
            rec["error"] = resp
            out["turns"].append(rec)
            out["errors"].append(f"send 실패(turn {turn}): {st}")
            break
        reply = resp.get("reply") or ""
        progress = resp.get("progress") or {}
        flat = flatten_slots(progress)
        if first_status is None:
            first_status = flat["status"]
        newly = [s for s, n in flat["asked"].items() if n > prev_asked.get(s, 0)]
        prev_asked = flat["asked"]
        complete = bool(progress.get("complete")) or reply.startswith(DONE_PREFIX)
        rec.update(reply=reply, asked_slots=newly, complete=complete,
                   reply_has_none=reply.strip().startswith("None"))
        out["turns"].append(rec)
        if complete:
            break
        # 모의 사용자: 물은 항목의 정답을 돌려준다
        if not newly:
            rec["mock"] = "질문 항목을 알아내지 못함"
            message = UNKNOWN_ANSWER
        else:
            parts = []
            for s in newly:
                if s in gold:
                    parts.append(gold[s]["answer"])
                    if s in answered:
                        rec.setdefault("reasked", []).append(s)
                    answered.add(s)
                else:
                    parts.append(UNKNOWN_ANSWER)
                    rec.setdefault("nice_unknown", []).append(s)
            message = " ".join(parts)
        user_inputs.append(message)

    out["complete"] = complete
    out["questions"] = sum(1 for t in out["turns"] if t.get("reply") and not t.get("complete"))
    out["first_status"] = first_status or {}

    # 초안 생성
    st, comp, lat = http("POST", f"{ai}/chat/compose", {"session_id": sid})
    out["compose"] = {"status": st, "latency_s": round(lat, 3), "body": comp}
    draft = ""
    if st == 200 and isinstance(comp, dict):
        sections = comp.get("sections") if isinstance(comp.get("sections"), dict) else {}
        draft = "\n\n".join(f"[{k}]\n{v}" for k, v in sections.items() if isinstance(v, str) and v.strip())
        if not draft:
            out["errors"].append("compose 응답에 초안 본문(sections)이 없다")
    else:
        out["errors"].append(f"compose 실패: {st}")
    out["draft"] = draft
    out["user_inputs"] = user_inputs

    # 판정 (M1, M8)
    if draft and judge_cfg["provider"] != "none":
        judge_case(out, judge_cfg)
    out["wall_s"] = round(time.time() - t0, 3)
    return out


# ---------------------------------------------------------------- 지표

def norm_num(s: str) -> str:
    return re.sub(r"[,\s.\-]", "", s)


def numeric_unsupported(draft: str, inputs: list[str]) -> list[str]:
    """초안의 숫자 표현 중 입력에 없는 것 (M1 규칙 판정)."""
    src = norm_num(" ".join(inputs))
    found = re.findall(r"\d[\d,.\-]*\d|\d", draft)
    return sorted({f for f in found if len(norm_num(f)) >= 2 and norm_num(f) not in src})


def label_match(keyword: str | None, gold: str) -> bool:
    k = (keyword or "").strip()
    return bool(k) and (gold in k or k in gold)


def primary_label(label) -> str:
    if isinstance(label, list):
        return str(label[0]) if label else ""
    return str(label or "").split(",")[0].strip()


def p95(values: list[float]):
    v = sorted(values)
    return round(v[max(0, math.ceil(0.95 * len(v)) - 1)], 1) if v else None


def pct(a: int, b: int):
    return round(100 * a / b, 1) if b else None


def load_calls(run_id: str, started: float) -> list[dict]:
    p = ROOT / "runs" / "llm_calls.jsonl"
    if not p.exists():
        return []
    calls = []
    for line in p.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if r.get("run_id") == run_id and r.get("ts", 0) >= started:
            calls.append(r)
    return calls


def call_kind(r: dict) -> str:
    if r.get("path", "").endswith("/embeddings"):
        return "embedding"
    body = json.dumps(r.get("request") or {}, ensure_ascii=False)
    if "[근거 없는 표현]" in body:
        return "rewrite"
    if "[사건 요소(JSON)]" in body:
        return "compose"
    if "근거가 없는 사실 서술" in body:
        return "verify"
    if "법적 구성요건(elements)" in body:
        return "extract"
    roles = [m.get("role") for m in (r.get("request") or {}).get("messages") or []]
    return "rag_summary" if "system" in roles else "rag_keyword"


def price_cost(model: str | None, usage: dict, prices: dict, missing: set) -> float | None:
    """캐시된 입력 토큰은 캐시 단가로 계산한다. 가격표에 없는 모델은 None을 돌려주고 missing에 남긴다."""
    model = prices["aliases"].get(model, model)
    p = prices["models"].get(model)
    if usage.get("prompt_tokens") is None:
        return None
    if not p:
        missing.add(str(model))
        return None
    cached = usage.get("cached_tokens") or 0
    fresh = (usage.get("prompt_tokens") or 0) - cached
    return (fresh * p["input"] + cached * p.get("cached_input", p["input"]) + (usage.get("completion_tokens") or 0) * p["output"]) / 1e6


def cost_of(r: dict, prices: dict, missing: set) -> float | None:
    return price_cost(r.get("response_model") or r.get("model"), r.get("usage") or {}, prices, missing)


def attribute(calls: list[dict], cases: list[dict]) -> dict:
    """동시 실행이라 사례 이름 대신 요청 본문에 사건 서술 앞부분이 들어 있는지로 사례를 찾는다."""
    keys = {c["id"]: c["narrative"][:30] for c in cases}
    by_case = {c["id"]: [] for c in cases}
    unattributed = []
    for r in calls:
        body = json.dumps(r.get("request") or {}, ensure_ascii=False)
        hit = [cid for cid, k in keys.items() if k in body]
        (by_case[hit[0]] if len(hit) == 1 else unattributed).append(r)
    by_case["_unattributed"] = unattributed
    return by_case


def summarize(results: list[dict], cases: list[dict], calls: list[dict], prices: dict) -> dict:
    gold = {c["id"]: c for c in cases}
    convo = [r for r in results if r.get("turns")]
    s = {"cases": len(results), "conversation_cases": len(convo),
         "errors": sum(1 for r in results if r["errors"])}

    # M2
    tp = fp = fn = 0
    for r in convo:
        for slot, g in gold[r["id"]]["slots"].items():
            pred = r["first_status"].get(slot) == "present"
            tp += pred and g["in_narrative"]; fp += pred and not g["in_narrative"]; fn += (not pred) and g["in_narrative"]
    s["M2_recall"] = pct(tp, tp + fn); s["M2_precision"] = pct(tp, tp + fp)

    # M3, M12
    q = [r["questions"] for r in convo]
    s["M3_questions_mean"] = round(statistics.mean(q), 2) if q else None
    s["M3_questions_max"] = max(q) if q else None
    s["completion_rate"] = pct(sum(1 for r in convo if r.get("complete")), len(convo))
    s["M12_reasked_total"] = sum(len(t.get("reasked", [])) for r in convo for t in r["turns"])
    s["M12_reasked_per_case"] = round(s["M12_reasked_total"] / len(convo), 2) if convo else None
    s["undetected_question_turns"] = sum(1 for r in convo for t in r["turns"] if t.get("mock"))

    # M4, M6
    kw = [label_match(r.get("rag", {}).get("keyword"), gold[r["id"]]["gold_crime_label"]) for r in results]
    s["M4_keyword_accuracy"] = pct(sum(kw), len(kw))
    hits = tot = 0
    for r in results:
        for c in r.get("rag", {}).get("cases", []):
            tot += 1
            hits += label_match(primary_label(c.get("label")), gold[r["id"]]["gold_crime_label"])
    s["M6_primary_label_match"] = pct(hits, tot)
    s["rag_failed"] = sum(1 for r in results if r.get("rag", {}).get("status") != "ready")

    # M5
    uns = [r for r in results if r["expected_offense"] == "unsupported"]
    s["M5_unsupported_mishandled"] = pct(sum(1 for r in uns if r["init"].get("offense") != "unsupported"), len(uns))

    # M1, M8
    judged = [r for r in convo if "judge" in r]
    s["M1_judge_fabricated_total"] = sum(len(r["judge"]["fabricated"]) for r in judged)
    s["M1_cases_with_fabrication"] = sum(1 for r in judged if r["judge"]["fabricated"])
    s["M1_rule_numeric_total"] = sum(len(numeric_unsupported(r.get("draft", ""), r.get("user_inputs", []))) for r in convo)
    s["M8_judge_assertions"] = sum(len(r["judge"]["assertions"]) for r in judged)
    s["M8_regex_assertions"] = sum(len(ASSERTION_RE.findall(r.get("draft", ""))) for r in convo)
    s["judged_cases"] = len(judged)
    s["reply_shows_None"] = sum(1 for r in convo for t in r["turns"] if t.get("reply_has_none"))

    # M9, M11
    by_case = attribute(calls, cases)
    # 가상 인적정보 값은 사례마다 달라서, 사례를 특정하지 못한 호출(초안 작성 등)까지 모든 호출에서 찾는다
    values = {v for c in cases for vs in c["pii"].values() for v in vs if v}
    pii_hits = 0
    pii_kinds = {}
    for r in calls:
        body = json.dumps(r.get("request") or {}, ensure_ascii=False)
        for v in values:
            if v in body:
                pii_hits += 1
                k = call_kind(r)
                pii_kinds[k] = pii_kinds.get(k, 0) + 1
    s["M9_pii_in_requests"] = pii_hits
    s["M9_by_kind"] = pii_kinds
    s["llm_calls"] = len(calls)
    s["llm_calls_unattributed"] = len(by_case["_unattributed"])
    kinds = {}
    missing_prices: set = set()
    for r in calls:
        k = kinds.setdefault(call_kind(r), {"calls": 0, "latency": [], "out": 0, "reasoning": 0, "cost": 0.0})
        u = r.get("usage") or {}
        k["calls"] += 1; k["latency"].append(r.get("latency_s") or 0)
        k["out"] += u.get("completion_tokens") or 0; k["reasoning"] += u.get("reasoning_tokens") or 0
        k["cost"] += cost_of(r, prices, missing_prices) or 0
    s["M11_by_kind"] = {k: {"calls": v["calls"],
                            "p50_s": round(statistics.median(v["latency"]), 1),
                            "p95_s": p95(v["latency"]),
                            "out_tokens": v["out"], "reasoning_tokens": v["reasoning"], "cost_usd": round(v["cost"], 4)}
                        for k, v in sorted(kinds.items())}
    # 정보 추출 요청에 실제로 실린 추론 강도. 설정이 아니라 기록된 요청에서 읽는다.
    s["extract_reasoning_effort"] = sorted({(r.get("request") or {}).get("reasoning_effort") or "default"
                                            for r in calls if call_kind(r) == "extract"})
    # 초안 검증 결과 (passed | rewritten | flagged | unverified | rewrite_failed | off)
    review = [((r.get("compose") or {}).get("body") or {}).get("verification") for r in results]
    review = [v for v in review if isinstance(v, dict)]
    s["verification_status"] = {k: sum(1 for v in review if v.get("status") == k)
                                for k in sorted({v.get("status") for v in review})}
    s["verification_removed_total"] = sum(len(v.get("removed") or []) for v in review)
    s["M11_service_cost_usd"] = round(sum(v["cost_usd"] for v in s["M11_by_kind"].values()), 4)
    send_lat = [t["latency_s"] for r in convo for t in r["turns"] if "latency_s" in t]
    s["M11_turn_latency_p50_s"] = round(statistics.median(send_lat), 1) if send_lat else None
    s["M11_turn_latency_p95_s"] = p95(send_lat)
    judge_cost = 0.0
    for r in judged:
        judge_cost += price_cost(r["judge"]["model"], r["judge"]["usage"], prices, missing_prices) or 0
    s["judge_cost_usd"] = round(judge_cost, 4)
    s["judge_failed"] = sum(1 for r in convo if r.get("draft") and "judge" not in r)
    s["models_missing_price"] = sorted(missing_prices)  # 비어 있지 않으면 비용이 과소 계산된 것이다
    return s


# ---------------------------------------------------------------- 실행

def load_openai_key() -> None:
    """판정 모델 키: 환경 변수가 없으면 ai/.env에서 읽는다 (값은 출력하지 않는다)."""
    if os.environ.get("OPENAI_API_KEY"):
        return
    env = REPO / "ai" / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("OPENAI_API_KEY="):
                os.environ["OPENAI_API_KEY"] = line.split("=", 1)[1].strip().strip('"')


def git_head() -> str:
    try:
        head = subprocess.check_output(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"], text=True).strip()
        # 평가 코드(eval/)에 커밋하지 않은 변경이 있으면 표시한다. 결과를 그 커밋으로 재현할 수 없다는 뜻이다.
        dirty = subprocess.run(["git", "-C", str(REPO), "diff", "--quiet", "HEAD", "--", "eval/*.py"]).returncode != 0
        untracked = subprocess.check_output(["git", "-C", str(REPO), "ls-files", "--others", "--exclude-standard", "--", "eval/*.py"], text=True).strip()
        return head + ("+eval-dirty" if dirty or untracked else "")
    except Exception:
        return "unknown"


def proxy_control(url: str, body: dict) -> None:
    st, resp, _ = http("POST", f"{url}/_control", body)
    if st != 200:
        raise SystemExit(f"기록 장치 제어 실패: {st} {resp}. compose.eval.yaml로 띄웠는지 확인한다.")


def write_report(run_id: str, meta: dict, summary: dict, path: Path) -> None:
    rows = "\n".join(f"| {k} | {v} |" for k, v in summary.items() if k not in ("M11_by_kind",))
    kinds = "\n".join(f"| {k} | {v['calls']} | {v['p50_s']} | {v['p95_s']} | {v['out_tokens']} | {v['reasoning_tokens']} | {v['cost_usd']} |"
                      for k, v in summary.get("M11_by_kind", {}).items())
    meta_rows = "\n".join(f"| {k} | {v} |" for k, v in meta.items())
    path.write_text(
        f"# 평가 결과 {run_id}\n\n## 실행 조건\n\n| 항목 | 값 |\n|---|---|\n{meta_rows}\n\n"
        f"## 지표\n\n| 지표 | 값 |\n|---|---|\n{rows}\n\n"
        f"## 호출 종류별 (M11)\n\n| 종류 | 호출 | p50 초 | p95 초 | 출력 토큰 | 추론 토큰 | 비용 USD |\n|---|---|---|---|---|---|---|\n{kinds}\n",
        encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--split", default="dev", choices=["dev", "holdout", "all"])
    ap.add_argument("--only", nargs="*", help="이 사례 id만 실행 (split 무시)")
    ap.add_argument("--concurrency", type=int, default=5)
    ap.add_argument("--max-turns", type=int, default=25)
    ap.add_argument("--rag-timeout", type=float, default=180)
    ap.add_argument("--ai-url", default="http://localhost:8001")
    ap.add_argument("--proxy-url", default="http://localhost:8090")
    ap.add_argument("--judge-provider", default=os.environ.get("EVAL_JUDGE_PROVIDER", "openai"))
    ap.add_argument("--judge-model", default=os.environ.get("EVAL_JUDGE_MODEL", "gpt-5-2025-08-07"))
    ap.add_argument("--flush-cache", action="store_true", help="실행 전 Redis 판례 요약 캐시를 비운다")
    args = ap.parse_args()

    load_openai_key()
    cases = load_cases(args.split, args.only)
    if not cases:
        raise SystemExit("실행할 사례가 없다")
    st, health, _ = http("GET", f"{args.ai_url}/")
    if st != 200:
        raise SystemExit(f"AI 서비스에 연결하지 못했다: {st}")
    if args.flush_cache:
        subprocess.run(["docker", "compose", "-f", "compose.yaml", "-f", "compose.eval.yaml", "exec", "-T",
                        "redis", "redis-cli", "FLUSHDB"], cwd=REPO, check=True, capture_output=True)
    # 예열: 재시작 직후 판례 DB 연결을 미리 만들어 둔다. 예열 호출은 별도 실행 이름으로 기록한다.
    proxy_control(args.proxy_url, {"run_id": f"{args.run_id}-warmup", "case_id": "", "fail_rate": 0})
    warmup = "init 실패"
    st, w, _ = http("POST", f"{args.ai_url}/chat/init", {"text": "예열용 요청입니다. 중고거래 사기", "offense": "사기"})
    if st == 200 and w:
        warmup = "timeout"
        for _ in range(60):
            _, rr, _ = http("GET", f"{args.ai_url}/chat/rag/{w['session_id']}")
            if (rr or {}).get("rag_status") != "pending":
                warmup = (rr or {}).get("rag_status")
                break
            time.sleep(2)
    if warmup != "ready":
        print(f"경고: 예열 결과가 {warmup}다. 첫 사례들의 지연과 판례 검색 실패가 섞일 수 있다.", flush=True)
    if args.flush_cache:  # 예열이 만든 캐시도 비운다
        subprocess.run(["docker", "compose", "-f", "compose.yaml", "-f", "compose.eval.yaml", "exec", "-T",
                        "redis", "redis-cli", "FLUSHDB"], cwd=REPO, check=True, capture_output=True)
    proxy_control(args.proxy_url, {"run_id": args.run_id, "case_id": "", "fail_rate": 0})

    run_dir = ROOT / "runs" / args.run_id
    (run_dir / "cases").mkdir(parents=True, exist_ok=True)
    started = time.time()
    judge_cfg = {"provider": args.judge_provider, "model": args.judge_model}
    results = []
    print(f"[{args.run_id}] 사례 {len(cases)}건, 동시 {args.concurrency}, 판정 {judge_cfg}", flush=True)
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futs = {pool.submit(run_case, c, args.ai_url, args.max_turns, judge_cfg, args.rag_timeout): c for c in cases}
        for f in as_completed(futs):
            c = futs[f]
            try:
                r = f.result()
            except Exception as e:  # 평가기 자체 오류도 숨기지 않는다
                r = {"id": c["id"], "group": c["group"], "split": c["split"], "expected_offense": c["expected_offense"],
                     "errors": [f"평가기 예외: {e!r}"], "turns": [], "init": {}, "rag": {}}
            results.append(r)
            (run_dir / "cases" / f"{c['id']}.json").write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"  {c['id']:32s} 질문 {r.get('questions', '-'):>3} 완료 {r.get('complete', '-')!s:5} "
                  f"{r.get('wall_s', 0):6.0f}s 오류 {len(r['errors'])}", flush=True)
    time.sleep(1)
    calls = load_calls(args.run_id, started)
    prices = json.loads((ROOT / "prices.json").read_text(encoding="utf-8"))
    summary = summarize(results, cases, calls, prices)
    service_models = sorted({(c.get("response_model") or c.get("model")) for c in calls if c.get("model")})
    meta = {
        "run_id": args.run_id, "date_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "git_head": git_head(), "split": args.split if not args.only else f"only {len(args.only)}",
        "cases_lock": cases_lock()[:16], "service_models": ", ".join(m for m in service_models if m),
        "judge": f"{judge_cfg['provider']}/{judge_cfg['model']}", "judge_version": JUDGE_VERSION, "prices_as_of": prices["as_of"],
        "concurrency": args.concurrency, "wall_min": round((time.time() - started) / 60, 1), "warmup": warmup,
    }
    (run_dir / "summary.json").write_text(json.dumps({"meta": meta, "summary": summary}, ensure_ascii=False, indent=1), encoding="utf-8")
    (ROOT / "results").mkdir(exist_ok=True)
    write_report(args.run_id, meta, summary, ROOT / "results" / f"{args.run_id}.md")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
