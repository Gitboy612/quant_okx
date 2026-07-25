import pytest
from unittest.mock import AsyncMock, MagicMock

from services.order_manager import OrderManager
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
