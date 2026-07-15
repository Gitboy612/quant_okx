"""资金上限校验单元测试（Task 1: 策略投入资金上限）。

覆盖：
- check_capital_limit：未超限返回 True / 超限返回 False 并记录事件 / investment_amount=0 不限制
- place_order_with_capital_check：超限时返回拒绝响应且不调 client
- 旧实例参数迁移：缺字段时补默认值并记录 param_migrated 事件

参考 test_strategy_engine_update_params.py 风格，用 Mock client + Mock db_session_factory。
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
    """构造带 Mock 依赖的策略实例与 mock db。

    返回 (strategy, db)，db 用于断言 _record_event 写入。
    """
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


# ============================================================
# check_capital_limit 测试（SubTask 1.1）
# ============================================================


def test_check_capital_limit_within_limit_returns_true():
    """未超限时返回 True。"""
    params = {"symbol": "BTC-USDT", "investment_amount": 1000}
    strategy, _ = _make_strategy(params)
    # new_value = 0.01 * 50000 = 500 <= cap 1000
    assert strategy.check_capital_limit("BTC-USDT", "buy", 0.01, 50000) is True


def test_check_capital_limit_exceeded_returns_false_and_records_event():
    """超限时返回 False 并记录 capital_limit 事件。"""
    params = {"symbol": "BTC-USDT", "investment_amount": 100}
    strategy, _ = _make_strategy(params)
    strategy._record_event = MagicMock()
    # new_value = 0.01 * 50000 = 500 > cap 100
    result = strategy.check_capital_limit("BTC-USDT", "buy", 0.01, 50000)
    assert result is False
    strategy._record_event.assert_called_once()
    assert strategy._record_event.call_args.args[0] == "capital_limit"


def test_check_capital_limit_zero_amount_no_limit():
    """investment_amount=0 时不限制，始终返回 True。"""
    params = {"symbol": "BTC-USDT", "investment_amount": 0}
    strategy, _ = _make_strategy(params)
    strategy._record_event = MagicMock()
    # 即使超大单也不限制
    assert strategy.check_capital_limit("BTC-USDT", "buy", 100, 50000) is True
    strategy._record_event.assert_not_called()


def test_check_capital_limit_contract_lever_amplifies_cap():
    """合约按杠杆放大上限：investment_amount=100, lever=10 → cap=1000。"""
    params = {"symbol": "BTC-USDT-SWAP", "investment_amount": 100, "lever": 10}
    strategy, _ = _make_strategy(params)
    strategy._record_event = MagicMock()
    # new_value = 0.01 * 50000 = 500 <= cap 1000 → 通过
    assert strategy.check_capital_limit("BTC-USDT-SWAP", "buy", 0.01, 50000) is True
    # new_value = 0.03 * 50000 = 1500 > cap 1000 → 拒绝
    assert strategy.check_capital_limit("BTC-USDT-SWAP", "buy", 0.03, 50000) is False
    strategy._record_event.assert_called_once()


# ============================================================
# place_order_with_capital_check 测试（SubTask 1.2）
# ============================================================


@pytest.mark.asyncio
async def test_place_order_with_capital_check_passes_through_to_client():
    """未超限时调用 client.place_order 并返回其响应。"""
    params = {"symbol": "BTC-USDT", "investment_amount": 1000}
    mock_client = AsyncMock()
    mock_client.place_order = AsyncMock(return_value={"code": "0", "data": [{"ordId": "123"}]})
    strategy, _ = _make_strategy(params, client=mock_client)
    resp = await strategy.place_order_with_capital_check("BTC-USDT", "buy", "limit", "0.01", "50000")
    assert resp["code"] == "0"
    mock_client.place_order.assert_awaited_once()


@pytest.mark.asyncio
async def test_place_order_with_capital_check_exceeded_no_client_call():
    """超限时返回拒绝响应且不调用 client.place_order。"""
    params = {"symbol": "BTC-USDT", "investment_amount": 100}
    mock_client = AsyncMock()
    mock_client.place_order = AsyncMock(return_value={"code": "0"})
    strategy, _ = _make_strategy(params, client=mock_client)
    # 屏蔽 _record_event 避免通知副作用
    strategy._record_event = MagicMock()
    resp = await strategy.place_order_with_capital_check("BTC-USDT", "buy", "limit", "0.01", "50000")
    assert resp["code"] == "-1"
    assert resp["msg"] == "capital_limit_exceeded"
    mock_client.place_order.assert_not_awaited()


# ============================================================
# 参数迁移测试（SubTask 1.4）
# ============================================================


def test_param_migration_adds_defaults_when_missing():
    """缺 investment_amount 时补默认值并记录 param_migrated 事件。"""
    params = {"symbol": "BTC-USDT", "order_qty": 0.01}  # 无 investment_amount
    strategy, db = _make_strategy(params)
    # 默认值已补入
    assert strategy.params["investment_amount"] == 0
    assert strategy.params["lever"] == 1
    assert strategy.params["td_mode"] == "cross"
    assert strategy._param_migrated is True
    assert strategy.investment_amount == 0.0
    # 事件已记录（db.add 被调用）
    assert db.add.call_count >= 1


def test_param_migration_skips_when_already_present():
    """已有 investment_amount 时不触发迁移，不记录事件。"""
    params = {"symbol": "BTC-USDT", "investment_amount": 500, "lever": 5}
    strategy, db = _make_strategy(params)
    assert strategy._param_migrated is False
    assert strategy.investment_amount == 500.0
    assert strategy.params["lever"] == 5  # 未被覆盖
    # __init__ 中无其他 _record_event 调用，db.add 不应被调用
    db.add.assert_not_called()
