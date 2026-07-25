#!/usr/bin/env python3
"""为前端 PnL 调试创建可回滚的本地测试数据。

安全约束：
- 只写入名称以 ``[PNL-TEST]`` 开头的数据；
- 测试账户为停用状态，策略实例保持 ``stopped``；
- 使用固定价格客户端，不访问 OKX、不启动策略、不发送订单；
- 默认在修改前使用 SQLite backup API 创建一致性备份。
"""

from __future__ import annotations

import argparse
import asyncio
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"
DATA_DIR = ROOT_DIR / "data"
DATABASE_PATH = DATA_DIR / "quant_okx.db"
TEST_PREFIX = "[PNL-TEST]"

sys.path.insert(0, str(BACKEND_DIR))

from database import SessionLocal, init_db  # noqa: E402
from models.account import Account  # noqa: E402
from models.order import Order  # noqa: E402
from models.pnl import PnlRecord  # noqa: E402
from models.strategy import StrategyInstance, StrategyTemplate  # noqa: E402
from models.strategy_event import StrategyEvent  # noqa: E402
from services.encryption_service import encrypt  # noqa: E402
from services.pnl_accounting_engine import pnl_accounting_engine  # noqa: E402


class FixedPriceClient:
    """只向 PnL 引擎返回固定行情，不包含任何交易能力。"""

    def __init__(self, last_price: float):
        self.last_price = last_price

    async def get_ticker(self, symbol: str) -> list[dict[str, str]]:
        return [{"instId": symbol, "last": str(self.last_price)}]


def backup_database() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = DATA_DIR / f"quant_okx-before-pnl-test-{timestamp}.db"
    with sqlite3.connect(DATABASE_PATH) as source, sqlite3.connect(backup_path) as target:
        source.backup(target)
    return backup_path


def remove_test_data() -> dict[str, int]:
    """删除本脚本创建的数据，不碰用户已有账户和策略。"""

    db = SessionLocal()
    try:
        accounts = db.query(Account).filter(Account.name.like(f"{TEST_PREFIX}%")).all()
        account_ids = [account.id for account in accounts]
        instances = (
            db.query(StrategyInstance)
            .filter(
                (StrategyInstance.name.like(f"{TEST_PREFIX}%"))
                | (StrategyInstance.account_id.in_(account_ids) if account_ids else False)
            )
            .all()
        )
        instance_ids = [instance.id for instance in instances]

        deleted = {
            "pnl_records": 0,
            "orders": 0,
            "strategy_events": 0,
            "strategy_instances": 0,
            "accounts": 0,
        }
        if instance_ids:
            deleted["pnl_records"] = db.query(PnlRecord).filter(
                PnlRecord.strategy_instance_id.in_(instance_ids)
            ).delete(synchronize_session=False)
            deleted["orders"] = db.query(Order).filter(
                Order.strategy_instance_id.in_(instance_ids)
            ).delete(synchronize_session=False)
            deleted["strategy_events"] = db.query(StrategyEvent).filter(
                StrategyEvent.strategy_instance_id.in_(instance_ids)
            ).delete(synchronize_session=False)
            deleted["strategy_instances"] = db.query(StrategyInstance).filter(
                StrategyInstance.id.in_(instance_ids)
            ).delete(synchronize_session=False)
        if account_ids:
            deleted["accounts"] = db.query(Account).filter(
                Account.id.in_(account_ids)
            ).delete(synchronize_session=False)
        db.commit()
        return deleted
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_builtin_template(db, strategy_type: str) -> StrategyTemplate:
    template = (
        db.query(StrategyTemplate)
        .filter(
            StrategyTemplate.strategy_type == strategy_type,
            StrategyTemplate.is_builtin.is_(True),
        )
        .first()
    )
    if template is None:
        raise RuntimeError(f"缺少内置策略模板: {strategy_type}，请先正常启动一次后端完成模板初始化")
    return template


