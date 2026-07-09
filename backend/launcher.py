"""QuantOKX 启动器 - PyInstaller 打包入口。

启动 uvicorn 后台服务，等待端口就绪后打开浏览器，关闭窗口/Ctrl+C 时优雅退出。
"""
import os
import sys
import time
import socket
import signal
import threading
import webbrowser

# 确保 backend 目录在 sys.path 中（源码运行时）
if not getattr(sys, "frozen", False):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _wait_for_port(host: str, port: int, timeout: float = 30.0) -> bool:
    """轮询等待端口可连接。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.3)
    return False


def main():
    from config import HOST, PORT
    import uvicorn
    from main import app

    # 后台线程运行 uvicorn
    config_obj = uvicorn.Config(
        app,
        host=HOST,
        port=PORT,
        log_level="info",
        ws="websockets",
    )
    server = uvicorn.Server(config_obj)

    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()

    print(f"[launcher] QuantOKX 启动中... http://{HOST}:{PORT}")

    # 等待端口就绪
    if _wait_for_port(HOST, PORT, timeout=30.0):
        print(f"[launcher] 服务已就绪，打开浏览器...")
        url = f"http://127.0.0.1:{PORT}" if HOST in ("0.0.0.0", "127.0.0.1") else f"http://{HOST}:{PORT}"
        # 避免浏览器抢焦点太早，稍作延迟
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    else:
        print("[launcher] 警告：服务启动超时，请手动访问")

    # 信号处理：Ctrl+C 优雅退出
    def _shutdown(signum, frame):
        print("\n[launcher] 正在关闭服务...")
        server.should_exit = True
        server_thread.join(timeout=5)
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    # 主线程保持运行
    try:
        while server_thread.is_alive():
            server_thread.join(timeout=1.0)
    except KeyboardInterrupt:
        _shutdown(None, None)


if __name__ == "__main__":
    main()
