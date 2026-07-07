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


def save_proxy_settings(proxy_enabled: str, proxy_url: str, proxy_config_path: str):
    """Save proxy settings to database."""
    db = SessionLocal()
    try:
        _set_setting(db, "proxy_enabled", proxy_enabled)
        _set_setting(db, "proxy_url", proxy_url)
        _set_setting(db, "proxy_config_path", proxy_config_path)
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
        config = yaml.safe_load(content)
    except Exception as e:
        raise ValueError(f"YAML 解析失败: {e}")

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
        config = yaml.safe_load(content)
    except Exception as e:
        raise ValueError(f"YAML 解析失败: {e}")

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


def get_proxy_url(node_name: str | None = None) -> str | None:
    """Get proxy URL. If node_name is given, try to find it from Clash config.
    Otherwise, use the manually set proxy_url from settings.
    Default Clash local port is 7890.
    """
    settings = get_proxy_settings()

    if settings.get("proxy_enabled") != "true":
        return None

    manual_url = settings.get("proxy_url", "")
    if manual_url:
        return manual_url

    config_path = settings.get("proxy_config_path", "")
    if config_path and node_name:
        try:
            nodes = parse_clash_config(config_path)
            for node in nodes:
                if node["name"] == node_name:
                    return f"http://127.0.0.1:{node['port']}"
        except Exception:
            pass

    return "http://127.0.0.1:7890"


def test_proxy(proxy_url: str | None = None) -> dict:
    """Test proxy connectivity by accessing OKX public time endpoint."""
    import httpx
    import time

    if proxy_url is None:
        proxy_url = get_proxy_url()

    if not proxy_url:
        return {"ok": False, "message": "未配置代理地址"}

    try:
        start = time.time()
        with httpx.Client(proxy=proxy_url, timeout=10) as client:
            resp = client.get("https://openapi.okx.com/api/v5/public/time")
            elapsed = round((time.time() - start) * 1000)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("code") == "0":
                    return {"ok": True, "message": "代理连通正常", "latency_ms": elapsed}
                return {"ok": False, "message": f"OKX API 返回错误: code={data.get('code')} msg={data.get('msg', '')}", "latency_ms": elapsed}
            return {"ok": False, "message": f"HTTP {resp.status_code}", "latency_ms": elapsed}
    except Exception as e:
        return {"ok": False, "message": str(e)}