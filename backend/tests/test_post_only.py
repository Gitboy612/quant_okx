"""post_only（只挂 maker）下单选项单元测试（Task 9）。

覆盖：
- post_only=True 时下单 payload ordType=post_only
- post_only=False（默认）时 payload ordType=limit
- post_only 被拒时降级为 limit 重挂 + 记录 post_only_rejected 事件
- 重挂次数上限（最多 3 轮）
- _on_order_filled 买单/卖单分支使用 post_only

参考 test_grid_responsiveness.py 风格，用 Mock client + Mock db_session_factory。
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from strategies.grid_strategy import GridStrategy
from services.order_manager import OrderInfo


# ============================================================
# 辅助构造
# ============================================================


def _base_params(post_only: bool = False) -> dict:
    """网格策略最小参数集。"""
    params = {
        "symbol": "BTC-USDT",
        "upper_price": 110.0,
        "lower_price": 90.0,
        "grid_count": 3,
        "order_qty": 1.0,
    }
    if post_only:
        params["post_only"] = True
    return params


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
            return_value={"code": "0", "data": [{"sCode": "0", "ordId": "ord1"}]}
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
# SubTask 9.1: post_only 参数与下单 payload
# ============================================================


async def test_place_grid_orders_post_only_payload_ordType():
    """post_only=True 时 _place_grid_orders 下单 payload ordType=post_only。"""
    strategy, client, _, _ = _make_strategy(_base_params(post_only=True))
    _setup_grid_state(strategy)

    await strategy._place_grid_orders("BTC-USDT", current_price=100.0)

    client.batch_place_orders.assert_awaited()
    # 检查所有调用中 payload 的 ordType 都是 post_only
    for call in client.batch_place_orders.call_args_list:
        payloads = call.args[0]
        for p in payloads:
            assert p["ordType"] == "post_only", f"期望 ordType=post_only, 实际 {p['ordType']}"


async def test_place_grid_orders_default_uses_limit():
    """post_only=False（默认）时 _place_grid_orders 下单 payload ordType=limit。"""
    strategy, client, _, _ = _make_strategy(_base_params(post_only=False))
    _setup_grid_state(strategy)

    await strategy._place_grid_orders("BTC-USDT", current_price=100.0)

    client.batch_place_orders.assert_awaited()
    for call in client.batch_place_orders.call_args_list:
        payloads = call.args[0]
        for p in payloads:
            assert p["ordType"] == "limit", f"期望 ordType=limit, 实际 {p['ordType']}"


async def test_on_order_filled_buy_post_only_payload():
    """post_only=True 时 _on_order_filled 买单分支下单 payload ordType=post_only。"""
    strategy, client, _, _ = _make_strategy(_base_params(post_only=True))
    _setup_grid_state(strategy)
    # 成交价 90.0 对应 grid_idx=0
    order_info = OrderInfo(
        ordId="buy123", symbol="BTC-USDT", side="buy", px="90", sz="1", state="filled"
    )

    await strategy._on_order_filled(order_info)

    client.batch_place_orders.assert_awaited()
    payloads = client.batch_place_orders.call_args.args[0]
    assert len(payloads) == 1
    assert payloads[0]["ordType"] == "post_only"
    assert payloads[0]["side"] == "sell"


async def test_on_order_filled_sell_post_only_payload():
    """post_only=True 时 _on_order_filled 卖单分支下单 payload ordType=post_only。"""
    strategy, client, _, _ = _make_strategy(_base_params(post_only=True))
    _setup_grid_state(strategy)
    # 成交价 110.0 对应 grid_idx=2，买单挂在 100.0
    order_info = OrderInfo(
        ordId="sell123", symbol="BTC-USDT", side="sell", px="110", sz="1", state="filled"
    )

    await strategy._on_order_filled(order_info)

    client.batch_place_orders.assert_awaited()
    payloads = client.batch_place_orders.call_args.args[0]
    assert len(payloads) == 1
    assert payloads[0]["ordType"] == "post_only"
    assert payloads[0]["side"] == "buy"


# ============================================================
# SubTask 9.2: post_only 被拒时降级为 limit 重挂
# ============================================================


async def test_post_only_rejected_downgrade_to_limit():
    """post_only 被拒时降级为 limit 重挂，并记录 post_only_rejected 事件。"""
    # 第一次调用返回 post_only 被拒（sCode=51031），第二次（limit 重挂）成功
    rejected_resp = {
        "code": "0",
        "data": [{"sCode": "51031", "sMsg": "Order will be executed immediately"}],
    }
    success_resp = {
        "code": "0",
        "data": [{"sCode": "0", "ordId": "retry_ord1"}],
    }

    strategy, client, _, _ = _make_strategy(_base_params(post_only=True))
    _setup_grid_state(strategy)
    strategy._record_event = MagicMock()
    client.batch_place_orders = AsyncMock(side_effect=[rejected_resp, success_resp])

    # current_price=120 使全部 3 档均为买单（level < price），只产生 1 个 batch
    await strategy._place_grid_orders("BTC-USDT", current_price=120.0)

    # 应被调用两次：初始 post_only + 降级 limit 重挂
    assert client.batch_place_orders.await_count >= 2
    # 第一次 payload ordType=post_only
    first_payloads = client.batch_place_orders.call_args_list[0].args[0]
    assert first_payloads[0]["ordType"] == "post_only"
    # 第二次（重挂）payload ordType=limit（降级）
    retry_payloads = client.batch_place_orders.call_args_list[1].args[0]
    assert retry_payloads[0]["ordType"] == "limit"

    # 验证 post_only_rejected 事件被记录
    event_types = [call.args[0] for call in strategy._record_event.call_args_list]
    assert "post_only_rejected" in event_types
    # 验证事件 details 含降级行为
    rejected_call = next(
        c for c in strategy._record_event.call_args_list if c.args[0] == "post_only_rejected"
    )
    details = rejected_call.args[2]
    assert details["downgrade"] == "limit"
    assert details["sCode"] == "51031"

    # 验证重挂后订单被正确跟踪（grid_idx=0 是买单，level=90 < 100）
    # 买单 idx=0 重挂成功后应记录 ordId
    assert strategy._active_buy_orders.get(0) == "retry_ord1"


async def test_post_only_rejected_by_smsg_post_keyword():
    """sMsg 含 'post' 关键字时也识别为 post_only 被拒。"""
    rejected_resp = {
        "code": "0",
        "data": [{"sCode": "51500", "sMsg": "post_only order rejected"}],
    }
    success_resp = {
        "code": "0",
        "data": [{"sCode": "0", "ordId": "retry_ord2"}],
    }

    strategy, client, _, _ = _make_strategy(_base_params(post_only=True))
    _setup_grid_state(strategy)
    strategy._record_event = MagicMock()
    client.batch_place_orders = AsyncMock(side_effect=[rejected_resp, success_resp])

    # current_price=120 使全部 3 档均为买单（level < price），只产生 1 个 batch
    await strategy._place_grid_orders("BTC-USDT", current_price=120.0)

    event_types = [call.args[0] for call in strategy._record_event.call_args_list]
    assert "post_only_rejected" in event_types


async def test_post_only_not_rejected_no_retry():
    """post_only 订单成功时不会触发重挂（batch_place_orders 只调用一次）。"""
    success_resp = {
        "code": "0",
        "data": [{"sCode": "0", "ordId": "ok_ord1"}],
    }

    strategy, client, _, _ = _make_strategy(_base_params(post_only=True))
    _setup_grid_state(strategy)
    client.batch_place_orders = AsyncMock(return_value=success_resp)

    # current_price=120 使全部 3 档均为买单，只产生 1 个 batch
    await strategy._place_grid_orders("BTC-USDT", current_price=120.0)

    # 只调用一次（初始 post_only），无重挂
    assert client.batch_place_orders.await_count == 1


async def test_non_post_only_failure_no_retry():
    """非 post_only 相关的失败（如余额不足）不触发降级重挂。"""
    # sCode=51011 是余额不足，不是 post_only 被拒
    rejected_resp = {
        "code": "0",
        "data": [{"sCode": "51011", "sMsg": "Insufficient balance"}],
    }

    strategy, client, _, _ = _make_strategy(_base_params(post_only=True))
    _setup_grid_state(strategy)
    strategy._record_event = MagicMock()
    client.batch_place_orders = AsyncMock(return_value=rejected_resp)

    # current_price=120 使全部 3 档均为买单，只产生 1 个 batch
    await strategy._place_grid_orders("BTC-USDT", current_price=120.0)

    # 只调用一次，不重挂
    assert client.batch_place_orders.await_count == 1
    # 不应有 post_only_rejected 事件
    event_types = [call.args[0] for call in strategy._record_event.call_args_list]
    assert "post_only_rejected" not in event_types


# ============================================================
# SubTask 9.2: 重挂次数上限
# ============================================================


async def test_post_only_retry_exhausted():
    """post_only 持续被拒时最多重挂 3 次，之后记录 post_only_retry_exhausted 事件。"""
    rejected_resp = {
        "code": "0",
        "data": [{"sCode": "51031", "sMsg": "Order will be executed immediately"}],
    }

    strategy, client, _, _ = _make_strategy(_base_params(post_only=True))
    _setup_grid_state(strategy)
    strategy._record_event = MagicMock()
    # 每次都返回被拒
    client.batch_place_orders = AsyncMock(return_value=rejected_resp)

    # current_price=120 使全部 3 档均为买单，只产生 1 个 batch
    await strategy._place_grid_orders("BTC-USDT", current_price=120.0)

    # 初始 1 次 + 重挂最多 3 次 = 4 次（第 3 次重挂后达到上限不再重挂）
    # 实际：attempt 0 → 重挂1, attempt 1 → 重挂2, attempt 2 → 达到上限不再重挂
    # 所以 batch_place_orders 调用 = 初始1 + 重挂2 = 3 次
    assert client.batch_place_orders.await_count == 3

    # 验证 post_only_retry_exhausted 事件
    event_types = [call.args[0] for call in strategy._record_event.call_args_list]
    assert "post_only_retry_exhausted" in event_types

    # 验证 post_only_rejected 事件被记录多次（每轮重挂都记录）
    rejected_count = sum(
        1 for c in strategy._record_event.call_args_list if c.args[0] == "post_only_rejected"
    )
    assert rejected_count == 3  # 3 轮各记录一次


async def test_post_only_retry_limit_max_3():
    """重挂次数上限为 3：验证不会无限重挂。"""
    rejected_resp = {
        "code": "0",
        "data": [{"sCode": "51031", "sMsg": "Order will be executed immediately"}],
    }

    strategy, client, _, _ = _make_strategy(_base_params(post_only=True))
    _setup_grid_state(strategy)
    strategy._record_event = MagicMock()
    client.batch_place_orders = AsyncMock(return_value=rejected_resp)

    # current_price=120 使全部 3 档均为买单，只产生 1 个 batch
    await strategy._place_grid_orders("BTC-USDT", current_price=120.0)

    # 初始 1 + 重挂 2 = 3 次（max_retries=3 但第 3 轮只记录不重挂）
    assert client.batch_place_orders.await_count <= 4  # 安全上限


# ============================================================
# _is_post_only_rejection 单元测试
# ============================================================


def test_is_post_only_rejection_by_scode():
    """sCode=51031 识别为 post_only 被拒。"""
    strategy, _, _, _ = _make_strategy(_base_params(post_only=True))
    assert strategy._is_post_only_rejection("51031", "") is True


def test_is_post_only_rejection_by_smsg_post():
    """sMsg 含 'post' 识别为 post_only 被拒。"""
    strategy, _, _, _ = _make_strategy(_base_params(post_only=True))
    assert strategy._is_post_only_rejection("51500", "post_only order rejected") is True


def test_is_post_only_rejection_by_smsg_chinese():
    """sMsg 含 '立即成交' 识别为 post_only 被拒。"""
    strategy, _, _, _ = _make_strategy(_base_params(post_only=True))
    assert strategy._is_post_only_rejection("51500", "订单会立即成交") is True


def test_is_post_only_rejection_success():
    """sCode=0 不识别为被拒。"""
    strategy, _, _, _ = _make_strategy(_base_params(post_only=True))
    assert strategy._is_post_only_rejection("0", "Success") is False


def test_is_post_only_rejection_other_error():
    """非 post_only 相关错误码不识别为被拒。"""
    strategy, _, _, _ = _make_strategy(_base_params(post_only=True))
    assert strategy._is_post_only_rejection("51011", "Insufficient balance") is False


# ============================================================
# _on_order_filled 被拒降级测试
# ============================================================


async def test_on_order_filled_buy_post_only_rejected_downgrade():
    """_on_order_filled 买单分支 post_only 被拒时降级为 limit 重挂。"""
    rejected_resp = {
        "code": "0",
        "data": [{"sCode": "51031", "sMsg": "Order will be executed immediately"}],
    }
    success_resp = {
        "code": "0",
        "data": [{"sCode": "0", "ordId": "sell_retry"}],
    }

    strategy, client, _, _ = _make_strategy(_base_params(post_only=True))
    _setup_grid_state(strategy)
    strategy._record_event = MagicMock()
    client.batch_place_orders = AsyncMock(side_effect=[rejected_resp, success_resp])

    order_info = OrderInfo(
        ordId="buy123", symbol="BTC-USDT", side="buy", px="90", sz="1", state="filled"
    )
    await strategy._on_order_filled(order_info)

    # 两次调用：初始 post_only + 降级 limit
    assert client.batch_place_orders.await_count == 2
    # 验证 post_only_rejected 事件
    event_types = [call.args[0] for call in strategy._record_event.call_args_list]
    assert "post_only_rejected" in event_types
    # 验证重挂后卖单被正确跟踪
    assert strategy._active_sell_orders.get(1) == "sell_retry"


async def test_on_order_filled_sell_post_only_rejected_downgrade():
    """_on_order_filled 卖单分支 post_only 被拒时降级为 limit 重挂。"""
    rejected_resp = {
        "code": "0",
        "data": [{"sCode": "51031", "sMsg": "Order will be executed immediately"}],
    }
    success_resp = {
        "code": "0",
        "data": [{"sCode": "0", "ordId": "buy_retry"}],
    }

    strategy, client, _, _ = _make_strategy(_base_params(post_only=True))
    _setup_grid_state(strategy)
    strategy._record_event = MagicMock()
    client.batch_place_orders = AsyncMock(side_effect=[rejected_resp, success_resp])

    order_info = OrderInfo(
        ordId="sell123", symbol="BTC-USDT", side="sell", px="110", sz="1", state="filled"
    )
    await strategy._on_order_filled(order_info)

    # 两次调用：初始 post_only + 降级 limit
    assert client.batch_place_orders.await_count == 2
    # 验证 post_only_rejected 事件
    event_types = [call.args[0] for call in strategy._record_event.call_args_list]
    assert "post_only_rejected" in event_types
    # 验证重挂后买单被正确跟踪
    assert strategy._active_buy_orders.get(1) == "buy_retry"
