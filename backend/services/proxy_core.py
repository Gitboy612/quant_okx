"""Embedded proxy core management - manages a local Clash proxy process."""
import os
import sys
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
_proxy_log_file = None  # file handle for mihomo stdout/stderr log
_proxy_log_path: str | None = None


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

# mihomo 启动时硬依赖的 GeoIP 数据库文件，需从 meta-rules-dat 仓库下载。
# 国内直连 GitHub 经常超时，会导致 mihomo 卡在 MMDB 就绪阶段无法监听端口。
MMDB_FILES = [
    {"name": "geoip.metadb", "url": "https://github.com/MetaCubeX/meta-rules-dat/releases/download/latest/geoip.metadb"},
    {"name": "geosite.dat", "url": "https://github.com/MetaCubeX/meta-rules-dat/releases/download/latest/geosite.dat"},
    {"name": "GeoIP.dat", "url": "https://github.com/MetaCubeX/meta-rules-dat/releases/download/latest/GeoIP.dat"},
    {"name": "GeoSite.dat", "url": "https://github.com/MetaCubeX/meta-rules-dat/releases/download/latest/GeoSite.dat"},
]

# 国内访问 GitHub 经常超时，使用镜像兜底。前缀式镜像把原始 GitHub URL 拼接在后面。
# 按稳定性排序，逐个尝试直到成功。
GITHUB_MIRROR_PREFIXES = [
    "",  # 直连 GitHub（用户已开系统 VPN 时可用）
    "https://gh-proxy.com/",
    "https://ghproxy.net/",
    "https://mirror.ghproxy.com/",
]
# 替换式镜像：把 github.com 替换为下列域名
GITHUB_MIRROR_HOSTS = [
    "hub.gitmirror.com",
    "download.fastgit.org",
]


def _wrap_with_mirrors(github_url: str) -> list[str]:
    """返回原始 URL + 各镜像 URL 的列表，按优先级排序。"""
    urls = []
    # 1. 原始直连（仅在用户已有系统代理时可用）
    urls.append(github_url)
    # 2. 前缀式镜像
    for prefix in GITHUB_MIRROR_PREFIXES:
        if prefix:
            urls.append(prefix + github_url)
    # 3. 替换式镜像
    for host in GITHUB_MIRROR_HOSTS:
        if "github.com" in github_url:
            urls.append(github_url.replace("github.com", host, 1))
    return urls


def _get_bin_dir() -> str:
    """Get the bin directory for storing binaries."""
    if getattr(sys, "frozen", False):
        # PyInstaller 打包后：mihomo.exe 携带在 _MEIPASS/bin
        bin_dir = os.path.join(sys._MEIPASS, "bin")
        os.makedirs(bin_dir, exist_ok=True)
        return bin_dir
    current_dir = os.path.dirname(os.path.abspath(__file__))
    bin_dir = os.path.join(os.path.dirname(current_dir), "bin")
    os.makedirs(bin_dir, exist_ok=True)
    return bin_dir


def _download_mihomo() -> str | None:
    """Download mihomo binary from GitHub releases (with China-accessible mirrors).
    Returns the path to the downloaded binary, or None on failure.
    """
    bin_dir = _get_bin_dir()
    mihomo_path = os.path.join(bin_dir, "mihomo.exe")

    # Check if already downloaded
    if os.path.exists(mihomo_path):
        return mihomo_path

    try:
        # Fetch the latest release info, trying GitHub direct + mirrors
        print(f"[proxy_core] Fetching latest mihomo release info...")
        release_data = None
        api_urls = _wrap_with_mirrors(MIHOMO_API_URL)
        for i, api_url in enumerate(api_urls):
            try:
                req = urllib.request.Request(api_url)
                req.add_header("Accept", "application/json")
                req.add_header("User-Agent", "quant-okx/1.0")
                with urllib.request.urlopen(req, timeout=15) as resp:
                    import json as json_module
                    release_data = json_module.loads(resp.read())
                print(f"[proxy_core] Release info fetched from {api_url}")
                break
            except Exception as e:
                print(f"[proxy_core] Source {i+1}/{len(api_urls)} failed ({api_url}): {e}")

        if release_data is None:
            print("[proxy_core] All sources failed to fetch release info")
            return None

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

        # Try downloading from each mirror in sequence
        mirror_urls = _wrap_with_mirrors(download_url)
        tmp_path = tempfile.mktemp(suffix=".zip")
        last_err = None
        for i, mirror_url in enumerate(mirror_urls):
            try:
                print(f"[proxy_core] Downloading mihomo from {mirror_url} (source {i+1}/{len(mirror_urls)})...")
                # Use a proxy-aware retrieval with timeout
                req = urllib.request.Request(mirror_url, headers={"User-Agent": "quant-okx/1.0"})
                with urllib.request.urlopen(req, timeout=60) as resp, open(tmp_path, "wb") as out:
                    out.write(resp.read())
                print(f"[proxy_core] Download succeeded from {mirror_url}")
                last_err = None
                break
            except Exception as e:
                print(f"[proxy_core] Download failed ({mirror_url}): {e}")
                last_err = e
                # Clean up partial file before trying next mirror
                if os.path.exists(tmp_path):
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass

        if last_err is not None or not os.path.exists(tmp_path):
            print("[proxy_core] All download sources failed")
            _print_manual_install_hint(bin_dir, mihomo_path)
            return None

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
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

        if os.path.exists(mihomo_path):
            return mihomo_path
        return None

    except Exception as e:
        print(f"[proxy_core] Failed to download mihomo: {e}")
        _print_manual_install_hint(bin_dir, mihomo_path)
        return None


