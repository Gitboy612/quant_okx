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
