from pydantic import BaseModel, Field
from typing import Any, Literal


class BlockRef(BaseModel):
    """统一积木引用形态"""
    kind: str
    args: dict[str, Any] = Field(default_factory=dict)


class IndicatorRef(BlockRef):
    pass


class ConditionRef(BlockRef):
    pass


class ActionRef(BlockRef):
    pass


class EventRef(BlockRef):
    """事件类积木，kind 以 on_ 前缀"""
    pass


class Trigger(BaseModel):
    """Rule 的触发器：condition（每 tick 评估）或 event（仅事件发生时触发）或 event+extra_condition"""
    mode: Literal["condition", "event"] = "condition"
    condition: ConditionRef | None = None
    event: EventRef | None = None
    extra_condition: ConditionRef | None = None


class Rule(BaseModel):
    name: str
    when: Trigger
    then: list[ActionRef] = Field(default_factory=list)
    recover_when: Trigger | None = None
    recover_then: list[ActionRef] = Field(default_factory=list)
    cool_down_seconds: float = 0.0


class BaseStrategyRef(BaseModel):
    kind: str
    params: dict[str, Any] = Field(default_factory=dict)


class StrategyDSL(BaseModel):
    version: Literal["1.0"] = "1.0"
    base_strategy: BaseStrategyRef
    rules: list[Rule] = Field(default_factory=list)
