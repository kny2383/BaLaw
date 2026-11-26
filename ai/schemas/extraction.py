"""정보 추출 호출의 출력 스키마.

항목(elements, details)과 슬롯 이름은 죄목 정의에서 오므로 죄목마다 모델을 만든다.
모델이 스키마에 맞는 JSON만 내도록 강제해서, 항목이나 슬롯이 빠지거나
허용하지 않은 값이 들어오는 일을 없앤다.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Dict, List, Literal, Tuple, Type

from pydantic import BaseModel, ConfigDict, create_model

from loaders.detail_loader import get_detail_schema
from loaders.offense_loader import get_offense_meta

SlotValue = Literal["present", "missing", "unclear", "unknown"]
ItemStatus = Literal["satisfied", "missing", "unclear"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _slot_names(slots_obj) -> List[str]:
    if isinstance(slots_obj, dict):
        must, nice = slots_obj.get("must"), slots_obj.get("nice_to_have")
    else:
        must, nice = getattr(slots_obj, "must", None), getattr(slots_obj, "nice_to_have", None)
    return list(must or []) + list(nice or [])


def _item_model(name: str, slots: List[str]) -> Type[BaseModel]:
    slots_model = create_model(f"{name}_slots", __base__=_Strict, **{s: (SlotValue, ...) for s in slots})
    return create_model(
        name,
        __base__=_Strict,
        status=(ItemStatus, ...),
        slots=(slots_model, ...),
        evidence=(str, ...),
        summary=(str, ...),
    )


def _group_model(name: str, items: List[Tuple[str, List[str]]]) -> Type[BaseModel]:
    fields: Dict[str, tuple] = {item_id: (_item_model(f"{name}_{item_id}", slots), ...) for item_id, slots in items}
    return create_model(name, __base__=_Strict, **fields)


@lru_cache(maxsize=8)
def extraction_model(offense: str) -> Type[BaseModel]:
    """죄목의 모든 항목과 슬롯을 필수로 갖는 추출 결과 모델."""
    meta = get_offense_meta(offense)
    elements = [(e.id, _slot_names(getattr(e, "slots", None))) for e in meta.elements]
    details = [(d["id"], list(d["must"]) + list(d["nice"])) for d in get_detail_schema(offense)]
    return create_model(
        f"Extraction_{offense}",
        __base__=_Strict,
        elements=(_group_model(f"{offense}_elements", elements), ...),
        details=(_group_model(f"{offense}_details", details), ...),
    )
