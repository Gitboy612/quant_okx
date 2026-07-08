import sys
import os
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_config import get_public_client, TestRunner


async def test_public_interfaces(runner: TestRunner):
    base_client = get_public_client()
    from services.okx.public import PublicAPI
    public_api = PublicAPI(base_client)
    
    try:
        await runner.run_test(
            "get_server_time()",
            public_api.get_server_time(),
            validate=lambda r: (len(r) > 0 and "ts" in r[0], f"返回数据异常: {r}")
        )
        
        await runner.run_test(
            'get_instruments(instType="SWAP")',
            public_api.get_instruments(instType="SWAP"),
            validate=lambda r: (isinstance(r, list), f"应返回list，实际: {type(r)}")
        )
        
        await runner.run_test(
            'get_funding_rate(instId="BTC-USDT-SWAP")',
            public_api.get_funding_rate(instId="BTC-USDT-SWAP"),
            validate=lambda r: (len(r) > 0 and "fundingRate" in r[0], f"返回数据异常: {r}")
        )
        
        await runner.run_test(
            'get_funding_rate_history(instId="BTC-USDT-SWAP", limit="3")',
            public_api.get_funding_rate_history(instId="BTC-USDT-SWAP", limit="3"),
            validate=lambda r: (isinstance(r, list) and len(r) >= 1, f"返回数据异常: {r}")
        )
        
        await runner.run_test(
            'get_mark_price(instType="SWAP")',
            public_api.get_mark_price(instType="SWAP"),
            validate=lambda r: (isinstance(r, list), f"应返回list，实际: {type(r)}")
        )
        
        await runner.run_test(
            'get_open_interest(instType="SWAP", instId="BTC-USDT-SWAP")',
            public_api.get_open_interest(instType="SWAP", instId="BTC-USDT-SWAP"),
            validate=lambda r: (len(r) > 0 and "oi" in r[0], f"返回数据异常: {r}")
        )
        
        await runner.run_test(
            "get_system_status()",
            public_api.get_system_status(),
            validate=lambda r: (isinstance(r, list), f"应返回list，实际: {type(r)}")
        )
    finally:
        await base_client.aclose()


if __name__ == "__main__":
    async def main():
        runner = TestRunner()
        await test_public_interfaces(runner)
        runner.print_summary("公共接口测试")
    
    asyncio.run(main())
