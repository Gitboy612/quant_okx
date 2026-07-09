# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for QuantOKX.

构建命令: pyinstaller QuantOKX.spec
产物: dist/QuantOKX/QuantOKX.exe (onedir 模式)
"""
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# 项目根目录
PROJECT_ROOT = os.path.dirname(os.path.abspath(SPEC))

# 数据文件：
# 1. frontend/dist → frontend/dist (后端 main.py 通过 _MEIPASS/frontend/dist 托管)
# 2. backend/bin/mihomo.exe → bin/mihomo.exe (proxy_core.py frozen 时查找 _MEIPASS/bin/mihomo.exe)
datas = [
    (os.path.join(PROJECT_ROOT, 'frontend', 'dist'), 'frontend/dist'),
    (os.path.join(PROJECT_ROOT, 'backend', 'bin', 'mihomo.exe'), 'bin'),
]

# 动态/延迟导入的模块
hiddenimports = []
# 注: PyPI 包 python-okx 的真实 import 名是 `okx` (用法 `from okx import Account`),
# 故用 collect_submodules('okx') 而非 'python_okx'。
hiddenimports += collect_submodules('okx')
hiddenimports += collect_submodules('apscheduler')
# python-jose 运行时动态加载加密后端 (jose.backends.*), PyInstaller 无内置 hook,
# 故收集全部子模块以免 jwt.encode/decode 找不到后端。
hiddenimports += collect_submodules('jose')
hiddenimports += [
    'httpx',
    'h11',
    'h2',
    'hpack',
    'hyperframe',
    'cryptography',
    'bcrypt',
    # aiosqlite 未实际安装：database.py 把 "sqlite+aiosqlite" 替换为 "sqlite" 走同步引擎
    'sqlalchemy.dialects.sqlite',
    'websockets',
    'yaml',
    'dotenv',
    'multipart',
    'uvicorn',
    'uvicorn.logging',
    'uvicorn.protocols',
    'uvicorn.protocols.http',
    'uvicorn.protocols.websockets',
    'uvicorn.protocols.websockets.auto',
    'uvicorn.lifespan',
    'uvicorn.lifespan.on',
]

a = Analysis(
    [os.path.join(PROJECT_ROOT, 'backend', 'launcher.py')],
    pathex=[os.path.join(PROJECT_ROOT, 'backend')],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['pytest', 'tests'],
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
    name='QuantOKX',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='QuantOKX',
)
