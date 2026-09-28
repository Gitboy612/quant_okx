# QuantOKX 本地开发、构建与部署指南

## 1. 环境要求

| 组件 | 代码/脚本要求 | 建议基线 |
|---|---|---|
| Python | 3.10+ | 3.11 或 3.12 |
| Node.js | README/Windows 脚本 18+；macOS 脚本和 Vite 8 实际要求更高 | 22.12+ |
| npm | 随 Node 安装 | 与 Node 22 LTS 配套 |
| Windows | 10/11、VC++ 2015–2022 x64；打包需 Inno Setup 6 | Windows 11 |
| macOS | Xcode Command Line Tools；可选 Homebrew | 当前受支持 macOS |
| Linux | 可手工开发启动 | 生产支持状态待确认 |

## 2. 从全新环境安装

### macOS 自动安装

```bash
chmod +x install_mac.sh start_mac.sh
./install_mac.sh
```

脚本检查 macOS、Xcode CLT、Python 3.10+、Node 22.12+ 和 npm；创建 `backend/.venv`，安装后端、测试和前端依赖，从 `.env.example` 生成 `.env` 并生成随机 JWT secret，最后执行关键依赖导入烟雾测试。

### Windows 自动安装

```bat
install.bat
```

脚本检查/尝试安装 Python、Node、VC++ runtime，创建 `backend\.venv`，安装依赖和生成 `.env`。脚本说明是 Node 18+，但当前 Vite 8 应使用 Node 22.12+。

### 手工安装

macOS/Linux：

```bash
cp .env.example .env
python3 -m venv backend/.venv
source backend/.venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r backend/requirements.txt aiosqlite python-dotenv PyYAML pytest pytest-asyncio
cd frontend
npm install
cd ..
```

Windows PowerShell 将复制命令改为 `Copy-Item .env.example .env`，激活命令改为 `backend\.venv\Scripts\Activate.ps1`。

注意：`backend/requirements.txt` 当前没有列出 `aiosqlite`、`python-dotenv` 和 `PyYAML`，但代码/安装脚本使用它们，因此手工命令必须补充。生成 `.env` 后必须替换 `JWT_SECRET_KEY` 的占位值；不得提交 `.env`。

## 3. 数据库初始化与迁移

无需单独初始化命令。FastAPI 第一次 startup 会：

1. `Base.metadata.create_all` 建表。
2. 执行 `backend/database.py` 中的兼容迁移。
3. 播种内置策略模板。
4. 空用户表时创建默认管理员。
5. 重建残留策略 PnL 基准并把 running/paused 改为 stopped。

正式升级前先停服务并备份 `data/`。`backend/migrations/` 脚本不是统一迁移框架，只有在明确理解目标版本和脚本幂等性后才运行。

## 4. 开发启动与停止

### macOS 一键启动

```bash
./start_mac.sh
```

它启动 Uvicorn reload 和 Vite，检测端口/就绪后打开浏览器。`Ctrl+C` 通过 trap 同时停止两个进程。

### Windows 一键启动

```bat
start.bat
```

它分别打开后端 `python launcher.py` 和前端 `npm run dev` 窗口；在各窗口停止进程。

### 手工启动

终端 1：

```bash
cd backend
source .venv/bin/activate
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

终端 2：

```bash
cd frontend
npm run dev
```

访问：Web `http://127.0.0.1:5173`，OpenAPI `http://127.0.0.1:8000/docs`。使用 `Ctrl+C` 停止。

### 启动验证

- `/docs` 能打开。
- `/api/auth/login` 能使用已修改的管理员密码登录。
- 前端登录后账户/策略页面无 401。
- 使用模拟盘账户验证 `/api/accounts/{id}/balance`。
- 日志中没有数据库迁移、端口占用或凭证解密错误。

## 5. 桌面客户端

```bash
python -m pip install -r backend/requirements.txt -r desktop/requirements.txt aiosqlite python-dotenv PyYAML
cd desktop
python main.py
```

默认桌面桥接直接读本地 DB，不启动 HTTP 后端。可选：

```bash
DESKTOP_BACKEND_HTTP=1 DESKTOP_BACKEND_HOST=127.0.0.1 DESKTOP_BACKEND_PORT=8000 python main.py
```

桌面端通过 `SingleInstance` 限制单实例，并在退出时停止内嵌后端和托盘。

## 6. 前端构建与单进程运行

```bash
cd frontend
npm run lint
npm run build
cd ../backend
python launcher.py
```

构建产物为 `frontend/dist`。`launcher.py` 启动 Uvicorn、等待端口并打开浏览器，FastAPI 同时提供 UI、REST 和 WebSocket。保持 `HOST=127.0.0.1` 是当前最安全的默认方式。

本次 2026-08-11 构建确认成功，但 Node 20.18.0 低于 Vite 8 推荐要求，且主 JS 大于 500 kB、背景视频约 70 MB；发布机应升级到 Node 22.12+。

