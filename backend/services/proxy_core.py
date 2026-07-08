"""Embedded proxy core management - manages a local Clash proxy process."""
import os
import socket
import subprocess
import time
import urllib.request
import zipfile
import tempfile
import yaml as yaml_lib
from datetime import datetime, timezone
from pathlib import Path
from database import SessionLocal

_proxy_process: subprocess.Popen | None = None
_proxy_port: int = 7890
_proxy_started_at: datetime | None = None


def _get_setting(db, key: str) -> str | None:
    from models.system_settings import SystemSetting
    s = db.query(SystemSetting).filter(SystemSetting.key == key).first()
    return s.value if s else None


def _set_setting(db, key: str, value: str):
    from models.system_settings import SystemSetting
    s = db.query(SystemSetting).filter(SystemSetting.key == key).first()
    if s:
        s.value = value
        s.updated_at = datetime.now(timezone.utc)
    else:
        s = SystemSetting(key=key, value=value)
        db.add(s)
    db.commit()


MIHOMO_API_URL = "https://api.github.com/repos/MetaCubeX/mihomo/releases/latest"


def _get_bin_dir() -> str:
    """Get the bin directory for storing binaries."""
    current_dir = os.path.dirname(os.path.abspath(__file__))
    bin_dir = os.path.join(os.path.dirname(current_dir), "bin")
    os.makedirs(bin_dir, exist_ok=True)
    return bin_dir


def _download_mihomo() -> str | None:
    """Download mihomo binary from GitHub releases.
    Returns the path to the downloaded binary, or None on failure.
    """
    bin_dir = _get_bin_dir()
    mihomo_path = os.path.join(bin_dir, "mihomo.exe")
    
    # Check if already downloaded
    if os.path.exists(mihomo_path):
        return mihomo_path
    
    try:
        # Fetch the latest release info from GitHub API
        print(f"[proxy_core] Fetching latest mihomo release info...")
        req = urllib.request.Request(MIHOMO_API_URL)
        req.add_header("Accept", "application/json")
        req.add_header("User-Agent", "quant-okx/1.0")
        
        with urllib.request.urlopen(req, timeout=30) as resp:
            import json as json_module
            release_data = json_module.loads(resp.read())
        
        # Find the Windows amd64 v3 asset
        download_url = None
        for asset in release_data.get("assets", []):
            name = asset.get("name", "")
            if "windows" in name.lower() and "amd64" in name and "v3" in name and name.endswith(".zip"):
                download_url = asset.get("browser_download_url")
                break
        
        if not download_url:
            # Fallback: try any Windows amd64 zip
            for asset in release_data.get("assets", []):
                name = asset.get("name", "")
                if "windows" in name.lower() and "amd64" in name and name.endswith(".zip"):
                    download_url = asset.get("browser_download_url")
                    break
        
        if not download_url:
            print("[proxy_core] No suitable mihomo binary found in release")
            return None
        
        print(f"[proxy_core] Downloading mihomo from {download_url}...")
        
        # Download the zip file
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
            tmp_path = tmp.name
        
        urllib.request.urlretrieve(download_url, tmp_path)
        
        # Extract mihomo.exe from the zip
        with zipfile.ZipFile(tmp_path, 'r') as zf:
            # Find the mihomo.exe in the zip
            exe_name = None
            for name in zf.namelist():
                if name.endswith('.exe'):
                    exe_name = name
                    break
            
            if exe_name:
                # Extract to bin directory
                zf.extract(exe_name, bin_dir)
                extracted_path = os.path.join(bin_dir, exe_name)
                if extracted_path != mihomo_path:
                    os.rename(extracted_path, mihomo_path)
                print(f"[proxy_core] mihomo downloaded to {mihomo_path}")
            else:
                # Try to extract all and find the exe
                zf.extractall(bin_dir)
                for f in os.listdir(bin_dir):
                    if f.endswith('.exe') and 'mihomo' in f.lower():
                        src = os.path.join(bin_dir, f)
                        if src != mihomo_path:
                            os.rename(src, mihomo_path)
                        print(f"[proxy_core] mihomo downloaded to {mihomo_path}")
                        break
        
        # Clean up temp file
        os.unlink(tmp_path)
        
        if os.path.exists(mihomo_path):
            return mihomo_path
        return None
        
    except Exception as e:
        print(f"[proxy_core] Failed to download mihomo: {e}")
        return None


