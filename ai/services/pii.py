"""식별정보 치환 (요구사항 S05).

사용자 서술의 이름·전화번호·계좌번호·주소를 '[이름1]' 같은 표식으로 바꾼다. 세션 상태와 LLM 요청에는
표식만 남고, 사용자에게 응답을 돌려줄 때 원래 값으로 되돌린다.

- 전화번호와 계좌번호는 정규식으로 찾는다.
- 이름과 주소는 정규식으로 찾을 수 없어, 호출하는 쪽(서버)이 입력 화면에서 받은 값을 넘겨준다.
  넘겨받지 못한 이름(제3자, 닉네임 등)은 가려지지 않는다.
- 날짜와 금액은 가리지 않는다 (추출과 작성에 필요하다).
"""
from __future__ import annotations

import re

LABELS = {"names": "이름", "addresses": "주소", "phones": "전화번호", "accounts": "계좌번호"}
TOKEN_RE = re.compile(r"\[(이름|주소|전화번호|계좌번호)\d+\]")

# 숫자나 하이픈에 붙어 있지 않은 덩어리만 잡는다. 한글 조사가 바로 붙어도 잡힌다 ("...5678로").
_EDGE_L, _EDGE_R = r"(?<![\d-])", r"(?![\d-])"
PHONE_RE = re.compile(_EDGE_L + r"(?:0\d{1,2}-\d{3,4}-\d{4}|01\d{8,9})" + _EDGE_R)
ACCOUNT_RE = re.compile(_EDGE_L + r"\d{2,6}(?:-\d{2,8}){1,4}" + _EDGE_R)
ACCOUNT_MIN_DIGITS = 9  # 2026-11-26 같은 날짜(8자리)는 계좌로 보지 않는다

# LLM 프롬프트에 붙이는 안내. 표식을 값이 있는 것으로 읽고 그대로 옮겨 쓰게 한다.
PROMPT_NOTE = (
    "- '[이름1]', '[전화번호1]', '[계좌번호1]', '[주소1]' 같은 표식은 가려 둔 실제 값입니다. "
    "값이 주어진 것으로 보고, 쓸 때는 표식을 한 글자도 바꾸지 말고 그대로 옮기십시오.\n"
)


def new_state(known: dict | None = None) -> dict:
    """세션의 치환 상태. known은 호출하는 쪽이 알려 준 값(이름, 주소 등), tokens는 표식 → 원래 값."""
    cleaned = {k: [v.strip() for v in (known or {}).get(k) or [] if isinstance(v, str) and len(v.strip()) >= 2]
               for k in LABELS}
    return {"known": cleaned, "tokens": {}}


def _token_for(state: dict, kind: str, value: str) -> str:
    for token, original in state["tokens"].items():
        if original == value and token.startswith(f"[{LABELS[kind]}"):
            return token
    n = sum(1 for t in state["tokens"] if t.startswith(f"[{LABELS[kind]}")) + 1
    token = f"[{LABELS[kind]}{n}]"
    state["tokens"][token] = value
    return token


def mask(text: str, state: dict) -> str:
    """text의 식별정보를 표식으로 바꾼다. state["tokens"]에 새 표식이 더해진다."""
    if not text:
        return text
    # 알려 준 값은 긴 것부터 바꾼다 (이름이 주소 안에 들어 있는 경우 등).
    known = sorted(((v, k) for k in LABELS for v in state["known"].get(k, [])), key=lambda p: -len(p[0]))
    for value, kind in known:
        if value in text:
            text = text.replace(value, _token_for(state, kind, value))
    text = PHONE_RE.sub(lambda m: _token_for(state, "phones", m.group(0)), text)

    def account(m: re.Match) -> str:
        if sum(ch.isdigit() for ch in m.group(0)) < ACCOUNT_MIN_DIGITS:
            return m.group(0)
        return _token_for(state, "accounts", m.group(0))

    return ACCOUNT_RE.sub(account, text)


def unmask(value, state: dict | None):
    """문자열, 목록, dict 안의 표식을 원래 값으로 되돌린다."""
    tokens = (state or {}).get("tokens") or {}
    if not tokens:
        return value
    if isinstance(value, str):
        return TOKEN_RE.sub(lambda m: tokens.get(m.group(0), m.group(0)), value)
    if isinstance(value, list):
        return [unmask(v, state) for v in value]
    if isinstance(value, dict):
        return {k: unmask(v, state) for k, v in value.items()}
    return value
