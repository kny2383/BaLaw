"""대화 그래프와 판례 그래프의 상태.

저장 규칙: 대화에서 나온 글(발화, 질문, 요약, 초안, 죄명 키워드, 오류 문구)은 반드시 dict나 list
안에 둔다. 체크포인터는 dict·list 값만 암호화해서 저장하고, 문자열·숫자·불리언 값은 암호화 없이
그대로 저장하기 때문이다. 최상위에 문자열로 둘 수 있는 것은 PLAIN_FIELDS의 고정된 코드와 표시뿐이다.
"""
from __future__ import annotations

from typing import TypedDict

# 암호화 없이 저장되어도 되는 최상위 값. 대화 내용이 아니라 정해진 코드와 표시다.
PLAIN_FIELDS = {"offense", "offense_selected"}


class ChatState(TypedDict, total=False):
    # 세션에 계속 남는 값
    offense: str                 # 질문과 작성에 쓰는 죄목 양식 코드 (fraud | insult)
    offense_selected: bool       # 사용자가 죄목을 직접 골랐는가
    history: list[dict]          # [{"role": "user" | "assistant", "content": str}]
    collected: dict              # {"elements": {...}, "details": {...}}
    pii: dict                    # 식별정보 치환 상태 {"known": {...}, "tokens": {표식: 원래 값}}. 대화 글은 표식으로만 저장된다

    # 이번 요청과 그 결과 (요청마다 덮어쓴다)
    request: dict                # {"action": "init" | "message" | "compose", ...}
    result: dict                 # {"reply": str, "complete": bool, "caution": bool}
    draft: dict                  # 작성 결과 {"offense", "title", "sections"}
    review: dict                 # 초안 검증 {"status", "rewrites", "rechecked", "unsupported": [{"quote", "reason"}], "removed": [...]}


class RagState(TypedDict, total=False):
    request: dict                # {"text": 사건 서술}
    found: dict                  # 중간 결과 {"keyword": str, "raw_cases": list}
    result: dict                 # {"status": "ready" | "failed", "keyword", "cases", "error"}
