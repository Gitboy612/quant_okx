"""WebSocket 消息处理延迟性能基准测试。

测试维度：
1. OKXPublicWsClient._handle_data 单条 ticker 消息处理延迟
2. OKXWsClient._handle_data 单条 orders 消息处理延迟
3. MarketDataService._on_ticker_data 回调分发延迟（1000 条消息）

基准标准：
- 单条消息处理 < 1ms
- 1000 条消息分发 < 100ms

实现说明：
- 使用 mock WebSocket 连接（不建立真实连接）
- 构造 OKX 格式的 ticker / orders 消息 dict
- 注册回调函数测量分发延迟
- 使用 time.perf_counter() 高精度计时
"""
import json
import os
import sys
import time
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest

from services.okx_ws_client import OKXWsClient, OKXPublicWsClient
from services.market_data_service import MarketDataService

pytestmark = pytest.mark.perf


# ============================================================
# Mock 数据生成
# ============================================================


def _make_ticker_msg(symbol: str = "BTC-USDT", last: str = "50000.0") -> dict:
    """构造 OKX tickers 频道消息。"""
    return {
        "arg": {"channel": "tickers", "instId": symbol},
        "data": [{
            "instId": symbol,
            "last": last,
            "lastSz": "0.01",
            "askPx": "50001.0",
            "askSz": "0.5",
            "bidPx": "49999.0",
            "bidSz": "0.5",
            "open24h": "49000.0",
            "high24h": "51000.0",
            "low24h": "48000.0",
            "vol24h": "1000.5",
            "ts": "1700000000000",
        }],
    }


def _make_orders_msg(ord_id: str = "order_001", state: str = "filled") -> dict:
    """构造 OKX orders 频道消息。"""
    return {
        "arg": {"channel": "orders", "instType": "SPOT", "instId": "BTC-USDT"},
        "data": [{
            "instId": "BTC-USDT",
            "ordId": ord_id,
            "state": state,
            "side": "buy",
            "px": "50000.0",
            "sz": "0.01",
            "fillPx": "50000.0",
            "fillSz": "0.01",
            "fee": "0.5",
            "ts": "1700000000000",
        }],
    }


# ============================================================
# 基准测试：OKXPublicWsClient ticker 消息处理
# ============================================================


@pytest.mark.asyncio
async def test_public_ws_single_ticker_latency():
    """单条 ticker 消息 _handle_data 处理 < 1ms。"""
    client = OKXPublicWsClient(trade_mode="live")
    client._connected = True
    client._ws = MagicMock()
    client._ws.send = AsyncMock()

    # 注册一个回调
    received = []
    client.on_ticker_update(lambda data: received.append(data))

    msg = _make_ticker_msg()

    # warm up
    await client._handle_data(msg)

    start = time.perf_counter()
    await client._handle_data(msg)
    elapsed_ms = (time.perf_counter() - start) * 1000

    print(f"\n[perf] public ws ticker _handle_data: {elapsed_ms:.3f}ms")
    assert elapsed_ms < 1.0, f"单条 ticker 消息处理耗时 {elapsed_ms:.3f}ms 超过 1ms 基准"
    assert len(received) >= 1


@pytest.mark.asyncio
async def test_public_ws_1000_ticker_messages():
    """1000 条 ticker 消息连续处理 < 100ms。"""
    client = OKXPublicWsClient(trade_mode="live")
    client._connected = True
    client._ws = MagicMock()
    client._ws.send = AsyncMock()

    received = []
    client.on_ticker_update(lambda data: received.append(data))

    msg = _make_ticker_msg()

    start = time.perf_counter()
    for _ in range(1000):
        await client._handle_data(msg)
    elapsed_ms = (time.perf_counter() - start) * 1000

    avg_us = (elapsed_ms / 1000) * 1000
    print(f"\n[perf] 1000 条 ticker 消息: total={elapsed_ms:.3f}ms, avg={avg_us:.3f}us/msg")
    assert elapsed_ms < 100.0, f"1000 条 ticker 消息处理耗时 {elapsed_ms:.2f}ms 超过 100ms"
    assert len(received) == 1000


# ============================================================
# 基准测试：OKXWsClient orders 消息处理
# ============================================================