## 7. Windows 安装包构建

前置：Python、Node 22.12+、PyInstaller、Inno Setup 6（`iscc` 在 PATH）。

```bat
installer\build_installer.bat
```

手工等价流程：

```bat
cd frontend
npm install
npm run build
cd ..
pyinstaller QuantOKX.spec --noconfirm
iscc installer\quant_okx.iss
```

中间产物为 `dist\QuantOKX\`，最终安装包为 `installer\Output\QuantOKX-Setup.exe`。`QuantOKX.spec` 入口为 `backend/launcher.py`，把前端 dist、后端代码、Mihomo 等资源纳入 `onedir` 包。安装后用户数据位于 `%APPDATA%\QuantOKX\data`，卸载默认不删除。

仓库还有 `desktop/QuantOKX-Desktop.spec` 和 `installer/quant_okx_desktop.iss`，属于 QML 桌面打包路径；其正式发布状态待确认。

## 8. 生产式配置与安全检查

代码库主要面向可信本机使用。若必须对外访问，至少完成：

1. 设置随机 `JWT_SECRET_KEY`，修改默认管理员密码。
2. `CORS_ORIGINS` 只列实际 HTTPS 前端域名。
3. 在反向代理终止 TLS；FastAPI 不直接暴露公网。
4. 防火墙限制来源；保护 `/ws/*`、公开 DSL/市场和维护接口。
5. 保持单 Uvicorn worker；当前进程内状态不支持多 worker。
6. 使用无提现权限、最小交易权限的 OKX Key，先在 demo 验证。
7. 配置 `data/` 和日志备份、磁盘告警、进程监督和定期恢复演练。
8. 增加通用速率限制、安全响应头、请求 ID 和敏感日志脱敏。

仅设置 `HOST=0.0.0.0` 与 `PRODUCTION=true` 不构成安全的生产部署。

## 9. 健康检查和运行验证

项目没有专用公开 `/healthz`。可选检查：

| 检查 | 方法 | 注意 |
|---|---|---|
| 进程/端口 | TCP connect 到 `HOST:PORT` | `launcher.py` 使用此方式 |
| API 就绪 | `GET /docs` 或 `/openapi.json` | 文档接口不代表 DB/OKX 正常 |
| 认证/DB | 登录后 `GET /api/auth/me` | 需要安全的测试用户 |
| OKX DNS | `GET /api/accounts/network-check` | 需认证，只检查 DNS |
| 账户连通 | `GET /api/accounts/{id}/balance` | 会访问 OKX 私有 API |
| 策略健康 | `GET /api/monitoring/health?account_id=...` | 需认证且可能访问 OKX |

## 10. 发布前后检查

发布前：

- 备份 DB 与 encryption key。
- 工作区干净，确认版本和变更日志。
- 后端目标测试集通过；若有失败，记录豁免和风险。
- `npm run lint` 无新增警告，`npm run build` 成功。
- 在新数据目录执行首次启动和升级副本迁移。
- 用 demo 账户执行登录、账户、模板、实例、dry-run、回测、启停、订单和 PnL 冒烟。
- 检查构建产物不含 `.env`、真实 DB、key 和日志。

发布后：验证静态页面刷新、OpenAPI、登录、DB、OKX、WebSocket、策略启停、日志和磁盘增长；保持实盘策略停止，直到验证完成。

## 11. 回滚

项目没有自动回滚脚本。建议流程：

1. 停止服务和策略，确认没有挂单/未完成维护任务。
2. 保存当前日志、程序版本和 `data/` 快照。
3. 恢复上一版本程序文件。
4. 只有在 schema 不兼容且确认没有新版本有效数据时，成对恢复旧 `quant_okx.db` 与 `.encryption_key`。
5. 单独在副本上验证启动迁移，再启动正式数据。
6. 用 demo/只读检查验证后再恢复策略。

数据库启动迁移没有 down 脚本，不能假设旧程序可读取新 schema；回滚 RTO/RPO 待项目负责人确认。

## 12. 备份与恢复

停服务后备份整个源码模式 `data/` 或冻结模式 `%APPDATA%\QuantOKX\data`。数据库和 `.encryption_key` 缺一不可。通知/代理设置在 DB 中，导入的代理文件可能位于 `backend/data`，如需恢复代理也应纳入备份。恢复时先移动原目录到保留位置，再放回备份，避免覆盖唯一可恢复副本。

## 13. CI/CD 与容器

代码中未发现 Dockerfile、Compose、Kubernetes、GitHub Actions、GitLab CI 或 Jenkins 配置；`.gitignore` 甚至显式忽略 `.github/`。因此当前没有可确认的自动化构建、测试、部署和回滚流程。不要声称支持容器部署；如新增 CI，应至少执行依赖安装、非外部 E2E 后端测试、前端 lint/build、打包 smoke test 和敏感文件扫描。
