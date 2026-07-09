# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for QuantOKX Desktop（PySide6 + QML 桌面客户端）。

构建命令:
    pyinstaller desktop/QuantOKX-Desktop.spec --noconfirm
产物:
    dist/QuantOKX-Desktop/QuantOKX-Desktop.exe  (onedir 模式)

体积说明:
    经 excludes 裁剪后预计 40-80MB（PySide6 QML 模块 + mihomo.exe + 后端依赖）。
    本 spec 默认 upx=False：Qt dll 经 UPX 压缩偶发加载失败 / 杀软误报，为保证稳定性
    不压缩；如需更小体积可改 upx=True 并自行验证运行时无异常。

与 web 版 QuantOKX.spec 的区别:
    - 入口 desktop/main.py（非 backend/launcher.py）
    - 含 PySide6 全量（collect_data_files + collect_submodules），让 QML 运行时能
      import QtQuick / QtCharts / QtQuick3D 等模块
    - datas 含 desktop/qml + 托盘图标 + mihomo.exe，**不含** frontend/dist（桌面端用 QML）
    - console=False（GUI 无控制台窗口），upx=False

约束:
    - 不改 web 版 QuantOKX.spec
    - 不改 desktop/** 的 Python/QML 代码（本 spec 只做打包配置）
"""
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# 项目根目录（本 spec 位于 desktop/ 下，故上溯一层到项目根）
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(SPEC)))
DESKTOP_DIR = os.path.join(PROJECT_ROOT, 'desktop')
BACKEND_DIR = os.path.join(PROJECT_ROOT, 'backend')
ICON_PATH = os.path.join(DESKTOP_DIR, 'resources', 'icons', 'app.ico')

# ---- 数据文件 ----
# 1. desktop/qml/** -> qml/      QML 源码（main.qml / components / pages）
#    运行时 main.py 用 os.path.dirname(__file__)/qml 定位；frozen onedir 下
#    __file__ 落在 _MEIPASS（= exe 所在目录），故 qml 平铺到 bundle 根的 qml/。
# 2. app.ico -> resources/icons/ 托盘图标（main.py 查 <qml_dir>/resources/icons/app.ico）
# 3. mihomo.exe -> bin/           嵌入式代理（复用 backend/bin；proxy_core.py frozen
#    时按 _MEIPASS/bin/mihomo.exe 查找）
datas = [
    (os.path.join(DESKTOP_DIR, 'qml'), 'qml'),
    (ICON_PATH, 'resources/icons'),
    (os.path.join(BACKEND_DIR, 'bin', 'mihomo.exe'), 'bin'),
]

# PySide6 的 Qt 插件 / QML 模块（QtQuick / QtQuick3D / QtCharts 的 qmldir + dll）随包。
# collect_data_files 把 PySide6/qml/** 等数据文件按目录结构放入 bundle，配合
# PyInstaller 自带的 hook-PySide6.Qt*.py 生成 qt.conf，运行时 QML 引擎才能 import
# QtQuick / QtCharts 等模块（这是 QML 桌面端打包的关键）。
# 注意：保留全量 collect_data_files('PySide6') 不做 includes 过滤（PyInstaller 该 API
# 的 includes 参数对 PySide6 的 qml 子树匹配不稳定，易漏 qmldir 导致运行时缺模块）。
# 体积控制主要靠 excludes 裁剪 Python 绑定层 + 不用的 Qt 模块 dll；QML 数据层
# （qmldir + 必需模块 dll）必须保留以避免运行时 import QtQuick 报"module not found"。
datas += collect_data_files('PySide6')

# ---- 隐式 / 延迟导入 ----
hiddenimports = []

# === 复用 web 版：后端第三方库的动态加载部分 ===
# python-okx 真实 import 名是 `okx`（from okx import Account），用 collect_submodules 收全
hiddenimports += collect_submodules('okx')
hiddenimports += collect_submodules('apscheduler')
# python-jose 运行时动态加载加密后端 (jose.backends.*)，PyInstaller 无内置 hook，收全
hiddenimports += collect_submodules('jose')
hiddenimports += [
    'httpx', 'h11', 'h2', 'hpack', 'hyperframe',
    'cryptography', 'bcrypt',
    # aiosqlite 未实际安装：database.py 把 "sqlite+aiosqlite" 替换为 "sqlite" 走同步引擎
    'sqlalchemy.dialects.sqlite',
    'websockets', 'yaml', 'dotenv', 'multipart',
    'uvicorn', 'uvicorn.logging',
    'uvicorn.protocols', 'uvicorn.protocols.http',
    'uvicorn.protocols.websockets', 'uvicorn.protocols.websockets.auto',
    'uvicorn.lifespan', 'uvicorn.lifespan.on',
]

# === PySide6 相关 ===
# 注意：不再使用 collect_submodules('PySide6') 全量收集（会引入 QtWebEngine/QtMultimedia
# 等不用的 Qt 模块的 Python 绑定层，体积膨胀 40MB+）。
# 改为显式列出本项目实际用到的 PySide6 子模块：
#   - QtCore/QtGui/QtWidgets：QApplication/QSystemTrayIcon/QMenu 等基础类
#   - QtQml/QtQuick/QtQuickControls2/QtQuickLayouts/QtQuickTemplates2：QML 引擎与基础模块
#   - QtQuick3D/QtQuick3DUtils：DashboardPage.qml 的 3D 氛围背景
#   - QtCharts/QtChartsQml：PnlPage.qml 的 ChartView
#   - QtNetwork：single_instance.py 的 QLocalServer/QLocalSocket
# 其他不用的 Qt 模块（QtWebEngine/QtMultimedia/QtSvg/QtSql/QtTest 等）在 excludes 中显式裁剪。
hiddenimports += [
    'PySide6.QtCore',
    'PySide6.QtGui',
    'PySide6.QtWidgets',  # QApplication/QSystemTrayIcon/QMenu
    'PySide6.QtQml',
    'PySide6.QtQuick',
    'PySide6.QtQuickControls2',
    'PySide6.QtQuickLayouts',
    'PySide6.QtQuickTemplates2',
    'PySide6.QtQuick3D',
    'PySide6.QtQuick3DUtils',
    'PySide6.QtCharts',
    'PySide6.QtChartsQml',
    'PySide6.QtNetwork',  # QLocalServer/QLocalSocket 单实例
    'shiboken6',
]

a = Analysis(
    [os.path.join(DESKTOP_DIR, 'main.py')],
    # pathex 顺序：backend 在前，desktop 在后。
    # 原因：desktop/main.py 内有 `from main import app`（由 backend/main.py 提供
    # FastAPI app）。若 desktop 在前，`import main` 会解析到 desktop/main.py（无 app
    # 属性）→ 导入失败。backend 在前则 `import main` 解析到 backend/main.py，与源码
    # 运行时（qml_bridge 把 backend 插到 sys.path[0]）行为一致。
    # desktop 也在 pathex 中，是为了让 qml_bridge / tray / single_instance 被分析器发现。
    pathex=[BACKEND_DIR, DESKTOP_DIR],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'pytest', 'tests',
        # 显式排除 QtWebEngine（Chromium 内核，本项目纯 QML 不用）
        'PySide6.QtWebEngineCore',
        'PySide6.QtWebEngineQuick',
        'PySide6.QtWebEngineWidgets',
        'PySide6.QtWebEngineCoreHeaders',
        # 排除其他不用的 Qt 模块（减小体积）
        'PySide6.QtMultimedia',
        'PySide6.QtMultimediaWidgets',
        'PySide6.QtPdf',
        'PySide6.QtPdfWidgets',
        'PySide6.QtPrintSupport',
        'PySide6.QtSvg',
        'PySide6.QtSvgWidgets',
        'PySide6.QtSql',
        'PySide6.QtTest',
        'PySide6.QtDesigner',
        'PySide6.QtHelp',
        'PySide6.QtBluetooth',
        'PySide6.QtNfc',
        'PySide6.QtPositioning',
        'PySide6.QtLocation',
        'PySide6.QtSensors',
        'PySide6.QtSerialPort',
        'PySide6.QtWebChannel',  # 纯 QML 不启用 QWebChannel
        'PySide6.QtWebSockets',
        'PySide6.QtXml',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='QuantOKX-Desktop',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # console=False：GUI 应用无控制台窗口；disable_windowed_traceback=False 保留
    # 启动早期异常的 traceback 弹窗（便于诊断 QML 加载失败等）。
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON_PATH if os.path.exists(ICON_PATH) else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='QuantOKX-Desktop',
)
