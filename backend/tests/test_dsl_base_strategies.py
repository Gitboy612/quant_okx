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


# 期望拥有 bar 参数的 4 个信号驱动型策略
SIGNAL_KINDS_WITH_BAR = {"trend", "rsi_strategy", "bollinger_bands", "donchian"}
EXPECTED_BAR_OPTIONS = ["1m", "5m", "15m", "1H", "4H", "1D"]
EXPECTED_BAR_OPTION_LABELS = ["1分钟", "5分钟", "15分钟", "1小时", "4小时", "1天"]


def test_grid_count_schema_is_integer():
    """grid 的 grid_count schema 类型应为 integer（与构造时 int() 一致）。"""
    cls = base_strategy_registry.get("grid")
    schema = cls.param_schema
    assert "grid_count" in schema, "grid 缺少 grid_count 参数"
    assert schema["grid_count"].get("type") == "integer", (
        "grid.grid_count 类型应为 'integer'"
    )


def test_signal_strategies_have_bar_param():
    """trend/rsi/bollinger/donchian 的 param_schema 应含 bar 参数且 schema 字段正确。"""
    for kind in SIGNAL_KINDS_WITH_BAR:
        cls = base_strategy_registry.get(kind)
        schema = cls.param_schema
        assert "bar" in schema, f"{kind} 缺少 bar 参数"
        bar_spec = schema["bar"]
        assert bar_spec.get("type") == "select", f"{kind}.bar type 应为 'select'"
        assert bar_spec.get("label") == "K线周期", f"{kind}.bar label 应为 'K线周期'"
        assert bar_spec.get("options") == EXPECTED_BAR_OPTIONS, f"{kind}.bar options 不匹配"
        assert bar_spec.get("option_labels") == EXPECTED_BAR_OPTION_LABELS, (
            f"{kind}.bar option_labels 不匹配"
        )
        assert bar_spec.get("default") == "1H", f"{kind}.bar default 应为 '1H'"
        assert bar_spec.get("required") is True, f"{kind}.bar required 应为 True"
        assert bar_spec.get("description") == "K线周期", f"{kind}.bar description 应为 'K线周期'"


def test_signal_strategies_bar_default_value():
    """4 个信号型策略省略 bar 实例化时 self.bar 默认 '1H'。"""
    trend = base_strategy_registry.get("trend")(
        fast_period=5, slow_period=20, symbol="BTC-USDT")
    assert trend.bar == "1H"

    rsi = base_strategy_registry.get("rsi_strategy")(
        period=14, symbol="BTC-USDT")
    assert rsi.bar == "1H"

    boll = base_strategy_registry.get("bollinger_bands")(
        period=20, symbol="BTC-USDT")
    assert boll.bar == "1H"

    don = base_strategy_registry.get("donchian")(
        entry_period=20, symbol="BTC-USDT")
    assert don.bar == "1H"


def test_signal_strategies_bar_custom_value():
    """4 个信号型策略传入自定义 bar 时 self.bar 取传入值。"""
    custom_bar = "5m"
    trend = base_strategy_registry.get("trend")(
        fast_period=5, slow_period=20, symbol="BTC-USDT", bar=custom_bar)
    assert trend.bar == custom_bar

    rsi = base_strategy_registry.get("rsi_strategy")(
        period=14, symbol="BTC-USDT", bar=custom_bar)
    assert rsi.bar == custom_bar

    boll = base_strategy_registry.get("bollinger_bands")(
        period=20, symbol="BTC-USDT", bar=custom_bar)
    assert boll.bar == custom_bar

    don = base_strategy_registry.get("donchian")(
        entry_period=20, symbol="BTC-USDT", bar=custom_bar)
    assert don.bar == custom_bar


def test_dca_martingale_have_no_bar_param():
    """dca/martingale 不应含 bar 参数（定投有自己的 frequency）。"""
    dca_schema = base_strategy_registry.get("dca").param_schema
    assert "bar" not in dca_schema, "dca 不应含 bar 参数"

    mart_schema = base_strategy_registry.get("martingale").param_schema
    assert "bar" not in mart_schema, "martingale 不应含 bar 参数"