def _print_manual_install_hint(bin_dir: str, mihomo_path: str):
    """Print a hint guiding the user to manually install mihomo when all downloads fail."""
    print("[proxy_core] ============================================")
    print("[proxy_core] 自动下载 mihomo 失败（国内访问 GitHub 受限）")
    print(f"[proxy_core] 请手动下载 mihomo 并放置到: {mihomo_path}")
    print("[proxy_core] 下载地址（任选其一可访问的）:")
    print("[proxy_core]   - https://github.com/MetaCubeX/mihomo/releases/latest")
    print("[proxy_core]   - https://gh-proxy.com/https://github.com/MetaCubeX/mihomo/releases/latest")
    print("[proxy_core]   - https://mirror.ghproxy.com/https://github.com/MetaCubeX/mihomo/releases/latest")
    print("[proxy_core] 选择 windows-amd64-v3.zip 下载，解压后把 mihomo.exe 放到上述目录即可")
    print(f"[proxy_core] 或安装 mihomo 到系统 PATH，或放置到 %USERPROFILE%\\.mihomo\\ 目录")
    print("[proxy_core] ============================================")


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

    # frozen 运行时 _MEIPASS 只读，不自动下载
    if getattr(sys, "frozen", False):
        return None

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


def _is_port_listening(port: int, timeout: float = 0.5) -> bool:
    """Check if a TCP port is currently accepting connections on 127.0.0.1."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(("127.0.0.1", port))
        s.close()
        return True
    except OSError:
        return False


def _wait_for_port_listening(port: int, process: subprocess.Popen, timeout: float = 8.0) -> tuple[bool, str]:
    """Wait until the port is accepting connections or the process exits.
    Returns (ok, reason) where reason describes why it failed.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        # Process exited before port came up
        if process.poll() is not None:
            return False, "process_exited"
        if _is_port_listening(port, timeout=0.5):
            return True, "ok"
        time.sleep(0.3)
    return False, "timeout"


def _read_mihomo_log_tail(log_path: str, max_lines: int = 40) -> str:
    """Read the last N lines of the mihomo log file for error diagnostics."""
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        if not lines:
            return "(日志为空)"
        tail = "".join(lines[-max_lines:]).strip()
        return tail or "(日志为空)"
    except Exception as e:
        return f"(读取日志失败: {e})"


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

    # 清理可能与 mixed-port 抢同一端口的独立端口配置。
    # 否则若用户配置里 port/socks-port 也是 7890，mihomo 会因端口冲突启动失败。
    for conflicting_key in ("port", "socks-port", "redir-port", "tproxy-port"):
        if conflicting_key in config:
            removed_value = config.pop(conflicting_key)
            print(f"[proxy_core] Removed conflicting '{conflicting_key}: {removed_value}' from config (using mixed-port={port})")

    # Write the rewritten config preserving original YAML style
    with open(rewritten_path, "w", encoding="utf-8") as f:
        yaml_lib.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    print(f"[proxy_core] Rewritten config saved to {rewritten_path}")
    return rewritten_path


def _get_mmdb_dir() -> str:
    """Get the directory where MMDB files should be placed (mihomo working dir)."""
    config_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
    os.makedirs(config_dir, exist_ok=True)
    return config_dir


