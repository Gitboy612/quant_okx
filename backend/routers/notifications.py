from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models.user import User
from models.notification_rule import NotificationRule
from middleware.auth import get_current_user
from services.notification_service import CHANNEL_REGISTRY, notification_service

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


VALID_CHANNEL_TYPES = set(CHANNEL_REGISTRY.keys())


def _serialize_rule(rule: NotificationRule) -> dict:
    return {
        "id": rule.id,
        "name": rule.name,
        "event_types": rule.event_types or [],
        "channel_type": rule.channel_type,
        "channel_config": rule.channel_config or {},
        "is_active": rule.is_active,
        "created_at": rule.created_at.isoformat() if rule.created_at else None,
        "updated_at": rule.updated_at.isoformat() if rule.updated_at else None,
    }


@router.get("/rules")
def list_rules(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    rules = db.query(NotificationRule).order_by(NotificationRule.created_at.desc()).all()
    return {"items": [_serialize_rule(r) for r in rules]}


@router.post("/rules")
def create_rule(
    body: dict,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="规则名称不能为空")
    event_types = body.get("event_types") or []
    if not isinstance(event_types, list) or not event_types:
        raise HTTPException(status_code=400, detail="event_types 必须为非空数组")
    channel_type = body.get("channel_type")
    if channel_type not in VALID_CHANNEL_TYPES:
        raise HTTPException(status_code=400, detail=f"不支持的渠道类型: {channel_type}")
    channel_config = body.get("channel_config") or {}
    if not isinstance(channel_config, dict):
        raise HTTPException(status_code=400, detail="channel_config 必须为对象")

    rule = NotificationRule(
        name=name,
        event_types=[str(t) for t in event_types],
        channel_type=channel_type,
        channel_config=channel_config,
        is_active=bool(body.get("is_active", True)),
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return _serialize_rule(rule)


@router.put("/rules/{rule_id}")
def update_rule(
    rule_id: int,
    body: dict,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    rule = db.query(NotificationRule).filter(NotificationRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="通知规则不存在")

    if "name" in body:
        name = (body.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="规则名称不能为空")
        rule.name = name
    if "event_types" in body:
        event_types = body.get("event_types") or []
        if not isinstance(event_types, list) or not event_types:
            raise HTTPException(status_code=400, detail="event_types 必须为非空数组")
        rule.event_types = [str(t) for t in event_types]
    if "channel_type" in body:
        channel_type = body.get("channel_type")
        if channel_type not in VALID_CHANNEL_TYPES:
            raise HTTPException(status_code=400, detail=f"不支持的渠道类型: {channel_type}")
        rule.channel_type = channel_type
    if "channel_config" in body:
        channel_config = body.get("channel_config") or {}
        if not isinstance(channel_config, dict):
            raise HTTPException(status_code=400, detail="channel_config 必须为对象")
        rule.channel_config = channel_config
    if "is_active" in body:
        rule.is_active = bool(body.get("is_active"))

    rule.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(rule)
    return _serialize_rule(rule)


@router.delete("/rules/{rule_id}")
def delete_rule(
    rule_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    rule = db.query(NotificationRule).filter(NotificationRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="通知规则不存在")
    db.delete(rule)
    db.commit()
    return {"message": f"已删除通知规则: {rule.name}"}


@router.post("/test")
async def test_notification(
    body: dict,
    user: User = Depends(get_current_user),
):
    """测试发送通知。

    请求体：
        {
            "channel_type": "email" | "webhook" | "telegram",
            "channel_config": { ... }  # 可选；缺省时使用系统默认渠道
        }
    """
    channel_type = body.get("channel_type")
    if channel_type not in VALID_CHANNEL_TYPES:
        raise HTTPException(status_code=400, detail=f"不支持的渠道类型: {channel_type}")
    channel_config = body.get("channel_config")
    ok = await notification_service.test_channel(channel_type, channel_config)
    return {"ok": ok, "channel_type": channel_type}
