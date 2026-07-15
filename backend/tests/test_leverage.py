"""合约杠杆设置单元测试（Task 2.2-2.3: 杠杆集成）。

覆盖：
- _apply_leverage_settings：合约+lever>1 调用 set_leverage 成功记录 leverage_set
- _apply_leverage_settings：失败记录 leverage_set_failed 且阻止启动
- lever=1 cross 默认跳过调用
- compute_order_qty：合约 qty=investment×lever/price、现货 qty=investment/price

参考 test_capital_limit.py 风格，用 Mock client + Mock db_session_factory。
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from strategies.base_strategy import BaseStrategy
from services.okx.exceptions import OKXAPIException


# ============================================================
# 辅助构造
# ============================================================


class _DummyStrategy(BaseStrategy):
    """最小可实例化策略子类，用于测试 BaseStrategy 能力。"""

    async def execute(self):
        pass

    async def validate_params(self) -> bool:
        return True


def _make_strategy(params: dict, client=None) -> tuple[_DummyStrategy, MagicMock]:
    """构造带 Mock 依赖的策略实例与 mock db。"""
    db = MagicMock()
    db_session_factory = MagicMock(return_value=db)
    mock_client = client or AsyncMock()
    strategy = _DummyStrategy(
        instance_id=1,
        params=params,
        client=mock_client,
        db_session_factory=db_session_factory,
        account_id=1,
        order_manager=MagicMock(),
        ws_client=None,
    )
    return strategy, db


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
# _apply_leverage_settings 测试（SubTask 2.2）
# ============================================================


@pytest.mark.asyncio
async def test_apply_leverage_success_records_event():
    """合约+lever>1：调用 set_leverage 成功，记录 leverage_set 事件。"""
    params = {"symbol": "BTC-USDT-SWAP", "investment_amount": 100, "lever": 10, "td_mode": "cross"}
    mock_client = AsyncMock()
    mock_client.set_leverage = AsyncMock(return_value={"code": "0"})
    strategy, _ = _make_strategy(params, client=mock_client)
    strategy._record_event = MagicMock()

    result = await strategy._apply_leverage_settings()

    assert result is True
    mock_client.set_leverage.assert_awaited_once_with(
        inst_id="BTC-USDT-SWAP", lever=10, mgn_mode="cross",
    )
    event_types = [call.args[0] for call in strategy._record_event.call_args_list]
    assert "leverage_set" in event_types


@pytest.mark.asyncio
async def test_apply_leverage_failure_records_event_and_blocks():
    """合约+lever>1：set_leverage 失败，记录 leverage_set_failed 且返回 False。"""
    params = {"symbol": "BTC-USDT-SWAP", "investment_amount": 100, "lever": 10, "td_mode": "isolated"}
    mock_client = AsyncMock()
    mock_client.set_leverage = AsyncMock(
        side_effect=OKXAPIException(code="50011", msg="杠杆设置失败", endpoint="/api/v5/account/set-leverage")
    )
    strategy, _ = _make_strategy(params, client=mock_client)
    strategy._record_event = MagicMock()

    result = await strategy._apply_leverage_settings()

    assert result is False
    mock_client.set_leverage.assert_awaited_once()
    event_types = [call.args[0] for call in strategy._record_event.call_args_list]
    assert "leverage_set_failed" in event_types
    # 事件 details 含错误码
    failed_call = next(c for c in strategy._record_event.call_args_list if c.args[0] == "leverage_set_failed")
    details = failed_call.args[2] if len(failed_call.args) > 2 else failed_call.kwargs.get("details")
    assert details["error_code"] == "50011"


@pytest.mark.asyncio
async def test_apply_leverage_skip_default_lever1_cross():
    """lever=1 + cross 默认：跳过 set_leverage 调用，不记录事件。"""
    params = {"symbol": "BTC-USDT-SWAP", "investment_amount": 100, "lever": 1, "td_mode": "cross"}
    mock_client = AsyncMock()
    mock_client.set_leverage = AsyncMock()
    strategy, _ = _make_strategy(params, client=mock_client)
    strategy._record_event = MagicMock()

    result = await strategy._apply_leverage_settings()

    assert result is True
    mock_client.set_leverage.assert_not_awaited()
    strategy._record_event.assert_not_called()


@pytest.mark.asyncio
async def test_apply_leverage_skip_spot_symbol():
    """现货品种：不调用 set_leverage。"""
    params = {"symbol": "BTC-USDT", "investment_amount": 100, "lever": 10, "td_mode": "cross"}
    mock_client = AsyncMock()
    mock_client.set_leverage = AsyncMock()
    strategy, _ = _make_strategy(params, client=mock_client)
    strategy._record_event = MagicMock()

    result = await strategy._apply_leverage_settings()

    assert result is True
    mock_client.set_leverage.assert_not_awaited()


@pytest.mark.asyncio
async def test_apply_leverage_isolated_mode_calls_set_leverage():
    """lever=1 + isolated（非默认 cross）：仍需调用 set_leverage。"""
    params = {"symbol": "BTC-USDT-SWAP", "investment_amount": 100, "lever": 1, "td_mode": "isolated"}
    mock_client = AsyncMock()
    mock_client.set_leverage = AsyncMock(return_value={"code": "0"})
    strategy, _ = _make_strategy(params, client=mock_client)
    strategy._record_event = MagicMock()

    result = await strategy._apply_leverage_settings()

    assert result is True
    mock_client.set_leverage.assert_awaited_once_with(
        inst_id="BTC-USDT-SWAP", lever=1, mgn_mode="isolated",
    )


@pytest.mark.asyncio
async def test_start_blocks_when_leverage_fails():
    """start() 在杠杆设置失败时更新状态为 error 且不记录 started 事件。"""
    params = {"symbol": "BTC-USDT-SWAP", "investment_amount": 100, "lever": 10, "td_mode": "cross"}
    mock_client = AsyncMock()
    mock_client.set_leverage = AsyncMock(
        side_effect=OKXAPIException(code="50011", msg="失败", endpoint="")
    )
    strategy, _ = _make_strategy(params, client=mock_client)
    strategy._record_event = MagicMock()
    strategy.update_status = MagicMock()

    await strategy.start()

    event_types = [call.args[0] for call in strategy._record_event.call_args_list]
    assert "leverage_set_failed" in event_types
    assert "started" not in event_types
    strategy.update_status.assert_called_with("error")


@pytest.mark.asyncio
async def test_start_records_started_when_leverage_ok():
    """start() 在杠杆设置成功后正常记录 started 事件。"""
    params = {"symbol": "BTC-USDT-SWAP", "investment_amount": 100, "lever": 10, "td_mode": "cross"}
    mock_client = AsyncMock()
    mock_client.set_leverage = AsyncMock(return_value={"code": "0"})
    strategy, _ = _make_strategy(params, client=mock_client)
    strategy._record_event = MagicMock()
    strategy.update_status = MagicMock()

    await strategy.start()

    event_types = [call.args[0] for call in strategy._record_event.call_args_list]
    assert "leverage_set" in event_types
    assert "started" in event_types
    strategy.update_status.assert_not_called()


# ============================================================
# compute_order_qty 测试（SubTask 2.3）
# ============================================================


def test_compute_order_qty_contract_with_ctval():
    """合约：qty = investment × lever / price，按 ctVal 向下取整为整数张。"""
    from services.instrument_cache import instrument_cache
    instrument_cache._cache["BTC-USDT-SWAP"] = {"ctVal": 0.01}
    params = {"symbol": "BTC-USDT-SWAP", "investment_amount": 100, "lever": 10, "td_mode": "cross"}
    strategy, _ = _make_strategy(params)
    # raw = 100 * 10 / 50000 = 0.02 BTC；ctVal=0.01 → 2 张
    qty = strategy.compute_order_qty(50000.0, "BTC-USDT-SWAP")
    assert qty == 2.0


def test_compute_order_qty_contract_floors_down():
    """合约：不足 1 张的部分向下取整。"""
    from services.instrument_cache import instrument_cache
    instrument_cache._cache["BTC-USDT-SWAP"] = {"ctVal": 0.01}
    params = {"symbol": "BTC-USDT-SWAP", "investment_amount": 100, "lever": 10, "td_mode": "cross"}
    strategy, _ = _make_strategy(params)
    # raw = 100 * 10 / 48000 ≈ 0.02083 BTC；/ 0.01 ≈ 2.083 → floor → 2
    qty = strategy.compute_order_qty(48000.0, "BTC-USDT-SWAP")
    assert qty == 2.0


def test_compute_order_qty_spot():
    """现货：qty = investment / price（lever 不适用）。"""
    params = {"symbol": "BTC-USDT", "investment_amount": 100, "lever": 10, "td_mode": "cross"}
    strategy, _ = _make_strategy(params)
    # qty = 100 / 50000 = 0.002
    qty = strategy.compute_order_qty(50000.0, "BTC-USDT")
    assert abs(qty - 0.002) < 1e-9


def test_compute_order_qty_spot_ignores_lever():
    """现货：lever 不影响 qty。"""
    params = {"symbol": "BTC-USDT", "investment_amount": 100, "lever": 10, "td_mode": "cross"}
    strategy, _ = _make_strategy(params)
    qty_lever10 = strategy.compute_order_qty(50000.0, "BTC-USDT")
    params2 = {"symbol": "BTC-USDT", "investment_amount": 100, "lever": 1, "td_mode": "cross"}
    strategy2, _ = _make_strategy(params2)
    qty_lever1 = strategy2.compute_order_qty(50000.0, "BTC-USDT")
    assert abs(qty_lever10 - qty_lever1) < 1e-9


def test_compute_order_qty_zero_investment_returns_zero():
    """investment_amount=0 时返回 0。"""
    params = {"symbol": "BTC-USDT-SWAP", "investment_amount": 0, "lever": 10, "td_mode": "cross"}
    strategy, _ = _make_strategy(params)
    assert strategy.compute_order_qty(50000.0, "BTC-USDT-SWAP") == 0.0


def test_compute_order_qty_zero_price_returns_zero():
    """price<=0 时返回 0。"""
    params = {"symbol": "BTC-USDT-SWAP", "investment_amount": 100, "lever": 10, "td_mode": "cross"}
    strategy, _ = _make_strategy(params)
    assert strategy.compute_order_qty(0.0, "BTC-USDT-SWAP") == 0.0


def test_compute_order_qty_contract_cache_miss_returns_float():
    """合约缓存未命中：返回 float 由调用方处理。"""
    params = {"symbol": "ETH-USDT-SWAP", "investment_amount": 100, "lever": 10, "td_mode": "cross"}
    strategy, _ = _make_strategy(params)
    # 缓存未命中（_clear_instrument_cache fixture 已清空），返回 float
    qty = strategy.compute_order_qty(3000.0, "ETH-USDT-SWAP")
    # raw = 100 * 10 / 3000 = 0.333...
    assert isinstance(qty, float)
    assert abs(qty - (100 * 10 / 3000)) < 1e-9
