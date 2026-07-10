from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from database import get_db
from models.pnl import PnlRecord
from models.user import User
from middleware.auth import get_current_user

router = APIRouter(prefix="/api/pnl", tags=["pnl"])


@router.get("")
def get_pnl_records(
    account_id: int | None = Query(None),
    strategy_instance_id: int | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = db.query(PnlRecord)
    if account_id is not None:
        query = query.filter(PnlRecord.account_id == account_id)
    if strategy_instance_id is not None:
        query = query.filter(PnlRecord.strategy_instance_id == strategy_instance_id)

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
            "recorded_at": r.recorded_at.isoformat() if r.recorded_at else None,
        }
        for r in records
    ]


@router.get("/summary")
def get_pnl_summary(
    account_id: int | None = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = db.query(PnlRecord)
    if account_id is not None:
        query = query.filter(PnlRecord.account_id == account_id)

    records = query.order_by(PnlRecord.recorded_at.desc()).limit(500).all()
    if not records:
        return {"total_realized_pnl": 0, "total_unrealized_pnl": 0, "total_pnl": 0, "latest_equity": 0, "by_strategy": []}

    latest = records[0]
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
        })

    return {
        "total_realized_pnl": total_realized,
        "total_unrealized_pnl": total_unrealized,
        "total_pnl": total_realized + total_unrealized,
        "latest_equity": latest.equity or 0,
        "by_strategy": by_strategy,
    }
