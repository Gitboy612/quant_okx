# -*- coding: utf-8 -*-
"""QuantOKX 桌面客户端入口（Task 2 + Task 3 集成）。

职责
----
- 创建 ``QApplication``（含 QtWidgets，供托盘 ``QMenu`` 使用）并设置应用基础信息。
- 单实例守卫：仅允许一个实例运行（``SingleInstance``）。
- 注册 QML↔Python 桥接服务（``qml_bridge``）并以 context property 暴露单例。
- 加载 ``qml/main.qml``（Task 1 的无边框标题栏保留不动）。
- 系统托盘（``TrayController``）：显示 / 退出 / 通知 / 最小化到托盘。
- 可选：以环境变量 ``DESKTOP_BACKEND_HTTP=1`` 启动 uvicorn 后台线程（默认不启）。
- 把桥接服务的主动推送信号（``orderFilled`` 等）简单连到托盘通知（Task 5 细化文案）。
- 启动后自检一次 DB 连通性（``AccountService.listAccounts()`` 打印）。
- ``aboutToQuit`` 清理：停 uvicorn 线程、隐藏托盘、关闭单实例 server。

说明
----
- main.qml 由 Task 4 改造；本文件不改 QML，只在 Python 侧暴露好接口与注释。
- 全局快捷键 ``Ctrl+K``（唤起搜索）由 QML 端 Task 4 用 ``Shortcut{}`` 实现，本文件不做。
"""

import os
import sys

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication
from PySide6.QtQml import QQmlApplicationEngine

# 导入即注册 QML 桥接类型（qml_bridge 末尾调用 register_qml_types()）
import qml_bridge  # noqa: F401
from qml_bridge import (
    AccountService,
    StrategyService,
    OrderService,
    PnlService,
    MonitoringService,
    LogService,
    AuthService,
)
from tray import TrayController
from single_instance import SingleInstance


def _fmt_order(d) -> str:
    """把订单 dict 格式化为简短通知文案。"""
    if not isinstance(d, dict):
        return str(d)
    return f"{d.get('side', '')} {d.get('symbol', '')} 数量={d.get('quantity', '')} 状态={d.get('status', '')}"


def _connect_notifications(services: dict, tray: TrayController):
    """把桥接服务的主动推送信号连到托盘通知（Task 5 再细化文案 / 接事件源）。"""
    order_svc: OrderService = services["orderService"]
    strategy_svc: StrategyService = services["strategyService"]
    monitor_svc: MonitoringService = services["monitoringService"]

    # 订单成交 → 通知
    order_svc.orderFilled.connect(
        lambda d: tray.showMessage("订单成交", _fmt_order(d))
    )
    # 策略触发 → 通知
    strategy_svc.strategyTriggered.connect(
        lambda d: tray.showMessage("策略触发", str(d))
    )
    # 策略状态变更 → 通知
    strategy_svc.strategyStatusChanged.connect(
        lambda d: tray.showMessage("策略状态变更", str(d))
    )
    # 通用告警 (title, body) → 通知
    order_svc.alert.connect(lambda t, b: tray.showMessage(t, b))
    strategy_svc.alert.connect(lambda t, b: tray.showMessage(t, b))
    monitor_svc.alert.connect(lambda t, b: tray.showMessage(t, b))


def _db_self_check(services: dict):
    """启动后自检 DB 连通性：调一次 listAccounts() 并打印结果。

    表不存在等异常会被捕获并打印提示，不影响应用启动。
    """
    account_svc: AccountService = services["accountService"]
    try:
        accounts = account_svc.listAccounts()
        count = len(accounts)
        print(f"[QuantOKX] DB 自检：accounts 表读取成功，共 {count} 条账户")
        if accounts:
            first = accounts[0]
            print(f"[QuantOKX] 首条账户：id={first.get('id')} name={first.get('name')} "
                  f"trade_mode={first.get('trade_mode')} is_active={first.get('is_active')}")
    except Exception as e:
        # 表未初始化等情况：提示用户先运行过后端 init_db，但不阻塞
        print(f"[QuantOKX] DB 自检失败（可能表未初始化）：{type(e).__name__}: {e}")


