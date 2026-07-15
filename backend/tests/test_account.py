import sys
import os
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_config import get_test_client, TestRunner


async def test_account_interfaces(runner: TestRunner):
    client = await get_test_client()
    try:
        await runner.run_test(
            "get_balance()",
            client.account.get_balance(),
            validate=lambda r: (
                isinstance(r, dict) and "totalEq" in r,
                f"返回数据异常或缺少totalEq: {r}"
            )
        )
        
        await runner.run_test(
            "get_positions()",
            client.account.get_positions(),
            validate=lambda r: (isinstance(r, list), f"应返回list，实际: {type(r)}")
        )
        
        await runner.run_test(
            "get_config()",
            client.account.get_config(),
            validate=lambda r: (isinstance(r, list), f"应返回list，实际: {type(r)}")
        )
        
        await runner.run_test(
            'get_bills(limit="5")',
            client.account.get_bills(limit="5"),
            validate=lambda r: (isinstance(r, list), f"应返回list，实际: {type(r)}")
        )
        
        await runner.run_test(
            'get_fee_rates(instType="SWAP", instId="BTC-USDT-SWAP")',
            client.account.get_fee_rates(instType="SWAP", instId="BTC-USDT-SWAP"),
            validate=lambda r: (
                isinstance(r, list) and len(r) > 0,
                f"返回数据异常: {r}"
            )
        )
        
        await runner.run_test(
            'get_leverage(instId="BTC-USDT-SWAP", mgnMode="cross")',
            client.account.get_leverage(instId="BTC-USDT-SWAP", mgnMode="cross"),
            validate=lambda r: (
                isinstance(r, list) and len(r) > 0 and "lever" in r[0],
                f"返回数据异常或缺少lever: {r}"
            )
        )
    finally:
        await client.aclose()


if __name__ == "__main__":
    async def main():
        runner = TestRunner()
        await test_account_interfaces(runner)
        runner.print_summary("账户接口测试")

    asyncio.run(main())


# ============================================================================
# 单元测试（Mock httpx，不依赖真实 OKX 账户）
# 下方测试通过 Mock OKXBaseClient._request 验证 get_position_risk 的返回结构
# ============================================================================

import pytest
from unittest.mock import AsyncMock, MagicMock

from services.okx.account import AccountAPI


# 上方 test_account_interfaces(runner) 为集成测试，需通过 run_tests.py 或 __main__ 运行。
# 此 fixture 让其在 pytest 下被跳过（而非因缺少 fixture 报错）；直接调用不受影响。
@pytest.fixture
def runner():
    pytest.skip("集成测试需通过 run_tests.py 或 python tests/test_account.py 运行")


def _make_account_api_with_mock():
    """构造一个绑定 Mock 基类客户端的 AccountAPI。"""
    mock_client = MagicMock()
    mock_client._request = AsyncMock()
    return AccountAPI(mock_client), mock_client


async def test_get_position_risk_with_position():
    """有持仓：返回包含 margin_ratio / liq_px / margin / pos / pos_side 的字典。"""
    api, mock_client = _make_account_api_with_mock()
    mock_client._request.return_value = {
        "code": "0",
        "data": [{
            "instId": "ETH-USDT-SWAP",
            "pos": "2",
            "posSide": "long",
            "margin": "200",
            "liqPx": "1500.5",
            "markPx": "2000.0",
        }],
    }
    result = await api.get_position_risk("ETH-USDT-SWAP")
    assert result is not None
    assert result["pos"] == "2"
    assert result["pos_side"] == "long"
    assert result["margin"] == "200"
    assert result["liq_px"] == 1500.5
    # margin_ratio = 200 / (2 * 2000) = 0.05
    assert result["margin_ratio"] == pytest.approx(0.05, rel=1e-6)
    # 验证请求路径与 instId 过滤
    call = mock_client._request.call_args
    assert call.args[0] == "GET"
    assert "/api/v5/account/positions" in call.args[1]
    assert "instId=ETH-USDT-SWAP" in call.args[1]


async def test_get_position_risk_short_position_abs():
    """空头持仓 pos 为负：margin_ratio 用 |pos| 计算。"""
    api, mock_client = _make_account_api_with_mock()
    mock_client._request.return_value = {
        "code": "0",
        "data": [{
            "instId": "ETH-USDT-SWAP",
            "pos": "-1",
            "posSide": "short",
            "margin": "100",
            "liqPx": "",
            "markPx": "2000.0",
        }],
    }
    result = await api.get_position_risk("ETH-USDT-SWAP")
    assert result is not None
    assert result["pos"] == "-1"
    assert result["pos_side"] == "short"
    assert result["liq_px"] is None  # 空 liqPx -> None
    # margin_ratio = 100 / (|-1| * 2000) = 0.05
    assert result["margin_ratio"] == pytest.approx(0.05, rel=1e-6)


async def test_get_position_risk_no_position():
    """无持仓：返回 None。"""
    api, mock_client = _make_account_api_with_mock()
    mock_client._request.return_value = {"code": "0", "data": []}
    result = await api.get_position_risk("ETH-USDT-SWAP")
    assert result is None


async def test_get_position_risk_missing_markpx_fallback():
    """markPx 缺失：margin_ratio 回退为 margin 原值(float)。"""
    api, mock_client = _make_account_api_with_mock()
    mock_client._request.return_value = {
        "code": "0",
        "data": [{
            "instId": "ETH-USDT-SWAP",
            "pos": "1",
            "posSide": "long",
            "margin": "150",
            "liqPx": "1000",
            "markPx": "",  # 缺失
        }],
    }
    result = await api.get_position_risk("ETH-USDT-SWAP")
    assert result is not None
    assert result["margin_ratio"] == 150.0  # 回退为 margin 原值
    assert result["liq_px"] == 1000.0

