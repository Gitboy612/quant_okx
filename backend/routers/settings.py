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
    proxy_embedded_port = str(body.get("proxy_embedded_port", "7890"))
    save_proxy_settings(proxy_enabled, proxy_url, proxy_config_path, proxy_embedded_port)
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


# ========== Embedded Proxy Core Management ==========

@router.get("/proxy/status")
def get_proxy_core_status(
    user: User = Depends(get_current_user),
):
    """Get embedded proxy core status."""
    from services.proxy_core import get_proxy_status
    return get_proxy_status()


@router.post("/proxy/start")
def start_proxy_core(
    body: dict | None = None,
    user: User = Depends(get_current_user),
):
    """Start embedded proxy core."""
    from services.proxy_core import start_proxy
    config_path = body.get("config_path") if body else None
    port = int(body.get("port", 7890)) if body else 7890
    result = start_proxy(config_path=config_path, port=port)
    return result


@router.post("/proxy/stop")
def stop_proxy_core(
    user: User = Depends(get_current_user),
):
    """Stop embedded proxy core."""
    from services.proxy_core import stop_proxy
    return stop_proxy()


@router.post("/proxy/config/import")
async def import_proxy_config(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
):
    from services.proxy_service import import_clash_config_from_content
    content = await file.read()
    # Save to config directory
    config_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
    os.makedirs(config_dir, exist_ok=True)
    config_path = os.path.join(config_dir, f"proxy_config_{file.filename}")
    with open(config_path, "wb") as f:
        f.write(content)
    try:
        # Try UTF-8 first, then GBK for Chinese configs
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            try:
                text = content.decode("gbk")
            except UnicodeDecodeError as e:
                raise HTTPException(status_code=400, detail=f"文件编码无法识别: {e}")
        result = import_clash_config_from_content(text, config_path)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/proxy/sample-configs")
def get_sample_configs_route(
    user: User = Depends(get_current_user),
):
    """List sample airport config files in backend directory."""
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    samples = []
    for fname in os.listdir(backend_dir):
        # Only include yml/yaml/net files, exclude rewritten configs and data-dir configs
        if fname.startswith("proxy_config_rewrite"):
            continue
        if fname.startswith("proxy_config_") and (fname.endswith(".yml") or fname.endswith(".yaml")):
            # skip the imported copies in backend root that match proxy_config_ prefix
            continue
        lower = fname.lower()
        if lower.endswith(".yml") or lower.endswith(".yaml") or lower.endswith(".net"):
            samples.append({"name": fname, "path": os.path.join(backend_dir, fname)})
    return {"samples": samples}


@router.post("/proxy/sample-configs/import")
def import_sample_config_route(
    body: dict,
    user: User = Depends(get_current_user),
):
    """Import a sample config file by path."""
    from services.proxy_service import import_clash_config_from_content
    config_path = body.get("path", "")
    if not config_path or not os.path.exists(config_path):
        raise HTTPException(status_code=400, detail="配置文件不存在")
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            content = f.read()
    except UnicodeDecodeError:
        with open(config_path, "r", encoding="gbk") as f:
            content = f.read()
    # Save a copy to data dir
    config_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
    os.makedirs(config_dir, exist_ok=True)
    dest_path = os.path.join(config_dir, f"proxy_config_{os.path.basename(config_path)}")
    with open(dest_path, "w", encoding="utf-8") as f:
        f.write(content)
    try:
        result = import_clash_config_from_content(content, dest_path)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
