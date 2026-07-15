"""突发行情快速响应单元测试（Task 8）。

覆盖：
- market_data_service.get_volatility：空数据返回 0；窗口内计算正确；超窗数据淘汰
- grid 波动检测：vol > 阈值触发 volatility_spike 事件、设置 _volatility_spike_until
- 主循环 sleep 动态：spike 期间用 0.5s，否则用 1.0s
- _rapid_realign_grid：撤单+重挂调用（Mock cancel_all/batch_place_orders）
- 快速重挂期间 _on_order_filled 被抑制

参考 test_grid_responsiveness.py 风格，用 Mock client + Mock db_session_factory。
"""
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from strategies.grid_strategy import GridStrategy
from services.market_data_service import market_data_service
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
        mock_client.batch_place_orders = AsyncMock(
            return_value={"code": "0", "data": [{"sCode": "0", "ordId": "o1"}]}
        )
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
    order_manager.cancel_all = AsyncMock(return_value=2)

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
    # SubTask 8.2: spike 状态
    strategy._volatility_spike_until = 0.0
    strategy._spike_active = False
    strategy._suppress_fill_callback = False


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


@pytest.fixture(autouse=True)
def _reset_market_data_history():
    """每个测试前后清空 market_data_service 价格历史，避免单例污染。"""
    market_data_service._price_history.clear()
    yield
    market_data_service._price_history.clear()


# ============================================================
# market_data_service.get_volatility 测试（SubTask 8.1）
# ============================================================


def test_get_volatility_empty_returns_zero():
    """无价格历史返回 0.0。"""
    assert market_data_service.get_volatility("BTC-USDT") == 0.0


def test_get_volatility_single_point_returns_zero():
    """仅一个价格点（不足 2 个）返回 0.0。"""
    market_data_service.update_price("BTC-USDT", 100.0)
    assert market_data_service.get_volatility("BTC-USDT") == 0.0


def test_get_volatility_calc_correct():
    """窗口内 (max - min) / mean 计算正确。"""
    prices = [100.0, 102.0, 98.0]
    for p in prices:
        market_data_service.update_price("BTC-USDT", p)
    vol = market_data_service.get_volatility("BTC-USDT", window_seconds=5.0)
    expected = (max(prices) - min(prices)) / (sum(prices) / len(prices))
    assert abs(vol - expected) < 1e-9


def test_get_volatility_window_expiry():
    """超窗数据被淘汰：全部数据超窗时返回 0.0。"""
    with patch("services.market_data_service.time.time") as mock_time:
        mock_time.return_value = 0.0
        market_data_service.update_price("BTC-USDT", 100.0)
        mock_time.return_value = 0.5
        market_data_service.update_price("BTC-USDT", 110.0)
        # t=10，窗口 5s，cutoff=5，两个旧点都被淘汰
        mock_time.return_value = 10.0
        vol = market_data_service.get_volatility("BTC-USDT", window_seconds=5.0)
        assert vol == 0.0


def test_get_volatility_partial_window():
    """部分数据超窗：仅窗口内数据参与计算。"""
    with patch("services.market_data_service.time.time") as mock_time:
        mock_time.return_value = 0.0
        market_data_service.update_price("BTC-USDT", 100.0)  # 会被淘汰
        mock_time.return_value = 8.0
        market_data_service.update_price("BTC-USDT", 104.0)
        mock_time.return_value = 9.0
        market_data_service.update_price("BTC-USDT", 106.0)
        mock_time.return_value = 10.0
        vol = market_data_service.get_volatility("BTC-USDT", window_seconds=5.0)
        # 窗口内价格 [104, 106]，cutoff=5，t=0 点淘汰
        expected = (106.0 - 104.0) / 105.0
        assert abs(vol - expected) < 1e-9


def test_get_latest_volatility():
    """get_latest_volatility 便捷接口使用默认窗口。"""
    market_data_service.update_price("BTC-USDT", 100.0)
    market_data_service.update_price("BTC-USDT", 102.0)
    vol = market_data_service.get_latest_volatility("BTC-USDT")
    expected = (102.0 - 100.0) / 101.0
    assert abs(vol - expected) < 1e-9


def test_update_price_via_ticker_callback():
    """_on_ticker_data 收到 last 时自动追加到价格历史。"""
    market_data_service._on_ticker_data({"instId": "BTC-USDT", "last": "100"})
    market_data_service._on_ticker_data({"instId": "BTC-USDT", "last": "102"})
    vol = market_data_service.get_latest_volatility("BTC-USDT")
    expected = (102.0 - 100.0) / 101.0
    assert abs(vol - expected) < 1e-9


