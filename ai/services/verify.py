"""초안 검증과 재작성.

초안의 지어낸 사실은 대부분 작성 단계에서 생긴다 (eval/results/m1-origin-dev10.md).
그래서 작성한 초안을 대화와 대조해 근거 없는 표현을 찾고, 그 표현만 고쳐 다시 쓴다.
"""
from __future__ import annotations

from schemas.verification import Verification
from services import llm
from services.llm import LLMCallError
from services.pipelines import PII_NOTE, postprocess_complaint, split_complaint_sections

SECTION_TITLES = {"criminal_facts": "범죄사실", "accusation_reason": "고소이유"}

VERIFY_SYSTEM = "You check a Korean criminal complaint draft against what the user actually said."

VERIFY_RULES = (
    "아래 [대화]는 사용자가 사건에 대해 말한 전부이고, [초안]은 그 대화로 쓴 고소장 초안입니다.\n"
    "초안에서 대화에 근거가 없는 사실 서술을 모두 찾으십시오.\n\n"
    "근거가 없는 것:\n"
    "- 사용자가 말하지 않은 감정, 피해의 정도 (예: 정신적 고통, 피해가 극심하다)\n"
    "- 사용자가 '모르겠다'고 답했거나 답하지 않은 것을 있다 또는 없다로 단정한 서술\n"
    "- 사용자가 말하지 않은 세부: 누가 했는지, 누구의 것인지, 언제, 몇 번, 어떤 방법으로, 요구하거나 거부했는지\n\n"
    "근거가 있는 것으로 보는 것:\n"
    "- 흩어진 답을 하나로 합친 문장\n"
    "- 사용자가 말한 사실을 법률 문장이나 법률 용어로 옮긴 것 (기망, 착오, 처분행위 같은 평가)\n"
    "- '모르겠다'고 한 것을 '확인하지 못하였다'고 적은 것\n"
    "- 사용자가 말한 사실에서 바로 따라 나오는 사실\n"
    "- 처벌을 바란다는 문장, 수사를 요청하는 문장\n\n"
    "quote에는 초안에서 근거가 없는 부분만, 한 글자도 바꾸지 말고 그대로 옮기십시오.\n"
    "- 문장 가운데 일부만 근거가 없으면 그 구절만 옮기십시오 "
    "(예: '두려움을 느껴 요구에 응하여 송금하였다'에서 요구가 있었다는 말이 대화에 없으면 '요구에 응하여').\n"
    "- 문장 전체가 근거 없을 때만 문장 전체를 옮기십시오.\n"
    "- 한 문장에 근거 없는 구절이 여럿이면 구절마다 따로 적으십시오.\n"
    "reason에는 대화의 어느 부분과 맞지 않는지 한 문장으로 적으십시오.\n"
    "근거 없는 서술이 없으면 unsupported를 빈 목록으로 두십시오.\n"
    + PII_NOTE
)

REWRITE_SYSTEM = (
    "You are a drafting assistant for Korean criminal complaints.\n"
    "You revise a draft by removing statements the user never made."
)

REWRITE_RULES = (
    "아래 [초안]에서 [근거 없는 표현]에 적힌 부분만 고치십시오. '문장:'이 함께 적혀 있으면 그 문장 안의 해당 구절입니다.\n"
    "- 사용자가 말하지 않은 내용은 지우십시오. 지운 뒤 문장이 어색하면 그 문장만 자연스럽게 다듬으십시오.\n"
    "- 사용자가 '모르겠다'고 답한 것을 단정한 서술은 지우거나 '확인하지 못하였습니다'로 바꾸십시오.\n"
    "- 새로운 사실, 날짜, 금액, 사람, 감정을 더하지 마십시오.\n"
    "- 지적되지 않은 문장은 그대로 두십시오.\n"
    "- 처벌을 바란다는 문장과 수사를 요청하는 문장은 지우지 마십시오. 그 문장에 근거 없는 표현이 섞여 있으면 그 표현만 빼십시오.\n"
    "- 출력은 [초안]과 같은 형식으로 하십시오: '=== 범죄사실 ===' 과 '=== 고소이유 ===' 두 부분.\n"
    + PII_NOTE
)


def format_dialogue(history: list[dict]) -> str:
    """대화 기록을 검증 입력으로 옮긴다. 질문이 있어야 '모르겠어요'가 무엇에 대한 답인지 알 수 있다."""
    names = {"user": "사용자", "assistant": "질문"}
    return "\n".join(f"{names.get(m['role'], m['role'])}: {m['content']}" for m in history)


def format_draft(sections: dict) -> str:
    return "\n\n".join(f"=== {title} ===\n{sections.get(key, '')}" for key, title in SECTION_TITLES.items())


def sentence_of(quote: str, draft_text: str) -> str:
    """인용이 들어 있는 초안의 문장(한 줄). 사용자에게 물을 때 구절이 놓인 문맥으로 보여 준다.

    구절이 여러 줄에 걸치거나 여러 문장에 나오면 어느 문장인지 정할 수 없으므로 구절만 돌려준다.
    """
    lines = [line for line in draft_text.splitlines() if quote in line]
    if len(lines) != 1:
        return quote
    return lines[0].strip().lstrip("○").strip()


def verify_draft(history: list[dict], sections: dict) -> list[dict]:
    """초안에서 대화에 근거가 없는 표현을 찾는다 (LLM 호출). 실패하면 StructuredOutputError."""
    user = f"{VERIFY_RULES}\n[대화]\n{format_dialogue(history)}\n\n[초안]\n{format_draft(sections)}\n"
    out = llm.parsed("verify", VERIFY_SYSTEM, user, Verification)
    draft_text = format_draft(sections)
    # 초안에 없는 인용은 고칠 대상을 가리키지 못하므로 버린다.
    found = []
    for c in out.unsupported:
        # 글머리표는 문장의 일부가 아니다. 떼어 내야 문장 안에서 구절의 자리를 찾을 수 있다.
        quote = c.quote.strip().lstrip("○").strip()
        if quote and quote in draft_text:
            found.append({"quote": quote, "reason": c.reason, "sentence": sentence_of(quote, draft_text)})
    dropped = len(out.unsupported) - len(found)
    if dropped:
        print(f"[VERIFY] 초안에서 찾지 못한 인용 {dropped}개를 버림")
    return found


def _listed(claim: dict) -> str:
    """재작성에 넘기는 한 줄. 구절이 짧으면 어느 문장의 것인지 함께 적는다."""
    sentence = claim.get("sentence") or claim["quote"]
    where = "" if sentence == claim["quote"] else f" — 문장: \"{sentence}\""
    return f"- \"{claim['quote']}\"{where} ({claim['reason']})"


def rewrite_draft(sections: dict, unsupported: list[dict]) -> dict | None:
    """근거 없는 표현만 고쳐 다시 쓴다 (LLM 호출). 쓸 수 있는 결과가 나오지 않으면 None."""
    listed = "\n".join(_listed(c) for c in unsupported)
    user = f"{REWRITE_RULES}\n[근거 없는 표현]\n{listed}\n\n[초안]\n{format_draft(sections)}\n"
    try:
        out = llm.text("rewrite", user, system=REWRITE_SYSTEM)
    except LLMCallError:
        return None  # 호출하는 쪽이 '다시 쓰지 못함'으로 남긴다. 초안은 그대로다.
    new = split_complaint_sections(postprocess_complaint(out))
    if not all(new.get(key, "").strip() for key in SECTION_TITLES if sections.get(key, "").strip()):
        return None
    return new
