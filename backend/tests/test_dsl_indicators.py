"""P0 指标库单元测试。

用 AsyncMock 构造假 OKX client，测试纯计算逻辑（不依赖网络）。
参考 test_backward_compat.py 的 sys.path.insert + pytest 风格。
"""
import sys
import os
import asyncio
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

# 导入 indicators 模块以触发 @indicator 注册
import dsl.blocks.indicators  # noqa: F401
from dsl.schema import IndicatorRef
from dsl.context import ExecutionContext
from dsl.blocks.indicators import compute_indicator, _window_to_bar


def make_ctx(client, symbol="BTC-USDT", current_price=0.0, realized_pnl=0.0):
    """构造测试用 ExecutionContext。"""
    return ExecutionContext(
        client=client,
        order_manager=MagicMock(),
        symbol=symbol,
        current_price=current_price,
        realized_pnl=realized_pnl,
    )


def test_window_to_bar():
    """测试窗口串到 OKX bar 参数的转换。"""
    assert _window_to_bar("1h") == "1H"
    assert _window_to_bar("5m") == "5m"
    assert _window_to_bar("1d") == "1D"
    assert _window_to_bar("4H") == "4H"


def test_price_change_pct():
    """测试 price_change_pct 涨跌幅计算。"""
    async def run():
        client = AsyncMock()
        # OKX 返回最新在前：candles[0] 是当前K线，candles[1] 是上一根（已完成）
        # 上一根 close = 110，当前价用 ctx.current_price = 121
        # 涨幅 = (121 - 110) / 110 = 0.1
        client.get_candles.return_value = [
            ["ts1", "o", "h", "l", "100", "vol", "volCcy"],
            ["ts2", "o", "h", "l", "110", "vol", "volCcy"],
        ]
        ctx = make_ctx(client, symbol="BTC-USDT", current_price=121.0)
        ref = IndicatorRef(kind="price_change_pct", args={"window": "1h", "symbol": "BTC-USDT"})
        result = await compute_indicator(ref, ctx)
        assert abs(result - 0.1) < 1e-9, f"期望 0.1，实际 {result}"
        # 验证 get_candles 用了正确的 bar 参数
        client.get_candles.assert_called_once_with("BTC-USDT", bar="1H", limit="2")
    asyncio.run(run())


def test_price_change_pct_fallback_ticker():
    """测试 price_change_pct 在 symbol != ctx.symbol 时用 get_ticker 取当前价。"""
    async def run():
        client = AsyncMock()
        client.get_candles.return_value = [
            ["ts1", "o", "h", "l", "100", "vol", "volCcy"],
            ["ts2", "o", "h", "l", "200", "vol", "volCcy"],
        ]
        client.get_ticker.return_value = [{"last": "210"}]
        ctx = make_ctx(client, symbol="ETH-USDT", current_price=3000.0)
        ref = IndicatorRef(kind="price_change_pct", args={"window": "1h", "symbol": "BTC-USDT"})
        result = await compute_indicator(ref, ctx)
        # ref = 200, current = 210, (210-200)/200 = 0.05
        assert abs(result - 0.05) < 1e-9
        client.get_ticker.assert_called_once_with("BTC-USDT")
    asyncio.run(run())


def test_price_change_pct_ref_zero():
    """测试 price_change_pct 在 ref 为 0 时返回 0.0。"""
    async def run():
        client = AsyncMock()
        client.get_candles.return_value = [
            ["ts1", "o", "h", "l", "0", "vol", "volCcy"],
            ["ts2", "o", "h", "l", "0", "vol", "volCcy"],
        ]
        ctx = make_ctx(client, symbol="BTC-USDT", current_price=100.0)
        ref = IndicatorRef(kind="price_change_pct", args={"window": "1h", "symbol": "BTC-USDT"})
        result = await compute_indicator(ref, ctx)
        assert result == 0.0
    asyncio.run(run())


def test_rsi_all_rising():
    """测试 RSI：全上涨序列 RSI 应为 100。"""
    async def run():
        client = AsyncMock()
        period = 14
        # 构造 period+1 根 K 线，close 从 1 涨到 15（每根涨 1）
        # OKX 返回最新在前，所以倒序构造
        candles = []
        for i in range(period + 1, 0, -1):
            # i 从 15 到 1，candles[0] close=15（最新），candles[14] close=1（最旧）
            candles.append([str(i * 1000), "o", "h", "l", str(i), "vol", "volCcy"])
        client.get_candles.return_value = candles
        ctx = make_ctx(client, symbol="BTC-USDT")
        ref = IndicatorRef(kind="rsi", args={"period": period, "symbol": "BTC-USDT"})
        result = await compute_indicator(ref, ctx)
        assert result == 100.0, f"全上涨 RSI 应为 100，实际 {result}"
        client.get_candles.assert_called_once_with(
            "BTC-USDT", bar="1H", limit=str(period + 1)
        )
    asyncio.run(run())


