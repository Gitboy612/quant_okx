import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from pydantic import ValidationError

from dsl.schema import (
    StrategyDSL, Rule, Trigger, BaseStrategyRef,
    BlockRef, IndicatorRef, ConditionRef, ActionRef, EventRef,
)


def test_condition_trigger_rule():
    """1. condition-trigger Rule 反序列化（用户示例的 when 字段）"""
    data = {
        "name": "止盈",
        "when": {
            "mode": "condition",
            "condition": {"kind": "price_above", "args": {"threshold": 100000}},
        },
        "then": [{"kind": "close_position", "args": {"pct": 1.0}}],
    }
    rule = Rule.model_validate(data)
    assert rule.name == "止盈"
    assert rule.when.mode == "condition"
    assert isinstance(rule.when.condition, ConditionRef)
    assert rule.when.condition.kind == "price_above"
    assert rule.when.condition.args == {"threshold": 100000}
    assert rule.when.event is None
    assert rule.when.extra_condition is None
    assert rule.then[0].kind == "close_position"
    assert rule.then[0].args == {"pct": 1.0}


def test_event_trigger_rule():
    """2. event-trigger Rule 反序列化（mode=event，event 字段）"""
    data = {
        "name": "止损",
        "when": {
            "mode": "event",
            "event": {"kind": "on_price_drop", "args": {"pct": 0.05}},
        },
        "then": [{"kind": "close_position", "args": {}}],
    }
    rule = Rule.model_validate(data)
    assert rule.when.mode == "event"
    assert isinstance(rule.when.event, EventRef)
    assert rule.when.event.kind == "on_price_drop"
    assert rule.when.event.args == {"pct": 0.05}
    assert rule.when.condition is None
    assert rule.when.extra_condition is None


def test_event_with_extra_condition():
    """3. event+extra_condition 模式"""
    data = {
        "name": "事件+额外条件",
        "when": {
            "mode": "event",
            "event": {"kind": "on_signal", "args": {"src": "external"}},
            "extra_condition": {"kind": "position_long", "args": {}},
        },
        "then": [{"kind": "notify", "args": {}}],
    }
    rule = Rule.model_validate(data)
    assert rule.when.mode == "event"
    assert isinstance(rule.when.event, EventRef)
    assert rule.when.event.kind == "on_signal"
    assert isinstance(rule.when.extra_condition, ConditionRef)
    assert rule.when.extra_condition.kind == "position_long"
    assert rule.when.condition is None


def test_strategy_dsl_roundtrip():
    """4. 完整 StrategyDSL 含 base_strategy + rules 序列化/反序列化往返"""
    dsl = StrategyDSL(
        base_strategy=BaseStrategyRef(kind="grid", params={"upper": 100, "lower": 50}),
        rules=[
            Rule(
                name="r1",
                when=Trigger(
                    mode="condition",
                    condition=ConditionRef(kind="price_above", args={"t": 1}),
                ),
                then=[ActionRef(kind="close_position", args={})],
            ),
        ],
    )
    dumped = dsl.model_dump()
    assert dumped["version"] == "1.0"
    assert dumped["base_strategy"]["kind"] == "grid"
    assert dumped["base_strategy"]["params"] == {"upper": 100, "lower": 50}

    # dict 往返
    dsl2 = StrategyDSL.model_validate(dumped)
    assert dsl2 == dsl
    assert dsl2.rules[0].when.condition.args == {"t": 1}

    # JSON 往返
    dsl3 = StrategyDSL.model_validate_json(dsl.model_dump_json())
    assert dsl3 == dsl


def test_defaults():
    """5. 默认值（cool_down_seconds=0.0，rules=[]）"""
    dsl = StrategyDSL(base_strategy=BaseStrategyRef(kind="grid"))
    assert dsl.version == "1.0"
    assert dsl.rules == []
    assert dsl.base_strategy.params == {}

    rule = Rule(
        name="r",
        when=Trigger(condition=ConditionRef(kind="c", args={})),
    )
    assert rule.cool_down_seconds == 0.0
    assert rule.then == []
    assert rule.recover_when is None
    assert rule.recover_then == []


def test_invalid_version_rejected():
    """6. 非法 version 被拒"""
    with pytest.raises(ValidationError):
        StrategyDSL.model_validate({
            "version": "2.0",
            "base_strategy": {"kind": "grid"},
        })


def test_block_ref_subtypes():
    """附加：BlockRef 子类型关系与默认 args"""
    ind = IndicatorRef(kind="rsi", args={"period": 14})
    assert isinstance(ind, BlockRef)
    assert ind.kind == "rsi"
    assert ind.args == {"period": 14}

    # 默认 args 为空 dict
    assert ConditionRef(kind="x").args == {}
    assert ActionRef(kind="y").args == {}
    assert EventRef(kind="on_z").args == {}


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
