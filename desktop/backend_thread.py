# -*- coding: utf-8 -*-
"""QuantOKX 桌面客户端 uvicorn 后台线程封装（Task 2，可选）。

职责
----
- 用 ``QThread`` 在后台运行 uvicorn，承载后端 FastAPI app，
  供 QML 走 HTTP / WebSocket 调用后端（与 Web 前端共用同一套 API）。

何时启用
--------
- **默认不启用**。桌面端默认走 ``qml_bridge.py`` 的同进程桥接（直接查 DB / 调服务），
  无需起 HTTP 服务。
- 仅当需要复用 Web 端的 HTTP/WS 接口（如 WebSocket 行情推送、复用 fetch 逻辑）时，
  设置环境变量 ``DESKTOP_BACKEND_HTTP=1`` 启用本线程（main.py 据此决定）。

为什么 uvicorn 延迟 import
--------------------------
- 桌面端运行环境未必安装 uvicorn（uvicorn 属于 backend/requirements.txt）。
- 延迟到 ``run()`` 内部 import，使 ``main.py`` 在不启用 HTTP 模式时无需依赖 uvicorn 即可启动。
"""

from PySide6.QtCore import QThread


class BackendThread(QThread):
    """在独立线程中运行 uvicorn Server 的封装。

    Parameters
    ----------
    app : FastAPI
        后端 FastAPI 应用对象（由 ``backend/main.py`` 的 ``app`` 提供）。
    host : str
        监听地址，默认 127.0.0.1（仅本机访问，安全）。
    port : int
        监听端口，默认 8000。
    """

    def __init__(self, app, host: str = "127.0.0.1", port: int = 8000, parent=None):
        super().__init__(parent)
        self._app = app
        self._host = host
        self._port = port
        self._server = None  # uvicorn.Server 实例，run() 中赋值

    def run(self):
        """线程入口：构造并运行 uvicorn Server（阻塞直至 should_exit）。"""
        # 延迟 import：避免未启用 HTTP 模式时强依赖 uvicorn
        import uvicorn

        config = uvicorn.Config(
            self._app,
            host=self._host,
            port=self._port,
            log_level="warning",  # 桌面端不打 info 级日志，避免刷屏
            ws="websockets",
        )
        self._server = uvicorn.Server(config)
        # 在子线程中运行；Windows 下 uvicorn 的信号处理本就受限，
        # 停止时由 stop() 置 should_exit=True 触发优雅退出，不依赖信号。
        self._server.run()

    def stop(self):
        """优雅停止 uvicorn：置 should_exit 后等待线程结束（最多 5s）。"""
        if self._server is not None:
            self._server.should_exit = True
        # 给 uvicorn 一点时间清理 in-flight 请求
        self.wait(5000)
