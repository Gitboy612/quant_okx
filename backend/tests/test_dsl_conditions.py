"""P0 条件积木库测试。

覆盖：
- 比较类 gt / lt / abs_gt / abs_lt 的真值表
- 逻辑组合类 and / or / not 的嵌套逻辑
- evaluate_condition 对未注册 kind 抛 ValueError

通过 patch `dsl.blocks.conditions._resolve_indicator_value` 控制指标返回值，
从而精确驱动各条件的真值分支。
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from unittest.mock import AsyncMock, patch

# 导入条件库即触发 @condition 装饰器注册
from dsl.blocks.conditions import (
    evaluate_condition,
    GreaterThan,
    LessThan,
    AbsGreaterThan,
    AbsLessThan,
    AndCondition,
    OrCondition,
    NotCondition,
)
from dsl.registry import condition_registry
from dsl.schema import ConditionRef


# —— 指标返回值映射：以 indicator kind 区分，供 fake_resolve 返回固定数值 ——
INDICATOR_VALUES = {
    "val_10": 10.0,
    "val_5": 5.0,
    "val_3": 3.0,
    "val_neg10": -10.0,
    "val_neg3": -3.0,
}


async def fake_resolve(ref, ctx):
    """模拟指标解析，按 ref.kind 返回预设数值。"""
    return INDICATOR_VALUES[ref.kind]


def make_indicator(kind: str, **args) -> dict:
    """构造 indicator 参数 dict（{kind, args} 形态）。"""
    return {"kind": kind, "args": args}


def make_ctx():
    """用 AsyncMock 构造 ExecutionContext，预设 indicator_cache 与 client。"""
    ctx = AsyncMock()
    ctx.indicator_cache = {}
    ctx.client = AsyncMock()
    return ctx


# ============================ 比较类真值表 ============================


@pytest.mark.asyncio
@patch("dsl.blocks.conditions._resolve_indicator_value", side_effect=fake_resolve)
async def test_gt_truth_table(mocked):
    """gt: indicator_value > threshold"""
    ctx = make_ctx()
    # 10 > 5 → True
    c = GreaterThan(indicator=make_indicator("val_10"), threshold=5)
    assert await c.evaluate(ctx) is True
    # 5 > 5 → False（等于不满足严格大于）
    c = GreaterThan(indicator=make_indicator("val_5"), threshold=5)
    assert await c.evaluate(ctx) is False
    # 3 > 5 → False
    c = GreaterThan(indicator=make_indicator("val_3"), threshold=5)
    assert await c.evaluate(ctx) is False


@pytest.mark.asyncio
@patch("dsl.blocks.conditions._resolve_indicator_value", side_effect=fake_resolve)
async def test_lt_truth_table(mocked):
    """lt: indicator_value < threshold"""
    ctx = make_ctx()
    # 3 < 5 → True
    c = LessThan(indicator=make_indicator("val_3"), threshold=5)
    assert await c.evaluate(ctx) is True
    # 5 < 5 → False
    c = LessThan(indicator=make_indicator("val_5"), threshold=5)
    assert await c.evaluate(ctx) is False
    # 10 < 5 → False
    c = LessThan(indicator=make_indicator("val_10"), threshold=5)
    assert await c.evaluate(ctx) is False


@pytest.mark.asyncio
@patch("dsl.blocks.conditions._resolve_indicator_value", side_effect=fake_resolve)
async def test_abs_gt_truth_table(mocked):
    """abs_gt: abs(indicator_value) > threshold"""
    ctx = make_ctx()
    # abs(-10) = 10 > 5 → True
    c = AbsGreaterThan(indicator=make_indicator("val_neg10"), threshold=5)
    assert await c.evaluate(ctx) is True
    # abs(10) = 10 > 5 → True
    c = AbsGreaterThan(indicator=make_indicator("val_10"), threshold=5)
    assert await c.evaluate(ctx) is True
    # abs(-3) = 3 > 5 → False
    c = AbsGreaterThan(indicator=make_indicator("val_neg3"), threshold=5)
    assert await c.evaluate(ctx) is False
    # abs(3) = 3 > 5 → False
    c = AbsGreaterThan(indicator=make_indicator("val_3"), threshold=5)
    assert await c.evaluate(ctx) is False


@pytest.mark.asyncio
@patch("dsl.blocks.conditions._resolve_indicator_value", side_effect=fake_resolve)
async def test_abs_lt_truth_table(mocked):
    """abs_lt: abs(indicator_value) < threshold"""
    ctx = make_ctx()
    # abs(-3) = 3 < 5 → True
    c = AbsLessThan(indicator=make_indicator("val_neg3"), threshold=5)
    assert await c.evaluate(ctx) is True
    # abs(3) = 3 < 5 → True
    c = AbsLessThan(indicator=make_indicator("val_3"), threshold=5)
    assert await c.evaluate(ctx) is True
    # abs(-10) = 10 < 5 → False
    c = AbsLessThan(indicator=make_indicator("val_neg10"), threshold=5)
    assert await c.evaluate(ctx) is False
    # abs(10) = 10 < 5 → False
    c = AbsLessThan(indicator=make_indicator("val_10"), threshold=5)
    assert await c.evaluate(ctx) is False


# ============================ 逻辑组合类嵌套 ============================


@pytest.mark.asyncio
@patch("dsl.blocks.conditions._resolve_indicator_value", side_effect=fake_resolve)
async def test_and_nested(mocked):
    """and: 全部子条件为真返回 True，任一为假返回 False。"""
    ctx = make_ctx()
    # 两个真 → True
    ref = ConditionRef(
        kind="and",
        args={
            "conditions": [
                {"kind": "gt", "args": {"indicator": make_indicator("val_10"), "threshold": 5}},
                {"kind": "lt", "args": {"indicator": make_indicator("val_3"), "threshold": 5}},
            ]
        },
    )
    assert await evaluate_condition(ref, ctx) is True

    # 一真一假 → False
    ref = ConditionRef(
        kind="and",
        args={
            "conditions": [
                {"kind": "gt", "args": {"indicator": make_indicator("val_10"), "threshold": 5}},
                {"kind": "gt", "args": {"indicator": make_indicator("val_3"), "threshold": 5}},
            ]
        },
    )
    assert await evaluate_condition(ref, ctx) is False

    # 空列表 → True（空真）
    ref = ConditionRef(kind="and", args={"conditions": []})
    assert await evaluate_condition(ref, ctx) is True

    # 直接实例化亦可
    inst = AndCondition(conditions=[
        {"kind": "lt", "args": {"indicator": make_indicator("val_10"), "threshold": 5}},
    ])
    assert await inst.evaluate(ctx) is False


@pytest.mark.asyncio
@patch("dsl.blocks.conditions._resolve_indicator_value", side_effect=fake_resolve)
async def test_or_nested(mocked):
    """or: 任一子条件为真返回 True，全部为假返回 False。"""
    ctx = make_ctx()
    # 一真一假 → True
    ref = ConditionRef(
        kind="or",
        args={
            "conditions": [
                {"kind": "gt", "args": {"indicator": make_indicator("val_3"), "threshold": 5}},   # False
                {"kind": "lt", "args": {"indicator": make_indicator("val_3"), "threshold": 5}},   # True
            ]
        },
    )
    assert await evaluate_condition(ref, ctx) is True

    # 全假 → False
    ref = ConditionRef(
        kind="or",
        args={
            "conditions": [
                {"kind": "gt", "args": {"indicator": make_indicator("val_3"), "threshold": 5}},
                {"kind": "gt", "args": {"indicator": make_indicator("val_5"), "threshold": 5}},
            ]
        },
    )
    assert await evaluate_condition(ref, ctx) is False

    # 空列表 → False（空假）
    ref = ConditionRef(kind="or", args={"conditions": []})
    assert await evaluate_condition(ref, ctx) is False

    # 直接实例化
    inst = OrCondition(conditions=[
        {"kind": "lt", "args": {"indicator": make_indicator("val_10"), "threshold": 5}},
        {"kind": "gt", "args": {"indicator": make_indicator("val_10"), "threshold": 5}},
    ])
    assert await inst.evaluate(ctx) is True


@pytest.mark.asyncio
@patch("dsl.blocks.conditions._resolve_indicator_value", side_effect=fake_resolve)
async def test_not_nested(mocked):
    """not: 子条件取反。"""
    ctx = make_ctx()
    # 内部 gt(10>5)=True → not → False
    ref = ConditionRef(
        kind="not",
        args={
            "condition": {"kind": "gt", "args": {"indicator": make_indicator("val_10"), "threshold": 5}},
        },
    )
    assert await evaluate_condition(ref, ctx) is False

    # 内部 gt(3>5)=False → not → True
    ref = ConditionRef(
        kind="not",
        args={
            "condition": {"kind": "gt", "args": {"indicator": make_indicator("val_3"), "threshold": 5}},
        },
    )
    assert await evaluate_condition(ref, ctx) is True

    # 直接实例化
    inst = NotCondition(condition={"kind": "lt", "args": {"indicator": make_indicator("val_10"), "threshold": 5}})
    # lt(10<5)=False → not → True
    assert await inst.evaluate(ctx) is True


@pytest.mark.asyncio
@patch("dsl.blocks.conditions._resolve_indicator_value", side_effect=fake_resolve)
async def test_deeply_nested(mocked):
    """多层嵌套：and( or( gt(10>5), lt(10<5) ), not( gt(3>5) ) ) → and(True, True) → True"""
    ctx = make_ctx()
    ref = ConditionRef(
        kind="and",
        args={
            "conditions": [
                {
                    "kind": "or",
                    "args": {
                        "conditions": [
                            {"kind": "gt", "args": {"indicator": make_indicator("val_10"), "threshold": 5}},
                            {"kind": "lt", "args": {"indicator": make_indicator("val_10"), "threshold": 5}},
                        ]
                    },
                },
                {
                    "kind": "not",
                    "args": {
                        "condition": {"kind": "gt", "args": {"indicator": make_indicator("val_3"), "threshold": 5}},
                    },
                },
            ]
        },
    )
    assert await evaluate_condition(ref, ctx) is True


# ============================ 异常分支 ============================


@pytest.mark.asyncio
async def test_evaluate_condition_unknown_kind_raises():
    """evaluate_condition 对未注册的 kind 抛 ValueError。"""
    ctx = make_ctx()
    ref = ConditionRef(kind="totally_unknown_kind", args={})
    with pytest.raises(ValueError, match="未知条件 kind"):
        await evaluate_condition(ref, ctx)


@pytest.mark.asyncio
@patch("dsl.blocks.conditions._resolve_indicator_value", side_effect=fake_resolve)
async def test_and_with_unknown_child_raises(mocked):
    """and 子条件含未注册 kind 时，递归求值抛 ValueError。"""
    ctx = make_ctx()
    ref = ConditionRef(
        kind="and",
        args={
            "conditions": [
                {"kind": "gt", "args": {"indicator": make_indicator("val_10"), "threshold": 5}},
                {"kind": "no_such_kind", "args": {}},
            ]
        },
    )
    with pytest.raises(ValueError, match="未知条件 kind"):
        await evaluate_condition(ref, ctx)


# ============================ 注册与元数据 ============================


def test_conditions_registered():
    """7 个 P0 条件均已注册到 condition_registry。"""
    for kind in ("gt", "lt", "abs_gt", "abs_lt", "and", "or", "not"):
        assert kind in condition_registry, f"kind {kind} 未注册"


def test_condition_metadata():
    """条件类元数据（category / priority / input_type / param_schema）符合规范。"""
    compare_cls = condition_registry.get("gt")
    assert compare_cls.category == "比较"
    assert compare_cls.priority == "P0"
    assert compare_cls.input_type == "number"
    assert "indicator" in compare_cls.param_schema
    assert "threshold" in compare_cls.param_schema

    and_cls = condition_registry.get("and")
    assert and_cls.category == "逻辑"
    assert and_cls.priority == "P0"
    assert and_cls.input_type == "bool"
    assert "conditions" in and_cls.param_schema

    not_cls = condition_registry.get("not")
    assert not_cls.category == "逻辑"
    assert not_cls.input_type == "bool"
    assert "condition" in not_cls.param_schema


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
