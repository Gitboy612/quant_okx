import asyncio
import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from models.account import Account
from models.order import Order
from models.pnl import PnlRecord
from models.strategy import StrategyInstance
from models.strategy_event import StrategyEvent
from services.okx_client import OKXClient


def _fetch_okx_total_eq(account: Account) -> float | None:
    """调用 OKX 拉取账户真实总权益（totalEq）。失败返回 None。"""
    client = OKXClient(
        api_key_encrypted=account.api_key_encrypted,
        secret_encrypted=account.secret_key_encrypted,
        passphrase_encrypted=account.passphrase_encrypted,
        trade_mode=account.trade_mode,
        account_name=account.name,
    )
    try:
        balances = asyncio.run(client.get_balance())
        return float(balances.get("totalEq", "0"))
    finally:
        try:
            asyncio.run(client.aclose())
        except Exception:
            pass


def reset_pnl(db: Session, account_id=None, strategy_instance_id=None) -> dict:
    """盈亏清零。"""
    try:
        if strategy_instance_id is not None:
            instance = db.query(StrategyInstance).filter(
                StrategyInstance.id == strategy_instance_id
            ).first()
            if not instance:
                return {"status": "error", "message": "策略实例不存在"}
            if instance.status == "running":
                return {"status": "error", "message": "请先停止策略再清零"}

            # 读取最新 PnlRecord 的 equity
            latest = db.query(PnlRecord).filter(
                PnlRecord.strategy_instance_id == strategy_instance_id
            ).order_by(PnlRecord.recorded_at.desc()).first()
            equity = latest.equity if latest else 0

            new_record = PnlRecord(
                account_id=instance.account_id,
                strategy_instance_id=instance.id,
                equity=equity,
                unrealized_pnl=0,
                realized_pnl=0,
                total_pnl=0,
                recorded_at=datetime.now(timezone.utc),
            )
            db.add(new_record)
            db.flush()

            event = StrategyEvent(
                strategy_instance_id=instance.id,
                event_type="manual_correction",
                message="盈亏清零",
                details=json.dumps({
                    "action": "reset_pnl",
                    "account_id": instance.account_id,
                    "strategy_instance_id": instance.id,
                    "equity": equity,
                    "unrealized_pnl": 0,
                    "realized_pnl": 0,
                }, ensure_ascii=False),
            )
            db.add(event)
            db.commit()
            return {
                "status": "ok",
                "message": "盈亏清零成功",
                "equity": equity,
                "account_id": instance.account_id,
                "strategy_instance_id": instance.id,
            }

        if account_id is not None:
            account = db.query(Account).filter(Account.id == account_id).first()
            if not account:
                return {"status": "error", "message": "账户不存在"}

            total_eq = _fetch_okx_total_eq(account)
            if total_eq is None:
                return {"status": "error", "message": "OKX 调用失败: 无法获取 totalEq"}

            new_record = PnlRecord(
                account_id=account_id,
                strategy_instance_id=None,
                equity=total_eq,
                unrealized_pnl=0,
                realized_pnl=0,
                total_pnl=0,
                recorded_at=datetime.now(timezone.utc),
            )
            db.add(new_record)
            db.flush()

            # StrategyEvent.strategy_instance_id 为 nullable=False，账户级操作无关联策略，
            # 改用 print 记录日志（不写 StrategyEvent）
            print(f"[maintenance] 盈亏清零: account_id={account_id}, equity={total_eq}, unrealized=0, realized=0")
            db.commit()
            return {
                "status": "ok",
                "message": "盈亏清零成功",
                "equity": total_eq,
                "account_id": account_id,
                "strategy_instance_id": None,
            }

        return {"status": "error", "message": "需要提供 account_id 或 strategy_instance_id"}
    except Exception as e:
        db.rollback()
        return {"status": "error", "message": str(e)}


def cleanup_pnl_records(db: Session, strategy_instance_id=None, before_date=None) -> dict:
    """删除 PnL 记录。"""
    try:
        query = db.query(PnlRecord)
        log_target = {}
        if strategy_instance_id is not None:
            query = query.filter(PnlRecord.strategy_instance_id == strategy_instance_id)
            log_target["strategy_instance_id"] = strategy_instance_id
        if before_date is not None:
            query = query.filter(PnlRecord.recorded_at < before_date)
            log_target["before_date"] = before_date.isoformat() if hasattr(before_date, "isoformat") else str(before_date)

        count = query.count()
        query.delete(synchronize_session=False)
        db.commit()

        # StrategyEvent.strategy_instance_id 为 nullable=False，无关联策略时仅 print 日志
        if strategy_instance_id is not None:
            event = StrategyEvent(
                strategy_instance_id=strategy_instance_id,
                event_type="data_cleanup",
                message=f"清理 PnL 记录: {count} 条",
                details=json.dumps({
                    "action": "cleanup_pnl_records",
                    "deleted": count,
                    **log_target,
                }, ensure_ascii=False),
            )
            db.add(event)
            db.commit()
        else:
            print(f"[maintenance] 清理 PnL 记录: {count} 条, target={log_target}")
        return {"status": "ok", "deleted": count}
    except Exception as e:
        db.rollback()
        return {"status": "error", "message": str(e)}


