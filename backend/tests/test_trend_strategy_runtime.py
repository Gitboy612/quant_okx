import pytest
from unittest.mock import AsyncMock, MagicMock

from services.okx_client import OKXClient
from services.order_manager import OrderManager
from strategies.grid_strategy import GridStrategy
from strategies.trend_strategy import TrendStrategy


def _strategy(params: dict) -> TrendStrategy:
    strategy = TrendStrategy.__new__(TrendStrategy)
    strategy.params = params
    return strategy


@pytest.mark.asyncio
async def test_validate_params_accepts_high_frequency_runtime_options():
    strategy = _strategy({
        "fast_ma_period": 2,
        "slow_ma_period": 5,
        "order_qty": 0.01,
        "symbol": "BTC-USDT-SWAP",
        "bar": "1m",
        "poll_interval": 15,
        "enter_on_start": True,
        "closed_candle_only": True,
        "long_only": True,
    })

    assert await strategy.validate_params() is True


@pytest.mark.asyncio
async def test_validate_params_rejects_unsupported_bar_and_too_fast_polling():
    unsupported_bar = _strategy({
        "fast_ma_period": 2,
        "slow_ma_period": 5,
        "order_qty": 0.01,
        "symbol": "BTC-USDT-SWAP",
        "bar": "10s",
        "poll_interval": 15,
    })
    too_fast = _strategy({
        "fast_ma_period": 2,
        "slow_ma_period": 5,
        "order_qty": 0.01,
        "symbol": "BTC-USDT-SWAP",
        "bar": "1m",
        "poll_interval": 1,
    })

    assert await unsupported_bar.validate_params() is False
    assert await too_fast.validate_params() is False


@pytest.mark.parametrize(
    ("response", "expected_order_id", "error_fragment"),
    [
        (
            {"code": "0", "data": [{"sCode": "0", "ordId": "12345"}]},
            "12345",
            None,
        ),
        (
            {"code": "51000", "msg": "Parameter error", "data": []},
            None,
            "code=51000",
        ),
        (
            {"code": "0", "data": [{"sCode": "51008", "sMsg": "Insufficient balance"}]},
            None,
            "sCode=51008",
        ),
        (
            {"code": "0", "data": [{"sCode": "0", "ordId": ""}]},
            None,
            "缺少 ordId",
        ),
    ],
)
def test_parse_place_order_response_checks_outer_and_per_order_codes(
    response,
    expected_order_id,
    error_fragment,
):
    order_id, error = TrendStrategy._parse_place_order_response(response)

    assert order_id == expected_order_id
    if error_fragment is None:
        assert error is None
    else:
        assert error_fragment in error


def test_calculate_signal_detects_crossovers_and_initial_entry():
    buy_signal, buy_snapshot = TrendStrategy._calculate_signal(
        [5, 4, 3, 2, 1, 6],
        fast_period=2,
        slow_period=5,
    )
    sell_signal, sell_snapshot = TrendStrategy._calculate_signal(
        [1, 2, 3, 4, 5, 0],
        fast_period=2,
        slow_period=5,
    )
    initial_signal, initial_snapshot = TrendStrategy._calculate_signal(
        [1, 2, 3, 4, 5, 6],
        fast_period=2,
        slow_period=5,
        enter_on_start=True,
    )

    assert buy_signal == "buy"
    assert buy_snapshot["reason"] == "golden_cross"
    assert sell_signal == "sell"
    assert sell_snapshot["reason"] == "death_cross"
    assert initial_signal == "buy"
    assert initial_snapshot["reason"] == "initial_trend"


def test_trend_builds_pos_side_for_long_short_mode():
    strategy = TrendStrategy.__new__(TrendStrategy)
    strategy._position_mode = "long_short_mode"

    strategy._position = 0
    assert strategy._build_market_order_kwargs(
        "BTC-USDT-SWAP", "buy", 0.01
    )["pos_side"] == "long"
    assert strategy._build_market_order_kwargs(
        "BTC-USDT-SWAP", "sell", 0.01
    )["pos_side"] == "short"

    strategy._position = 0.01
    assert strategy._build_market_order_kwargs(
        "BTC-USDT-SWAP", "sell", 0.01
    )["pos_side"] == "long"

    strategy._position = -0.01
    assert strategy._build_market_order_kwargs(
        "BTC-USDT-SWAP", "buy", 0.01
    )["pos_side"] == "short"