def _check_mmdb_ready() -> dict:
    """检查每个 MMDB 文件是否存在，返回结构化状态。
    文件不存在时不抛异常，仅标记 exists=False。
    """
    mmdb_dir = _get_mmdb_dir()
    files_info = []
    missing = []
    for f in MMDB_FILES:
        path = os.path.join(mmdb_dir, f["name"])
        if os.path.exists(path):
            try:
                size = os.path.getsize(path)
                mtime = datetime.fromtimestamp(os.path.getmtime(path), timezone.utc).isoformat()
            except OSError:
                size = 0
                mtime = None
            files_info.append({"name": f["name"], "exists": True, "size": size, "mtime": mtime})
        else:
            files_info.append({"name": f["name"], "exists": False, "size": 0, "mtime": None})
            missing.append(f["name"])
    return {
        "ready": len(missing) == 0,
        "files": files_info,
        "missing": missing,
    }


def _download_mmdb_files() -> dict:
    """复用 _wrap_with_mirrors 镜像兜底逻辑，逐文件下载 MMDB 文件到 backend/data/。
    单文件失败不中断整个流程。
    """
    mmdb_dir = _get_mmdb_dir()
    downloaded = []
    failed = []
    skipped = []

    for f in MMDB_FILES:
        name = f["name"]
        url = f["url"]
        target_path = os.path.join(mmdb_dir, name)

        # 已存在则跳过
        if os.path.exists(target_path):
            skipped.append(name)
            continue

        mirror_urls = _wrap_with_mirrors(url)
        success = False
        for i, mirror_url in enumerate(mirror_urls):
            try:
                print(f"[proxy_core] Downloading MMDB {name} from {mirror_url} (source {i+1}/{len(mirror_urls)})...")
                req = urllib.request.Request(mirror_url, headers={"User-Agent": "quant-okx/1.0"})
                with urllib.request.urlopen(req, timeout=60) as resp, open(target_path, "wb") as out:
                    out.write(resp.read())
                print(f"[proxy_core] MMDB file {name} downloaded from {mirror_url}")
                success = True
                break
            except Exception as e:
                print(f"[proxy_core] MMDB download failed ({mirror_url}): {e}")
                # 清理可能残留的部分文件
                if os.path.exists(target_path):
                    try:
                        os.unlink(target_path)
                    except OSError:
                        pass

        if success:
            downloaded.append(name)
        else:
            print(f"[proxy_core] MMDB file {name} 所有镜像下载均失败，跳过")
            failed.append(name)

    return {"downloaded": downloaded, "failed": failed, "skipped": skipped}


def _print_mmdb_manual_hint(missing_files: list[str], mmdb_dir: str):
    """参考 _print_manual_install_hint 风格，输出 MMDB 手动下载指引。"""
    print("[proxy_core] ============================================")
    print("[proxy_core] 自动下载 MMDB 文件失败（国内访问 GitHub 受限）")
    print(f"[proxy_core] 请手动下载以下文件并放置到: {mmdb_dir}")
    print("[proxy_core] 缺失文件:")
    for name in missing_files:
        print(f"[proxy_core]   - {name}")
    print("[proxy_core] 下载地址（任选其一可访问的）:")
    for name in missing_files:
        # 找到对应文件的原始 URL
        original_url = ""
        for f in MMDB_FILES:
            if f["name"] == name:
                original_url = f["url"]
                break
        print(f"[proxy_core]   - {original_url}")
        print(f"[proxy_core]   - https://gh-proxy.com/{original_url}")
        print(f"[proxy_core]   - https://mirror.ghproxy.com/{original_url}")
    print("[proxy_core] ============================================")


