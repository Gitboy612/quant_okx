# -*- coding: utf-8 -*-
"""QuantOKX 桌面客户端单实例控制（Task 3）。

职责
----
- 用 ``QLocalSocket`` / ``QLocalServer`` 实现「只允许一个实例运行」。
- 第二个实例启动时：连接到已存在的 server 成功 → 判定为「已有实例」，
  emit ``anotherInstanceStarted`` 信号后由 main.py 退出本进程。
- 第一个实例：创建 ``QLocalServer`` 监听，当第二个实例连接进来时，
  server 的 ``newConnection`` → emit ``anotherInstanceStarted``，
  便于主窗口 show / raise 聚焦。

Windows 注意
------------
- ``QLocalServer`` 在 Windows 上基于命名管道，server 名需全局唯一；
  这里用 "QuantOKX" 作为名字（组织名/应用名已设为 QuantOKX）。
- 异常退出可能残留 server，创建前先 ``removeServer`` 清理。
"""

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket


class SingleInstance(QObject):
    """单实例守卫。"""

    # 当第二个实例尝试启动时发射（两种来源都接同一个信号）：
    # 1) 本进程是第二个实例，连上了已有 server；
    # 2) 本进程是首个实例，其 server 收到了新连接。
    # main.py 据此：情况1 退出本进程；情况2 show/raise 主窗口。
    anotherInstanceStarted = Signal()

    def __init__(self, name: str = "QuantOKX", parent=None):
        super().__init__(parent)
        self._name = name
        self._server = None
        self._is_first = False

        # 尝试连接已存在的 server：能连上说明已有实例在跑
        socket = QLocalSocket()
        socket.connectToServer(name)
        # waitForConnected 在 Windows 上对命名管道即时返回
        if socket.waitForConnected(500):
            # 已有实例：本进程是第二个 → 通知对方后由 main.py 退出
            socket.disconnectFromServer()
            self._is_first = False
            # 稍后由 main.py 处理：先发射信号再退出
            self.anotherInstanceStarted.emit()
        else:
            # 首个实例：清理可能残留的 server（上次崩溃残留）后监听
            QLocalServer.removeServer(name)
            self._server = QLocalServer(self)
            self._server.setSocketOptions(QLocalServer.UserAccessOption)
            self._server.listen(name)
            self._server.newConnection.connect(self.anotherInstanceStarted)
            self._is_first = True

    def is_first(self) -> bool:
        """是否为首个（主）实例。"""
        return self._is_first

    def teardown(self):
        """应用退出时关闭 server（下次启动可正常重建）。"""
        if self._server is not None:
            self._server.close()
            self._server = None
