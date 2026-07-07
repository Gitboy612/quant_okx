from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from datetime import datetime, timezone
from database import get_db
from models.user import User
from models.setting import UserSetting
from middleware.auth import get_current_user

router = APIRouter(prefix="/api/settings", tags=["settings"])

DEFAULT_SETTINGS = {
    "refresh_interval": "30",
}


def _get_setting(db: Session, key: str) -> str:
    s = db.query(UserSetting).filter(UserSetting.key == key).first()
    return s.value if s else DEFAULT_SETTINGS.get(key, "")


@router.get("")
def get_settings(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = {}
    for key in DEFAULT_SETTINGS:
        result[key] = _get_setting(db, key)
    return result


@router.put("")
def save_settings(
    body: dict,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    for key, value in body.items():
        if key not in DEFAULT_SETTINGS:
            continue
        s = db.query(UserSetting).filter(UserSetting.key == key).first()
        if s:
            s.value = str(value)
            s.updated_at = datetime.now(timezone.utc)
        else:
            s = UserSetting(key=key, value=str(value))
            db.add(s)
    db.commit()
    return {"message": "设置已保存"}