def start_proxy(config_path: str | None = None, port: int = 7890, bootstrap_proxy: str | None = None) -> dict:
    """Start the embedded proxy core.
    
    Args:
        config_path: Path to Clash config file. If None, uses the saved config path.
        port: Proxy listening port (default 7890).
        bootstrap_proxy: Optional bootstrap proxy URL (e.g. http://127.0.0.1:7897) used to
            help mihomo download MMDB files through an existing system proxy.
    
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

    # MMDB 文件预检查与预下载：mihomo 启动时会尝试下载 GeoIP 数据库，国内直连 GitHub
    # 会卡死导致端口轮询超时。这里提前下载，未就绪则不启动 mihomo 以避免死锁。
    mmdb_status = _check_mmdb_ready()
    if not mmdb_status["ready"]:
        print("[proxy_core] MMDB files not ready, attempting download...")
        _download_mmdb_files()
        mmdb_status = _check_mmdb_ready()

    if not mmdb_status["ready"] and not bootstrap_proxy:
        _print_mmdb_manual_hint(mmdb_status["missing"], _get_mmdb_dir())
        return {
            "status": "error",
            "message": "MMDB 文件缺失且无法下载。请手动放置或填写引导代理后重试。",
            "mmdb_status": mmdb_status,
        }

    # 构造子进程环境变量：配置了 bootstrap_proxy 时让 mihomo 走引导代理下载 MMDB
    if bootstrap_proxy:
        env = os.environ.copy()
        env["HTTP_PROXY"] = bootstrap_proxy
        env["HTTPS_PROXY"] = bootstrap_proxy
    else:
        env = None

    # Log file for mihomo stdout/stderr - replaces DEVNULL so we can diagnose startup failures
    global _proxy_log_file, _proxy_log_path
    log_path = os.path.join(config_dir, f"mihomo_{port}.log")
    try:
        _proxy_log_file = open(log_path, "w", encoding="utf-8")
        _proxy_log_path = log_path
    except Exception as e:
        return {"status": "error", "message": f"无法创建日志文件: {e}"}

    try:
        # Start the proxy process - redirect output to log file for diagnostics
        cmd = [binary, "-d", config_dir, "-f", config_path]

        _proxy_process = subprocess.Popen(
            cmd,
            stdout=_proxy_log_file,
            stderr=subprocess.STDOUT,
            cwd=config_dir,
            env=env,
        )
        _proxy_port = port
        _proxy_started_at = datetime.now(timezone.utc)

        # Flush log file so we can read it back immediately
        try:
            _proxy_log_file.flush()
        except Exception:
            pass

        # Wait for the port to actually accept connections (replaces fixed sleep).
        # mihomo usually needs 1-3s to start; some configs need more (node testing, etc.)
        ok, reason = _wait_for_port_listening(port, _proxy_process, timeout=8.0)

        if not ok:
            # Read mihomo log to surface the real reason
            log_tail = _read_mihomo_log_tail(log_path, max_lines=40)
            print(f"[proxy_core] mihomo failed to listen on {port} (reason={reason})")
            print(f"[proxy_core] mihomo log tail:\n{log_tail}")

            # Kill the process if it's still hanging
            if _proxy_process.poll() is None:
                try:
                    _proxy_process.terminate()
                    try:
                        _proxy_process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        _proxy_process.kill()
                except Exception:
                    pass

            # Close log file handle
            try:
                _proxy_log_file.close()
            except Exception:
                pass
            _proxy_log_file = None

            return {
                "status": "error",
                "message": f"代理进程启动失败（{reason}）。mihomo 日志：\n{log_tail}",
                "log_path": log_path,
            }

        print(f"[proxy_core] mihomo is listening on 127.0.0.1:{port}")

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
            "log_path": log_path,
            "message": "代理已启动",
            "connectivity": connectivity,
            "mmdb_status": mmdb_status,
        }
        return result
    except Exception as e:
        # Make sure to close log file on error
        try:
            if _proxy_log_file is not None:
                _proxy_log_file.close()
                _proxy_log_file = None
        except Exception:
            pass
        return {"status": "error", "message": f"启动代理失败: {str(e)}"}


def stop_proxy() -> dict:
    """Stop the embedded proxy core."""
    global _proxy_process, _proxy_port, _proxy_started_at, _proxy_log_file, _proxy_log_path

    if _proxy_process is None or _proxy_process.poll() is not None:
        _proxy_process = None
        _proxy_started_at = None
        # Close any lingering log file
        try:
            if _proxy_log_file is not None:
                _proxy_log_file.close()
                _proxy_log_file = None
        except Exception:
            pass
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

    # Close log file handle
    try:
        if _proxy_log_file is not None:
            _proxy_log_file.close()
            _proxy_log_file = None
    except Exception:
        pass

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


def get_proxy_log(max_lines: int = 200) -> dict:
    """Return the tail of the mihomo log for diagnostics."""
    global _proxy_log_path
    if not _proxy_log_path or not os.path.exists(_proxy_log_path):
        return {"log_path": _proxy_log_path, "content": "(无日志文件)"}
    # Flush the file if it's still open so we read the latest content
    try:
        if _proxy_log_file is not None:
            _proxy_log_file.flush()
    except Exception:
        pass
    content = _read_mihomo_log_tail(_proxy_log_path, max_lines=max_lines)
    return {"log_path": _proxy_log_path, "content": content}


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