# ============================================================
# grid 波动检测测试（SubTask 8.2 / 8.3）
# ============================================================


async def test_volatility_spike_records_event_and_sets_until():
    """vol > 阈值首次触发：记录 volatility_spike 事件并设置 _volatility_spike_until。"""
    params = {**_base_params(), "volatility_threshold": 0.005, "spike_duration": 10.0}
    strategy, client, om, _ = _make_strategy(params)
    _setup_grid_state(strategy)
    strategy._record_event = MagicMock()
    client.batch_place_orders = AsyncMock(side_effect=[
        {"code": "0", "data": [{"sCode": "0", "ordId": "nb1"}]},
        {"code": "0", "data": [{"sCode": "0", "ordId": "ns1"}]},
    ])

    with patch("strategies.grid_strategy.market_data_service") as mock_mds:
        mock_mds.get_volatility = MagicMock(return_value=0.02)
        await strategy._check_volatility_spike("BTC-USDT", 100.0)

    event_types = [call.args[0] for call in strategy._record_event.call_args_list]
    assert "volatility_spike" in event_types
    assert "grid_realigned" in event_types
    assert strategy._spike_active is True
    assert strategy._volatility_spike_until > 0


async def test_volatility_spike_no_duplicate_realign():
    """spike 持续中不重复触发 _rapid_realign_grid（避免重复撤单重挂）。"""
    params = {**_base_params(), "volatility_threshold": 0.005, "spike_duration": 10.0}
    strategy, client, om, _ = _make_strategy(params)
    _setup_grid_state(strategy)
    strategy._record_event = MagicMock()
    client.batch_place_orders = AsyncMock(
        return_value={"code": "0", "data": [{"sCode": "0", "ordId": "x"}]}
    )

    with patch("strategies.grid_strategy.market_data_service") as mock_mds:
        mock_mds.get_volatility = MagicMock(return_value=0.02)
        await strategy._check_volatility_spike("BTC-USDT", 100.0)  # 首次触发
        await strategy._check_volatility_spike("BTC-USDT", 100.0)  # 持续中

    # cancel_all 只被调用一次（首次触发）
    om.cancel_all.assert_awaited_once_with("BTC-USDT")
    # volatility_spike 事件只记录一次
    spike_calls = [c for c in strategy._record_event.call_args_list if c.args[0] == "volatility_spike"]
    assert len(spike_calls) == 1


async def test_volatility_spike_resets_when_low():
    """波动率回落且 spike 窗口已过：重置 _spike_active，允许下次重新触发。"""
    params = {**_base_params(), "volatility_threshold": 0.005, "spike_duration": 1.0}
    strategy, client, om, _ = _make_strategy(params)
    _setup_grid_state(strategy)
    strategy._record_event = MagicMock()
    client.batch_place_orders = AsyncMock(
        return_value={"code": "0", "data": [{"sCode": "0", "ordId": "x"}]}
    )

    with patch("strategies.grid_strategy.market_data_service") as mock_mds, \
         patch("strategies.grid_strategy.time.time") as mock_time:
        # t=0: 触发 spike，spike_until = 0 + 1 = 1
        mock_time.return_value = 0.0
        mock_mds.get_volatility = MagicMock(return_value=0.02)
        await strategy._check_volatility_spike("BTC-USDT", 100.0)
        assert strategy._spike_active is True

        # t=2: vol 回落，spike_until=1 已过 → 重置
        mock_time.return_value = 2.0
        mock_mds.get_volatility = MagicMock(return_value=0.001)
        await strategy._check_volatility_spike("BTC-USDT", 100.0)
        assert strategy._spike_active is False


# ============================================================
# 主循环 sleep 动态测试（SubTask 8.2）
# ============================================================


async def test_loop_sleep_normal_uses_default_interval():
    """非 spike 期间主循环 sleep 1.0s。"""
    strategy, client, om, _ = _make_strategy(_base_params())
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

    assert 1.0 in sleep_args


