"""网格策略成交→补单响应性重构单元测试（Task 7）。

覆盖：
- get_latency_stats：空样本返回 0；有样本计算 P50/P95
- 主循环间隔可配（默认 1.0、自定义值）
- REST 兜底间隔可配（默认 5s、自定义跳过/触发）
- 延迟超阈值记录 order_latency 事件
- _on_order_filled 买单分支使用 batch_place_orders

参考 test_margin_monitor.py 风格，用 Mock client + Mock db_session_factory。
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from strategies.grid_strategy import GridStrategy
from services.order_manager import OrderInfo


# ============================================================
# 辅助构造
# ============================================================


def _base_params() -> dict:
    """网格策略最小参数集。"""
    return {
        "symbol": "BTC-USDT",
        "upper_price": 110.0,
        "lower_price": 90.0,
        "grid_count": 3,
        "order_qty": 1.0,
    }


def _make_strategy(params: dict, client=None):
    """构造 GridStrategy 实例（不运行 execute）。

    返回 (strategy, mock_client, mock_order_manager, mock_db)。
    """
    db = MagicMock()
    db_session_factory = MagicMock(return_value=db)
    db.query.return_value.filter.return_value.order_by.return_value.first.return_value = None
    db.query.return_value.filter.return_value.all.return_value = []

    mock_client = client or AsyncMock()
    if client is None:
        mock_client.get_ticker = AsyncMock(return_value=[{"last": "100"}])
        mock_client.batch_place_orders = AsyncMock(return_value={"code": "0", "data": [{"sCode": "0", "ordId": "sell1"}]})
        mock_client.cancel_order = AsyncMock(return_value={"code": "0"})
        mock_client.get_order = AsyncMock(return_value=[{"state": "live"}])

    order_manager = MagicMock()
    order_manager.get_active_orders = MagicMock(return_value=[])
    order_manager.load_from_db = MagicMock(return_value=0)
    order_manager.on = MagicMock()
    order_manager.get_order_fill_px = MagicMock(return_value=0.0)
    order_manager.get_order_fee = MagicMock(return_value=0.0)
    order_manager.update_order = MagicMock()
    order_manager.add_order = AsyncMock()

    strategy = GridStrategy(
        instance_id=1,
        params=params,
        client=mock_client,
        db_session_factory=db_session_factory,
        account_id=1,
        order_manager=order_manager,
        ws_client=None,
    )
    return strategy, mock_client, order_manager, db


def _setup_grid_state(strategy):
    """手动设置 execute() 中会设置的网格实例变量，便于直接测试回调。"""
    strategy._grid_levels = [90.0, 100.0, 110.0]
    strategy._grid_step = 10.0
    strategy._grid_tick_size = 0.01
    strategy._grid_tick_decimals = 2
    strategy._grid_order_qty = 1.0
    strategy._grid_symbol = "BTC-USDT"
    strategy._active_buy_orders = {}
    strategy._active_sell_orders = {}
    strategy._latency_samples = []


@pytest.fixture(autouse=True)
def _stub_notification():
    """禁用真实通知，避免测试副作用。"""
    with patch("services.notification_service.notification_service") as mock_ns:
        mock_ns.notify = AsyncMock(return_value=0)
        yield


@pytest.fixture(autouse=True)
def _clear_instrument_cache():
    """每个测试前后清空 instrument 缓存，避免相互污染。"""
    from services.instrument_cache import instrument_cache
    instrument_cache.clear_cache()
    yield
    instrument_cache.clear_cache()


# ============================================================
# get_latency_stats 测试（SubTask 7.5）
# ============================================================


def test_get_latency_stats_empty():
    """空样本返回全 0。"""
    strategy, _, _, _ = _make_strategy(_base_params())
    # _latency_samples 未初始化（execute 未运行）
    stats = strategy.get_latency_stats()
    assert stats == {"p50": 0.0, "p95": 0.0, "count": 0}

    # 显式空列表也返回全 0
    strategy._latency_samples = []
    stats = strategy.get_latency_stats()
    assert stats == {"p50": 0.0, "p95": 0.0, "count": 0}


def test_get_latency_stats_with_samples():
    """有样本计算 P50/P95。"""
    strategy, _, _, _ = _make_strategy(_base_params())
    strategy._latency_samples = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
    stats = strategy.get_latency_stats()
    assert stats["count"] == 10
    # P50 = sorted[int(10*0.5)] = sorted[5] = 6.0
    assert stats["p50"] == 6.0
    # P95 = sorted[int(10*0.95)] = sorted[9] = 10.0
    assert stats["p95"] == 10.0


def test_get_latency_stats_single_sample():
    """单样本：P50 = P95 = 该样本。"""
    strategy, _, _, _ = _make_strategy(_base_params())
    strategy._latency_samples = [0.5]
    stats = strategy.get_latency_stats()
    assert stats["count"] == 1
    assert stats["p50"] == 0.5
    assert stats["p95"] == 0.5


# ============================================================
# _on_order_filled 买单分支测试（SubTask 7.1 / 7.5）
# ============================================================


async def test_on_order_filled_buy_uses_batch_place_orders():
    """买单成交后使用 batch_place_orders 下卖单。"""
    strategy, client, om, _ = _make_strategy(_base_params())
    _setup_grid_state(strategy)
    # 成交价 90.0 对应 grid_idx=0，卖单价 = 90 + 10 = 100.0
    order_info = OrderInfo(ordId="buy123", symbol="BTC-USDT", side="buy", px="90", sz="1", state="filled")

    await strategy._on_order_filled(order_info)

    client.batch_place_orders.assert_awaited_once()
    payloads = client.batch_place_orders.call_args.args[0]
    assert len(payloads) == 1
    assert payloads[0]["side"] == "sell"
    assert payloads[0]["instId"] == "BTC-USDT"
    assert payloads[0]["ordType"] == "limit"


async def test_on_order_filled_buy_records_latency():
    """买单成交后记录补单延迟到 _latency_samples。"""
    strategy, client, om, _ = _make_strategy(_base_params())
    _setup_grid_state(strategy)
    order_info = OrderInfo(ordId="buy123", symbol="BTC-USDT", side="buy", px="90", sz="1", state="filled")

    await strategy._on_order_filled(order_info)

    assert len(strategy._latency_samples) == 1
    assert strategy._latency_samples[0] >= 0.0


async def test_on_order_filled_buy_latency_exceeds_threshold():
    """补单延迟超阈值时记录 order_latency 事件。"""
    params = {**_base_params(), "latency_threshold": 0.0}  # 阈值 0，任何延迟都触发
    strategy, client, om, _ = _make_strategy(params)
    _setup_grid_state(strategy)
    strategy._record_event = MagicMock()
    order_info = OrderInfo(ordId="buy123", symbol="BTC-USDT", side="buy", px="90", sz="1", state="filled")

    await strategy._on_order_filled(order_info)

    event_types = [call.args[0] for call in strategy._record_event.call_args_list]
    assert "order_latency" in event_types
    latency_call = next(c for c in strategy._record_event.call_args_list if c.args[0] == "order_latency")
    details = latency_call.args[2] if len(latency_call.args) > 2 else latency_call.kwargs.get("details")
    assert "latency" in details
    assert details["buy_ord_id"] == "buy123"


async def test_on_order_filled_buy_latency_below_threshold_no_event():
    """补单延迟未超阈值时不记录 order_latency 事件。"""
    params = {**_base_params(), "latency_threshold": 999.0}  # 极大阈值
    strategy, client, om, _ = _make_strategy(params)
    _setup_grid_state(strategy)
    strategy._record_event = MagicMock()
    order_info = OrderInfo(ordId="buy123", symbol="BTC-USDT", side="buy", px="90", sz="1", state="filled")

    await strategy._on_order_filled(order_info)

    event_types = [call.args[0] for call in strategy._record_event.call_args_list]
    assert "order_latency" not in event_types


async def test_on_order_filled_buy_exception_no_latency_recorded():
    """batch_place_orders 异常时不记录延迟（下单未完成）。"""
    strategy, client, om, _ = _make_strategy(_base_params())
    _setup_grid_state(strategy)
    client.batch_place_orders = AsyncMock(side_effect=RuntimeError("network error"))
    strategy._record_event = MagicMock()
    order_info = OrderInfo(ordId="buy123", symbol="BTC-USDT", side="buy", px="90", sz="1", state="filled")

    await strategy._on_order_filled(order_info)

    assert len(strategy._latency_samples) == 0
    event_types = [call.args[0] for call in strategy._record_event.call_args_list]
    assert "order_failed" in event_types


# ============================================================
# OrderManager.get_order_latency 测试（SubTask 7.4）
# ============================================================


async def test_order_manager_get_order_latency():
    """OrderManager 记录下单/成交时间戳并计算延迟。"""
    from services.order_manager import OrderManager
    from services.instrument_cache import instrument_cache

    # Mock instrument_cache.get_instrument
    instrument_cache._cache["BTC-USDT"] = {"ctVal": 1.0, "ctType": None, "settleCcy": "USDT"}
    db_session_factory = MagicMock(return_value=MagicMock())
    client = AsyncMock()
    om = OrderManager(db_session_factory, client, strategy_instance_id=1, account_id=1)

    # add_order 记录 place_ts
    await om.add_order(ordId="ord1", clOrdId="", symbol="BTC-USDT", side="buy", px="100", sz="1", state="live")
    assert "ord1" in om._place_ts_map

    # 成交前 latency 为 None
    assert om.get_order_latency("ord1") is None

    # update_order 到 filled 记录 fill_ts
    om.update_order("ord1", state="filled", fillPx="100", fillSz="1", fee="0.1")
    latency = om.get_order_latency("ord1")
    assert latency is not None
    assert latency >= 0.0


def test_order_manager_get_order_latency_unknown_order():
    """未知订单返回 None。"""
    from services.order_manager import OrderManager
    db_session_factory = MagicMock(return_value=MagicMock())
    client = AsyncMock()
    om = OrderManager(db_session_factory, client, strategy_instance_id=1, account_id=1)
    assert om.get_order_latency("nonexistent") is None


# ============================================================
# 主循环间隔可配测试（SubTask 7.2）
# ============================================================


async def _run_execute_one_loop(strategy, expected_interval):
    """运行 execute() 直到主循环 sleep(expected_interval) 被调用。

    patch asyncio.sleep：记录参数，遇到 expected_interval 时停止循环。
    """
    sleep_args = []
    strategy._running = True  # execute() 依赖 _running 进入主循环

    async def mock_sleep(delay=1, result=None):
        sleep_args.append(delay)
        # 主循环 sleep 命中时停止
        if strategy._running and abs(delay - expected_interval) < 1e-9:
            strategy._running = False
        # 不实际 sleep

    with patch("strategies.grid_strategy.market_data_service") as mock_mds, \
         patch("strategies.grid_strategy.asyncio.sleep", mock_sleep), \
         patch("services.strategy_engine.strategy_engine") as mock_engine:
        mock_mds.subscribe_ticker = AsyncMock()
        mock_mds.unsubscribe_ticker = AsyncMock()
        mock_mds.get_latest_ticker = MagicMock(return_value={"last": "100"})
        mock_mds.get_volatility = MagicMock(return_value=0.0)
        mock_engine.get_shared_balance = AsyncMock(return_value={})
        await strategy.execute()

    return sleep_args


async def test_loop_interval_default():
    """主循环默认间隔 1.0s（从 3 降至 1）。"""
    strategy, client, om, _ = _make_strategy(_base_params())
    sleep_args = await _run_execute_one_loop(strategy, 1.0)
    assert 1.0 in sleep_args


async def test_loop_interval_custom():
    """主循环自定义间隔 0.5s 生效。"""
    params = {**_base_params(), "loop_interval": 0.5}
    strategy, client, om, _ = _make_strategy(params)
    sleep_args = await _run_execute_one_loop(strategy, 0.5)
    assert 0.5 in sleep_args


# ============================================================
# REST 兜底间隔可配测试（SubTask 7.3）
# ============================================================


async def test_rest_poll_interval_skips_when_short():
    """rest_poll_interval=100：时间差不足时跳过 REST 兜底（get_order 不被调用）。"""
    params = {**_base_params(), "rest_poll_interval": 100.0}
    strategy, client, om, _ = _make_strategy(params)
    client.get_order = AsyncMock(return_value=[{"state": "live"}])
    om.get_active_orders = MagicMock(return_value=[])

    sleep_args = []
    strategy._running = True

    async def mock_sleep(delay=1, result=None):
        sleep_args.append(delay)
        if strategy._running and abs(delay - 1.0) < 1e-9:
            strategy._running = False

    # time.time() 返回固定小值，使 now - last_rest_check(0.0) = 1.0 < 100
    with patch("strategies.grid_strategy.market_data_service") as mock_mds, \
         patch("strategies.grid_strategy.asyncio.sleep", mock_sleep), \
         patch("strategies.grid_strategy.time.time", lambda: 1.0), \
         patch("services.strategy_engine.strategy_engine") as mock_engine:
        mock_mds.subscribe_ticker = AsyncMock()
        mock_mds.unsubscribe_ticker = AsyncMock()
        mock_mds.get_latest_ticker = MagicMock(return_value={"last": "100"})
        mock_mds.get_volatility = MagicMock(return_value=0.0)
        mock_engine.get_shared_balance = AsyncMock(return_value={})
        await strategy.execute()

    # REST 兜底未触发（因 1.0 < 100）
    client.get_order.assert_not_awaited()


async def test_rest_poll_interval_triggers_when_elapsed():
    """rest_poll_interval=0：时间差始终满足，触发 REST 兜底（get_order 被调用）。"""
    from services.order_manager import OrderInfo as OI
    params = {**_base_params(), "rest_poll_interval": 0.0}
    strategy, client, om, _ = _make_strategy(params)
    client.get_order = AsyncMock(return_value=[{"state": "live"}])
    # sync_orders 阶段返回空（避免 init 阶段调用 get_order），
    # while 循环 REST 兜底阶段返回活跃订单
    active = OI(ordId="act1", symbol="BTC-USDT", side="buy", px="90", sz="1", state="live")
    call_count = [0]

    def _ga_side_effect():
        call_count[0] += 1
        return [] if call_count[0] == 1 else [active]

    om.get_active_orders = MagicMock(side_effect=_ga_side_effect)

    sleep_args = []
    strategy._running = True

    async def mock_sleep(delay=1, result=None):
        sleep_args.append(delay)
        if strategy._running and abs(delay - 1.0) < 1e-9:
            strategy._running = False

    with patch("strategies.grid_strategy.market_data_service") as mock_mds, \
         patch("strategies.grid_strategy.asyncio.sleep", mock_sleep), \
         patch("strategies.grid_strategy.time.time", lambda: 1.0), \
         patch("services.strategy_engine.strategy_engine") as mock_engine:
        mock_mds.subscribe_ticker = AsyncMock()
        mock_mds.unsubscribe_ticker = AsyncMock()
        mock_mds.get_latest_ticker = MagicMock(return_value={"last": "100"})
        mock_mds.get_volatility = MagicMock(return_value=0.0)
        mock_engine.get_shared_balance = AsyncMock(return_value={})
        await strategy.execute()

    # REST 兜底触发（1.0 - 0.0 > 0.0）
    client.get_order.assert_awaited()