def test_rsi_all_falling():
    """测试 RSI：全下跌序列 RSI 应为 0。"""
    async def run():
        client = AsyncMock()
        period = 14
        # close 从 15 跌到 1（每根跌 1），最新在前
        candles = []
        for i in range(1, period + 2):
            candles.append([str(i * 1000), "o", "h", "l", str(i), "vol", "volCcy"])
        client.get_candles.return_value = candles
        ctx = make_ctx(client, symbol="BTC-USDT")
        ref = IndicatorRef(kind="rsi", args={"period": period, "symbol": "BTC-USDT"})
        result = await compute_indicator(ref, ctx)
        assert result == 0.0, f"全下跌 RSI 应为 0，实际 {result}"
    asyncio.run(run())


def test_rsi_insufficient_data():
    """测试 RSI：数据不足时返回 50.0（中性）。"""
    async def run():
        client = AsyncMock()
        client.get_candles.return_value = [
            ["ts1", "o", "h", "l", "100", "vol", "volCcy"],
            ["ts2", "o", "h", "l", "101", "vol", "volCcy"],
        ]
        ctx = make_ctx(client, symbol="BTC-USDT")
        ref = IndicatorRef(kind="rsi", args={"period": 14, "symbol": "BTC-USDT"})
        result = await compute_indicator(ref, ctx)
        assert result == 50.0
    asyncio.run(run())


def test_rsi_mixed():
    """测试 RSI：混合涨跌序列 RSI 在 (0, 100) 之间。"""
    async def run():
        client = AsyncMock()
        period = 5
        # 构造 close 序列（旧→新）：10, 12, 11, 13, 12, 14
        # 涨跌：+2, -1, +2, -1, +2
        closes_oldest_to_newest = [10, 12, 11, 13, 12, 14]
        candles = []
        for c in reversed(closes_oldest_to_newest):
            candles.append(["ts", "o", "h", "l", str(c), "vol", "volCcy"])
        client.get_candles.return_value = candles
        ctx = make_ctx(client, symbol="BTC-USDT")
        ref = IndicatorRef(kind="rsi", args={"period": period, "symbol": "BTC-USDT"})
        result = await compute_indicator(ref, ctx)
        assert 0.0 < result < 100.0, f"混合序列 RSI 应在 (0,100)，实际 {result}"
    asyncio.run(run())


def test_position_qty():
    """测试 position_qty 持仓量读取。"""
    async def run():
        client = AsyncMock()
        client.get_positions.return_value = [
            {"instId": "ETH-USDT", "pos": "2.5", "upl": "10"},
            {"instId": "BTC-USDT", "pos": "-1.0", "upl": "-50"},
        ]
        ctx = make_ctx(client, symbol="BTC-USDT")
        ref = IndicatorRef(kind="position_qty", args={"symbol": "BTC-USDT"})
        result = await compute_indicator(ref, ctx)
        assert result == -1.0, f"期望 -1.0（空仓），实际 {result}"
    asyncio.run(run())


def test_position_qty_no_position():
    """测试 position_qty 无持仓返回 0.0。"""
    async def run():
        client = AsyncMock()
        client.get_positions.return_value = []
        ctx = make_ctx(client, symbol="BTC-USDT")
        ref = IndicatorRef(kind="position_qty", args={"symbol": "BTC-USDT"})
        result = await compute_indicator(ref, ctx)
        assert result == 0.0
    asyncio.run(run())


def test_position_pnl():
    """测试 position_pnl 持仓盈亏读取。"""
    async def run():
        client = AsyncMock()
        client.get_positions.return_value = [
            {"instId": "BTC-USDT", "pos": "1.0", "upl": "123.45"},
        ]
        ctx = make_ctx(client, symbol="BTC-USDT")
        ref = IndicatorRef(kind="position_pnl", args={"symbol": "BTC-USDT"})
        result = await compute_indicator(ref, ctx)
        assert abs(result - 123.45) < 1e-9
    asyncio.run(run())