def cleanup_order_records(db: Session, strategy_instance_id=None, status_list=None) -> dict:
    """删除订单记录。"""
    try:
        query = db.query(Order)
        log_target = {}
        if strategy_instance_id is not None:
            query = query.filter(Order.strategy_instance_id == strategy_instance_id)
            log_target["strategy_instance_id"] = strategy_instance_id
        if status_list:
            query = query.filter(Order.status.in_(status_list))
            log_target["status_list"] = status_list

        count = query.count()
        query.delete(synchronize_session=False)
        db.commit()

        # StrategyEvent.strategy_instance_id 为 nullable=False，无关联策略时仅 print 日志
        if strategy_instance_id is not None:
            event = StrategyEvent(
                strategy_instance_id=strategy_instance_id,
                event_type="data_cleanup",
                message=f"清理订单记录: {count} 条",
                details=json.dumps({
                    "action": "cleanup_order_records",
                    "deleted": count,
                    **log_target,
                }, ensure_ascii=False),
            )
            db.add(event)
            db.commit()
        else:
            print(f"[maintenance] 清理订单记录: {count} 条, target={log_target}")
        return {"status": "ok", "deleted": count}
    except Exception as e:
        db.rollback()
        return {"status": "error", "message": str(e)}


def cleanup_strategy_events(db: Session, strategy_instance_id=None) -> dict:
    """删除策略事件。注意：不写新的 StrategyEvent，改为返回日志。"""
    try:
        query = db.query(StrategyEvent)
        if strategy_instance_id is not None:
            query = query.filter(StrategyEvent.strategy_instance_id == strategy_instance_id)

        count = query.count()
        query.delete(synchronize_session=False)
        db.commit()
        return {
            "status": "ok",
            "deleted": count,
            "log": f"清理策略事件: {count} 条",
        }
    except Exception as e:
        db.rollback()
        return {"status": "error", "message": str(e)}


def correct_equity(db: Session, account_id) -> dict:
    """总权益校正。"""
    try:
        account = db.query(Account).filter(Account.id == account_id).first()
        if not account:
            return {"status": "error", "message": "账户不存在"}

        total_eq = _fetch_okx_total_eq(account)
        if total_eq is None:
            return {"status": "error", "message": "OKX 调用失败: 无法获取 totalEq"}

        # 读取该账户最新 PnlRecord，保留 unrealized_pnl 和 realized_pnl
        latest = db.query(PnlRecord).filter(
            PnlRecord.account_id == account_id
        ).order_by(PnlRecord.recorded_at.desc()).first()

        old_equity = latest.equity if latest else None
        unrealized = latest.unrealized_pnl if latest else 0
        realized = latest.realized_pnl if latest else 0
        si_id = latest.strategy_instance_id if latest else None

        new_record = PnlRecord(
            account_id=account_id,
            strategy_instance_id=si_id,
            equity=total_eq,
            unrealized_pnl=unrealized,
            realized_pnl=realized,
            total_pnl=unrealized + realized,
            recorded_at=datetime.now(timezone.utc),
        )
        db.add(new_record)
        db.flush()

        # StrategyEvent.strategy_instance_id 为 nullable=False，无关联策略时仅 print 日志
        if si_id is not None:
            event = StrategyEvent(
                strategy_instance_id=si_id,
                event_type="manual_correction",
                message=f"总权益校正: 旧{old_equity} → 新{total_eq}",
                details=json.dumps({
                    "action": "correct_equity",
                    "account_id": account_id,
                    "old_equity": old_equity,
                    "new_equity": total_eq,
                    "unrealized_pnl": unrealized,
                    "realized_pnl": realized,
                }, ensure_ascii=False),
            )
            db.add(event)
            db.commit()
        else:
            print(f"[maintenance] 总权益校正: account_id={account_id}, 旧{old_equity} → 新{total_eq}")
        return {
            "status": "ok",
            "message": "总权益校正成功",
            "old_equity": old_equity,
            "new_equity": total_eq,
        }
    except Exception as e:
        db.rollback()
        return {"status": "error", "message": str(e)}


