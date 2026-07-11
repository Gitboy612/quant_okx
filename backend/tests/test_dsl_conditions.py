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
    CrossAbove,
    CrossBelow,
    InRange,
    OutRange,
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
    # 让 get_state / set_state 真实操作 kv_state 字典（默认 AsyncMock 返回 MagicMock）
    ctx.kv_state = {}
    ctx.get_state = lambda key, default=None: ctx.kv_state.get(key, default)
    ctx.set_state = lambda key, value: ctx.kv_state.__setitem__(key, value)
    ctx.clear_state = lambda key: ctx.kv_state.pop(key, None)
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
    """P0 + P1 条件均已注册到 condition_registry。"""
    for kind in ("gt", "lt", "abs_gt", "abs_lt", "and", "or", "not"):
        assert kind in condition_registry, f"kind {kind} 未注册"
    for kind in ("cross_above", "cross_below", "in_range", "out_range"):
        assert kind in condition_registry, f"P1 kind {kind} 未注册"


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


def test_p1_condition_metadata():
    """P1 条件元数据：交叉类与区间类。"""
    cross_above_cls = condition_registry.get("cross_above")
    assert cross_above_cls.category == "交叉"
    assert cross_above_cls.priority == "P1"
    assert cross_above_cls.label == "上穿"
    assert cross_above_cls.display_template == "{indicator_a} 上穿 {indicator_b}"
    assert "indicator_a" in cross_above_cls.param_schema
    assert "indicator_b" in cross_above_cls.param_schema

    cross_below_cls = condition_registry.get("cross_below")
    assert cross_below_cls.category == "交叉"
    assert cross_below_cls.priority == "P1"
    assert cross_below_cls.label == "下穿"
    assert cross_below_cls.display_template == "{indicator_a} 下穿 {indicator_b}"

    in_range_cls = condition_registry.get("in_range")
    assert in_range_cls.category == "区间"
    assert in_range_cls.priority == "P1"
    assert in_range_cls.label == "在区间内"
    assert in_range_cls.display_template == "{indicator} 在 {lower} 到 {upper} 之间"
    assert "indicator" in in_range_cls.param_schema
    assert "lower" in in_range_cls.param_schema
    assert "upper" in in_range_cls.param_schema

    out_range_cls = condition_registry.get("out_range")
    assert out_range_cls.category == "区间"
    assert out_range_cls.priority == "P1"
    assert out_range_cls.label == "在区间外"
    assert out_range_cls.display_template == "{indicator} 不在 {lower} 到 {upper} 之间"


# ============================ 交叉类 ============================


class _CrossResolver:
    """可变指标解析器：按调用次序返回队列中的值，模拟跨 tick 变化。

    注意：作为 ``side_effect`` 传给 ``AsyncMock`` 时，需用 ``make_resolver``
    工厂返回的 ``async def`` 函数（而非 ``async def __call__``），
    以确保 ``AsyncMock`` 正确 ``await`` 返回值。
    """

    def __init__(self, value_map: dict):
        # value_map: {ref_kind: [v_tick0, v_tick1, ...]}
        self.value_map = value_map
        self.counters: dict[str, int] = {}

    def make_resolver(self):
        """返回一个 async def 函数，闭包捕获本实例的 counters/value_map。"""
        counters = self.counters
        value_map = self.value_map

        async def resolve(ref, ctx):
            idx = counters.get(ref.kind, 0)
            counters[ref.kind] = idx + 1
            return value_map[ref.kind][idx]

        return resolve


@pytest.mark.asyncio
@patch("dsl.blocks.conditions._resolve_indicator_value")
async def test_cross_above_first_tick_no_cross(mocked):
    """cross_above 首次执行无 prev 数据，返回 False。"""
    resolver = _CrossResolver({"val_a": [5.0], "val_b": [10.0]})
    mocked.side_effect = resolver.make_resolver()
    ctx = make_ctx()
    ctx.kv_state = {}
    c = CrossAbove(indicator_a=make_indicator("val_a"), indicator_b=make_indicator("val_b"))
    assert await c.evaluate(ctx) is False


@pytest.mark.asyncio
@patch("dsl.blocks.conditions._resolve_indicator_value")
async def test_cross_above_detects_upward_cross(mocked):
    """cross_above: tick0 A<B, tick1 A>B → 触发上穿。"""
    resolver = _CrossResolver({"val_a": [5.0, 15.0], "val_b": [10.0, 10.0]})
    mocked.side_effect = resolver.make_resolver()
    # 共享 kv_state 模拟跨 tick 持久
    kv_state = {}
    ctx0 = make_ctx()
    ctx0.kv_state = kv_state
    c = CrossAbove(indicator_a=make_indicator("val_a"), indicator_b=make_indicator("val_b"))
    assert await c.evaluate(ctx0) is False  # 首次无 prev
    ctx1 = make_ctx()
    ctx1.kv_state = kv_state  # 复用同一 kv_state
    assert await c.evaluate(ctx1) is True  # 5<10, 15>10 → 上穿


