import sys
import os
import asyncio
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_config import TestRunner
from test_public import test_public_interfaces
from test_market import test_market_interfaces
from test_account import test_account_interfaces
from test_trade import test_trade_interfaces
from test_funding import test_funding_interfaces
from test_backward_compat import test_backward_compat


async def run_all_tests():
    test_modules = [
        ("公共接口测试", test_public_interfaces),
        ("行情接口测试", test_market_interfaces),
        ("账户接口测试", test_account_interfaces),
        ("交易接口测试", test_trade_interfaces),
        ("资金接口测试", test_funding_interfaces),
        ("向后兼容测试", test_backward_compat),
    ]
    
    total_passed = 0
    total_tests = 0
    all_failures = []
    
    for module_name, test_func in test_modules:
        print(f"\n{'='*60}")
        print(f"  {module_name}")
        print(f"{'='*60}")
        try:
            runner = TestRunner()
            await test_func(runner)
            passed, total, failures = runner.print_summary(module_name)
            total_passed += passed
            total_tests += total
            for name, err in failures:
                all_failures.append((module_name, name, err))
        except Exception as e:
            print(f"\n  模块执行异常: {str(e)}")
            traceback.print_exc()
            all_failures.append((module_name, "模块异常", str(e)))
    
    print(f"\n{'='*60}")
    print(f"  总体结果")
    print(f"{'='*60}")
    print(f"=== 总体结果: {total_passed}/{total_tests} 测试通过 ===")
    
    if all_failures:
        print("\n失败列表:")
        for module, name, err in all_failures:
            print(f"  [{module}] {name}: {err}")
    
    return total_passed, total_tests, all_failures


if __name__ == "__main__":
    print("OKX API 接口测试套件")
    print("使用模拟盘账户")
    asyncio.run(run_all_tests())