def _find_clash_binary() -> str | None:
    """Find an available Clash/Mihomo binary on the system."""
    # Check bin directory first (where we download to)
    bin_dir = _get_bin_dir()
    mihomo_path = os.path.join(bin_dir, "mihomo.exe")
    if os.path.exists(mihomo_path):
        return mihomo_path
    
    # Common names for Clash/Mihomo binaries
    candidates = ["mihomo", "clash", "clash-meta", "clash-verge", "mihomo.exe", "clash.exe", "clash-meta.exe"]
    
    import shutil
    for name in candidates:
        found = shutil.which(name)
        if found:
            return found
    
    # Check common install locations
    common_paths = [
        os.path.expandvars(r"%USERPROFILE%\.mihomo\mihomo.exe"),
        os.path.expandvars(r"%USERPROFILE%\scoop\apps\clash\current\clash.exe"),
        os.path.expandvars(r"%USERPROFILE%\scoop\shims\mihomo.exe"),
        os.path.expandvars(r"%USERPROFILE%\scoop\shims\clash.exe"),
        r"C:\Program Files\Clash\clash.exe",
        r"C:\Program Files\Clash Verge\clash.exe",
        r"C:\Program Files\mihomo\mihomo.exe",
    ]
    for p in common_paths:
        if os.path.exists(p):
            return p
    
    # Try to download mihomo
    downloaded = _download_mihomo()
    if downloaded:
        return downloaded
    
    return None


def _test_connectivity(proxy_url: str, port: int) -> dict:
    """Test if the proxy can reach multiple targets (Google, GitHub, OKX).

    Verifies the proxy can actually reach sites behind the GFW.
    Returns multi-target results:
    {google: {ok, latency_ms}, github: {ok, latency_ms}, okx: {ok, latency_ms, message}}
    """
    import time as time_module
    import httpx

    def _test_single(target_name: str, url: str) -> dict:
        try:
            start = time_module.time()
            with httpx.Client(proxy=proxy_url, timeout=8) as client:
                resp = client.get(url)
                elapsed = round((time_module.time() - start) * 1000)
                if target_name == "okx":
                    if resp.status_code == 200:
                        data = resp.json()
                        if data.get("code") == "0":
                            return {"ok": True, "latency_ms": elapsed, "message": "OKX API 连通正常"}
                        return {"ok": False, "latency_ms": elapsed, "message": f"OKX API 返回错误: code={data.get('code')}"}
                    return {"ok": False, "latency_ms": elapsed, "message": f"HTTP {resp.status_code}"}
                else:
                    # google (expect 204) and github (expect 200/301)
                    if resp.status_code in (200, 204, 301):
                        return {"ok": True, "latency_ms": elapsed}
                    return {"ok": False, "latency_ms": elapsed, "message": f"HTTP {resp.status_code}"}
        except Exception as e:
            return {"ok": False, "latency_ms": 0, "message": str(e)[:100]}

    # No extra sleep needed - the proxy already slept 1.5s during startup in start_proxy()
    return {
        "google": _test_single("google", "https://www.google.com/generate_204"),
        "github": _test_single("github", "https://github.com"),
        "okx": _test_single("okx", "https://www.okx.com/api/v5/public/time"),
    }


