import sys
import os
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_config import get_test_client, TestRunner

INST_ID = "BTC-USDT-SWAP"


async def cancel_all_pending(client):
    pending = await client.trade.get_pending_orders(instId=INST_ID)
    if pending:
        print(f"  清理挂单: {len(pending)} 笔")
        cancel_reqs = [{"instId": INST_ID, "ordId": o["ordId"]} for o in pending if "ordId" in o]
        if cancel_reqs:
            await client.trade.batch_cancel_orders(cancel_reqs)
            await asyncio.sleep(0.5)
    return pending


async def test_trade_interfaces(runner: TestRunner):
    client = await get_test_client()
    placed_order_ids = []
    
    try:
        print("\n=== 交易接口测试开始，先清理遗留挂单 ===")
        await cancel_all_pending(client)
        
        ticker_resp = await client.market.get_ticker(instId=INST_ID)
        print(f'测试: get_ticker(instId="{INST_ID}") [获取参考价格]')
        if not ticker_resp or "last" not in ticker_resp[0]:
            print(f"  FAIL: 无法获取ticker价格: {ticker_resp}")
            runner.total += 1
            runner.failures.append(("get_ticker", f"无法获取价格: {ticker_resp}"))
            print("  跳过下单相关测试")
        else:
            last_price = float(ticker_resp[0]["last"])
            buy_price = str(int(last_price * 0.9 * 100) / 100)
            batch_buy_price = str(int(last_price * 0.85 * 100) / 100)
            runner.passed += 1
            runner.total += 1
            print(f"  PASS: code=0 last={last_price}")
            print(f"  当前价格: {last_price}, 买单价格: {buy_price}, 批量买单价格: {batch_buy_price}")
            
            place_resp = await client.trade.place_order(
                instId=INST_ID,
                tdMode="cross",
                side="buy",
                ordType="limit",
                sz="1",
                px=buy_price
            )
            print(f'测试: place_order(instId="{INST_ID}", side="buy", ordType="limit", sz="1", px="{buy_price}")')
            if place_resp.get("code") == "0" and place_resp.get("data"):
                ord_id = place_resp["data"][0]["ordId"]
                placed_order_ids.append(ord_id)
                runner.passed += 1
                runner.total += 1
                print(f"  PASS: code=0 ordId={ord_id}")
                
                await runner.run_test(
                    f'get_order(instId="{INST_ID}", ordId="{ord_id}")',
                    client.trade.get_order(instId=INST_ID, ordId=ord_id),
                    validate=lambda r: (
                        isinstance(r, list) and len(r) > 0 and r[0].get("ordId") == ord_id,
                        f"查询订单失败: {r}"
                    )
                )
                
                await runner.run_test(
                    f'get_pending_orders(instId="{INST_ID}")',
                    client.trade.get_pending_orders(instId=INST_ID),
                    validate=lambda r: (
                        isinstance(r, list) and any(o.get("ordId") == ord_id for o in r),
                        f"订单不在挂单列表中: {r}"
                    )
                )
                
                batch_orders = [
                    {"instId": INST_ID, "side": "buy", "ordType": "limit", "sz": "1", "px": batch_buy_price, "tdMode": "cross"},
                    {"instId": INST_ID, "side": "buy", "ordType": "limit", "sz": "1", "px": batch_buy_price, "tdMode": "cross"},
                ]
                batch_resp = await client.trade.batch_place_orders(batch_orders)
                print(f"测试: batch_place_orders(2笔限价单 @ {batch_buy_price})")
                batch_ord_ids = []
                if batch_resp.get("code") == "0" and batch_resp.get("data"):
                    for o in batch_resp["data"]:
                        if "ordId" in o:
                            batch_ord_ids.append(o["ordId"])
                            placed_order_ids.append(o["ordId"])
                    runner.passed += 1
                    runner.total += 1
                    print(f"  PASS: code=0 ordIds={batch_ord_ids}")
                else:
                    runner.total += 1
                    runner.failures.append(("batch_place_orders", str(batch_resp)))
                    print(f"  FAIL: {batch_resp}")
                
                cancel_resp = await client.trade.cancel_order(instId=INST_ID, ordId=ord_id)
                print(f'测试: cancel_order(instId="{INST_ID}", ordId="{ord_id}")')
                if cancel_resp.get("code") == "0":
                    runner.passed += 1
                    runner.total += 1
                    print(f"  PASS: code=0")
                    if ord_id in placed_order_ids:
                        placed_order_ids.remove(ord_id)
                else:
                    runner.total += 1
                    runner.failures.append(("cancel_order", str(cancel_resp)))
                    print(f"  FAIL: {cancel_resp}")
                await asyncio.sleep(0.3)
                
                pending = await client.trade.get_pending_orders(instId=INST_ID)
                remaining = [o for o in pending if o.get("ordId") in batch_ord_ids]
                if remaining:
                    cancel_batch = [{"instId": INST_ID, "ordId": o["ordId"]} for o in remaining]
                    cancel_batch_resp = await client.trade.batch_cancel_orders(cancel_batch)
                    print(f"测试: batch_cancel_orders(撤销剩余{len(cancel_batch)}笔订单)")
                    if cancel_batch_resp.get("code") == "0":
                        runner.passed += 1
                        runner.total += 1
                        print(f"  PASS: code=0")
                        for o in remaining:
                            if o["ordId"] in placed_order_ids:
                                placed_order_ids.remove(o["ordId"])
                    else:
                        runner.total += 1
                        runner.failures.append(("batch_cancel_orders", str(cancel_batch_resp)))
                        print(f"  FAIL: {cancel_batch_resp}")
                    await asyncio.sleep(0.3)
            else:
                runner.total += 1
                runner.failures.append(("place_order", str(place_resp)))
                print(f"  FAIL: code={place_resp.get('code')} msg={place_resp.get('msg')}")
        
        await runner.run_test(
            f'get_orders_history(instId="{INST_ID}", limit="5")',
            client.trade.get_orders_history(instId=INST_ID, limit="5"),
            validate=lambda r: (isinstance(r, list), f"应返回list，实际: {type(r)}")
        )
        
        await runner.run_test(
            f'get_fills(instId="{INST_ID}", limit="5")',
            client.trade.get_fills(instId=INST_ID, limit="5"),
            validate=lambda r: (isinstance(r, list), f"应返回list，实际: {type(r)}")
        )
        
    finally:
        print("\n=== 测试结束，最终清理所有挂单 ===")
        for attempt in range(3):
            final_pending = await client.trade.get_pending_orders(instId=INST_ID)
            if not final_pending:
                break
            print(f"  尝试清理 {len(final_pending)} 笔挂单...")
            cancel_reqs = [{"instId": INST_ID, "ordId": o["ordId"]} for o in final_pending if "ordId" in o]
            if cancel_reqs:
                await client.trade.batch_cancel_orders(cancel_reqs)
                await asyncio.sleep(0.5)
        
        final_check = await client.trade.get_pending_orders(instId=INST_ID)
        if final_check:
            print(f"  警告: 仍有 {len(final_check)} 笔挂单未撤销!")
        else:
            print("  OK: 无遗留挂单")
        await client.aclose()