async def test_loop_sleep_spike_uses_short_interval():
    """spike 期间主循环 sleep 0.5s。

    通过 mock get_volatility 返回超阈值波动率，让 _check_volatility_spike
    在主循环内自然触发 spike（execute 初始化会重置 spike 状态，故不能预设）。
    """
    params = {**_base_params(), "spike_loop_interval": 0.5, "volatility_threshold": 0.005}
    strategy, client, om, _ = _make_strategy(params)
    sleep_args = []
    strategy._running = True

    async def mock_sleep(delay=1, result=None):
        sleep_args.append(delay)
        # 仅在主循环尾部 sleep(0.5) 时停止（init 阶段的 0.15 不停止）
        if strategy._running and abs(delay - 0.5) < 1e-9:
            strategy._running = False

    with patch("strategies.grid_strategy.market_data_service") as mock_mds, \
         patch("strategies.grid_strategy.asyncio.sleep", mock_sleep), \
         patch("strategies.grid_strategy.time.time", lambda: 1.0), \
         patch("services.strategy_engine.strategy_engine") as mock_engine:
        mock_mds.subscribe_ticker = AsyncMock()
        mock_mds.unsubscribe_ticker = AsyncMock()
        mock_mds.get_latest_ticker = MagicMock(return_value={"last": "100"})
        # 返回超阈值的波动率，触发 spike 快速路径
        mock_mds.get_volatility = MagicMock(return_value=0.02)
        mock_engine.get_shared_balance = AsyncMock(return_value={})
        await strategy.execute()

    assert 0.5 in sleep_args


# ============================================================
# _rapid_realign_grid 测试（SubTask 8.3）
# ============================================================


async def test_rapid_realign_grid_cancels_and_replaces():
    """_rapid_realign_grid 撤销所有订单并批量重挂。"""
    strategy, client, om, _ = _make_strategy(_base_params())
    _setup_grid_state(strategy)
    # 预设活跃订单
    strategy._active_buy_orders = {0: "b1"}
    strategy._active_sell_orders = {2: "s1"}
    client.batch_place_orders = AsyncMock(side_effect=[
        {"code": "0", "data": [{"sCode": "0", "ordId": "nb1"}]},  # buy batch
        {"code": "0", "data": [{"sCode": "0", "ordId": "ns1"}]},  # sell batch
    ])

    await strategy._rapid_realign_grid("BTC-USDT", 100.0)

    om.cancel_all.assert_awaited_once_with("BTC-USDT")
    # level 90 < 100 → buy idx 0；level 110 > 100 → sell idx 2
    assert strategy._active_buy_orders == {0: "nb1"}
    assert strategy._active_sell_orders == {2: "ns1"}
    client.batch_place_orders.assert_awaited()


async def test_rapid_realign_grid_releases_suppress_flag():
    """快速重挂后释放 _suppress_fill_callback 标志。"""
    strategy, client, om, _ = _make_strategy(_base_params())
    _setup_grid_state(strategy)
    client.batch_place_orders = AsyncMock(
        return_value={"code": "0", "data": [{"sCode": "0", "ordId": "x"}]}
    )

    await strategy._rapid_realign_grid("BTC-USDT", 100.0)

    assert strategy._suppress_fill_callback is False


async def test_on_order_filled_suppressed_during_realign():
    """快速重挂期间 _on_order_filled 被抑制，不触发补单。"""
    strategy, client, om, _ = _make_strategy(_base_params())
    _setup_grid_state(strategy)
    strategy._suppress_fill_callback = True
    client.batch_place_orders = AsyncMock()
    order_info = OrderInfo(ordId="x", symbol="BTC-USDT", side="buy", px="90", sz="1", state="filled")

    await strategy._on_order_filled(order_info)

    client.batch_place_orders.assert_not_awaited()


# ============================================================
# _place_grid_orders 提取验证（SubTask 8.3）
# ============================================================


async def test_place_grid_orders_buy_and_sell_split():
    """_place_grid_orders 按 current_price 正确划分买卖单。"""
    strategy, client, om, _ = _make_strategy(_base_params())
    _setup_grid_state(strategy)
    client.batch_place_orders = AsyncMock(side_effect=[
        {"code": "0", "data": [{"sCode": "0", "ordId": "b0"}]},
        {"code": "0", "data": [{"sCode": "0", "ordId": "s2"}]},
    ])

    await strategy._place_grid_orders("BTC-USDT", 100.0)

    # grid_levels=[90, 100, 110]，current_price=100
    # level 90 < 100 → buy idx 0；level 100 == 100 跳过；level 110 > 100 → sell idx 2
    assert strategy._active_buy_orders == {0: "b0"}
    assert strategy._active_sell_orders == {2: "s2"}
    assert client.batch_place_orders.await_count == 2
