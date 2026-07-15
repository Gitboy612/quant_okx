"""检查 strategy_engine 的运行状态。"""
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_BACKEND_ROOT = _PROJECT_ROOT / "backend"
for _p in (str(_PROJECT_ROOT), str(_BACKEND_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import asyncio
from database import SessionLocal
from models.strategy import StrategyInstance
from services.strategy_engine import strategy_engine


def main():
    db = SessionLocal()
    try:
        instances = db.query(StrategyInstance).all()
        print("=== DB Strategy Instances ===")
        for i in instances:
            print(f"  id={i.id} name={i.name} status={i.status} started={i.started_at} stopped={i.stopped_at}")

        print("\n=== strategy_engine._tasks (in-memory running tasks) ===")
        if not strategy_engine._tasks:
            print("  (empty - no strategies running in memory)")
        for sid, entry in strategy_engine._tasks.items():
            task, strategy = entry
            print(f"  instance_id={sid} task_done={task.done()} strategy={strategy.__class__.__name__}")
            print(f"    params={strategy.params}")

        print("\n=== strategy_engine._account_clients ===")
        if not strategy_engine._account_clients:
            print("  (empty)")
        for k, v in strategy_engine._account_clients.items():
            print(f"  account={k} client={v.__class__.__name__}")

        # Try to verify if backend was reloaded
        print("\n=== Process info ===")
        import os
        print(f"  PID: {os.getpid()}")
        print(f"  Python: {sys.executable}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
