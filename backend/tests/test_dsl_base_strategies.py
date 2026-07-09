"""DSL 基础策略库测试（QS-Model 策略构建优化改造）。

验证 7 个基础策略（grid/trend/rsi_strategy/bollinger_bands/donchian/dca/martingale）：
- 全部注册成功
- 每个 strategy 类含 label 字段
- grid 的 order_qty/grid_mode/direction 为可选参数
- 每个策略的 param_schema 参数含 label

参考 test_dsl_indicators.py 的 sys.path.insert + pytest 风格。
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

# 导入 bases 模块以触发 @base_strategy 注册
import dsl.blocks.bases  # noqa: F401
from dsl.registry import base_strategy_registry


# 期望的 7 个基础策略 kind
EXPECTED_KINDS = {
    "grid", "trend", "rsi_strategy", "bollinger_bands",
    "donchian", "dca", "martingale",
}


def _registry_map() -> dict:
    """kind -> 注册元数据 dict。"""
    return {item["kind"]: item for item in base_strategy_registry.list()}


def test_base_strategy_registry_count():
    """7 个基础策略都注册成功（base_strategy_registry.list() 含 7 项）。"""
    items = base_strategy_registry.list()
    registered_kinds = {item["kind"] for item in items}
    missing = EXPECTED_KINDS - registered_kinds
    assert not missing, f"缺失基础策略: {missing}"
    # 至少 7 项（允许未来扩展，但当前必须有这 7 项）
    assert len(items) >= 7, f"基础策略数量不足: {len(items)} < 7"


def test_base_strategy_all_seven_registered():
    """逐一断言 7 个 kind 均可从注册表取到。"""
    for kind in EXPECTED_KINDS:
        assert base_strategy_registry.exists(kind), f"基础策略未注册: {kind}"
        cls = base_strategy_registry.get(kind)
        assert cls is not None, f"基础策略 get 返回 None: {kind}"


def test_base_strategy_each_has_label():
    """每个策略类含 label 字段（中文名）。"""
    rmap = _registry_map()
    for kind in EXPECTED_KINDS:
        assert kind in rmap, f"{kind} 未出现在 registry.list()"
        cls = base_strategy_registry.get(kind)
        label = getattr(cls, "label", None)
        assert isinstance(label, str) and label, f"{kind} 缺少非空 label 字段"
        # 列表项自身不含 label（registry.list 只回传 category/description/param_schema/
        # output_type/priority），所以这里直接校验类属性。


def test_base_strategy_each_has_category_and_priority():
    """每个策略类含 category="基础策略" 与 priority 字段。"""
    for kind in EXPECTED_KINDS:
        cls = base_strategy_registry.get(kind)
        assert getattr(cls, "category", None) == "基础策略", f"{kind} category 应为 '基础策略'"
        assert getattr(cls, "priority", None) is not None, f"{kind} 缺少 priority"


def test_grid_optional_params():
    """grid 的 order_qty/grid_mode/direction 为可选参数。"""
    cls = base_strategy_registry.get("grid")
    schema = cls.param_schema

    # order_qty 可选 + 默认 0.001
    assert "order_qty" in schema, "grid 缺少 order_qty 参数"
    assert schema["order_qty"].get("required") is False, "grid.order_qty 应为可选"
    assert schema["order_qty"].get("default") == 0.001, "grid.order_qty 默认值应为 0.001"

    # grid_mode 可选 + 含 options/option_labels/default
    assert "grid_mode" in schema, "grid 缺少 grid_mode 参数"
    assert schema["grid_mode"].get("required") is False, "grid.grid_mode 应为可选"
    assert schema["grid_mode"].get("default") == "arithmetic"
    assert schema["grid_mode"].get("options") == ["arithmetic", "geometric"]
    assert schema["grid_mode"].get("option_labels") == ["等差", "等比"]

    # direction 可选 + 含 options/option_labels/default
    assert "direction" in schema, "grid 缺少 direction 参数"
    assert schema["direction"].get("required") is False, "grid.direction 应为可选"
    assert schema["direction"].get("default") == "neutral"
    assert schema["direction"].get("options") == ["long", "short", "neutral"]
    assert schema["direction"].get("option_labels") == ["做多", "做空", "双向"]


def test_grid_constructor_accepts_optional_defaults():
    """grid 实例化时省略可选参数应使用默认值（executor 通过 **params 实例化）。"""
    cls = base_strategy_registry.get("grid")
    # 仅传必填参数
    block = cls(upper_price=50000, lower_price=40000, grid_count=10, symbol="BTC-USDT")
    assert block.order_qty == 0.001
    assert block.grid_mode == "arithmetic"
    assert block.direction == "neutral"
    # 默认 arithmetic 网格为首尾等差
    assert len(block.levels) == 10
    assert abs(block.levels[0] - 40000) < 1e-6
    assert abs(block.levels[-1] - 50000) < 1e-6


def test_grid_geometric_mode():
    """grid 几何模式生成等比网格位。"""
    cls = base_strategy_registry.get("grid")
    block = cls(upper_price=40000, lower_price=10000, grid_count=5,
                symbol="BTC-USDT", grid_mode="geometric")
    # 等比：ratio = (40000/10000)^(1/4) = 4^0.25 = sqrt(2)
    # levels[0]=10000, levels[4]=40000
    assert abs(block.levels[0] - 10000) < 1e-6
    assert abs(block.levels[-1] - 40000) < 1e-6
    # 等比相邻比值应一致
    ratios = [block.levels[i + 1] / block.levels[i] for i in range(4)]
    for r in ratios:
        assert abs(r - ratios[0]) < 1e-6


def test_base_strategy_param_schema_has_label():
    """每个策略的 param_schema 参数含 label。"""
    for kind in EXPECTED_KINDS:
        cls = base_strategy_registry.get(kind)
        schema = getattr(cls, "param_schema", {})
        assert schema, f"{kind} param_schema 为空"
        for name, spec in schema.items():
            label = spec.get("label") if isinstance(spec, dict) else None
            assert isinstance(label, str) and label, (
                f"{kind}.param_schema['{name}'] 缺少非空 label"
            )


def test_base_strategy_select_params_have_options():
    """select 类型参数必须含 options 与 option_labels。"""
    for kind in EXPECTED_KINDS:
        cls = base_strategy_registry.get(kind)
        schema = getattr(cls, "param_schema", {})
        for name, spec in schema.items():
            if not isinstance(spec, dict):
                continue
            if spec.get("type") != "select":
                continue
            assert "options" in spec, f"{kind}.{name} select 缺少 options"
            assert "option_labels" in spec, f"{kind}.{name} select 缺少 option_labels"
            assert len(spec["options"]) == len(spec["option_labels"]), (
                f"{kind}.{name} options 与 option_labels 数量不一致"
            )


def test_base_strategy_hooks_are_async():
    """每个策略类的 on_start/on_tick/on_pause/on_resume/on_stop 为协程函数。"""
    import inspect
    hook_names = ("on_start", "on_tick", "on_pause", "on_resume", "on_stop")
    for kind in EXPECTED_KINDS:
        cls = base_strategy_registry.get(kind)
        for hook in hook_names:
            method = getattr(cls, hook, None)
            assert method is not None, f"{kind} 缺少钩子方法 {hook}"
            assert inspect.iscoroutinefunction(method), (
                f"{kind}.{hook} 应为 async def"
            )


def test_signal_strategies_instantiate_with_required_only():
    """信号型策略仅传必填参数也能实例化（可选参数走默认值）。"""
    # trend: fast_period/slow_period/symbol 必填
    trend = base_strategy_registry.get("trend")(
        fast_period=5, slow_period=20, symbol="BTC-USDT")
    assert trend.direction == "both"

    # rsi_strategy: period/symbol 必填
    rsi = base_strategy_registry.get("rsi_strategy")(
        period=14, symbol="BTC-USDT")
    assert rsi.oversold == 30 and rsi.overbought == 70

    # bollinger_bands: period/symbol 必填
    boll = base_strategy_registry.get("bollinger_bands")(
        period=20, symbol="BTC-USDT")
    assert boll.std_multiplier == 2.0

    # donchian: entry_period/symbol 必填
    don = base_strategy_registry.get("donchian")(
        entry_period=20, symbol="BTC-USDT")
    assert don.exit_period == 10

    # dca: amount/symbol 必填
    dca = base_strategy_registry.get("dca")(
        amount=100, symbol="BTC-USDT")
    assert dca.frequency == "daily"

    # martingale: initial_size/symbol 必填
    mart = base_strategy_registry.get("martingale")(
        initial_size=0.001, symbol="BTC-USDT")
    assert mart.multiplier == 2.0 and mart.max_levels == 5


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