def make_filled_order(
    *,
    instance: StrategyInstance,
    suffix: str,
    side: str,
    price: float,
    quantity: float,
    fee: float,
    update_time: int,
) -> Order:
    return Order(
        strategy_instance_id=instance.id,
        account_id=instance.account_id,
        symbol=instance.symbol,
        order_id=f"pnl-test-{instance.id}-{suffix}",
        cl_ord_id=f"pnltest{instance.id}{suffix}",
        side=side,
        order_type="market",
        price=price,
        quantity=quantity,
        filled_quantity=quantity,
        fill_px=price,
        fill_sz=quantity,
        fee=fee,
        state="filled",
        status="filled",
        update_time=str(update_time),
        pnl_accounted=False,
        actual_qty=quantity,
    )


def create_test_entities() -> dict[str, int]:
    db = SessionLocal()
    try:
        grid_template = get_builtin_template(db, "grid")
        trend_template = get_builtin_template(db, "trend")

        account = Account(
            name=f"{TEST_PREFIX} 本地盈亏测试账户",
            api_key_encrypted=encrypt("LOCAL_TEST_NOT_A_REAL_API_KEY"),
            secret_key_encrypted=encrypt("LOCAL_TEST_NOT_A_REAL_SECRET"),
            passphrase_encrypted=encrypt("LOCAL_TEST_ONLY"),
            trade_mode="demo",
            exchange="local",
            is_active=False,
        )
        db.add(account)
        db.flush()

        scenarios = [
            StrategyInstance(
                template_id=grid_template.id,
                account_id=account.id,
                name=f"{TEST_PREFIX} 持仓浮盈",
                symbol="BTC-USDT",
                market_type="spot",
                params={"scenario": "open_profit", "fee_rate": 0.0, "test_only": True},
                status="stopped",
            ),
            StrategyInstance(
                template_id=trend_template.id,
                account_id=account.id,
                name=f"{TEST_PREFIX} 闭环盈利",
                symbol="ETH-USDT",
                market_type="spot",
                params={"scenario": "closed_profit", "fee_rate": 0.001, "test_only": True},
                status="stopped",
            ),
            StrategyInstance(
                template_id=grid_template.id,
                account_id=account.id,
                name=f"{TEST_PREFIX} 闭环亏损",
                symbol="SOL-USDT",
                market_type="spot",
                params={"scenario": "closed_loss", "fee_rate": 0.001, "test_only": True},
                status="stopped",
            ),
        ]
        db.add_all(scenarios)
        db.flush()

        base_update_time = 1_750_000_000_000
        orders = [
            make_filled_order(
                instance=scenarios[0], suffix="buy", side="buy",
                price=100.0, quantity=1.0, fee=0.0,
                update_time=base_update_time,
            ),
            make_filled_order(
                instance=scenarios[1], suffix="buy", side="buy",
                price=100.0, quantity=2.0, fee=0.20,
                update_time=base_update_time + 1_000,
            ),
            make_filled_order(
                instance=scenarios[1], suffix="sell", side="sell",
                price=115.0, quantity=2.0, fee=0.23,
                update_time=base_update_time + 2_000,
            ),
            make_filled_order(
                instance=scenarios[2], suffix="buy", side="buy",
                price=200.0, quantity=1.0, fee=0.20,
                update_time=base_update_time + 3_000,
            ),
            make_filled_order(
                instance=scenarios[2], suffix="sell", side="sell",
                price=190.0, quantity=1.0, fee=0.19,
                update_time=base_update_time + 4_000,
            ),
        ]
        db.add_all(orders)
        db.commit()
        return {
            "account_id": account.id,
            "open_profit_id": scenarios[0].id,
            "closed_profit_id": scenarios[1].id,
            "closed_loss_id": scenarios[2].id,
        }
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def move_latest_snapshot(instance_id: int, recorded_at: datetime, base_equity: float = 10_000.0) -> None:
    db = SessionLocal()
    try:
        record = (
            db.query(PnlRecord)
            .filter(PnlRecord.strategy_instance_id == instance_id)
            .order_by(PnlRecord.id.desc())
            .first()
        )
        if record is None:
            raise RuntimeError(f"策略 {instance_id} 未生成 PnL 快照")
        record.recorded_at = recorded_at
        record.equity = base_equity + float(record.total_pnl or 0)
        db.commit()
    finally:
        db.close()


