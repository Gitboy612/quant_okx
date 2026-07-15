"""深入查询策略 #1 的 PnL 记录与订单。"""
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_BACKEND_ROOT = _PROJECT_ROOT / "backend"
for _p in (str(_PROJECT_ROOT), str(_BACKEND_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from database import SessionLocal
from models.pnl import PnlRecord
from models.order import Order
from models.strategy_event import StrategyEvent


def main():
    db = SessionLocal()
    try:
        print("=== Strategy #1 PnL Records ===")
        records = db.query(PnlRecord).filter(PnlRecord.strategy_instance_id == 1).order_by(PnlRecord.recorded_at).all()
        for r in records:
            print(f"  id={r.id} ts={r.recorded_at} equity={r.equity} unrealized={r.unrealized_pnl} "
                  f"realized={r.realized_pnl} total={r.total_pnl} net_pos={r.net_position} "
                  f"avg_buy={r.avg_buy_price} fee={r.total_fee} order_count={r.order_count}")

        print("\n=== Strategy #1 Filled Orders ===")
        orders = db.query(Order).filter(Order.strategy_instance_id == 1).all()
        for o in orders:
            print(f"  id={o.id} ordId={o.order_id} side={o.side} status={o.status} "
                  f"price={o.price} qty={o.quantity} fill_px={o.fill_px} fill_sz={o.fill_sz} "
                  f"fee={o.fee} state={o.state} ct_val={o.ct_val}")

        print("\n=== Strategy #2 PnL Records ===")
        records2 = db.query(PnlRecord).filter(PnlRecord.strategy_instance_id == 2).order_by(PnlRecord.recorded_at).all()
        for r in records2:
            print(f"  id={r.id} ts={r.recorded_at} total={r.total_pnl}")

        print("\n=== Strategy #2 Recent Events (last 10) ===")
        events = db.query(StrategyEvent).filter(StrategyEvent.strategy_instance_id == 2).order_by(
            StrategyEvent.created_at.desc()
        ).limit(10).all()
        for e in events:
            print(f"  ts={e.created_at} type={e.event_type} msg={e.message[:150]}")

        print("\n=== Strategy #2 Orders ===")
        orders2 = db.query(Order).filter(Order.strategy_instance_id == 2).all()
        print(f"  total: {len(orders2)}")
        for o in orders2[:5]:
            print(f"  id={o.id} ordId={o.order_id} side={o.side} status={o.status} price={o.price} qty={o.quantity}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
