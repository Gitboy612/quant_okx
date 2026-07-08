from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models.user import User
from middleware.auth import get_current_user

router = APIRouter(prefix="/api/maintenance", tags=["maintenance"])


@router.post("/reset-pnl")
def reset_pnl_route(
    body: dict,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from services import maintenance_service
    account_id = body.get("account_id")
    strategy_instance_id = body.get("strategy_instance_id")
    return maintenance_service.reset_pnl(db, account_id=account_id, strategy_instance_id=strategy_instance_id)


@router.post("/cleanup/pnl-records")
def cleanup_pnl_records_route(
    body: dict,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from services import maintenance_service
    strategy_instance_id = body.get("strategy_instance_id")
    before_date_str = body.get("before_date")
    before_date = None
    if before_date_str:
        try:
            before_date = datetime.fromisoformat(before_date_str)
        except (ValueError, TypeError) as e:
            raise HTTPException(status_code=400, detail=f"before_date 格式无效: {e}")
    return maintenance_service.cleanup_pnl_records(
        db, strategy_instance_id=strategy_instance_id, before_date=before_date
    )


@router.post("/cleanup/order-records")
def cleanup_order_records_route(
    body: dict,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from services import maintenance_service
    strategy_instance_id = body.get("strategy_instance_id")
    status_list = body.get("status_list")
    return maintenance_service.cleanup_order_records(
        db, strategy_instance_id=strategy_instance_id, status_list=status_list
    )


@router.post("/cleanup/strategy-events")
def cleanup_strategy_events_route(
    body: dict,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from services import maintenance_service
    strategy_instance_id = body.get("strategy_instance_id")
    return maintenance_service.cleanup_strategy_events(
        db, strategy_instance_id=strategy_instance_id
    )


@router.post("/correct/equity")
def correct_equity_route(
    body: dict,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from services import maintenance_service
    account_id = body.get("account_id")
    if not account_id:
        raise HTTPException(status_code=400, detail="需要提供 account_id")
    return maintenance_service.correct_equity(db, account_id=account_id)


@router.post("/correct/unrealized-pnl")
def correct_unrealized_pnl_route(
    body: dict,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from services import maintenance_service
    strategy_instance_id = body.get("strategy_instance_id")
    if not strategy_instance_id:
        raise HTTPException(status_code=400, detail="需要提供 strategy_instance_id")
    return maintenance_service.correct_unrealized_pnl(db, strategy_instance_id=strategy_instance_id)


@router.post("/correct/realized-pnl")
def correct_realized_pnl_route(
    body: dict,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from services import maintenance_service
    strategy_instance_id = body.get("strategy_instance_id")
    if not strategy_instance_id:
        raise HTTPException(status_code=400, detail="需要提供 strategy_instance_id")
    return maintenance_service.correct_realized_pnl(db, strategy_instance_id=strategy_instance_id)