if __name__ == "__main__":
    async def main():
        runner = TestRunner()
        await test_trade_interfaces(runner)
        runner.print_summary("交易接口测试")

    asyncio.run(main())


# ============================================================================
# 单元测试（Mock httpx，不依赖真实 OKX 账户）
# 下方测试通过 Mock OKXBaseClient._request 验证 set_leverage 的请求参数与错误处理
# ============================================================================

import pytest
from unittest.mock import AsyncMock, MagicMock

from services.okx.trade import TradeAPI
from services.okx.exceptions import OKXAPIException


# 上方 test_trade_interfaces(runner) 为集成测试，需通过 run_tests.py 或 __main__ 运行。
# 此 fixture 让其在 pytest 下被跳过（而非因缺少 fixture 报错）；直接调用不受影响。
@pytest.fixture
def runner():
    pytest.skip("集成测试需通过 run_tests.py 或 python tests/test_trade.py 运行")


def _make_trade_api_with_mock():
    """构造一个绑定 Mock 基类客户端的 TradeAPI。"""
    mock_client = MagicMock()
    mock_client._request = AsyncMock()
    return TradeAPI(mock_client), mock_client


async def test_set_leverage_request_params_cross():
    """全仓模式：lever(int) 转 str，posSide 不传。"""
    api, mock_client = _make_trade_api_with_mock()
    mock_client._request.return_value = {
        "code": "0", "msg": "",
        "data": [{"instId": "ETH-USDT-SWAP", "lever": "10", "mgnMode": "cross"}],
    }
    resp = await api.set_leverage("ETH-USDT-SWAP", 10, "cross")
    assert resp["code"] == "0"
    mock_client._request.assert_awaited_once()
    call = mock_client._request.call_args
    assert call.args[0] == "POST"
    assert call.args[1] == "/api/v5/account/set-leverage"
    body = call.kwargs["body"]
    assert body["instId"] == "ETH-USDT-SWAP"
    assert body["lever"] == "10"  # int -> str
    assert body["mgnMode"] == "cross"
    assert "posSide" not in body  # 单向持仓不传 posSide
    assert call.kwargs["is_private"] is True


async def test_set_leverage_request_params_dual_side():
    """双向持仓：pos_side 传入且 mgn_mode 可为 isolated。"""
    api, mock_client = _make_trade_api_with_mock()
    mock_client._request.return_value = {"code": "0", "msg": "", "data": []}
    await api.set_leverage("ETH-USDT-SWAP", 5, mgn_mode="isolated", pos_side="long")
    body = mock_client._request.call_args.kwargs["body"]
    assert body["mgnMode"] == "isolated"
    assert body["posSide"] == "long"
    assert body["lever"] == "5"


async def test_set_leverage_default_mgn_mode():
    """默认 mgn_mode=cross。"""
    api, mock_client = _make_trade_api_with_mock()
    mock_client._request.return_value = {"code": "0", "msg": "", "data": []}
    await api.set_leverage("ETH-USDT-SWAP", 3)
    body = mock_client._request.call_args.kwargs["body"]
    assert body["mgnMode"] == "cross"


async def test_set_leverage_error_raises():
    """code!=0 时抛 OKXAPIException，msg 含错误码映射后的可读描述。"""
    api, mock_client = _make_trade_api_with_mock()
    mock_client._request.return_value = {
        "code": "51108",
        "msg": "Leverage out of valid range",
        "_error_desc": "杠杆不在有效范围内",
        "data": [],
    }
    with pytest.raises(OKXAPIException) as exc_info:
        await api.set_leverage("ETH-USDT-SWAP", 999)
    assert exc_info.value.code == "51108"
    assert "杠杆不在有效范围内" in exc_info.value.msg
    assert exc_info.value.endpoint == "/api/v5/account/set-leverage"

