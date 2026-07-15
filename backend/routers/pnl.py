from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session
from database import get_db
from models.pnl import PnlRecord
from models.user import User
from middleware.auth import get_current_user

router = APIRouter(prefix="/api/pnl", tags=["pnl"])


def _snapshot_to_dict(snapshot) -> dict:
    """将 PnlSnapshot 转换为可 JSON 序列化的字典。"""
    if hasattr(snapshot, "to_dict"):
        return snapshot.to_dict()
    return {
        "strategy_instance_id": snapshot.strategy_instance_id,
        "realized_pnl": snapshot.realized_pnl,
        "unrealized_pnl": snapshot.unrealized_pnl,
        "total_pnl": snapshot.total_pnl,
        "equity": snapshot.equity,
        "net_position": snapshot.net_position,
        "avg_buy_price": snapshot.avg_buy_price,
        "total_fee": snapshot.total_fee,
        "order_count": snapshot.order_count,
        "recorded_at": snapshot.recorded_at.isoformat() if snapshot.recorded_at else None,
    }


@router.get("")
def get_pnl_records(
    account_id: int | None = Query(None),
    strategy_instance_id: int | None = Query(None),
    start_time: str | None = Query(None),
    end_time: str | None = Query(None),
    limit: int = Query(1000, ge=1, le=5000),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = db.query(PnlRecord)
    if account_id is not None:
        query = query.filter(PnlRecord.account_id == account_id)
    if strategy_instance_id is not None:
        query = query.filter(PnlRecord.strategy_instance_id == strategy_instance_id)
    if start_time:
        try:
            start_dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
            query = query.filter(PnlRecord.recorded_at >= start_dt)
        except ValueError:
            pass
    if end_time:
        try:
            end_dt = datetime.fromisoformat(end_time.replace('Z', '+00:00'))
            query = query.filter(PnlRecord.recorded_at <= end_dt)
        except ValueError:
            pass

    records = query.order_by(PnlRecord.recorded_at.desc()).limit(limit).all()
    return [
        {
            "id": r.id,
            "account_id": r.account_id,
            "strategy_instance_id": r.strategy_instance_id,
            "equity": r.equity,
            "unrealized_pnl": r.unrealized_pnl,
            "realized_pnl": r.realized_pnl,
            "total_pnl": r.total_pnl,
            "is_final": r.is_final,
            "net_position": r.net_position,
            "avg_buy_price": r.avg_buy_price,
            "total_fee": r.total_fee,
            "order_count": r.order_count,
            "recorded_at": r.recorded_at.isoformat() if r.recorded_at else None,
        }
        for r in records
    ]


@router.get("/summary")
def get_pnl_summary(
    account_id: int | None = Query(None),
    strategy_instance_id: int | None = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = db.query(PnlRecord)
    if account_id is not None:
        query = query.filter(PnlRecord.account_id == account_id)
    # 按策略实例筛选汇总
    if strategy_instance_id is not None:
        query = query.filter(PnlRecord.strategy_instance_id == strategy_instance_id)

    records = query.order_by(PnlRecord.recorded_at.desc()).limit(500).all()
    if not records:
        return {"total_realized_pnl": 0, "total_unrealized_pnl": 0, "total_pnl": 0, "latest_equity": 0, "by_strategy": []}

    # summary 基准：跳过全 0 无意义记录（total_pnl=0 且 net_position=0 且 order_count=0），
    # 向前追溯最近的有效记录；若全部为全 0 则退化为第一条（值均为 0，不影响汇总）
    latest = records[0]
    for r in records:
        if not ((r.total_pnl or 0) == 0 and (r.net_position or 0) == 0 and (r.order_count or 0) == 0):
            latest = r
            break
    # realized_pnl 与 unrealized_pnl 均取最新时点值（unrealized 是时点浮动值，不能跨记录求和）
    total_realized = latest.realized_pnl or 0
    total_unrealized = latest.unrealized_pnl or 0

    # 按策略实例聚合：每个策略取最新一条记录
    by_strategy = []
    seen_strategy_ids = set()
    for r in records:
        sid = r.strategy_instance_id
        if sid is None or sid in seen_strategy_ids:
            continue
        seen_strategy_ids.add(sid)
        by_strategy.append({
            "strategy_instance_id": sid,
            "realized_pnl": r.realized_pnl or 0,
            "unrealized_pnl": r.unrealized_pnl or 0,
            "total_pnl": (r.realized_pnl or 0) + (r.unrealized_pnl or 0),
            "equity": r.equity or 0,
            "net_position": r.net_position,
            "avg_buy_price": r.avg_buy_price,
            "total_fee": r.total_fee,
            "order_count": r.order_count,
        })

    return {
        "total_realized_pnl": total_realized,
        "total_unrealized_pnl": total_unrealized,
        "total_pnl": total_realized + total_unrealized,
        "latest_equity": latest.equity or 0,
        "by_strategy": by_strategy,
    }


@router.post("/recompute/{strategy_id}")
async def recompute_pnl(
    strategy_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from services.pnl_accounting_engine import pnl_accounting_engine

    client = await pnl_accounting_engine._get_client(strategy_id)
    snapshot = await pnl_accounting_engine.recompute(strategy_id, client)
    # 无成交订单时不返回全 0，返回失败信息
    if snapshot is None:
        return {"success": False, "message": "无成交订单"}
    return _snapshot_to_dict(snapshot)


@router.post("/snapshot")
async def snapshot_pnl(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from services.pnl_accounting_engine import pnl_accounting_engine
    from services.strategy_engine import strategy_engine

    results = []
    for sid in strategy_engine.get_running_ids():
        client = await pnl_accounting_engine._get_client(sid)
        snapshot = await pnl_accounting_engine.incremental_update(sid, client)
        if snapshot:
            results.append(_snapshot_to_dict(snapshot))
    return {"snapshots": results, "count": len(results)}
