# Tasks

- [x] Task 1: 后端配置支持打包运行（frozen）
  - [x] SubTask 1.1: 修改 `backend/config.py`：新增 `IS_FROZEN` 判断；`DATA_DIR` 在 frozen 时指向 `%APPDATA%/QuantOKX/data`，非 frozen 保持现状；`KEY_FILE`、`DATABASE_URL` 跟随 `DATA_DIR`
  - [x] SubTask 1.2: `FRONTEND_DIR` 在 frozen 时指向 `sys._MEIPASS/frontend/dist`，非 frozen 保持 `BASE_DIR/frontend/dist`
  - [x] SubTask 1.3: 新增 `HOST`（默认 127.0.0.1）、`PORT`（默认 8000）、`PRODUCTION` 配置项，支持环境变量覆盖
  - [x] SubTask 1.4: 修改 `backend/main.py` CORS 中间件读取配置化来源；同源托管时保持最小放行

- [x] Task 2: mihomo 二进制定位适配 frozen
  - [x] SubTask 2.1: 修改 `backend/services/proxy_core.py` 的 `_get_bin_dir()`：frozen 时返回 `sys._MEIPASS/bin`，非 frozen 保持现有 `backend/bin/`
  - [x] SubTask 2.2: `_find_clash_binary()` 在 frozen 优先查找携带的 mihomo.exe，兼容现有自动下载兜底

- [x] Task 3: 启动器 launcher.py
  - [x] SubTask 3.1: 新增 `backend/launcher.py`：在后台线程启动 uvicorn（host/port 读 config），主线程等待端口就绪
  - [x] SubTask 3.2: 端口就绪后调用 `webbrowser.open` 打开 `http://127.0.0.1:{PORT}`，主线程保持运行
  - [x] SubTask 3.3: 注册信号处理（SIGINT/SIGTERM），Ctrl+C 或关闭窗口时优雅关闭 uvicorn 释放端口

- [x] Task 4: PyInstaller 打包配置
  - [x] SubTask 4.1: 新增根目录 `QuantOKX.spec`：入口 `backend/launcher.py`，onedir 模式，名称 `QuantOKX`
  - [x] SubTask 4.2: 配置 `datas`：`frontend/dist` → `frontend/dist`、`backend/bin/mihomo.exe` → `bin/mihomo.exe`
  - [x] SubTask 4.3: 配置 `hiddenimports`：httpx、cryptography、bcrypt、aiosqlite、apscheduler、python_okx 等动态导入的库
  - [x] SubTask 4.4: 配置 `collect_data_files` 收集 python_okx 等包的数据文件；排除 __pycache__、tests

- [x] Task 5: Inno Setup 安装包
  - [x] SubTask 5.1: 新增 `installer/quant_okx.iss`：源文件指向 `dist/QuantOKX/*`，安装到 `{app}`，生成开始菜单与桌面快捷方式（指向 `QuantOKX.exe`）
  - [x] SubTask 5.2: 配置卸载清理快捷方式；`%APPDATA%\QuantOKX` 数据目录默认保留
  - [x] SubTask 5.3: 可选"开机自启"任务项（创建注册表 Run 项）

- [x] Task 6: 一键构建脚本与文档
  - [x] SubTask 6.1: 新增 `installer/build_installer.bat`：检查依赖（node、python、pyinstaller、inno setup）→ `cd frontend && npm run build` → `cd .. && pyinstaller QuantOKX.spec` → `iscc installer/quant_okx.iss` → 产物 `installer/Output/QuantOKX-Setup.exe`
  - [x] SubTask 6.2: 新增 `.env.example`：文档化 JWT_SECRET_KEY、HOST、PORT、PRODUCTION、OKX_BASE_URL、OKX_PROXY 等
  - [x] SubTask 6.3: 新增 `installer/README.md`：打包前置依赖、构建步骤、产物说明、安装后使用说明、首次登录账号 admin/admin123、常见问题（如防火墙放行 8000 端口）

# Task Dependencies
- [Task 4] PyInstaller 打包依赖 [Task 1] frozen 配置、[Task 2] mihomo 适配、[Task 3] launcher
- [Task 5] Inno Setup 依赖 [Task 4] 生成 dist/QuantOKX
- [Task 6] 构建脚本依赖 [Task 4]、[Task 5]