async def generate_snapshots(ids: dict[str, int]) -> None:
    now = datetime.now(timezone.utc)

    # 持仓策略：同一笔买入在三个固定行情下形成曲线 0 -> 5 -> 10。
    for price, recorded_at in [
        (100.0, now - timedelta(hours=2)),
        (105.0, now - timedelta(hours=1)),
        (110.0, now),
    ]:
        await pnl_accounting_engine.recompute(
            ids["open_profit_id"], FixedPriceClient(price)
        )
        move_latest_snapshot(ids["open_profit_id"], recorded_at)

    # 已平仓策略不需要行情：PnL 完全由实际成交和手续费决定。
    await pnl_accounting_engine.recompute(ids["closed_profit_id"], client=None)
    move_latest_snapshot(ids["closed_profit_id"], now - timedelta(minutes=30))

    await pnl_accounting_engine.recompute(ids["closed_loss_id"], client=None)
    move_latest_snapshot(ids["closed_loss_id"], now - timedelta(minutes=15))


def summarize(ids: dict[str, int]) -> dict[str, float]:
    db = SessionLocal()
    try:
        latest_by_strategy = []
        for key in ("open_profit_id", "closed_profit_id", "closed_loss_id"):
            record = (
                db.query(PnlRecord)
                .filter(PnlRecord.strategy_instance_id == ids[key])
                .order_by(PnlRecord.recorded_at.desc(), PnlRecord.id.desc())
                .first()
            )
            if record is None:
                raise RuntimeError(f"策略 {ids[key]} 缺少 PnL 记录")
            latest_by_strategy.append(record)

        global_latest = (
            db.query(PnlRecord)
            .filter(PnlRecord.account_id == ids["account_id"])
            .order_by(PnlRecord.recorded_at.desc(), PnlRecord.id.desc())
            .first()
        )
        return {
            "open_profit": float(latest_by_strategy[0].total_pnl or 0),
            "closed_profit": float(latest_by_strategy[1].total_pnl or 0),
            "closed_loss": float(latest_by_strategy[2].total_pnl or 0),
            "expected_account_total": sum(float(r.total_pnl or 0) for r in latest_by_strategy),
            "global_latest_total": float(global_latest.total_pnl or 0) if global_latest else 0.0,
        }
    finally:
        db.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="创建或清理本地 PnL 测试数据")
    parser.add_argument("--remove", action="store_true", help="只清理 [PNL-TEST] 数据")
    parser.add_argument("--no-backup", action="store_true", help="跳过数据库备份")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    init_db()

    if not args.no_backup:
        backup_path = backup_database()
        print(f"数据库备份: {backup_path}")

    deleted = remove_test_data()
    if args.remove:
        print(f"已清理测试数据: {deleted}")
        return

    ids = create_test_entities()
    asyncio.run(generate_snapshots(ids))
    values = summarize(ids)

    print("已创建本地 PnL 测试数据（账户停用、策略 stopped、无 OKX 请求）:")
    print(f"  account_id={ids['account_id']}")
    print(f"  持仓浮盈 strategy_id={ids['open_profit_id']} total={values['open_profit']:.2f}")
    print(f"  闭环盈利 strategy_id={ids['closed_profit_id']} total={values['closed_profit']:.2f}")
    print(f"  闭环亏损 strategy_id={ids['closed_loss_id']} total={values['closed_loss']:.2f}")
    print(f"  正确账户总盈亏（每策略最新快照求和）={values['expected_account_total']:.2f}")
    print(f"  当前全局最近快照值={values['global_latest_total']:.2f}")
    print("刷新前端后选择 [PNL-TEST] 本地盈亏测试账户即可查看。")


if __name__ == "__main__":
    main()