def main() -> int:
    # 应用基础信息（QSettings 等会用到组织名/应用名）
    QCoreApplication.setOrganizationName("QuantOKX")
    QCoreApplication.setApplicationName("QuantOKX")

    # 用 QApplication（非 QGuiApplication）：托盘 QMenu/QAction 属于 QtWidgets，
    # 需要 QApplication 才能正常工作。QApplication 是 QGuiApplication 的超集，不影响 QML。
    app = QApplication(sys.argv)
    # setApplicationDisplayName 属于 QGuiApplication，需在 app 创建后调用
    app.setApplicationDisplayName("QuantOKX")
    # 关闭按钮默认退出行为由 QML 控制；这里保证 Quit 时干净退出
    app.setQuitOnLastWindowClosed(False)  # 关闭主窗口不立即退出（托盘仍可唤醒），Task 4 接 minimizeToTray

    # ---- 单实例守卫：第二个实例直接退出 ----
    single = SingleInstance("QuantOKX")
    if not single.is_first():
        print("[QuantOKX] 已有实例在运行，本进程退出。")
        return 0

    # ---- QML 引擎 ----
    engine = QQmlApplicationEngine()

    # 让 QML 文件可以直接 import "components" / "theme" 等子目录
    qml_dir = os.path.dirname(os.path.abspath(__file__))
    qml_root = os.path.join(qml_dir, "qml")
    engine.addImportPath(qml_root)

    # ---- 桥接服务单例（在 load 前创建并暴露为 context property）----
    # 这样 Task 4 的 QML 无需 import QuantOKX.Services 即可直接用 accountService.listAccounts()
    # 同时便于此处连接信号。引用保留在 services dict，防止 Python 侧 GC。
    services = {
        "accountService": AccountService(),
        "strategyService": StrategyService(),
        "orderService": OrderService(),
        "pnlService": PnlService(),
        "monitoringService": MonitoringService(),
        "logService": LogService(),
        "authService": AuthService(),
    }
    ctx = engine.rootContext()
    for name, svc in services.items():
        ctx.setContextProperty(name, svc)

    # ---- 加载 main.qml ----
    main_qml = os.path.join(qml_root, "main.qml")
    engine.load(main_qml)
    if not engine.rootObjects():
        print(f"[QuantOKX] 无法加载 QML 主文件: {main_qml}", file=sys.stderr)
        return 1
    window = engine.rootObjects()[0]

    # ---- 系统托盘 ----
    # icon_path 留空 → tray.py 自动绘制简易图标；Task 6 打包时可换 resources/icons/app.ico
    icon_path = os.path.join(qml_dir, "resources", "icons", "app.ico")
    if not os.path.exists(icon_path):
        icon_path = None
    tray = TrayController(window, icon_path=icon_path)
    # 暴露给 QML（Task 4 标题栏关闭按钮调 trayController.minimizeToTray()）
    ctx.setContextProperty("trayController", tray)

    # 第二个实例尝试启动时：show / raise 主窗口并通知
    single.anotherInstanceStarted.connect(
        lambda: (
            tray.restore(),
            tray.showMessage("QuantOKX", "已恢复到运行中的实例"),
        )
    )

    # ---- 信号 → 托盘通知 ----
    _connect_notifications(services, tray)

    # ---- DB 连通性自检 ----
    _db_self_check(services)

    # ---- 可选：uvicorn 后台线程（默认不启）----
    backend_thread = None
    if os.getenv("DESKTOP_BACKEND_HTTP", "").lower() in ("1", "true", "yes"):
        try:
            # 延迟 import：仅启用 HTTP 模式时才加载后端 FastAPI app
            sys.path.insert(0, os.path.join(qml_dir, "..", "backend"))
            from main import app as fastapi_app  # backend/main.py
            from backend_thread import BackendThread

            host = os.getenv("DESKTOP_BACKEND_HOST", "127.0.0.1")
            port = int(os.getenv("DESKTOP_BACKEND_PORT", "8000"))
            backend_thread = BackendThread(fastapi_app, host=host, port=port)
            backend_thread.start()
            print(f"[QuantOKX] uvicorn 后台线程已启动：http://{host}:{port}")
        except Exception as e:
            print(f"[QuantOKX] 启动 uvicorn 后台线程失败（不影响桌面端运行）：{type(e).__name__}: {e}",
                  file=sys.stderr)
            backend_thread = None

    # ---- 退出清理 ----
    def on_about_to_quit():
        if backend_thread is not None and backend_thread.isRunning():
            backend_thread.stop()
        tray.teardown()
        single.teardown()

    app.aboutToQuit.connect(on_about_to_quit)

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
