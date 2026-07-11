"""Tests for the public WebSocket channel support and MarketDataService.

Covers:
1. OKXPublicWsClient.subscribe_ticker / unsubscribe_ticker (mocked WebSocket)
2. OKXPublicWsClient._handle_data ticker dispatch
3. OKXPublicWsClient.subscribe_candle interval mapping
4. MarketDataService reference counting (multi-subscriber single channel)
5. MarketDataService ticker cache update
6. MarketDataService callback fan-out
"""
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import AsyncMock, MagicMock

import pytest

from services.okx_ws_client import OKXPublicWsClient, CANDLE_INTERVALS
from services.market_data_service import MarketDataService


# ============================================================
# OKXPublicWsClient tests
# ============================================================


def _make_public_client() -> OKXPublicWsClient:
    """Create an OKXPublicWsClient with a mocked WebSocket (no real connection)."""
    client = OKXPublicWsClient(trade_mode="live")
    # Simulate a connected state without hitting the network.
    client._connected = True
    client._ws = MagicMock()
    client._ws.send = AsyncMock()
    return client


@pytest.mark.asyncio
async def test_subscribe_ticker_sends_correct_message():
    """subscribe_ticker sends the OKX-formatted subscribe message."""
    client = _make_public_client()

    await client.subscribe_ticker(["BTC-USDT"])

    # Exactly one subscribe message sent.
    assert client._ws.send.call_count == 1
    sent = json.loads(client._ws.send.call_args.args[0])
    assert sent["op"] == "subscribe"
    assert sent["args"] == [{"channel": "tickers", "instId": "BTC-USDT"}]


@pytest.mark.asyncio
async def test_subscribe_ticker_multiple_symbols():
    """subscribe_ticker with multiple symbols sends one message per symbol."""
    client = _make_public_client()

    await client.subscribe_ticker(["BTC-USDT", "ETH-USDT"])

    assert client._ws.send.call_count == 2
    channels = []
    for call in client._ws.send.call_args_list:
        msg = json.loads(call.args[0])
        assert msg["op"] == "subscribe"
        channels.append(msg["args"][0]["instId"])
    assert set(channels) == {"BTC-USDT", "ETH-USDT"}


@pytest.mark.asyncio
async def test_subscribe_ticker_tracks_subscriptions():
    """Subscriptions are tracked for re-subscribe on reconnect."""
    client = _make_public_client()

    await client.subscribe_ticker(["BTC-USDT"])

    assert {"channel": "tickers", "instId": "BTC-USDT"} in client._public_subscriptions


@pytest.mark.asyncio
async def test_unsubscribe_ticker_sends_correct_message():
    """unsubscribe_ticker sends the OKX-formatted unsubscribe message."""
    client = _make_public_client()

    await client.subscribe_ticker(["BTC-USDT"])
    client._ws.send.reset_mock()

    await client.unsubscribe_ticker(["BTC-USDT"])

    assert client._ws.send.call_count == 1
    sent = json.loads(client._ws.send.call_args.args[0])
    assert sent["op"] == "unsubscribe"
    assert sent["args"] == [{"channel": "tickers", "instId": "BTC-USDT"}]


@pytest.mark.asyncio
async def test_unsubscribe_removes_from_subscriptions():
    """Unsubscribing removes the entry from _public_subscriptions."""
    client = _make_public_client()

    await client.subscribe_ticker(["BTC-USDT"])
    assert len(client._public_subscriptions) == 1

    await client.unsubscribe_ticker(["BTC-USDT"])
    assert len(client._public_subscriptions) == 0


@pytest.mark.asyncio
async def test_subscribe_candle_interval_mapping():
    """subscribe_candle maps short interval labels to OKX channel names."""
    client = _make_public_client()

    await client.subscribe_candle(["BTC-USDT"], interval="5m")

    sent = json.loads(client._ws.send.call_args.args[0])
    assert sent["args"][0]["channel"] == "candle5m"


@pytest.mark.asyncio
async def test_subscribe_candle_all_intervals():
    """All intervals in CANDLE_INTERVALS produce correct channel names."""
    client = _make_public_client()

    for short, full in CANDLE_INTERVALS.items():
        client._ws.send.reset_mock()
        await client.subscribe_candle(["BTC-USDT"], interval=short)
        sent = json.loads(client._ws.send.call_args.args[0])
        assert sent["args"][0]["channel"] == full


@pytest.mark.asyncio
async def test_subscribe_books():
    """subscribe_books sends the correct books channel subscription."""
    client = _make_public_client()

    await client.subscribe_books(["ETH-USDT"])

    sent = json.loads(client._ws.send.call_args.args[0])
    assert sent["op"] == "subscribe"
    assert sent["args"] == [{"channel": "books", "instId": "ETH-USDT"}]