def test_grid_has_no_bar_param():
    """grid 不应含 bar 参数（网格靠挂单维护，不依赖 K 线）。"""
    grid_schema = base_strategy_registry.get("grid").param_schema
    assert "bar" not in grid_schema, "grid 不应含 bar 参数"


# ============================================================
# Task 4: GridBlock.on_start 去重 + on_resume 增量补挂
# ============================================================

from unittest.mock import AsyncMock, MagicMock
from dsl.context import ExecutionContext


def _mock_batch_place_orders(payload):
    """模拟 OKX batch_place_orders 成功响应：为每个订单返回唯一 ordId。"""
    data = [{"sCode": "0", "ordId": f"oid_{i}_{o['side']}"} for i, o in enumerate(payload)]
    return {"code": "0", "data": data}


def _make_grid_ctx(current_price=45000.0, symbol="BTC-USDT"):
    """构造带 mock client/order_manager 的 ExecutionContext。"""
    client = MagicMock()
    client.batch_place_orders = AsyncMock(side_effect=_mock_batch_place_orders)
    client.place_order = AsyncMock(side_effect=lambda **kw: {
        "code": "0", "data": [{"ordId": f"single_{kw.get('side', 'x')}_{kw.get('px', '0')}"}]
    })
    order_manager = MagicMock()
    order_manager.add_order = AsyncMock()
    strategy = MagicMock()
    strategy._record_event = MagicMock()
    strategy.add_realized_pnl = MagicMock()
    ctx = ExecutionContext(
        client=client,
        order_manager=order_manager,
        strategy=strategy,
        symbol=symbol,
        current_price=current_price,
    )
    return ctx, client, order_manager, strategy


@pytest.mark.asyncio
async def test_grid_on_start_no_duplicate_orders():
    """on_start 被调用 2 次后总挂单数不翻倍（Task 4.3）。

    12 格网格在 current_price=45000 下应挂 5 买单 + 5 卖单 = 10 单。
    第二次调用 on_start 后挂单数应保持 10（已活跃层级被跳过）。
    """
    cls = base_strategy_registry.get("grid")
    block = cls(upper_price=50000, lower_price=40000, grid_count=10,
                symbol="BTC-USDT", order_qty=0.01)
    ctx, client, _, _ = _make_grid_ctx(current_price=45000.0)

    # 第一次 on_start
    await block.on_start(ctx)
    first_total = len(block.active_buy) + len(block.active_sell)
    assert first_total > 0, "第一次 on_start 应挂出订单"

    # 第二次 on_start（模拟 on_resume 误调或自环触发）
    await block.on_start(ctx)
    second_total = len(block.active_buy) + len(block.active_sell)
    assert second_total == first_total, (
        f"第二次 on_start 后挂单数应保持 {first_total}，实际 {second_total}（重复挂单）"
    )


@pytest.mark.asyncio
async def test_grid_on_start_skips_active_levels():
    """on_start 循环跳过已活跃的层级（Task 4.1）。

    预填 active_buy[0] 和 active_sell[9]，调用 on_start 后这些层级
    不被重新挂单（ordId 保持原值）。
    """
    cls = base_strategy_registry.get("grid")
    block = cls(upper_price=50000, lower_price=40000, grid_count=10,
                symbol="BTC-USDT", order_qty=0.01)
    block.active_buy = {0: "existing_buy_0"}
    block.active_sell = {9: "existing_sell_9"}

    ctx, client, _, _ = _make_grid_ctx(current_price=45000.0)
    await block.on_start(ctx)

    # 已活跃层级 ordId 不变
    assert block.active_buy[0] == "existing_buy_0"
    assert block.active_sell[9] == "existing_sell_9"
    # 其他层级被正常挂出
    assert len(block.active_buy) > 1
    assert len(block.active_sell) > 1


