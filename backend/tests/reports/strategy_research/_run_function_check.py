"""临时脚本：运行一次功能检测并打印结果。"""
import asyncio
import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_BACKEND_DIR))

from tests.reports.strategy_research.function_checker import run_function_check

if __name__ == "__main__":
    r = asyncio.run(run_function_check())
    print("=" * 60)
    print(f"overall_passed: {r['overall_passed']}")
    print(f"duration: {r.get('duration_seconds', 0):.3f}s")
    for k, v in r["checks"].items():
        print(f"\n--- {k} ---")
        print(f"  passed: {v['passed']}")
        if k == "theoretical_vs_actual_orders":
            for s in v.get("per_strategy", []):
                print(f"  策略#{s['strategy_instance_id']} {s['symbol']}:")
                print(f"    当前价={s.get('current_price')}")
                print(f"    理论买单数={len(s.get('theoretical_buy_levels', []))}")
                print(f"    理论卖单数={len(s.get('theoretical_sell_levels', []))}")
                print(f"    实际live订单={s.get('actual_live_orders')}")
                print(f"    缺失={len(s.get('missing_orders', []))}")
                print(f"    多余={len(s.get('extra_orders', []))}")
                print(f"    价格不匹配={len(s.get('price_mismatches', []))}")
                print(f"    matched={s.get('matched')}")
        elif k == "strategy_errors":
            print(f"  错误数={v.get('error_count')}")
            for e in v.get("errors_by_type", []):
                print(f"    {e['type']}: {e['count']}次 - {e['suggestion']}")
        elif k == "actual_pnl":
            print(f"  总OKX盈亏={v.get('total_okx_pnl')}")
            print(f"  总DB盈亏={v.get('total_db_pnl')}")
            print(f"  总差异={v.get('total_diff')}")
            for s in v.get("per_strategy", []):
                print(f"  策略#{s['strategy_instance_id']} {s['symbol']}:")
                print(f"    OKX盈亏={s.get('okx_realized_pnl')} DB盈亏={s.get('db_realized_pnl')} 差异={s.get('diff')}")
                print(f"    成交数={s.get('trade_count')} matched={s.get('matched')}")
