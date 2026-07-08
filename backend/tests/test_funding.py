import sys
import os
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_config import get_test_client, TestRunner


def find_ccy_balance(balances, ccy):
    for b in balances:
        if b.get("ccy") == ccy:
            return float(b.get("bal", "0"))
    return 0.0


async def test_funding_interfaces(runner: TestRunner):
    client = await get_test_client()
    try:
        await runner.run_test(
            "get_currencies()",
            client.funding.get_currencies(),
            validate=lambda r: (isinstance(r, list), f"应返回list，实际: {type(r)}")
        )
        
        await runner.run_test(
            "get_balances()",
            client.funding.get_balances(),
            validate=lambda r: (isinstance(r, list), f"应返回list，实际: {type(r)}")
        )
        
        await runner.run_test(
            'get_bills(limit="3")',
            client.funding.get_bills(limit="3"),
            validate=lambda r: (isinstance(r, list), f"应返回list，实际: {type(r)}")
        )
        
        await runner.run_test(
            'get_deposit_address(ccy="USDT")',
            client.funding.get_deposit_address(ccy="USDT"),
            validate=lambda r: (isinstance(r, list), f"应返回list，实际: {type(r)}")
        )
        
        print("\n--- 资金划转测试 ---")
        funding_balances = await client.funding.get_balances()
        trading_balance_resp = await client.account.get_balance(ccy="USDT")
        
        funding_avail = find_ccy_balance(funding_balances, "USDT")
        trading_avail = 0.0
        if trading_balance_resp and "details" in trading_balance_resp:
            for d in trading_balance_resp["details"]:
                if d.get("ccy") == "USDT":
                    trading_avail = float(d.get("availBal", d.get("cashBal", "0")))
                    break
        
        print(f"  资金账户USDT余额: {funding_avail}")
        print(f"  交易账户USDT余额: {trading_avail}")
        
        transfer_amt = "1"
        
        if funding_avail >= 1.0:
            trans_id = None
            
            print("测试: transfer(6->18, 1 USDT)")
            transfer_resp_1 = await client.funding.transfer(
                ccy="USDT",
                amt=transfer_amt,
                from_="6",
                to="18",
                type="0"
            )
            if transfer_resp_1.get("code") == "0" and transfer_resp_1.get("data"):
                trans_id = transfer_resp_1["data"][0].get("transId")
                runner.passed += 1
                runner.total += 1
                print(f"  PASS: code=0 transId={trans_id}")
                
                await asyncio.sleep(1)
                
                if trans_id:
                    await runner.run_test(
                        f'get_transfer_state(transId="{trans_id}")',
                        client.funding.get_transfer_state(transId=trans_id),
                        validate=lambda r: (
                            isinstance(r, list) and len(r) > 0,
                            f"查询划转状态失败: {r}"
                        )
                    )
                
                await asyncio.sleep(0.5)
                
                print("测试: transfer(18->6, 1 USDT) [转回]")
                transfer_resp_2 = await client.funding.transfer(
                    ccy="USDT",
                    amt=transfer_amt,
                    from_="18",
                    to="6",
                    type="0"
                )
                if transfer_resp_2.get("code") == "0":
                    runner.passed += 1
                    runner.total += 1
                    print(f"  PASS: code=0 已转回")
                else:
                    runner.total += 1
                    runner.failures.append(("transfer(18->6)", str(transfer_resp_2)))
                    print(f"  FAIL: {transfer_resp_2}")
            else:
                runner.total += 1
                runner.failures.append(("transfer(6->18)", str(transfer_resp_1)))
                print(f"  FAIL: code={transfer_resp_1.get('code')} msg={transfer_resp_1.get('msg')}")
        else:
            print("测试: transfer(双向划转)")
            print("  SKIP: 资金账户USDT余额不足1，跳过划转测试")
            runner.total += 1
            runner.failures.append(("transfer", "资金账户余额不足，跳过"))
        
    finally:
        await client.aclose()


if __name__ == "__main__":
    async def main():
        runner = TestRunner()
        await test_funding_interfaces(runner)
        runner.print_summary("资金接口测试")
    
    asyncio.run(main())
