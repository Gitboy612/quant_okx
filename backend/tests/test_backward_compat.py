import sys
import os
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_config import get_test_client, TestRunner


async def test_backward_compat(runner: TestRunner):
    client = await get_test_client()
    try:
        runner.check(
            "client.api_key 存在",
            hasattr(client, "api_key") and isinstance(client.api_key, str),
            "api_key 不存在或类型错误",
            f"前缀: {client.api_key[:8]}..."
        )
        
        runner.check(
            "client.secret_key 存在",
            hasattr(client, "secret_key") and isinstance(client.secret_key, str),
            "secret_key 不存在或类型错误"
        )
        
        runner.check(
            "client.passphrase 存在",
            hasattr(client, "passphrase") and isinstance(client.passphrase, str),
            "passphrase 不存在或类型错误"
        )
        
        runner.check(
            "client.public 存在",
            hasattr(client, "public") and client.public is not None,
            "public 不存在"
        )
        
        runner.check(
            "client.market 存在",
            hasattr(client, "market") and client.market is not None,
            "market 不存在"
        )
        
        runner.check(
            "client.account 存在",
            hasattr(client, "account") and client.account is not None,
            "account 不存在"
        )
        
        runner.check(
            "client.trade 存在",
            hasattr(client, "trade") and client.trade is not None,
            "trade 不存在"
        )
        
        runner.check(
            "client.funding 存在",
            hasattr(client, "funding") and client.funding is not None,
            "funding 不存在"
        )
        
        await runner.run_test(
            "get_balance() 返回dict，包含totalEq和details",
            client.get_balance(),
            validate=lambda r: (
                isinstance(r, dict) and "totalEq" in r and "details" in r,
                f"返回格式异常: {type(r)} keys={list(r.keys()) if isinstance(r, dict) else 'N/A'}"
            )
        )
        
        await runner.run_test(
            "get_positions() 返回list",
            client.get_positions(),
            validate=lambda r: (isinstance(r, list), f"应返回list，实际: {type(r)}")
        )
        
        await runner.run_test(
            'get_ticker(inst_id="BTC-USDT-SWAP") 下划线参数',
            client.get_ticker(inst_id="BTC-USDT-SWAP"),
            validate=lambda r: (
                isinstance(r, list) and len(r) > 0 and "last" in r[0],
                f"返回异常: {r}"
            )
        )
        
        await runner.run_test(
            'get_candles(inst_id="BTC-USDT-SWAP", bar="1m", limit="3") 下划线参数',
            client.get_candles(inst_id="BTC-USDT-SWAP", bar="1m", limit="3"),
            validate=lambda r: (
                isinstance(r, list) and len(r) == 3,
                f"应返回3根K线: {len(r) if isinstance(r, list) else type(r)}"
            )
        )
        
        runner.check(
            "client._request 同步方法存在且可调用",
            hasattr(client, "_request") and callable(client._request),
            "_request 不存在或不可调用"
        )
        
        print("  调用同步_request获取账户余额...")
        try:
            bal_resp = client._request("GET", "/api/v5/account/balance")
            print("测试: _request('GET', '/api/v5/account/balance')")
            if bal_resp.get("code") == "0" and bal_resp.get("data"):
                runner.passed += 1
                runner.total += 1
                total_eq = bal_resp["data"][0].get("totalEq", "0")
                print(f"  PASS: code=0 totalEq={total_eq}")
            else:
                runner.total += 1
                runner.failures.append(("_request", str(bal_resp)))
                print(f"  FAIL: {bal_resp}")
        except Exception as e:
            runner.total += 1
            runner.failures.append(("_request", str(e)))
            print(f"  FAIL: {str(e)}")
        
    finally:
        await client.aclose()


if __name__ == "__main__":
    async def main():
        runner = TestRunner()
        await test_backward_compat(runner)
        runner.print_summary("向后兼容测试")
    
    asyncio.run(main())
