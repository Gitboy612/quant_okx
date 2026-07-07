from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from database import get_db
from models.order import Order
from models.user import User
from middleware.auth import get_current_user

router = APIRouter(prefix="/api/orders", tags=["orders"])


@router.get("")
def list_orders(
    account_id: int | None = Query(None),
    strategy_instance_id: int | None = Query(None),
    symbol: str | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = db.query(Order)
    if account_id is not None:
        query = query.filter(Order.account_id == account_id)
    if strategy_instance_id is not None:
        query = query.filter(Order.strategy_instance_id == strategy_instance_id)
    if symbol:
        query = query.filter(Order.symbol.ilike(f"%{symbol}%"))

    orders = query.order_by(Order.created_at.desc()).limit(limit).all()
    return [
        {
            "id": o.id,
            "strategy_instance_id": o.strategy_instance_id,
            "account_id": o.account_id,
            "symbol": o.symbol,
            "order_id": o.order_id,
            "side": o.side,
            "order_type": o.order_type,
            "price": o.price,
            "quantity": o.quantity,
            "filled_quantity": o.filled_quantity,
            "status": o.status,
            "created_at": o.created_at.isoformat() if o.created_at else None,
        }
        for o in orders
    ]
