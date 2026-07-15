"""快速调研当前 DB 状态（不入库，仅打印）。"""
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_BACKEND_ROOT = _PROJECT_ROOT / "backend"
for _p in (str(_PROJECT_ROOT), str(_BACKEND_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from datetime import datetime, timezone
from sqlalchemy import func
from database import SessionLocal
from models.account import Account
from models.strategy import StrategyInstance, StrategyTemplate
from models.pnl import PnlRecord
from models.order import Order
from models.strategy_event import StrategyEvent


def main():
    db = SessionLocal()
    try:
        print("=== Accounts ===")
        for a in db.query(Account).all():
            print(f"  id={a.id} name={a.name} mode={a.trade_mode} exchange={a.exchange} active={a.is_active}")

        print("\n=== Strategy Templates ===")
        for t in db.query(StrategyTemplate).all():
            print(f"  id={t.id} name={t.name} type={t.strategy_type} builtin={t.is_builtin}")

        print("\n=== Strategy Instances ===")
        for i in db.query(StrategyInstance).order_by(StrategyInstance.id).all():
            now = datetime.now(timezone.utc)
            days = (now - i.started_at.replace(tzinfo=timezone.utc)).total_seconds() / 86400 if i.started_at else 0
            print(f"  id={i.id} name={i.name} symbol={i.symbol} status={i.status} "
                  f"acct={i.account_id} tmpl={i.template_id} started={i.started_at} days={days:.2f}")
            print(f"    params={i.params}")

        print("\n=== PnL Records by Strategy ===")
        rows = db.query(
            PnlRecord.strategy_instance_id,
            func.count(PnlRecord.id).label("cnt"),
            func.min(PnlRecord.recorded_at).label("first"),
            func.max(PnlRecord.recorded_at).label("last"),
            func.max(PnlRecord.total_pnl).label("latest_total"),
        ).group_by(PnlRecord.strategy_instance_id).all()
        for r in rows:
            print(f"  instance={r.strategy_instance_id} count={r.cnt} "
                  f"first={r.first} last={r.last} latest_total={r.latest_total}")

        print("\n=== Orders by Strategy ===")
        order_rows = db.query(
            Order.strategy_instance_id,
            Order.status,
            func.count(Order.id).label("cnt"),
        ).group_by(Order.strategy_instance_id, Order.status).all()
        for r in order_rows:
            print(f"  instance={r.strategy_instance_id} status={r.status} count={r.cnt}")

        print("\n=== Recent Strategy Events (last 24h) ===")
        cutoff = datetime.now(timezone.utc)
        from datetime import timedelta
        cutoff = cutoff - timedelta(hours=24)
        events = db.query(StrategyEvent).filter(StrategyEvent.created_at >= cutoff).order_by(
            StrategyEvent.created_at.desc()
        ).limit(50).all()
        for e in events:
            print(f"  ts={e.created_at} inst={e.strategy_instance_id} type={e.event_type} msg={e.message[:120]}")

        print("\n=== Risk events count by instance (last 7d) ===")
        cutoff7 = datetime.now(timezone.utc) - timedelta(days=7)
        risk_types = ["capital_limit", "margin_warning", "margin_critical", "position_conflict", "position_mismatch", "order_latency", "leverage_set_failed"]
        for inst in db.query(StrategyInstance).all():
            for rt in risk_types:
                cnt = db.query(func.count(StrategyEvent.id)).filter(
                    StrategyEvent.strategy_instance_id == inst.id,
                    StrategyEvent.event_type == rt,
                    StrategyEvent.created_at >= cutoff7,
                ).scalar()
                if cnt > 0:
                    print(f"  instance={inst.id} type={rt} count={cnt}")

    finally:
        db.close()


if __name__ == "__main__":
    main()
