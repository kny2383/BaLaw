"""대화 그래프와 판례 그래프의 상태."""
from __future__ import annotations

from typing import Optional, TypedDict


class ChatState(TypedDict, total=False):
    # 세션에 계속 남는 값
    offense: str                 # 질문과 작성에 쓰는 죄목 양식 (fraud | insult)
    offense_selected: bool       # 사용자가 죄목을 직접 골랐는가
    history: list[dict]          # [{"role": "user" | "assistant", "content": str}]
    collected: dict              # {"elements": {...}, "details": {...}}

    # 이번 요청과 그 결과 (요청마다 덮어쓴다)
    request: dict                # {"action": "init" | "message" | "compose", ...}
    reply: str
    complete: bool
    caution: bool
    draft: dict                  # 작성 결과 {"offense", "title", "sections"}


class RagState(TypedDict, total=False):
    text: str
    status: str                  # ready | failed (없으면 아직 pending)
    keyword: Optional[str]
    raw_cases: list[dict]
    cases: list[dict]
    error: Optional[str]
