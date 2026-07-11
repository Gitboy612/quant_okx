from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from database import get_db
from models.user import User
from middleware.auth import get_current_user
from services.attribution_service import attribution_service

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("/attribution/by-symbol")
def attribution_by_symbol(
    account_id: int = Query(...),
    start_date: str = Query(..., description="ISO 8601, 如 2026-07-01T00:00:00"),
    end_date: str = Query(..., description="ISO 8601, 如 2026-07-11T23:59:59"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """按币种归因：返回各 symbol 的 realized_pnl / fee / trade_count / win_rate / pnl_percentage。"""
    return attribution_service.get_attribution_by_symbol(db, account_id, start_date, end_date)


@router.get("/attribution/by-strategy-type")
def attribution_by_strategy_type(
    account_id: int = Query(...),
    start_date: str = Query(...),
    end_date: str = Query(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """按策略类型归因：返回各类策略的 realized_pnl / unrealized_pnl / trade_count / win_rate / avg_return / max_drawdown。"""
    return attribution_service.get_attribution_by_strategy_type(db, account_id, start_date, end_date)


@router.get("/attribution/by-period")
def attribution_by_period(
    account_id: int = Query(...),
    start_date: str = Query(...),
    end_date: str = Query(...),
    period: str = Query("daily", description="daily | weekly | monthly"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """按时间段归因：返回每个周期桶的 realized_pnl / unrealized_pnl / total_pnl / trade_count。"""
    return attribution_service.get_attribution_by_period(db, account_id, start_date, end_date, period)


@router.get("/drill-down")
def drill_down(
    start_date: str = Query(...),
    end_date: str = Query(...),
    symbol: str | None = Query(None),
    strategy_type: str | None = Query(None),
    account_id: int | None = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """下钻查看订单明细：按 symbol / strategy_type 过滤。"""
    return attribution_service.get_drill_down(
        db,
        start_date=start_date,
        end_date=end_date,
        symbol=symbol,
        strategy_type=strategy_type,
        account_id=account_id,
    )