def correct_unrealized_pnl(db: Session, strategy_instance_id) -> dict:
    """未实现盈亏校正。"""
    try:
        instance = db.query(StrategyInstance).filter(
            StrategyInstance.id == strategy_instance_id
        ).first()
        if not instance:
            return {"status": "error", "message": "策略实例不存在"}
        if instance.status == "running":
            return {"status": "error", "message": "请先停止策略再校正"}

        # 读取该策略最新 PnlRecord，保留 realized_pnl 和 equity
        latest = db.query(PnlRecord).filter(
            PnlRecord.strategy_instance_id == strategy_instance_id
        ).order_by(PnlRecord.recorded_at.desc()).first()

        realized = latest.realized_pnl if latest else 0
        equity = latest.equity if latest else 0

        new_record = PnlRecord(
            account_id=instance.account_id,
            strategy_instance_id=instance.id,
            equity=equity,
            unrealized_pnl=0,
            realized_pnl=realized,
            total_pnl=0 + realized,
            recorded_at=datetime.now(timezone.utc),
        )
        db.add(new_record)
        db.flush()

        event = StrategyEvent(
            strategy_instance_id=instance.id,
            event_type="manual_correction",
            message="未实现盈亏校正: 清零",
            details=json.dumps({
                "action": "correct_unrealized_pnl",
                "strategy_instance_id": instance.id,
                "account_id": instance.account_id,
                "old_unrealized": latest.unrealized_pnl if latest else None,
                "new_unrealized": 0,
                "realized_pnl": realized,
                "equity": equity,
            }, ensure_ascii=False),
        )
        db.add(event)
        db.commit()
        return {"status": "ok", "message": "未实现盈亏校正成功"}
    except Exception as e:
        db.rollback()
        return {"status": "error", "message": str(e)}


def correct_realized_pnl(db: Session, strategy_instance_id) -> dict:
    """已实现盈亏校正。"""
    try:
        instance = db.query(StrategyInstance).filter(
            StrategyInstance.id == strategy_instance_id
        ).first()
        if not instance:
            return {"status": "error", "message": "策略实例不存在"}
        if instance.status == "running":
            return {"status": "error", "message": "请先停止策略再校正"}

        # 读取该策略最新 PnlRecord，保留 unrealized_pnl 和 equity
        latest = db.query(PnlRecord).filter(
            PnlRecord.strategy_instance_id == strategy_instance_id
        ).order_by(PnlRecord.recorded_at.desc()).first()

        old_realized = latest.realized_pnl if latest else 0
        unrealized = latest.unrealized_pnl if latest else 0
        equity = latest.equity if latest else 0

        # 查询该策略所有 status='filled' 且 side='sell' 的订单
        sell_orders = db.query(Order).filter(
            Order.strategy_instance_id == strategy_instance_id,
            Order.status == "filled",
            Order.side == "sell",
        ).all()

        # 尝试从订单精确重算 realized_pnl。
        # 简化实现：无法精确匹配对应买单价，因此保持原值并返回提示。
        new_realized = old_realized
        hint = "无法从订单精确重算，已保持原值"

        new_record = PnlRecord(
            account_id=instance.account_id,
            strategy_instance_id=instance.id,
            equity=equity,
            unrealized_pnl=unrealized,
            realized_pnl=new_realized,
            total_pnl=unrealized + new_realized,
            recorded_at=datetime.now(timezone.utc),
        )
        db.add(new_record)
        db.flush()

        event = StrategyEvent(
            strategy_instance_id=instance.id,
            event_type="manual_correction",
            message=f"已实现盈亏校正: 旧{old_realized} → 新{new_realized}",
            details=json.dumps({
                "action": "correct_realized_pnl",
                "strategy_instance_id": instance.id,
                "account_id": instance.account_id,
                "old_realized": old_realized,
                "new_realized": new_realized,
                "unrealized_pnl": unrealized,
                "equity": equity,
                "sell_order_count": len(sell_orders),
                "hint": hint,
            }, ensure_ascii=False),
        )
        db.add(event)
        db.commit()
        return {
            "status": "ok",
            "message": "已实现盈亏校正成功",
            "old_realized": old_realized,
            "new_realized": new_realized,
            "hint": hint,
        }
    except Exception as e:
        db.rollback()
        return {"status": "error", "message": str(e)}
