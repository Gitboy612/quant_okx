# -*- coding: utf-8 -*-
"""QuantOKX 桌面客户端系统托盘控制器（Task 3）。

职责
----
- ``QSystemTrayIcon`` + 右键 ``QMenu``（显示主窗口 / 退出）。
- 双击托盘图标显示并聚焦主窗口。
- ``showMessage(title, msg)`` 封装系统通知。
- ``minimizeToTray()`` 隐藏主窗口到托盘（供 QML 标题栏关闭按钮调用，
  QML 端由 Task 4 接入；本任务仅在 Python 侧备好接口）。

说明
----
- ``window`` 为 QML ``ApplicationWindow`` 的根对象（``QQuickWindow``），
  由 main.py 通过 ``engine.rootObjects()[0]`` 传入。
- 若未提供 ``icon_path``，用代码绘制一个简易图标，保证托盘始终可见。
- 全局快捷键 ``Ctrl+K``（唤起搜索）由 QML 端 Task 4 用 ``Shortcut{}`` 实现，
  本文件不做。
"""

import os

from PySide6.QtCore import QObject, Qt, Slot, Signal
from PySide6.QtGui import (
    QIcon,
    QPixmap,
    QPainter,
    QColor,
    QAction,
    QKeySequence,
)
from PySide6.QtWidgets import QMenu, QSystemTrayIcon


class TrayController(QObject):
    """系统托盘控制器。"""

    # 托盘「显示」被触发（双击或菜单），便于 main.py / QML 做额外处理
    showRequested = Signal()

    def __init__(self, window, icon_path: str = None, parent=None):
        super().__init__(parent)
        self._window = window

        # ---- 图标 ----
        icon = self._build_icon(icon_path)

        # ---- 托盘 ----
        self._tray = QSystemTrayIcon(icon, parent=self)
        self._tray.setToolTip("QuantOKX")
        self._tray.setVisible(True)

        # ---- 右键菜单 ----
        # 持有菜单与 action 引用，避免被 GC 回收
        self._menu = QMenu()
        self._act_show = QAction("显示主窗口", self._menu)
        self._act_show.triggered.connect(self.restore)
        self._act_quit = QAction("退出", self._menu)
        self._act_quit.setShortcut(QKeySequence("Ctrl+Q"))
        self._act_quit.triggered.connect(self._on_quit)
        self._menu.addAction(self._act_show)
        self._menu.addSeparator()
        self._menu.addAction(self._act_quit)
        self._tray.setContextMenu(self._menu)

        # ---- 激活（双击显示）----
        self._tray.activated.connect(self._on_activated)

    # ------------------------------------------------------------------
    # 图标构建
    # ------------------------------------------------------------------
    @staticmethod
    def _build_icon(icon_path: str) -> QIcon:
        """构造托盘图标：优先用 icon_path，否则绘制一个简易方块图标。"""
        if icon_path and os.path.exists(icon_path):
            return QIcon(icon_path)
        # 回退：绘制 64x64 深色方块 + "Q" 字样
        pix = QPixmap(64, 64)
        pix.fill(Qt.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QColor("#1e1e2e"))
        painter.setPen(QColor("#89b4fa"))
        painter.drawRoundedRect(2, 2, 60, 60, 12, 12)
        painter.setPen(QColor("#cdd6f4"))
        font = painter.font()
        font.setPixelSize(34)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(pix.rect(), Qt.AlignCenter, "Q")
        painter.end()
        return QIcon(pix)

    # ------------------------------------------------------------------
    # 槽 / 公共方法
    # ------------------------------------------------------------------
    @Slot()
    def restore(self):
        """显示、置顶并激活主窗口。"""
        if self._window is None:
            return
        self._window.show()
        self._window.raise_()
        # requestActivate 让窗口获取焦点
        try:
            self._window.requestActivate()
        except AttributeError:
            pass
        self.showRequested.emit()

    @Slot()
    def minimizeToTray(self):
        """隐藏主窗口到托盘（关闭按钮最小化到托盘）。

        供 QML 标题栏关闭按钮调用：QML 端 ``onClicked: trayController.minimizeToTray()``。
        Task 4 接入；本任务先在 Python 侧备好。
        """
        if self._window is None:
            return
        self._window.hide()

    @Slot(str, str)
    def showMessage(self, title: str, msg: str):
        """弹出系统通知（托盘气泡）。"""
        if self._tray.isVisible():
            self._tray.showMessage(title, msg, QSystemTrayIcon.Information, 4000)

    @Slot(result="bool")
    def isAvailable(self):
        """系统托盘是否可用。"""
        return QSystemTrayIcon.isSystemTrayAvailable()

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    def _on_activated(self, reason):
        # 双击托盘图标 → 显示窗口
        if reason == QSystemTrayIcon.DoubleClick:
            self.restore()

    def _on_quit(self):
        # 退出菜单 → 真正退出应用（区别于 minimizeToTray 的隐藏）
        from PySide6.QtCore import QCoreApplication
        QCoreApplication.quit()

    # ------------------------------------------------------------------
    # 资源清理
    # ------------------------------------------------------------------
    def teardown(self):
        """应用退出前隐藏托盘图标。"""
        if self._tray is not None:
            self._tray.hide()
