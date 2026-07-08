import sys
import os
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_config import get_public_client, TestRunner


async def test_market_interfaces(runner: TestRunner):
    base_client = get_public_client()
    from services.okx.market import MarketAPI
    market_api = MarketAPI(base_client)
    
    try:
        await runner.run_test(
            'get_ticker(instId="ETH-USDT-SWAP")',
            market_api.get_ticker(instId="ETH-USDT-SWAP"),
            validate=lambda r: (
                isinstance(r, list) and len(r) > 0 and "last" in r[0],
                f"返回数据异常或缺少last字段: {r}"
            )
        )
        
        await runner.run_test(
            'get_tickers(instType="SWAP")',
            market_api.get_tickers(instType="SWAP"),
            validate=lambda r: (isinstance(r, list), f"应返回list，实际: {type(r)}")
        )
        
        await runner.run_test(
            'get_candles(instId="BTC-USDT-SWAP", bar="1m", limit="5")',
            market_api.get_candles(instId="BTC-USDT-SWAP", bar="1m", limit="5"),
            validate=lambda r: (
                isinstance(r, list) and len(r) == 5,
                f"应返回5根K线，实际: {len(r) if isinstance(r, list) else type(r)}"
            )
        )
        
        await runner.run_test(
            'get_orderbook(instId="BTC-USDT-SWAP", sz="5")',
            market_api.get_orderbook(instId="BTC-USDT-SWAP", sz="5"),
            validate=lambda r: (
                isinstance(r, list) and len(r) > 0 and 
                len(r[0].get("bids", [])) == 5 and len(r[0].get("asks", [])) == 5,
                f"应返回5档深度: {r}"
            )
        )
        
        await runner.run_test(
            'get_trades(instId="BTC-USDT-SWAP", limit="5")',
            market_api.get_trades(instId="BTC-USDT-SWAP", limit="5"),
            validate=lambda r: (
                isinstance(r, list) and len(r) == 5,
                f"应返回5条成交: {len(r) if isinstance(r, list) else type(r)}"
            )
        )
        
        await runner.run_test(
            'get_index_ticker(instId="BTC-USDT")',
            market_api.get_index_ticker(instId="BTC-USDT"),
            validate=lambda r: (
                isinstance(r, list) and len(r) > 0,
                f"返回数据异常: {r}"
            )
        )
    finally:
        await base_client.aclose()


if __name__ == "__main__":
    async def main():
        runner = TestRunner()
        await test_market_interfaces(runner)
        runner.print_summary("行情接口测试")
    
    asyncio.run(main())