@pytest.mark.asyncio
async def test_grid_on_resume_only_places_missing():
    """on_resume 只补挂缺失层级，不重复挂已活跃层级（Task 4.2）。

    预填部分 active_buy/active_sell，调用 on_resume 后：
    - 已活跃层级 ordId 不变
    - 缺失层级被补挂
    - 总挂单数等于预期网格数
    """
    cls = base_strategy_registry.get("grid")
    block = cls(upper_price=50000, lower_price=40000, grid_count=10,
                symbol="BTC-USDT", order_qty=0.01)
    # 预填 level 0 买单 和 level 9 卖单
    block.active_buy = {0: "existing_buy_0"}
    block.active_sell = {9: "existing_sell_9"}

    ctx, client, _, _ = _make_grid_ctx(current_price=45000.0)
    await block.on_resume(ctx)

    # 已活跃层级不变
    assert block.active_buy[0] == "existing_buy_0"
    assert block.active_sell[9] == "existing_sell_9"
    # 缺失层级被补挂（levels 1-4 买单，levels 5-8 卖单）
    for i in range(1, 5):
        assert i in block.active_buy, f"level {i} 买单应被补挂"
    for i in range(5, 9):
        assert i in block.active_sell, f"level {i} 卖单应被补挂"
    # _started 不被重置（on_resume 不调 on_start）
    assert block._started is False  # on_resume 不会设置 _started


@pytest.mark.asyncio
async def test_grid_on_resume_does_not_call_on_start():
    """on_resume 不再调 self.on_start()（Task 4.2）。

    验证：on_resume 后 _started 保持原值（True），说明没有走 on_start 路径。
    """
    cls = base_strategy_registry.get("grid")
    block = cls(upper_price=50000, lower_price=40000, grid_count=10,
                symbol="BTC-USDT", order_qty=0.01)
    block._started = True  # 模拟已启动

    ctx, client, _, _ = _make_grid_ctx(current_price=45000.0)
    await block.on_resume(ctx)

    # _started 保持 True（on_resume 不重置）
    assert block._started is True


# ============================================================
# Task 5: on_order_filled 反向挂单 + grid_idx 匹配容差
# ============================================================


@pytest.mark.asyncio
async def test_grid_on_order_filled_buy_places_sell():
    """买单成交触发 on_order_filled 挂反向卖单（Task 5.4）。

    模拟 level 3 的买单成交，验证：
    - active_buy[3] 被移除
    - active_sell[4] 被新增（反向卖单挂在 level 4）
    - client.place_order 被调用，side="sell"
    """
    cls = base_strategy_registry.get("grid")
    block = cls(upper_price=50000, lower_price=40000, grid_count=10,
                symbol="BTC-USDT", order_qty=0.01)
    block.active_buy = {3: "buy_oid_3"}

    # 构造成交订单（买单，价格 = level 3 的四舍五入价）
    filled_px = block._price_str(block.levels[3])
    order_info = MagicMock()
    order_info.side = "buy"
    order_info.px = filled_px
    order_info.sz = "0.01"
    order_info.ordId = "buy_oid_3"

    ctx, client, order_manager, strategy = _make_grid_ctx(current_price=45000.0)

    await block.on_order_filled(order_info, ctx)

    #买单已从 active_buy 移除
    assert 3 not in block.active_buy
    # 反向卖单挂在 level 4
    assert 4 in block.active_sell
    # client.place_order 被调用，side="sell"
    client.place_order.assert_awaited_once()
    call_kwargs = client.place_order.call_args.kwargs
    assert call_kwargs["side"] == "sell"
    assert call_kwargs["inst_id"] == "BTC-USDT"
    assert call_kwargs["ord_type"] == "limit"


