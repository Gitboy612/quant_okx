# QuantOKX 故障排查、已知问题与技术债务

## 1. 依赖安装失败

| 项目 | 内容 |
|---|---|
| 现象 | `ModuleNotFoundError: aiosqlite/dotenv/yaml`，cryptography/bcrypt 安装失败，Vite 拒绝 Node 版本 |
| 可能原因 | `requirements.txt` 未列全部运行依赖；Python/Node 版本过低；Windows 缺 VC++ runtime |
| 检查 | `python --version`、`node --version`、`npm --version`；运行安装脚本的 import smoke test |
| 处理 | Python 3.10+；Node 22.12+；安装 `aiosqlite python-dotenv PyYAML`；Windows 安装 VC++ 2015–2022 x64 |

不要在现有用户环境里混装；优先使用 `backend/.venv`。

## 2. 后端无法启动

| 现象 | 可能原因 | 检查 | 处理 |
|---|---|---|---|
| 端口占用 | 8000 已有进程 | `lsof -nP -iTCP:8000 -sTCP:LISTEN`（macOS） | 停旧进程或改 `.env PORT` |
| import 错误 | 未从 `backend` 启动或依赖缺失 | 查看 traceback | `cd backend` 后用 venv 执行 Uvicorn |
| DB migration 失败 | 旧库重复 `order_id`、损坏或无写权限 | 备份后查启动日志和 SQLite schema | 在副本清理重复/恢复备份，勿直接删正式库 |
| Fernet 解密错误 | DB 与 `.encryption_key` 不配套 | 确认备份来源 | 成对恢复 DB 和 key；无法从密文重建 key |
| 前端页面空白 | `frontend/dist` 缺失或资源路径错误 | 看浏览器 Network 和 backend 日志 | 重新 `npm run build`，确认 dist 随包发布 |

## 3. 前端无法启动或构建

| 项目 | 内容 |
|---|---|
| 现象 | Vite Node 版本错误、`npm install` 原生包失败、TypeScript/Oxlint 报错 |
| 检查 | `node --version`，确认在 `frontend/`；查看第一条实际 error 而非后续连锁错误 |
| 处理 | 使用 Node 22.12+；重新 `npm install --include=optional`；修复 TS error 后再构建 |

当前 lint 有 20 条 warning，构建有大 chunk、CSS selector 和资源体积 warning。它们不阻断当前构建，但不应继续累积。

## 4. 刷新 React 页面返回 404

确认使用当前 `backend/spa_static.py` 且已构建 `frontend/dist`。生产式本地运行必须通过 `backend/launcher.py` 或导入当前 `main:app`；仅启动 Vite 时由 Vite 自己处理 History fallback。`/api/*`、`/ws/*` 和缺失静态资源不应回退为 HTML。

## 5. 登录返回 401 或 423

| 状态 | 原因 | 处理 |
|---:|---|---|
| 401 | 用户不存在、密码错误、JWT 无效/过期、用户被删除 | 检查系统时间和 JWT secret 是否在重启后变化；重新登录 |
| 423 | 5 次失败后锁定 | 等待 15 分钟；不要反复尝试 |

首次空库账号由代码创建为默认管理员。立即修改密码；如果对外暴露且默认账号仍存在，应先隔离服务。

前端收到 401 会清除 `sessionStorage.token` 并跳到 `/login`。代码没有 refresh token 或服务端登出。

## 6. 账户添加或 OKX 访问失败

| 现象 | 可能原因 | 检查 | 处理 |
|---|---|---|---|
| API Key 验证失败 | key/passphrase 错、权限不足、demo/live 不匹配 | OKX 控制台权限；后端错误 `msg` | 使用 read/trade、无提现权限的正确模式 key |
| DNS/timeout | 地区网络、代理、域名不可达 | `/api/accounts/network-check`；代理 test | 配 `OKX_PROXY` 或应用内代理；验证主/备用域名 |
| 签名/时间错误 | 本机时间漂移 | 系统时间、OKX code | 开启系统 NTP 后重启客户端 |
| 合约下单 51010 | OKX 账户模式不支持 | feasibility 和 API log | 在 OKX demo 调整账户模式，再启动策略 |

不要把 API key、secret、passphrase 或完整 API 日志粘贴到公开 issue。

## 7. 策略无法启动、状态不一致或不下单

检查顺序：

1. 实例状态是否为 `stopped`；paused 应调用 resume。
2. `GET /api/strategies/instances/{id}/feasibility` 的 `ok/reason`。
3. 账户是否 active、trade_mode 是否正确、余额/账户模式是否满足。
4. 参数 `symbol`、market type、杠杆、数量、价格精度和最小下单量。
5. 策略事件和 API call logs 是否有 `order_rejected`、`capital_limit`、`margin_warning`。
6. OKX 响应必须同时检查外层 `code` 与单笔 `sCode`。