def _check_port_available(port: int) -> bool:
    """Check if a port is available on localhost."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", port))
        s.close()
        return True
    except OSError:
        return False


def _rewrite_config(config_path: str, port: int) -> str:
    """Rewrite Clash config to use the specified mixed-port and avoid conflicts.
    Returns the path to the rewritten config file.
    """
    config_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
    os.makedirs(config_dir, exist_ok=True)
    rewritten_path = os.path.join(config_dir, f"proxy_config_rewrite_{port}.yaml")
    
    with open(config_path, "r", encoding="utf-8") as f:
        content = f.read()
    
    try:
        try:
            config = yaml_lib.load(content, Loader=yaml_lib.CSafeLoader)
        except (AttributeError, ImportError):
            config = yaml_lib.safe_load(content)
    except Exception as e:
        raise ValueError(f"配置文件解析失败: {e}")
    
    if config is None:
        config = {}
    
    # Override mixed-port and external-controller
    config["mixed-port"] = port
    config["external-controller"] = "127.0.0.1:0"  # random port, avoid conflicts
    
    # Write the rewritten config preserving original YAML style
    with open(rewritten_path, "w", encoding="utf-8") as f:
        yaml_lib.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    
    print(f"[proxy_core] Rewritten config saved to {rewritten_path}")
    return rewritten_path


def start_proxy(config_path: str | None = None, port: int = 7890) -> dict:
    """Start the embedded proxy core.
    
    Args:
        config_path: Path to Clash config file. If None, uses the saved config path.
        port: Proxy listening port (default 7890).
    
    Returns:
        dict with status info.
    """
    global _proxy_process, _proxy_port, _proxy_started_at
    
    if _proxy_process is not None and _proxy_process.poll() is None:
        return {"status": "already_running", "port": _proxy_port, "message": "代理已在运行中"}
    
    # Check port availability
    if not _check_port_available(port):
        return {"status": "error", "message": f"端口 {port} 已被占用，请修改端口后重试"}
    
    binary = _find_clash_binary()
    if binary is None:
        return {"status": "error", "message": "未找到 Clash/Mihomo 可执行文件。请安装 mihomo 或 clash-meta 到系统 PATH 或 %USERPROFILE%\\.mihomo\\ 目录"}
    
    # Get config path from DB if not provided
    if config_path is None:
        db = SessionLocal()
        try:
            config_path = _get_setting(db, "proxy_config_path") or ""
        finally:
            db.close()
    
    if not config_path or not os.path.exists(config_path):
        # Try to find a default config
        default_configs = [
            os.path.expandvars(r"%USERPROFILE%\.mihomo\config.yaml"),
            os.path.expandvars(r"%USERPROFILE%\.config\clash\config.yaml"),
            os.path.expandvars(r"%USERPROFILE%\.config\mihomo\config.yaml"),
        ]
        config_path = None
        for dc in default_configs:
            if os.path.exists(dc):
                config_path = dc
                break
        
        if config_path is None:
            return {"status": "error", "message": "未找到代理配置文件。请先在代理设置中导入 Clash 配置文件"}
    
    # Save original config path for reference
    original_config_path = config_path
    
    # Rewrite config to avoid port conflicts
    try:
        rewritten_config = _rewrite_config(config_path, port)
    except Exception as e:
        return {"status": "error", "message": str(e)}
    
    # Use rewritten config
    config_path = rewritten_config
    config_dir = os.path.dirname(config_path)
    
    try:
        # Start the proxy process
        cmd = [binary, "-d", config_dir, "-f", config_path]
        
        _proxy_process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=config_dir,
        )
        _proxy_port = port
        _proxy_started_at = datetime.now(timezone.utc)
        
        # Wait a moment for the proxy to start
        time.sleep(1.5)
        
        if _proxy_process.poll() is not None:
            return {"status": "error", "message": "代理进程启动失败，请检查配置文件是否正确"}
        
        # Set global proxy for OKXClient
        from services.okx_client import OKXClient
        proxy_url = f"http://127.0.0.1:{port}"
        OKXClient.set_global_proxy(proxy_url)
        
        # Save proxy settings
        db = SessionLocal()
        try:
            _set_setting(db, "proxy_enabled", "true")
            _set_setting(db, "proxy_url", proxy_url)
        finally:
            db.close()
        
        # Test connectivity
        connectivity = _test_connectivity(proxy_url, port)
        
        result = {
            "status": "running",
            "port": port,
            "pid": _proxy_process.pid,
            "started_at": _proxy_started_at.isoformat(),
            "binary": binary,
            "config_path": config_path,
            "original_config_path": original_config_path,
            "message": "代理已启动",
            "connectivity": connectivity,
        }
        return result
    except Exception as e:
        return {"status": "error", "message": f"启动代理失败: {str(e)}"}


def stop_proxy() -> dict:
    """Stop the embedded proxy core."""
    global _proxy_process, _proxy_port, _proxy_started_at
    
    if _proxy_process is None or _proxy_process.poll() is not None:
        _proxy_process = None
        _proxy_started_at = None
        return {"status": "stopped", "message": "代理未在运行"}
    
    try:
        _proxy_process.terminate()
        try:
            _proxy_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _proxy_process.kill()
            _proxy_process.wait()
    except Exception as e:
        return {"status": "error", "message": f"停止代理失败: {str(e)}"}
    
    _proxy_process = None
    _proxy_started_at = None
    
    # Clear global proxy for OKXClient
    from services.okx_client import OKXClient
    OKXClient.set_global_proxy(None)
    
    # Update settings
    db = SessionLocal()
    try:
        _set_setting(db, "proxy_enabled", "false")
    finally:
        db.close()
    
    return {"status": "stopped", "message": "代理已停止"}


def get_proxy_status() -> dict:
    """Get current proxy status."""
    global _proxy_process, _proxy_port, _proxy_started_at
    
    is_running = _proxy_process is not None and _proxy_process.poll() is None
    
    if is_running:
        uptime_seconds = (datetime.now(timezone.utc) - _proxy_started_at).total_seconds() if _proxy_started_at else 0
        return {
            "status": "running",
            "port": _proxy_port,
            "pid": _proxy_process.pid,
            "started_at": _proxy_started_at.isoformat() if _proxy_started_at else None,
            "uptime_seconds": int(uptime_seconds),
        }
    else:
        return {
            "status": "stopped",
            "port": _proxy_port,
            "pid": None,
            "started_at": None,
            "uptime_seconds": 0,
        }