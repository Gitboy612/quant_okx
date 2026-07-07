import os
import tempfile
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
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


# ========== Proxy Settings ==========

@router.get("/proxy")
def get_proxy_settings_route(
    user: User = Depends(get_current_user),
):
    from services.proxy_service import get_proxy_settings, get_proxy_settings_with_nodes
    return get_proxy_settings_with_nodes()


@router.put("/proxy")
def save_proxy_settings_route(
    body: dict,
    user: User = Depends(get_current_user),
):
    from services.proxy_service import save_proxy_settings
    proxy_enabled = str(body.get("proxy_enabled", "false")).lower()
    proxy_url = str(body.get("proxy_url", ""))
    proxy_config_path = str(body.get("proxy_config_path", ""))
    save_proxy_settings(proxy_enabled, proxy_url, proxy_config_path)
    return {"message": "代理设置已保存"}


@router.post("/proxy/test")
def test_proxy_route(
    body: dict | None = None,
    user: User = Depends(get_current_user),
):
    from services.proxy_service import test_proxy, get_proxy_url
    proxy_url = body.get("proxy_url") if body else None
    if proxy_url:
        result = test_proxy(proxy_url)
    else:
        result = test_proxy(get_proxy_url())
    return result


@router.post("/proxy/config/import")
async def import_proxy_config(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
):
    from services.proxy_service import import_clash_config_from_content
    content = await file.read()
    # Save to temp file for storage reference
    config_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
    os.makedirs(config_dir, exist_ok=True)
    config_path = os.path.join(config_dir, f"proxy_config_{file.filename}")
    with open(config_path, "wb") as f:
        f.write(content)
    try:
        result = import_clash_config_from_content(content.decode("utf-8"), config_path)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