@pytest.mark.asyncio
async def test_grid_on_order_filled_sell_places_buy():
    """卖单成交触发 on_order_filled 挂反向买单（Task 5.4）。

    模拟 level 7 的卖单成交，验证：
    - active_sell[7] 被移除
    - active_buy[6] 被新增（反向买单挂在 level 6）
    - client.place_order 被调用，side="buy"
    - strategy.add_realized_pnl 被调用（记录 cycle_pnl）
    """
    cls = base_strategy_registry.get("grid")
    block = cls(upper_price=50000, lower_price=40000, grid_count=10,
                symbol="BTC-USDT", order_qty=0.01)
    block.active_sell = {7: "sell_oid_7"}

    filled_px = block._price_str(block.levels[7])
    order_info = MagicMock()
    order_info.side = "sell"
    order_info.px = filled_px
    order_info.sz = "0.01"
    order_info.ordId = "sell_oid_7"

    ctx, client, order_manager, strategy = _make_grid_ctx(current_price=45000.0)

    await block.on_order_filled(order_info, ctx)

    # 卖单已从 active_sell 移除
    assert 7 not in block.active_sell
    # 反向买单挂在 level 6
    assert 6 in block.active_buy
    # client.place_order 被调用，side="buy"
    client.place_order.assert_awaited_once()
    call_kwargs = client.place_order.call_args.kwargs
    assert call_kwargs["side"] == "buy"
    # cycle_pnl 被记录
    strategy.add_realized_pnl.assert_called_once()


@pytest.mark.asyncio
async def test_grid_on_order_filled_nearest_fallback():
    """无精确匹配时回退到最近层级（Task 5.3）。

    成交价偏离所有 level 超过 tick_size * 0.5 容差时，
    应回退到 abs(price - level_price) 最小的 level。
    """
    cls = base_strategy_registry.get("grid")
    block = cls(upper_price=50000, lower_price=40000, grid_count=10,
                symbol="BTC-USDT", order_qty=0.01)
    block.active_buy = {3: "buy_oid_3"}

    # 构造一个偏离 level 3 超过 0.5*tick_size 但仍最接近 level 3 的价格
    level3_price = block._round_price(block.levels[3])
    # 偏离 0.8 * tick_size（超过 0.5 容差，但 level 3 仍是最接近的）
    off_price = level3_price + block.tick_size * 0.8

    order_info = MagicMock()
    order_info.side = "buy"
    order_info.px = str(off_price)
    order_info.sz = "0.01"
    order_info.ordId = "buy_oid_3"

    ctx, client, order_manager, strategy = _make_grid_ctx(current_price=45000.0)

    # 应回退到最近层级（level 3）而非 return
    await block.on_order_filled(order_info, ctx)

    # 买单已从 active_buy 移除（说明 on_order_filled 正常执行而非 return）
    assert 3 not in block.active_buy
    # 反向卖单挂在 level 4（level 3 + 1）
    assert 4 in block.active_sell
    client.place_order.assert_awaited_once()


@pytest.mark.asyncio
async def test_grid_on_order_filled_tolerance_half_tick():
    """grid_idx 匹配容差为 tick_size * 0.5（Task 5.2）。

    偏离 0.4 * tick_size（< 0.5 容差）应精确匹配；
    偏离 0.6 * tick_size（> 0.5 容差）应走最近层级回退。
    """
    cls = base_strategy_registry.get("grid")
    block = cls(upper_price=50000, lower_price=40000, grid_count=10,
                symbol="BTC-USDT", order_qty=0.01)
    block.active_buy = {3: "buy_oid_3"}

    level3_price = block._round_price(block.levels[3])

    # 偏离 0.4 * tick_size → 精确匹配 level 3
    within_px = level3_price + block.tick_size * 0.4
    order_info = MagicMock()
    order_info.side = "buy"
    order_info.px = str(within_px)
    order_info.sz = "0.01"
    order_info.ordId = "buy_oid_3"

    ctx, client, _, _ = _make_grid_ctx(current_price=45000.0)
    await block.on_order_filled(order_info, ctx)

    # 精确匹配 level 3 → 反向卖单挂在 level 4
    assert 4 in block.active_sell
    # 重置状态测试超出容差的情况
    block.active_buy = {3: "buy_oid_3b"}
    block.active_sell.clear()
    client.place_order.reset_mock()

    # 偏离 0.6 * tick_size → 超出 0.5 容差，走最近层级回退
    beyond_px = level3_price + block.tick_size * 0.6
    order_info2 = MagicMock()
    order_info2.side = "buy"
    order_info2.px = str(beyond_px)
    order_info2.sz = "0.01"
    order_info2.ordId = "buy_oid_3b"

    await block.on_order_filled(order_info2, ctx)
    # 最近层级仍为 level 3 → 反向卖单挂在 level 4
    assert 4 in block.active_sell


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