def test_account_equity():
    """测试 account_equity 账户净值读取。"""
    async def run():
        client = AsyncMock()
        client.get_balance.return_value = {"totalEq": "50000.5", "details": []}
        ctx = make_ctx(client)
        ref = IndicatorRef(kind="account_equity", args={})
        result = await compute_indicator(ref, ctx)
        assert abs(result - 50000.5) < 1e-9
    asyncio.run(run())


def test_realized_pnl():
    """测试 realized_pnl 从 ctx 读取。"""
    async def run():
        client = AsyncMock()
        ctx = make_ctx(client, realized_pnl=999.99)
        ref = IndicatorRef(kind="realized_pnl", args={})
        result = await compute_indicator(ref, ctx)
        assert abs(result - 999.99) < 1e-9
    asyncio.run(run())


def test_unrealized_pnl():
    """测试 unrealized_pnl 从持仓 upl 读取。"""
    async def run():
        client = AsyncMock()
        client.get_positions.return_value = [
            {"instId": "BTC-USDT", "pos": "1.0", "upl": "55.5"},
        ]
        ctx = make_ctx(client, symbol="BTC-USDT")
        ref = IndicatorRef(kind="unrealized_pnl", args={})
        result = await compute_indicator(ref, ctx)
        assert abs(result - 55.5) < 1e-9
    asyncio.run(run())


def test_unrealized_pnl_no_position():
    """测试 unrealized_pnl 无持仓返回 0.0。"""
    async def run():
        client = AsyncMock()
        client.get_positions.return_value = []
        ctx = make_ctx(client, symbol="BTC-USDT")
        ref = IndicatorRef(kind="unrealized_pnl", args={})
        result = await compute_indicator(ref, ctx)
        assert result == 0.0
    asyncio.run(run())


def test_price_last_uses_cached_price():
    """测试 price_last 在 symbol==ctx.symbol 时用缓存价，不调 get_ticker。"""
    async def run():
        client = AsyncMock()
        ctx = make_ctx(client, symbol="BTC-USDT", current_price=50000.0)
        ref = IndicatorRef(kind="price_last", args={"symbol": "BTC-USDT"})
        result = await compute_indicator(ref, ctx)
        assert result == 50000.0
        client.get_ticker.assert_not_called()
    asyncio.run(run())


def test_price_last_falls_back_to_ticker():
    """测试 price_last 在 symbol!=ctx.symbol 时调 get_ticker。"""
    async def run():
        client = AsyncMock()
        client.get_ticker.return_value = [{"last": "3000.5"}]
        ctx = make_ctx(client, symbol="BTC-USDT", current_price=50000.0)
        ref = IndicatorRef(kind="price_last", args={"symbol": "ETH-USDT"})
        result = await compute_indicator(ref, ctx)
        assert abs(result - 3000.5) < 1e-9
        client.get_ticker.assert_called_once_with("ETH-USDT")
    asyncio.run(run())


def test_compute_indicator_caching():
    """测试 compute_indicator 缓存：同一 IndicatorRef 二次调用只计算一次。"""
    async def run():
        client = AsyncMock()
        client.get_ticker.return_value = [{"last": "50000"}]
        ctx = make_ctx(client, symbol="ETH-USDT", current_price=0.0)
        ref = IndicatorRef(kind="price_last", args={"symbol": "BTC-USDT"})
        # 第一次调用，触发 get_ticker
        result1 = await compute_indicator(ref, ctx)
        assert result1 == 50000.0
        assert client.get_ticker.call_count == 1
        # 第二次调用，应命中缓存，不触发 get_ticker
        result2 = await compute_indicator(ref, ctx)
        assert result2 == 50000.0
        assert client.get_ticker.call_count == 1, "二次调用应命中缓存，不重复请求"
    asyncio.run(run())


def test_compute_indicator_unknown_kind():
    """测试 compute_indicator 对未注册 kind 抛 ValueError。"""
    async def run():
        client = AsyncMock()
        ctx = make_ctx(client)
        ref = IndicatorRef(kind="nonexistent_indicator", args={})
        with pytest.raises(ValueError, match="未知指标 kind"):
            await compute_indicator(ref, ctx)
    asyncio.run(run())


def test_all_indicators_registered():
    """测试所有 P0 指标均已注册。"""
    expected_kinds = {
        "price_last", "price_change_pct", "rsi",
        "position_qty", "position_pnl",
        "account_equity", "realized_pnl", "unrealized_pnl",
    }
    registered = {item["kind"] for item in __import__("dsl.registry", fromlist=["indicator_registry"]).indicator_registry.list()}
    assert expected_kinds.issubset(registered), f"缺失指标: {expected_kinds - registered}"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
