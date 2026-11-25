"""cases_src/*.py의 원본 데이터를 eval/cases/*.yaml로 만들고 정답 잠금 파일을 갱신한다.

    python eval/cases_src/build_cases.py

- 이미 있는 사례 파일은 덮어쓰지 않는다 (--force로 덮어쓰기).
- 모든 사례 파일의 sha256을 eval/cases/LOCK.sha256에 기록한다.
  평가기는 실행 때 이 값을 결과에 함께 남기고, 파일이 잠금과 다르면 경고한다.
"""

import hashlib
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import fraud  # noqa: E402
import others  # noqa: E402

CASES_DIR = HERE.parent / "cases"
LOCK = CASES_DIR / "LOCK.sha256"

# 화면에서 '사이버사기'를 고르는 경우도 섞어 죄목 이름 변환을 함께 확인한다
CYBER_FRAUD_IDS = {"fraud-used-goods-05", "fraud-leading-room-02"}


def slot_block(slots: dict, order: list) -> dict:
    missing = [s for s in order if s not in slots]
    extra = [s for s in slots if s not in order]
    if missing or extra:
        raise ValueError(f"slot 불일치: missing={missing} extra={extra}")
    return {s: {"in_narrative": bool(slots[s][0]), "answer": slots[s][1]} for s in order}


def fraud_case(c: dict, group: str) -> dict:
    return {
        "id": c["id"], "group": group, "split": c["split"], "author": "claude", "style": c["style"],
        "offense_selected": "사이버사기" if c["id"] in CYBER_FRAUD_IDS else "사기",
        "expected_offense": "fraud", "gold_crime_label": "사기", "run_conversation": True,
        "narrative": c["narrative"], "pii": c["pii"],
        "slots": slot_block(c["slots"], fraud.FRAUD_SLOTS),
    }


def build() -> list:
    out = []
    for c in fraud.CASES:
        out.append(fraud_case(c, c["group"]))
    for c in others.INSULT:
        out.append({
            "id": c["id"], "group": "insult", "split": c["split"], "author": "claude", "style": c["style"],
            "offense_selected": "모욕", "expected_offense": "insult", "gold_crime_label": "모욕",
            "run_conversation": True, "narrative": c["narrative"], "pii": c["pii"],
            "slots": slot_block(c["slots"], others.INSULT_SLOTS),
            "notes": "결정 0001에 따른 보류 판단용 사례",
        })
    for c in others.UNSUPPORTED:
        out.append({
            "id": c["id"], "group": "unsupported", "split": c["split"], "author": "claude", "style": "정돈",
            "offense_selected": c["offense_selected"], "expected_offense": "unsupported",
            "gold_crime_label": c["gold_crime_label"], "run_conversation": False,
            "narrative": c["narrative"], "pii": {"names": [], "phones": [], "accounts": [], "addresses": []},
            "notes": "대화는 진행하지 않고 대화 시작 응답의 죄목 처리(M5)와 판례 키워드(M4)만 본다",
        })
    for group, items in (("sparse", others.SPARSE), ("vague", others.VAGUE), ("pii", others.PII)):
        for c in items:
            out.append(fraud_case(c, group))
    return out


def main(force: bool) -> None:
    CASES_DIR.mkdir(parents=True, exist_ok=True)
    cases = build()
    ids = [c["id"] for c in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("중복된 사례 id가 있다")
    written = skipped = 0
    for c in cases:
        path = CASES_DIR / f"{c['id']}.yaml"
        if path.exists() and not force:
            skipped += 1
            continue
        header = "# 생성: eval/cases_src/build_cases.py. 모든 인물·계좌·전화번호·주소는 가상이다.\n"
        path.write_text(header + yaml.safe_dump(c, allow_unicode=True, sort_keys=False, width=1000), encoding="utf-8")
        written += 1

    files = sorted(p for p in CASES_DIR.glob("*.yaml") if not p.name.startswith("_"))
    lines = [f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}" for p in files]
    combined = hashlib.sha256("\n".join(lines).encode()).hexdigest()
    LOCK.write_text("\n".join(lines) + f"\n{combined}  (전체)\n", encoding="utf-8")
    print(f"written={written} skipped={skipped} total_files={len(files)} lock={combined[:12]}")


if __name__ == "__main__":
    main(force="--force" in sys.argv)