服务重启会把数据库残留的 running/paused 重置 stopped，这是预期行为。若 UI 状态旧，等待 5 秒刷新或重新聚焦页面；若数据库显示 running 但内存无 task，检查 `StrategyEngine._on_strategy_task_done` 的异常日志。

## 8. PnL、订单或仓位不一致

| 现象 | 检查 | 安全处理 |
|---|---|---|
| PnL 曲线为 0/跳变 | 订单 status/fill 字段、最新 PnlRecord、事件、当前测试失败 | 先备份；用 `POST /api/pnl/recompute/{id}` 在 demo/副本验证 |
| 真实仓位与虚拟仓位不一致 | `/api/monitoring/reconcile`、孤儿订单、所有活跃策略净持仓 | 停策略、核对 OKX；不要直接删订单 |
| 多策略平仓冲突 | `/api/monitoring/position_conflicts` | 按 hedge group 和带符号持仓逐个核对 |
| 订单缺失 | API 文件/DB 日志、OKX fills、`order_id` 唯一冲突 | 先使用对账/孤儿订单逻辑，人工补数据前做备份 |

维护接口会物理删除或校正数据，没有 undo。只有在明确影响范围、停策略并备份后使用。

## 9. WebSocket 没有数据

- 开发环境确认 Vite `/ws` 代理目标为 `ws://127.0.0.1:8000`。
- `/ws/strategy` 和 `/ws/dashboard` 需要客户端先发送 text 才响应；它们不是定时主动推送。
- `/ws/market/{symbol}` 订阅 OKX 公共 ticker，客户端仍需发送 ping/text 保持接收循环。
- 检查 symbol 是否是 OKX instrument 格式、网络/代理和 OKX 公共 WS 状态。
- 多 worker 会把连接与策略任务分散，当前只能单进程。

当前 WebSocket 无认证；若服务已公网暴露，优先隔离并补鉴权，而不是仅排查数据问题。

## 10. 数据库迁移失败

1. 停止服务并复制整个 `data/`。
2. 在副本执行 `sqlite3 <copy> 'PRAGMA integrity_check;'`（环境有 sqlite3 时）。
3. 查表列和索引是否处于半迁移状态。
4. 特别检查 `orders.order_id` 重复值；唯一索引创建会因重复失败。
5. 不要重复运行独立 migration/fix 脚本，除非已阅读脚本和确认适用版本。
6. 修复副本并完成启动验证后，再制定正式操作与回滚步骤。

项目没有 Alembic version 表和 down migration，无法自动判断所有历史版本。

## 11. 环境变量未生效

- `.env` 应位于项目根目录，且进程工作目录/`load_dotenv` 能找到它。
- 进程环境变量优先于文件；检查 shell/service manager 是否注入旧值。
- 修改后重启后端；已创建的 HTTP 客户端不会自动重读代理/URL。
- 不要输出完整 `.env`。只核对变量名、是否为空和非敏感格式。

## 12. 代理或 Mihomo 失败

| 现象 | 检查 | 处理 |
|---|---|---|
| 端口占用 | `/api/settings/proxy/status`、系统端口 | 改 embedded port 或停冲突进程 |
| 配置解析失败 | YAML 编码、节点格式、路径 | UTF-8/GBK；重新导入可信配置 |
| MMDB 缺失 | `/proxy/mmdb-status` | 按日志下载/放置；验证文件来源 |
| macOS 无法运行仓库 exe | `backend/bin/*.exe` 是 Windows | 安装系统 Mihomo/Clash，或禁用代理 |
| OKX 仍超时 | `/proxy/test` 三目标结果 | 检查代理 URL、规则和 DNS override |

上传配置可包含代理凭证，应按敏感文件处理。

## 13. 通知失败

- 确认规则 active、event type 匹配、channel type 为 email/webhook/telegram。
- 用 `/api/notifications/test` 测试单一渠道。
- Email 检查 SMTP host/port/TLS/账号；Webhook 检查 URL/HTTP 状态；Telegram 检查 bot token/chat ID。
- 不在日志、截图或文档中公开 `channel_config`。
- 通知失败不应被当作交易失败；查看 NotificationService 的异常处理和返回 `ok`。

## 14. 测试失败

