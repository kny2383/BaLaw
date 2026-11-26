"""초안 검증 결과의 스키마."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class UnsupportedClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quote: str    # 초안에서 그대로 옮긴 표현
    reason: str   # 대화의 어느 부분과 맞지 않는지


class Verification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unsupported: list[UnsupportedClaim]
