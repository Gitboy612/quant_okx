from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from database import get_db
from models.log import OperationLog
from models.user import User
from middleware.auth import get_current_user

router = APIRouter(prefix="/api/logs", tags=["logs"])


def to_utc_iso(dt: datetime | None) -> str | None:
    """将 datetime 序列化为带 Z 后缀的 UTC ISO 字符串。

    - None 返回 None
    - naive datetime（无 tzinfo，SQLite 常见情况）视为 UTC
    - aware datetime 转换为 UTC
    - 输出 isoformat 并确保以 'Z' 结尾
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


@router.get("")
def list_logs(
    action: str | None = Query(None),
    target_type: str | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = db.query(OperationLog)
    if action:
        query = query.filter(OperationLog.action == action)
    if target_type:
        query = query.filter(OperationLog.target_type == target_type)

    total = query.count()
    logs = query.order_by(OperationLog.created_at.desc()).offset(offset).limit(limit).all()
    return {
        "total": total,
        "items": [
            {
                "id": l.id,
                "user_id": l.user_id,
                "action": l.action,
                "target_type": l.target_type,
                "target_id": l.target_id,
                "detail": l.detail,
                "ip_address": l.ip_address,
                "created_at": to_utc_iso(l.created_at),
            }
            for l in logs
        ],
    }
