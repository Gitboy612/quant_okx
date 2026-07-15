"""保证金与强平价监控单元测试（Task 3.2-3.4: 保证金监控）。

覆盖：
- check_margin_risk：现货返回 True（不查 API）
- check_margin_risk：合约无持仓返回 True
- check_margin_risk：margin_ratio 0.85 记录 margin_warning 返回 True
- check_margin_risk：margin_ratio 0.97 记录 margin_critical 返回 False
- check_margin_risk：节流期内第二次调用不查 API
- okx_client.get_position_risk 转发

参考 test_leverage.py 风格，用 Mock client + Mock db_session_factory。
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from strategies.base_strategy import BaseStrategy


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


def _risk_dict(margin_ratio: float, liq_px=None) -> dict:
    """构造 get_position_risk 返回值。"""
    return {
        "margin_ratio": margin_ratio,
        "liq_px": liq_px,
        "margin": "100.5",
        "pos": "1",
        "pos_side": "net",
    }


# ============================================================
# check_margin_risk 测试（SubTask 3.2）
# ============================================================


@pytest.mark.asyncio
async def test_check_margin_risk_spot_returns_true():
    """现货品种：直接返回 True，不查 API。"""
    params = {"symbol": "BTC-USDT", "investment_amount": 100, "lever": 1, "td_mode": "cross"}
    mock_client = AsyncMock()
    mock_client.get_position_risk = AsyncMock()
    strategy, _ = _make_strategy(params, client=mock_client)

    result = await strategy.check_margin_risk("BTC-USDT")

    assert result is True
    mock_client.get_position_risk.assert_not_awaited()


@pytest.mark.asyncio
async def test_check_margin_risk_contract_no_position_returns_true():
    """合约无持仓（返回 None）：返回 True。"""
    params = {"symbol": "BTC-USDT-SWAP", "investment_amount": 100, "lever": 10, "td_mode": "cross"}
    mock_client = AsyncMock()
    mock_client.get_position_risk = AsyncMock(return_value=None)
    strategy, _ = _make_strategy(params, client=mock_client)
    strategy._record_event = MagicMock()

    result = await strategy.check_margin_risk("BTC-USDT-SWAP")

    assert result is True
    mock_client.get_position_risk.assert_awaited_once_with("BTC-USDT-SWAP")


@pytest.mark.asyncio
async def test_check_margin_risk_warning_records_event_returns_true():
    """margin_ratio=0.85：记录 margin_warning 事件，返回 True（不拒单）。"""
    params = {"symbol": "BTC-USDT-SWAP", "investment_amount": 100, "lever": 10, "td_mode": "cross"}
    mock_client = AsyncMock()
    mock_client.get_position_risk = AsyncMock(return_value=_risk_dict(0.85, liq_px=45000.0))
    strategy, _ = _make_strategy(params, client=mock_client)
    strategy._record_event = MagicMock()

    result = await strategy.check_margin_risk("BTC-USDT-SWAP")

    assert result is True
    event_types = [call.args[0] for call in strategy._record_event.call_args_list]
    assert "margin_warning" in event_types
    # 确认 details 含 margin_ratio 与 liq_px
    warning_call = next(c for c in strategy._record_event.call_args_list if c.args[0] == "margin_warning")
    details = warning_call.args[2] if len(warning_call.args) > 2 else warning_call.kwargs.get("details")
    assert details["margin_ratio"] == 0.85
    assert details["liq_px"] == 45000.0


@pytest.mark.asyncio
async def test_check_margin_risk_critical_records_event_returns_false():
    """margin_ratio=0.97：记录 margin_critical 事件，返回 False（拒单）。"""
    params = {"symbol": "BTC-USDT-SWAP", "investment_amount": 100, "lever": 10, "td_mode": "cross"}
    mock_client = AsyncMock()
    mock_client.get_position_risk = AsyncMock(return_value=_risk_dict(0.97, liq_px=46000.0))
    strategy, _ = _make_strategy(params, client=mock_client)
    strategy._record_event = MagicMock()

    result = await strategy.check_margin_risk("BTC-USDT-SWAP")

    assert result is False
    event_types = [call.args[0] for call in strategy._record_event.call_args_list]
    assert "margin_critical" in event_types
    critical_call = next(c for c in strategy._record_event.call_args_list if c.args[0] == "margin_critical")
    details = critical_call.args[2] if len(critical_call.args) > 2 else critical_call.kwargs.get("details")
    assert details["margin_ratio"] == 0.97
    assert details["liq_px"] == 46000.0


@pytest.mark.asyncio
async def test_check_margin_risk_normal_returns_true():
    """margin_ratio=0.3：正常，返回 True，不记录告警事件。"""
    params = {"symbol": "BTC-USDT-SWAP", "investment_amount": 100, "lever": 10, "td_mode": "cross"}
    mock_client = AsyncMock()
    mock_client.get_position_risk = AsyncMock(return_value=_risk_dict(0.3))
    strategy, _ = _make_strategy(params, client=mock_client)
    strategy._record_event = MagicMock()

    result = await strategy.check_margin_risk("BTC-USDT-SWAP")

    assert result is True
    event_types = [call.args[0] for call in strategy._record_event.call_args_list]
    assert "margin_warning" not in event_types
    assert "margin_critical" not in event_types


@pytest.mark.asyncio
async def test_check_margin_risk_throttle_no_api_call_within_interval():
    """节流：30s 内第二次调用不查 API，返回上次结果。"""
    params = {"symbol": "BTC-USDT-SWAP", "investment_amount": 100, "lever": 10, "td_mode": "cross"}
    mock_client = AsyncMock()
    mock_client.get_position_risk = AsyncMock(return_value=_risk_dict(0.97))
    strategy, _ = _make_strategy(params, client=mock_client)
    strategy._record_event = MagicMock()

    # 第一次调用：margin_ratio=0.97 → 返回 False
    result1 = await strategy.check_margin_risk("BTC-USDT-SWAP")
    assert result1 is False
    assert mock_client.get_position_risk.await_count == 1

    # 第二次调用（节流期内）：不查 API，返回上次结果 False
    result2 = await strategy.check_margin_risk("BTC-USDT-SWAP")
    assert result2 is False
    assert mock_client.get_position_risk.await_count == 1  # 仍只调用一次


@pytest.mark.asyncio
async def test_check_margin_risk_throttle_custom_interval():
    """节流：自定义 margin_check_interval 生效。"""
    params = {
        "symbol": "BTC-USDT-SWAP", "investment_amount": 100, "lever": 10, "td_mode": "cross",
        "margin_check_interval": 5,
    }
    mock_client = AsyncMock()
    mock_client.get_position_risk = AsyncMock(return_value=_risk_dict(0.3))
    strategy, _ = _make_strategy(params, client=mock_client)
    strategy._record_event = MagicMock()

    # 第一次调用查 API
    await strategy.check_margin_risk("BTC-USDT-SWAP")
    assert mock_client.get_position_risk.await_count == 1

    # 第二次调用（5s 内）不查 API
    await strategy.check_margin_risk("BTC-USDT-SWAP")
    assert mock_client.get_position_risk.await_count == 1


# ============================================================
# okx_client.get_position_risk 转发测试（SubTask 3.2）
# ============================================================


@pytest.mark.asyncio
async def test_okx_client_forwards_get_position_risk():
    """OKXClient.get_position_risk 转发至 account.get_position_risk。"""
    from services.okx_client import OKXClient

    # 绕过 __init__（需要加密密钥），手动设置必要属性
    client = OKXClient.__new__(OKXClient)
    client._time_synced = True
    client.account = AsyncMock()
    expected = _risk_dict(0.5, liq_px=40000.0)
    client.account.get_position_risk = AsyncMock(return_value=expected)

    result = await client.get_position_risk("BTC-USDT-SWAP")

    client.account.get_position_risk.assert_awaited_once_with(inst_id="BTC-USDT-SWAP")
    assert result == expected
    assert result["margin_ratio"] == 0.5
