import csv
import io
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from database import get_db
from models.user import User
from models.strategy_event import StrategyEvent
from middleware.auth import get_current_user

router = APIRouter(prefix="/api/monitoring", tags=["monitoring"])


@router.get("/strategy/{strategy_id}/events")
def list_strategy_events(
    strategy_id: int,
    limit: int = Query(100, ge=1, le=1000),
    event_type: str | None = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = db.query(StrategyEvent).filter(
        StrategyEvent.strategy_instance_id == strategy_id
    )
    if event_type:
        query = query.filter(StrategyEvent.event_type == event_type)

    total = query.count()
    events = query.order_by(StrategyEvent.created_at.desc()).limit(limit).all()
    return {
        "total": total,
        "items": [
            {
                "id": e.id,
                "strategy_instance_id": e.strategy_instance_id,
                "event_type": e.event_type,
                "message": e.message,
                "details": e.details,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in events
        ],
    }


@router.delete("/strategy/{strategy_id}/events")
def delete_strategy_events(
    strategy_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    deleted = db.query(StrategyEvent).filter(
        StrategyEvent.strategy_instance_id == strategy_id
    ).delete(synchronize_session=False)
    db.commit()
    return {"message": f"已删除 {deleted} 条事件", "deleted": deleted}


@router.get("/strategy/{strategy_id}/events/export")
def export_strategy_events(
    strategy_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    events = db.query(StrategyEvent).filter(
        StrategyEvent.strategy_instance_id == strategy_id
    ).order_by(StrategyEvent.created_at.desc()).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "event_type", "message", "details", "created_at"])
    for e in events:
        writer.writerow([
            e.id,
            e.event_type,
            e.message,
            e.details or "",
            e.created_at.isoformat() if e.created_at else "",
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=strategy_{strategy_id}_events.csv"},
    )