@pytest.mark.asyncio
async def test_handle_data_ticker_dispatch():
    """_handle_data dispatches ticker data to registered callbacks."""
    client = OKXPublicWsClient(trade_mode="live")
    received = []
    client.on_ticker_update(lambda data: received.append(data))

    msg = {
        "arg": {"channel": "tickers", "instId": "BTC-USDT"},
        "data": [{"instId": "BTC-USDT", "last": "45000.5", "bidPx": "45000.0"}],
    }
    await client._handle_data(msg)

    assert len(received) == 1
    assert received[0]["instId"] == "BTC-USDT"
    assert received[0]["last"] == "45000.5"


@pytest.mark.asyncio
async def test_handle_data_ticker_multiple_callbacks():
    """Multiple ticker callbacks are all invoked."""
    client = OKXPublicWsClient(trade_mode="live")
    calls_a = []
    calls_b = []
    client.on_ticker_update(lambda data: calls_a.append(data))
    client.on_ticker_update(lambda data: calls_b.append(data))

    msg = {
        "arg": {"channel": "tickers", "instId": "BTC-USDT"},
        "data": [{"instId": "BTC-USDT", "last": "46000"}],
    }
    await client._handle_data(msg)

    assert len(calls_a) == 1
    assert len(calls_b) == 1


@pytest.mark.asyncio
async def test_handle_data_candle_dispatch():
    """_handle_data dispatches candle data with inst_id and channel name."""
    client = OKXPublicWsClient(trade_mode="live")
    received = []
    client.on_candle_update(lambda inst_id, channel, candle: received.append((inst_id, channel, candle)))

    msg = {
        "arg": {"channel": "candle1m", "instId": "BTC-USDT"},
        "data": [["1234567890", "45000", "45100", "44900", "45050", "1.5"]],
    }
    await client._handle_data(msg)

    assert len(received) == 1
    assert received[0][0] == "BTC-USDT"
    assert received[0][1] == "candle1m"
    assert received[0][2][0] == "1234567890"


@pytest.mark.asyncio
async def test_handle_data_books_dispatch():
    """_handle_data dispatches order-book data."""
    client = OKXPublicWsClient(trade_mode="live")
    received = []
    client.on_books_update(lambda inst_id, books: received.append((inst_id, books)))

    msg = {
        "arg": {"channel": "books", "instId": "BTC-USDT"},
        "data": [{"bids": [["45000", "1"]], "asks": [["45001", "0.5"]]}],
    }
    await client._handle_data(msg)

    assert len(received) == 1
    assert received[0][0] == "BTC-USDT"
    assert "bids" in received[0][1]


@pytest.mark.asyncio
async def test_subscribe_no_send_when_disconnected():
    """subscribe_ticker does not send when not connected (only records subscription)."""
    client = OKXPublicWsClient(trade_mode="live")
    client._connected = False
    client._ws = None

    # Should not raise even though ws is None.
    await client.subscribe_ticker(["BTC-USDT"])

    # Subscription recorded for later re-subscribe.
    assert {"channel": "tickers", "instId": "BTC-USDT"} in client._public_subscriptions


# ============================================================
# MarketDataService tests
# ============================================================


@pytest.fixture
def fresh_mds():
    """Provide a fresh MarketDataService singleton (isolated from other tests)."""
    saved = MarketDataService._instance
    MarketDataService._instance = None
    service = MarketDataService()
    # Inject a mock ws_client so _ensure_client doesn't try to connect.
    service._ws_client = MagicMock()
    service._ws_client.subscribe_ticker = AsyncMock()
    service._ws_client.unsubscribe_ticker = AsyncMock()
    yield service
    # Restore original singleton.
    MarketDataService._instance = saved


@pytest.mark.asyncio
async def test_mds_subscribe_ticker_calls_ws_once(fresh_mds):
    """First subscriber triggers exactly one ws_client.subscribe_ticker call."""
    cb = MagicMock()
    await fresh_mds.subscribe_ticker("BTC-USDT", cb)

    fresh_mds._ws_client.subscribe_ticker.assert_awaited_once_with(["BTC-USDT"])
    assert fresh_mds._ticker_subscribers["BTC-USDT"] == 1


@pytest.mark.asyncio
async def test_mds_reference_counting_multi_subscribe(fresh_mds):
    """Two subscribers for the same symbol → only one ws subscribe call."""
    cb1 = MagicMock()
    cb2 = MagicMock()
    await fresh_mds.subscribe_ticker("BTC-USDT", cb1)
    await fresh_mds.subscribe_ticker("BTC-USDT", cb2)

    # WebSocket subscribe called only once (reference counting).
    fresh_mds._ws_client.subscribe_ticker.assert_awaited_once_with(["BTC-USDT"])
    assert fresh_mds._ticker_subscribers["BTC-USDT"] == 2


