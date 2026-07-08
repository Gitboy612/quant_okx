import os
import json
from pathlib import Path
from database import SessionLocal


def _get_setting(db, key: str) -> str | None:
    from models.system_settings import SystemSetting
    s = db.query(SystemSetting).filter(SystemSetting.key == key).first()
    return s.value if s else None


def _set_setting(db, key: str, value: str):
    from datetime import datetime, timezone
    from models.system_settings import SystemSetting
    s = db.query(SystemSetting).filter(SystemSetting.key == key).first()
    if s:
        s.value = value
        s.updated_at = datetime.now(timezone.utc)
    else:
        s = SystemSetting(key=key, value=value)
        db.add(s)
    db.commit()


def get_proxy_settings() -> dict:
    """Get current proxy settings from database."""
    db = SessionLocal()
    try:
        return {
            "proxy_enabled": _get_setting(db, "proxy_enabled") or "false",
            "proxy_url": _get_setting(db, "proxy_url") or "",
            "proxy_config_path": _get_setting(db, "proxy_config_path") or "",
            "proxy_embedded_port": _get_setting(db, "proxy_embedded_port") or "7890",
        }
    finally:
        db.close()


def get_proxy_settings_with_nodes() -> dict:
    """Get current proxy settings including parsed nodes from config file."""
    settings = get_proxy_settings()
    nodes = []
    config_path = settings.get("proxy_config_path", "")
    if config_path and os.path.exists(config_path):
        try:
            nodes = parse_clash_config(config_path)
        except Exception:
            pass
    settings["nodes"] = nodes
    return settings


def save_proxy_settings(proxy_enabled: str, proxy_url: str, proxy_config_path: str, proxy_embedded_port: str = "7890"):
    """Save proxy settings to database."""
    db = SessionLocal()
    try:
        _set_setting(db, "proxy_enabled", proxy_enabled)
        _set_setting(db, "proxy_url", proxy_url)
        _set_setting(db, "proxy_config_path", proxy_config_path)
        _set_setting(db, "proxy_embedded_port", proxy_embedded_port)
    finally:
        db.close()


def parse_clash_config(config_path: str) -> list[dict]:
    """Parse a Clash YAML config file and extract proxy nodes."""
    import yaml

    if not os.path.exists(config_path):
        raise FileNotFoundError(f"配置文件不存在: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        content = f.read()

    try:
        try:
            config = yaml.load(content, Loader=yaml.CSafeLoader)
        except (AttributeError, ImportError):
            config = yaml.safe_load(content)
    except yaml.YAMLError as e:
        detail = str(e)
        if hasattr(e, 'problem_mark') and e.problem_mark:
            mark = e.problem_mark
            detail = f"第 {mark.line + 1} 行, 第 {mark.column + 1} 列: {e.problem}"
        raise ValueError(f"YAML 解析失败: {detail}")
    except Exception as e:
        raise ValueError(f"配置解析失败: {type(e).__name__}: {e}")

    proxies = config.get("proxies", [])
    if not proxies:
        return []

    nodes = []
    for p in proxies:
        if isinstance(p, dict):
            nodes.append({
                "name": p.get("name", ""),
                "type": p.get("type", ""),
                "server": p.get("server", ""),
                "port": p.get("port", ""),
            })
    return nodes


def import_clash_config(config_path: str) -> dict:
    """Import a Clash config file and return node list.
    Also saves the config path to database.
    """
    nodes = parse_clash_config(config_path)
    db = SessionLocal()
    try:
        _set_setting(db, "proxy_config_path", config_path)
    finally:
        db.close()
    return {"nodes": nodes, "count": len(nodes)}


def import_clash_config_from_content(content: str, config_path: str) -> dict:
    """Parse Clash config from string content and save path to DB."""
    import yaml
    try:
        try:
            config = yaml.load(content, Loader=yaml.CSafeLoader)
        except (AttributeError, ImportError):
            config = yaml.safe_load(content)
    except yaml.YAMLError as e:
        detail = str(e)
        if hasattr(e, 'problem_mark') and e.problem_mark:
            mark = e.problem_mark
            detail = f"第 {mark.line + 1} 行, 第 {mark.column + 1} 列: {e.problem}"
        raise ValueError(f"YAML 解析失败: {detail}")
    except Exception as e:
        raise ValueError(f"配置解析失败: {type(e).__name__}: {e}")

    proxies = config.get("proxies", [])
    if not proxies:
        return {"nodes": [], "count": 0, "message": "配置文件中未找到代理节点"}

    nodes = []
    for p in proxies:
        if isinstance(p, dict):
            nodes.append({
                "name": p.get("name", ""),
                "type": p.get("type", ""),
                "server": p.get("server", ""),
                "port": p.get("port", ""),
            })

    db = SessionLocal()
    try:
        _set_setting(db, "proxy_config_path", config_path)
    finally:
        db.close()
    return {"nodes": nodes, "count": len(nodes), "message": f"成功导入 {len(nodes)} 个节点"}


def get_proxy_url() -> str | None:
    """Get proxy URL based on current settings.

    If proxy_enabled is true:
    - If proxy_url (manual) is set, use it.
    - Otherwise, use embedded proxy at http://127.0.0.1:{proxy_embedded_port} (default 7890).
    If proxy_enabled is false, return None.
    """
    settings = get_proxy_settings()

    if settings.get("proxy_enabled") != "true":
        return None

    manual_url = settings.get("proxy_url", "")
    if manual_url:
        return manual_url

    embedded_port = settings.get("proxy_embedded_port", "7890")
    return f"http://127.0.0.1:{embedded_port}"


def test_proxy(proxy_url: str | None = None) -> dict:
    """Test proxy connectivity against multiple targets (Google, GitHub, OKX).

    Verifies the proxy can actually reach sites behind the GFW.
    Returns multi-target results:
    {google: {ok, latency_ms}, github: {ok, latency_ms}, okx: {ok, latency_ms, message}}
    """
    import httpx
    import time

    if proxy_url is None:
        proxy_url = get_proxy_url()

    if not proxy_url:
        return {
            "google": {"ok": False, "latency_ms": 0, "message": "未配置代理地址"},
            "github": {"ok": False, "latency_ms": 0, "message": "未配置代理地址"},
            "okx": {"ok": False, "latency_ms": 0, "message": "未配置代理地址"},
        }

    def _test_single(target_name: str, url: str) -> dict:
        try:
            start = time.time()
            with httpx.Client(proxy=proxy_url, timeout=8) as client:
                resp = client.get(url)
                elapsed = round((time.time() - start) * 1000)
                if target_name == "okx":
                    if resp.status_code == 200:
                        data = resp.json()
                        if data.get("code") == "0":
                            return {"ok": True, "latency_ms": elapsed, "message": "OKX API 连通正常"}
                        return {"ok": False, "latency_ms": elapsed, "message": f"OKX API 返回错误: code={data.get('code')} msg={data.get('msg', '')}"}
                    return {"ok": False, "latency_ms": elapsed, "message": f"HTTP {resp.status_code}"}
                else:
                    # google (expect 204) and github (expect 200/301)
                    if resp.status_code in (200, 204, 301):
                        return {"ok": True, "latency_ms": elapsed}
                    return {"ok": False, "latency_ms": elapsed, "message": f"HTTP {resp.status_code}"}
        except Exception as e:
            return {"ok": False, "latency_ms": 0, "message": str(e)[:100]}

    return {
        "google": _test_single("google", "https://www.google.com/generate_204"),
        "github": _test_single("github", "https://github.com"),
        "okx": _test_single("okx", "https://www.okx.com/api/v5/public/time"),
    }