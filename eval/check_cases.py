"""평가 사례 검사. CI와 로컬에서 같이 쓴다.

    python eval/check_cases.py

검사 항목:
  1. 정답 잠금: eval/cases/*.yaml의 sha256이 LOCK.sha256과 같은지
  2. 형식: 필수 필드, split 값, 죄목별 slot 목록, id와 파일 이름 일치, id 중복
  3. 원본 일치: eval/cases_src로 다시 만든 결과가 커밋된 YAML과 같은지

정답을 일부러 바꿨다면 build_cases.py --force로 다시 만들고 잠금 파일을 함께 커밋한다.
그 PR은 이전 실행 결과와 비교할 수 없게 되므로 PR 본문에 이유를 적는다.
"""

import hashlib
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
CASES = ROOT / "cases"
LOCK = CASES / "LOCK.sha256"

sys.path.insert(0, str(ROOT / "cases_src"))
import build_cases  # noqa: E402
from fraud import FRAUD_SLOTS  # noqa: E402
from others import INSULT_SLOTS  # noqa: E402

SLOTS = {"fraud": FRAUD_SLOTS, "insult": INSULT_SLOTS}
REQUIRED = ["id", "group", "split", "author", "style", "offense_selected", "expected_offense",
            "gold_crime_label", "run_conversation", "narrative", "pii"]


def case_files():
    return sorted(p for p in CASES.glob("*.yaml") if not p.name.startswith("_"))


def check_lock(errors):
    if not LOCK.exists():
        errors.append("LOCK.sha256이 없다")
        return
    locked = {}
    for line in LOCK.read_text(encoding="utf-8").splitlines():
        digest, _, name = line.partition("  ")
        if name and not name.startswith("("):
            locked[name] = digest
    actual = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in case_files()}
    for name in sorted(set(locked) | set(actual)):
        if name not in actual:
            errors.append(f"잠금에는 있지만 파일이 없다: {name}")
        elif name not in locked:
            errors.append(f"잠금에 없는 새 파일: {name}")
        elif locked[name] != actual[name]:
            errors.append(f"정답이 잠금과 다르다: {name}")


def check_schema(errors):
    seen = set()
    for p in case_files():
        c = yaml.safe_load(p.read_text(encoding="utf-8"))
        cid = c.get("id")
        for f in REQUIRED:
            if f not in c:
                errors.append(f"{p.name}: 필드 없음 {f}")
        if cid != p.stem:
            errors.append(f"{p.name}: id({cid})와 파일 이름이 다르다")
        if cid in seen:
            errors.append(f"{p.name}: 중복 id")
        seen.add(cid)
        if c.get("split") not in ("dev", "holdout"):
            errors.append(f"{p.name}: split은 dev 또는 holdout")
        exp = c.get("expected_offense")
        if c.get("run_conversation"):
            want = SLOTS.get(exp)
            if want is None:
                errors.append(f"{p.name}: 대화를 진행하는 사례의 죄목은 fraud 또는 insult")
                continue
            got = list((c.get("slots") or {}).keys())
            if got != want:
                errors.append(f"{p.name}: slot 목록이 {exp} 스키마와 다르다")
            for s, v in (c.get("slots") or {}).items():
                if not isinstance(v, dict) or "in_narrative" not in v or not str(v.get("answer", "")).strip():
                    errors.append(f"{p.name}: slot {s}에 in_narrative와 answer가 모두 있어야 한다")


def check_source(errors):
    for c in build_cases.build():
        p = CASES / f"{c['id']}.yaml"
        if not p.exists():
            errors.append(f"원본에는 있지만 YAML이 없다: {c['id']}")
            continue
        if yaml.safe_load(p.read_text(encoding="utf-8")) != c:
            errors.append(f"원본(cases_src)과 YAML이 다르다: {c['id']}")


def main() -> int:
    errors = []
    check_lock(errors)
    check_schema(errors)
    check_source(errors)
    n = len(case_files())
    if errors:
        print(f"평가 사례 검사 실패 ({n}건 중 문제 {len(errors)}개)")
        for e in errors:
            print(" -", e)
        return 1
    print(f"평가 사례 검사 통과: {n}건, 잠금 일치, 원본 일치")
    return 0


if __name__ == "__main__":
    sys.exit(main())