当前默认测试不是绿色：870 passed、13 failed、4 skipped、4 setup errors。先看 [testing-guide.md](testing-guide.md) 的已知失败摘要。若修改 PnL、strategy start 或 research runner，应先复现相关失败，区分工作区已有问题与新增回归。4 个 runner setup error 是测试组织问题，不代表 OKX 接口本身已验证。

## 15. Docker 启动失败

代码中没有 Dockerfile 或 Compose 配置，因此不存在受支持的 Docker 启动流程。来自第三方或自行编写的容器配置不属于当前项目事实；需要容器化时应另行设计单进程状态、数据卷、encryption key、静态资源、健康检查和优雅停止。

## 16. 已知问题和技术债务

| 风险 | 问题 | 位置/证据 | 影响 | 建议 |
|---|---|---|---|---|
| 高 | 默认后端测试有 13 fail + 4 error | 2026-08-11 实测 | 无法建立可靠发布基线 | 先修 fixture 和 PnL/runner 回归，建立 CI |
| 高 | 默认管理员和 JWT 默认 secret | `main.py`、`config.py` | 误公网暴露可被接管 | 首次启动强制设密，不允许生产默认值 |
| 高 | WebSocket 与 DSL 公开无认证/限流 | `routers/ws.py`、`routers/dsl.py` | 数据暴露、资源滥用 | 增加 token、origin、配额和输入上限 |
| 高 | 维护接口无角色且可物理删除 | `routers/maintenance.py` | 数据不可恢复 | RBAC、确认令牌、审计和备份 |
| 中 | PnL 增量相关测试回归 | PnL tests 当前失败 | 仓位/PnL 可能错误 | 在修改业务前锁定最小复现并修复 |
| 中 | 批量网格下单未接单笔资金上限校验 | `strategies/grid_strategy.py:475` TODO | 批量订单可能越过预期控制 | 在批量组装/提交两层校验总额 |
| 中 | 上传文件名、大小和扩展名限制不足 | `routers/settings.py:import_proxy_config` | 路径/磁盘/恶意配置风险 | `Path.name`、白名单、size limit、隔离目录 |
| 中 | API 日志无通用敏感字段脱敏 | `services/log_service.py` | 凭证/个人数据落盘风险 | 结构化 allowlist + redaction |
| 中 | 无迁移版本/回滚 | `database.py` | 升降级不可预测 | 引入 Alembic 和旧库矩阵测试 |
| 中 | 多数 API 使用裸 dict | OpenAPI 仅 15 schemas | 前后端契约漂移 | Pydantic request/response model |
| 中 | 单进程内存状态多 | StrategyEngine、sandbox、backtest、WS | 多 worker/重启丢状态 | 明确单进程或外置 Redis/队列 |
| 中 | async route 混合同步 DB/网络入口 | accounts/backtest 等 | 阻塞事件循环/吞吐下降 | threadpool 或异步 DB/HTTP 收敛 |
| 中 | 没有统一异常/业务错误码/request ID | 全 routers | 客户端处理和追踪困难 | 统一 exception handler/envelope |
| 中 | 依赖未锁且 requirements 缺项 | requirements 与安装脚本差异 | 环境不可复现 | 补全并生成锁文件 |
| 中 | 没有 CI/CD、Docker 或生产 supervision | 仓库扫描 | 发布依赖人工 | 建立最小 CI 与发布清单 |
| 中 | 日志/PnL 无保留期 | log/PnL heartbeat | 磁盘持续增长 | retention、归档、维护计划 |
| 低 | 前端 20 lint warning | 2026-08-11 实测 | hook 陈旧闭包/维护噪声 | 逐项修复并将新增 warning 设为失败 |
| 低 | 主 JS 和视频体积大 | Vite build | 首屏、安装包体积 | code split、延迟加载、压缩视频 |
| 低 | Node 版本文档矛盾 | README/脚本/Vite | 新人搭建失败 | 统一 Node 22.12+ |
| 低 | 账户锁定用 `datetime.replace` 算分钟 | `routers/auth.py` | 边界行为脆弱 | 改为 `now + timedelta(minutes=...)` |
| 待确认 | `correct_unrealized_pnl` 文档称未实现 | `maintenance_service.py` docstring | 功能预期不清 | 明确设计或隐藏接口 |

## 17. 故障处理原则

- 先停止可能继续下单的策略，再收集证据。
- 优先只读检查：状态、事件、API 日志、OKX 挂单/持仓和 DB 副本。
- 修改数据前备份 DB 与 encryption key；记录命令、时间和影响范围。
- 不因 UI 显示成功就假设 OKX 下单成功；检查 `code/sCode/ordId`。
- 不在不确定时运行清理/校正脚本；无法确认的情况升级给项目负责人。