@pytest.mark.asyncio
async def test_private_ws_single_order_latency():
    """单条 orders 消息 _handle_data 处理 < 1ms。"""
    client = OKXWsClient(
        api_key="test_key",
        secret_key="test_secret",
        passphrase="test_pass",
        trade_mode="demo",
    )
    client._connected = True
    client._ws = MagicMock()

    # 注册订单回调
    received = []
    client.on_order_update(lambda oid, state, data: received.append((oid, state)))

    msg = _make_orders_msg()

    start = time.perf_counter()
    await client._handle_data(msg)
    elapsed_ms = (time.perf_counter() - start) * 1000

    print(f"\n[perf] private ws orders _handle_data: {elapsed_ms:.3f}ms")
    assert elapsed_ms < 1.0, f"单条 orders 消息处理耗时 {elapsed_ms:.3f}ms 超过 1ms 基准"
    assert len(received) == 1


@pytest.mark.asyncio
async def test_private_ws_1000_order_messages():
    """1000 条 orders 消息连续处理 < 100ms。"""
    client = OKXWsClient(
        api_key="test_key",
        secret_key="test_secret",
        passphrase="test_pass",
        trade_mode="demo",
    )
    client._connected = True
    client._ws = MagicMock()

    received = []
    client.on_order_update(lambda oid, state, data: received.append(oid))

    start = time.perf_counter()
    for i in range(1000):
        msg = _make_orders_msg(ord_id=f"order_{i:04d}")
        await client._handle_data(msg)
    elapsed_ms = (time.perf_counter() - start) * 1000

    avg_us = (elapsed_ms / 1000) * 1000
    print(f"\n[perf] 1000 条 orders 消息: total={elapsed_ms:.3f}ms, avg={avg_us:.3f}us/msg")
    assert elapsed_ms < 100.0, f"1000 条 orders 消息处理耗时 {elapsed_ms:.2f}ms 超过 100ms"
    assert len(received) == 1000


# ============================================================
# 基准测试：MarketDataService 回调分发
# ============================================================


@pytest.mark.asyncio
async def test_market_data_service_single_dispatch():
    """MarketDataService 单条 ticker 分发 < 1ms。"""
    # 重置单例
    MarketDataService._instance = None
    service = MarketDataService()

    received = []
    callback = lambda data: received.append(data)
    service._ticker_callbacks["BTC-USDT"] = [callback]

    msg = _make_ticker_msg()

    start = time.perf_counter()
    service._on_ticker_data(msg["data"][0])
    elapsed_ms = (time.perf_counter() - start) * 1000

    print(f"\n[perf] MarketDataService 单条分发: {elapsed_ms:.3f}ms")
    assert elapsed_ms < 1.0, f"单条分发耗时 {elapsed_ms:.3f}ms 超过 1ms 基准"
    assert len(received) == 1


@pytest.mark.asyncio
async def test_market_data_service_1000_dispatch():
    """MarketDataService 1000 条 ticker 分发 < 100ms（含多回调 fan-out）。"""
    MarketDataService._instance = None
    service = MarketDataService()

    # 注册 3 个回调（模拟多策略订阅同一 symbol）
    received1, received2, received3 = [], [], []
    service._ticker_callbacks["BTC-USDT"] = [
        received1.append,
        received2.append,
        received3.append,
    ]

    ticker_data = _make_ticker_msg()["data"][0]

    start = time.perf_counter()
    for _ in range(1000):
        service._on_ticker_data(ticker_data)
    elapsed_ms = (time.perf_counter() - start) * 1000

    avg_us = (elapsed_ms / 1000) * 1000
    print(f"\n[perf] 1000 条 ticker 分发 (3 callbacks): total={elapsed_ms:.3f}ms, avg={avg_us:.3f}us/msg")
    assert elapsed_ms < 100.0, f"1000 条分发耗时 {elapsed_ms:.2f}ms 超过 100ms"
    assert len(received1) == 1000
    assert len(received2) == 1000
    assert len(received3) == 1000


# ============================================================
# 基准测试：JSON 解析延迟（附加）
# ============================================================


def test_json_parse_1000_messages():
    """1000 条消息 JSON 解析 < 50ms（WS message_loop 中的 json.loads 开销）。"""
    msg = _make_ticker_msg()
    raw = json.dumps(msg)

    start = time.perf_counter()
    for _ in range(1000):
        json.loads(raw)
    elapsed_ms = (time.perf_counter() - start) * 1000

    avg_us = (elapsed_ms / 1000) * 1000
    print(f"\n[perf] 1000 次 JSON 解析: total={elapsed_ms:.3f}ms, avg={avg_us:.3f}us/parse")
    assert elapsed_ms < 50.0, f"1000 次 JSON 解析耗时 {elapsed_ms:.2f}ms 超过 50ms"
