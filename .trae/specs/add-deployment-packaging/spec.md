# Windows 安装包打包方案 Spec

## Why
当前项目仅在本地通过 `start.bat` 以开发模式（`--reload` + Vite dev server）运行，无法分发给客户。用户希望打包成标准 Windows 安装包：客户安装完成后得到一个 `.exe`，双击即可启动服务并自动打开浏览器访问界面，无需配置 Python/Node 环境。该 exe 也可部署在 Windows 云服务器上对外提供演示访问。

## What Changes
- 新增 **PyInstaller 打包方案**：将 Python 后端 + 已构建的 `frontend/dist` 静态资源 + `mihomo.exe` 打包为单一可执行程序 `QuantOKX.exe`
- 新增 **启动器 `backend/launcher.py`**：启动 uvicorn 后台服务 → 等待端口就绪 → 自动打开默认浏览器 → 前台保持运行（关闭窗口即退出服务）
- 修改 `backend/config.py`：运行时数据目录（SQLite db、加密密钥、日志）改为按"是否冻结打包"区分——打包后使用 `%APPDATA%\QuantOKX\data`，开发态仍用项目内 `data/`，避免安装到 Program Files 后写入失败
- 新增 **Inno Setup 安装脚本**：生成 `QuantOKX-Setup.exe` 安装包，含开始菜单/桌面快捷方式、卸载支持、可选开机自启
- 生产配置：通过环境变量/配置文件覆盖 JWT 密钥等敏感项；CORS 同源托管时无需额外配置
- **BREAKING**：`start.bat` 保留用于开发；生产入口改为 `launcher.py`（被 PyInstaller 编译进 exe）

## Impact
- Affected specs: 无（新能力）
- Affected code:
  - `backend/config.py`：`DATA_DIR` 支持打包后重定向到 `%APPDATA%\QuantOKX\data`；新增 `IS_FROZEN`、`HOST`、`PORT`、`PRODUCTION` 配置
  - `backend/main.py`：CORS 来源支持配置化（同源托管时保持最小放行）
  - 新增 `backend/launcher.py`：启动器（uvicorn 后台线程 + 浏览器拉起 + 信号处理）
  - 新增 `QuantOKX.spec`：PyInstaller 打包配置（含 hidden imports、datas、mihomo.exe 携带）
  - 新增 `installer/quant_okx.iss`：Inno Setup 脚本
  - 新增 `installer/build_installer.bat`：一键构建脚本（npm build → pyinstaller → inno setup）
  - 新增 `installer/README.md`：打包步骤与依赖说明

## ADDED Requirements

### Requirement: PyInstaller 单文件/单目录打包
系统 SHALL 通过 PyInstaller 将后端代码、前端构建产物、mihomo.exe 打包为 Windows 可执行程序 `QuantOKX.exe`，运行时无需目标机器安装 Python 或 Node。

#### Scenario: 打包生成 exe
- **WHEN** 开发者执行 `installer/build_installer.bat`
- **THEN** 脚本依次完成：`npm run build` 构建前端 → `pyinstaller QuantOKX.spec` 生成 `dist/QuantOKX/QuantOKX.exe`（含 frontend/dist 与 mihomo.exe）

#### Scenario: 目标机器无依赖运行
- **WHEN** 客户在纯净 Windows 上双击 `QuantOKX.exe`
- **THEN** 程序启动，无需预装 Python/Node，后端监听 127.0.0.1:8000 并自动打开浏览器

### Requirement: 启动器自动拉起浏览器
系统 SHALL 提供启动器，启动 uvicorn 服务后等待端口就绪，再调用系统默认浏览器打开应用首页，并在前台保持运行以便用户关闭窗口时退出服务。

#### Scenario: 双击启动
- **WHEN** 用户双击 `QuantOKX.exe`
- **THEN** 控制台窗口显示启动日志，uvicorn 就绪后自动打开 `http://127.0.0.1:8000`

#### Scenario: 关闭退出
- **WHEN** 用户关闭控制台窗口或 Ctrl+C
- **THEN** uvicorn 服务随之优雅退出，释放端口

### Requirement: 数据目录重定向
系统 SHALL 在打包（frozen）运行时将 SQLite 数据库、加密密钥、日志等可写数据放置到用户可写目录 `%APPDATA%\QuantOKX\data`，避免写入 Program Files 等只读位置失败。

#### Scenario: 首次运行创建数据目录
- **WHEN** 打包后的 exe 首次运行，`%APPDATA%\QuantOKX\data` 不存在
- **THEN** 自动创建该目录，数据库与加密密钥在此生成

#### Scenario: 开发态路径不变
- **WHEN** 以源码方式运行（非 frozen）
- **THEN** `DATA_DIR` 仍为项目 `data/`，不影响开发流程

### Requirement: Inno Setup 安装包
系统 SHALL 通过 Inno Setup 生成标准 Windows 安装程序 `QuantOKX-Setup.exe`，支持图形化安装、开始菜单与桌面快捷方式、卸载、可选开机自启。

#### Scenario: 安装
- **WHEN** 客户双击 `QuantOKX-Setup.exe` 按向导完成安装
- **THEN** 程序安装到 `C:\Program Files\QuantOKX\`（或用户选择目录），开始菜单与桌面生成 `QuantOKX` 快捷方式

#### Scenario: 卸载
- **WHEN** 客户通过"控制面板→卸载程序"卸载
- **THEN** 程序文件与快捷方式被清除；`%APPDATA%\QuantOKX` 数据目录默认保留（可选清理）

### Requirement: 生产环境配置
系统 SHALL 支持通过环境变量或 exe 同目录的 `.env` 文件覆盖关键配置，避免硬编码敏感信息。

#### Scenario: 自定义 JWT 密钥
- **WHEN** 在 exe 同目录放置 `.env` 文件设置 `JWT_SECRET_KEY=xxx`
- **THEN** 后端使用该密钥而非代码默认值

#### Scenario: 监听地址可配置
- **WHEN** 设置 `HOST=0.0.0.0`（用于云服务器对外暴露）
- **THEN** uvicorn 监听所有网卡，可通过公网 IP 访问；默认仍为 127.0.0.1 以保障本地演示安全

## MODIFIED Requirements

### Requirement: 后端配置与数据目录
`backend/config.py` 修改如下：
- 新增 `IS_FROZEN = getattr(sys, "frozen", False)` 判断是否 PyInstaller 打包
- `DATA_DIR`：`IS_FROZEN` 为 True 时使用 `%APPDATA%/QuantOKX/data`，否则保持现有 `BASE_DIR/data`
- `KEY_FILE`、`DATABASE_URL` 跟随 `DATA_DIR`
- `FRONTEND_DIR`：frozen 时指向 `sys._MEIPASS/frontend/dist`（PyInstaller 解包临时目录）；非 frozen 保持 `BASE_DIR/frontend/dist`
- 新增 `HOST`（默认 `127.0.0.1`）、`PORT`（默认 `8000`）、`PRODUCTION`（默认 False）配置项，支持环境变量

### Requirement: mihomo 二进制定位
`backend/services/proxy_core.py` 的 `_get_bin_dir()` 与 `_find_clash_binary()`：
- frozen 运行时，mihomo.exe 通过 PyInstaller datas 携带到 `sys._MEIPASS/bin/mihomo.exe`
- 非 frozen 保持现有 `backend/bin/` 逻辑
- 兼容现有自动下载逻辑（已携带则跳过下载）