def test_trend_spot_market_order_uses_base_currency_quantity():
    strategy = TrendStrategy.__new__(TrendStrategy)
    strategy._position_mode = "net_mode"
    strategy._position = 0

    kwargs = strategy._build_market_order_kwargs("BTC-USDT", "buy", 0.0001)

    assert kwargs["tgt_ccy"] == "base_ccy"
    assert "pos_side" not in kwargs


@pytest.mark.asyncio
async def test_grid_demo_test_order_places_one_spot_market_buy():
    strategy = GridStrategy.__new__(GridStrategy)
    strategy.instance_id = 1
    strategy.params = {"demo_test_order_on_start": True}
    strategy.client = MagicMock()
    strategy.client.trade_mode = "demo"
    strategy.client.place_order = AsyncMock(
        return_value={
            "code": "0",
            "data": [{"sCode": "0", "ordId": "demo-grid-order"}],
        }
    )
    strategy.record_order = AsyncMock()
    strategy._disable_demo_test_order = MagicMock()
    strategy._record_event = MagicMock()

    await strategy._place_demo_test_order("BTC-USDT", 64500, 0.0001)

    strategy.client.place_order.assert_awaited_once_with(
        inst_id="BTC-USDT",
        side="buy",
        ord_type="market",
        sz="0.0001",
        tgt_ccy="base_ccy",
    )
    strategy.record_order.assert_awaited_once_with(
        "BTC-USDT",
        "buy",
        "market",
        64500,
        0.0001,
        order_id="demo-grid-order",
        status="live",
    )
    strategy._disable_demo_test_order.assert_called_once()


@pytest.mark.asyncio
async def test_trend_rest_sync_updates_filled_market_order():
    strategy = TrendStrategy.__new__(TrendStrategy)
    active_order = MagicMock()
    active_order.symbol = "BTC-USDT-SWAP"
    active_order.ordId = "trend-order"
    active_order.state = "live"
    strategy.order_manager = MagicMock()
    strategy.order_manager.get_active_orders.return_value = [active_order]
    strategy.client = MagicMock()
    strategy.client.get_order = AsyncMock(return_value=[{
        "state": "filled",
        "fillPx": "64512.7",
        "fillSz": "0.01",
        "fee": "-0.0032",
        "uTime": "123",
    }])
    strategy._record_event = MagicMock()

    await strategy._sync_active_orders("BTC-USDT-SWAP")

    strategy.order_manager.update_order.assert_called_once_with(
        "trend-order",
        state="filled",
        fillPx="64512.7",
        fillSz="0.01",
        fee="-0.0032",
        uTime="123",
    )


@pytest.mark.asyncio
async def test_okx_client_forwards_optional_order_mode_fields():
    client = OKXClient.__new__(OKXClient)
    client._ensure_time_synced = AsyncMock()
    client.trade = MagicMock()
    client.trade.place_order = AsyncMock(return_value={"code": "0", "data": []})

    await client.place_order(
        "BTC-USDT-SWAP",
        "sell",
        "market",
        "0.01",
        pos_side="short",
        reduce_only=False,
    )

    client.trade.place_order.assert_awaited_once_with(
        instId="BTC-USDT-SWAP",
        tdMode="cross",
        side="sell",
        ordType="market",
        sz="0.01",
        px=None,
        posSide="short",
        reduceOnly=False,
    )


def test_order_manager_load_from_db_filters_by_strategy_instance():
    db = MagicMock()
    query = db.query.return_value
    filtered = query.filter.return_value
    filtered.all.return_value = []
    manager = OrderManager(
        MagicMock(return_value=db),
        MagicMock(),
        strategy_instance_id=3,
        account_id=1,
        instrument_cache=MagicMock(),
    )

    assert manager.load_from_db() == 0
    assert len(query.filter.call_args.args) == 3
    db.close.assert_called_once()


@pytest.mark.asyncio
async def test_order_manager_keeps_market_order_type():
    instrument_cache = MagicMock()
    instrument_cache.get_instrument = AsyncMock(
        return_value={"ctVal": 0.01, "ctType": "linear", "settleCcy": "USDT"}
    )
    manager = OrderManager(
        MagicMock(),
        MagicMock(),
        strategy_instance_id=3,
        account_id=1,
        instrument_cache=instrument_cache,
    )
    manager._async_persist = MagicMock()

    order = await manager.add_order(
        ordId="test-order-id",
        clOrdId="",
        symbol="BTC-USDT-SWAP",
        side="buy",
        px="64000",
        sz="0.01",
        state="live",
        order_type="market",
    )

    assert order.orderType == "market"
    assert order.to_dict()["orderType"] == "market"
    manager._async_persist.assert_called_once_with(order)