@pytest.mark.asyncio
async def test_mds_unsubscribe_partial(fresh_mds):
    """Unsubscribing one of two callbacks does NOT trigger ws unsubscribe."""
    cb1 = MagicMock()
    cb2 = MagicMock()
    await fresh_mds.subscribe_ticker("BTC-USDT", cb1)
    await fresh_mds.subscribe_ticker("BTC-USDT", cb2)

    await fresh_mds.unsubscribe_ticker("BTC-USDT", cb1)

    # WebSocket unsubscribe NOT called (count still 1).
    fresh_mds._ws_client.unsubscribe_ticker.assert_not_awaited()
    assert fresh_mds._ticker_subscribers["BTC-USDT"] == 1


@pytest.mark.asyncio
async def test_mds_unsubscribe_last_triggers_ws_unsubscribe(fresh_mds):
    """Unsubscribing the last subscriber triggers ws unsubscribe + cache clear."""
    cb1 = MagicMock()
    cb2 = MagicMock()
    await fresh_mds.subscribe_ticker("BTC-USDT", cb1)
    await fresh_mds.subscribe_ticker("BTC-USDT", cb2)

    await fresh_mds.unsubscribe_ticker("BTC-USDT", cb1)
    await fresh_mds.unsubscribe_ticker("BTC-USDT", cb2)

    # WebSocket unsubscribe called when count reaches zero.
    fresh_mds._ws_client.unsubscribe_ticker.assert_awaited_once_with(["BTC-USDT"])
    assert "BTC-USDT" not in fresh_mds._ticker_subscribers
    assert fresh_mds.get_latest_ticker("BTC-USDT") is None


@pytest.mark.asyncio
async def test_mds_ticker_cache_update(fresh_mds):
    """_on_ticker_data caches the latest ticker for get_latest_ticker."""
    # Inject ticker data directly (simulates a WS push).
    fresh_mds._on_ticker_data({"instId": "BTC-USDT", "last": "45000.5"})

    cached = fresh_mds.get_latest_ticker("BTC-USDT")
    assert cached is not None
    assert cached["last"] == "45000.5"


@pytest.mark.asyncio
async def test_mds_ticker_cache_overwrite(fresh_mds):
    """Successive ticker pushes overwrite the cache."""
    fresh_mds._on_ticker_data({"instId": "BTC-USDT", "last": "45000"})
    fresh_mds._on_ticker_data({"instId": "BTC-USDT", "last": "46000"})

    cached = fresh_mds.get_latest_ticker("BTC-USDT")
    assert cached["last"] == "46000"


@pytest.mark.asyncio
async def test_mds_callback_fanout(fresh_mds):
    """Registered callbacks are invoked when ticker data arrives."""
    received = []
    cb = lambda data: received.append(data)
    await fresh_mds.subscribe_ticker("BTC-USDT", cb)

    fresh_mds._on_ticker_data({"instId": "BTC-USDT", "last": "45000"})

    assert len(received) == 1
    assert received[0]["last"] == "45000"


@pytest.mark.asyncio
async def test_mds_callback_only_for_subscribed_symbol(fresh_mds):
    """Callbacks for symbol A are not invoked when data arrives for symbol B."""
    received_a = []
    received_b = []
    await fresh_mds.subscribe_ticker("BTC-USDT", lambda d: received_a.append(d))
    await fresh_mds.subscribe_ticker("ETH-USDT", lambda d: received_b.append(d))

    fresh_mds._on_ticker_data({"instId": "BTC-USDT", "last": "45000"})

    assert len(received_a) == 1
    assert len(received_b) == 0


@pytest.mark.asyncio
async def test_mds_get_latest_ticker_returns_none_for_unknown(fresh_mds):
    """get_latest_ticker returns None for a symbol with no data."""
    assert fresh_mds.get_latest_ticker("UNKNOWN-USDT") is None


@pytest.mark.asyncio
async def test_mds_unsubscribe_unknown_callback_is_safe(fresh_mds):
    """Unsubscribing a callback that was never registered does not crash."""
    cb_registered = MagicMock()
    cb_unknown = MagicMock()
    await fresh_mds.subscribe_ticker("BTC-USDT", cb_registered)

    # Should not raise.
    await fresh_mds.unsubscribe_ticker("BTC-USDT", cb_unknown)

    # Reference count unchanged.
    assert fresh_mds._ticker_subscribers["BTC-USDT"] == 1