@pytest.mark.asyncio
@patch("dsl.blocks.conditions._resolve_indicator_value")
async def test_cross_above_no_cross_when_both_above(mocked):
    """cross_above: A 始终大于 B，不算上穿。"""
    resolver = _CrossResolver({"val_a": [15.0, 20.0], "val_b": [10.0, 10.0]})
    mocked.side_effect = resolver.make_resolver()
    kv_state = {}
    ctx0 = make_ctx()
    ctx0.kv_state = kv_state
    c = CrossAbove(indicator_a=make_indicator("val_a"), indicator_b=make_indicator("val_b"))
    await c.evaluate(ctx0)
    ctx1 = make_ctx()
    ctx1.kv_state = kv_state
    assert await c.evaluate(ctx1) is False  # prev_a(15) > prev_b(10)，不满足上穿


@pytest.mark.asyncio
@patch("dsl.blocks.conditions._resolve_indicator_value")
async def test_cross_below_detects_downward_cross(mocked):
    """cross_below: tick0 A>B, tick1 A<B → 触发下穿。"""
    resolver = _CrossResolver({"val_a": [15.0, 5.0], "val_b": [10.0, 10.0]})
    mocked.side_effect = resolver.make_resolver()
    kv_state = {}
    ctx0 = make_ctx()
    ctx0.kv_state = kv_state
    c = CrossBelow(indicator_a=make_indicator("val_a"), indicator_b=make_indicator("val_b"))
    assert await c.evaluate(ctx0) is False  # 首次无 prev
    ctx1 = make_ctx()
    ctx1.kv_state = kv_state
    assert await c.evaluate(ctx1) is True  # 15>10, 5<10 → 下穿


@pytest.mark.asyncio
@patch("dsl.blocks.conditions._resolve_indicator_value")
async def test_cross_below_no_cross_when_both_below(mocked):
    """cross_below: A 始终小于 B，不算下穿。"""
    resolver = _CrossResolver({"val_a": [3.0, 4.0], "val_b": [10.0, 10.0]})
    mocked.side_effect = resolver.make_resolver()
    kv_state = {}
    ctx0 = make_ctx()
    ctx0.kv_state = kv_state
    c = CrossBelow(indicator_a=make_indicator("val_a"), indicator_b=make_indicator("val_b"))
    await c.evaluate(ctx0)
    ctx1 = make_ctx()
    ctx1.kv_state = kv_state
    assert await c.evaluate(ctx1) is False


# ============================ 区间类 ============================


@pytest.mark.asyncio
@patch("dsl.blocks.conditions._resolve_indicator_value", side_effect=fake_resolve)
async def test_in_range_truth_table(mocked):
    """in_range: 指标值在 [lower, upper] 闭区间内为 True。"""
    ctx = make_ctx()
    # 10 在 [5, 15] → True
    c = InRange(indicator=make_indicator("val_10"), lower=5, upper=15)
    assert await c.evaluate(ctx) is True
    # 5 在边界 [5, 15] → True（闭区间）
    c = InRange(indicator=make_indicator("val_5"), lower=5, upper=15)
    assert await c.evaluate(ctx) is True
    # 15 在边界 [5, 15] → True
    c = InRange(indicator=make_indicator("val_10"), lower=5, upper=15)
    assert await c.evaluate(ctx) is True
    # 3 不在 [5, 15] → False
    c = InRange(indicator=make_indicator("val_3"), lower=5, upper=15)
    assert await c.evaluate(ctx) is False
    # -10 不在 [5, 15] → False
    c = InRange(indicator=make_indicator("val_neg10"), lower=5, upper=15)
    assert await c.evaluate(ctx) is False


@pytest.mark.asyncio
@patch("dsl.blocks.conditions._resolve_indicator_value", side_effect=fake_resolve)
async def test_out_range_truth_table(mocked):
    """out_range: 指标值在 [lower, upper] 闭区间外为 True。"""
    ctx = make_ctx()
    # 10 不在 [5, 15] 外 → False
    c = OutRange(indicator=make_indicator("val_10"), lower=5, upper=15)
    assert await c.evaluate(ctx) is False
    # 3 在 [5, 15] 外 → True
    c = OutRange(indicator=make_indicator("val_3"), lower=5, upper=15)
    assert await c.evaluate(ctx) is True
    # -10 在 [5, 15] 外 → True
    c = OutRange(indicator=make_indicator("val_neg10"), lower=5, upper=15)
    assert await c.evaluate(ctx) is True
    # 5 在边界 → 不算外 → False
    c = OutRange(indicator=make_indicator("val_5"), lower=5, upper=15)
    assert await c.evaluate(ctx) is False


@pytest.mark.asyncio
@patch("dsl.blocks.conditions._resolve_indicator_value", side_effect=fake_resolve)
async def test_in_range_via_evaluate_condition(mocked):
    """通过 evaluate_condition 调度 in_range 条件。"""
    ctx = make_ctx()
    ref = ConditionRef(
        kind="in_range",
        args={"indicator": make_indicator("val_10"), "lower": 5, "upper": 15},
    )
    assert await evaluate_condition(ref, ctx) is True
    ref = ConditionRef(
        kind="out_range",
        args={"indicator": make_indicator("val_3"), "lower": 5, "upper": 15},
    )
    assert await evaluate_condition(ref, ctx) is True


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
