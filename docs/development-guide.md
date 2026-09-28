# 《QuantOKX 技术开发手册》

> 本文档是开发手册总索引与项目级说明。接口、数据、部署、测试和排障内容按主题拆分，以便长期维护。所有结论基于 2026-08-11 的工作区代码；代码与文档冲突时以代码为准。

## 1. 文档信息

| 项目 | 内容 |
|---|---|
| 项目名称 | QuantOKX |
| 应用/API 版本 | `1.0.0`（`backend/main.py`） |
| 前端包版本 | `0.0.0`（`frontend/package.json`，与应用版本未统一） |
| 文档版本 | `1.0.0` |
| 最后更新时间 | 2026-08-11（Australia/Sydney） |
| 适用环境 | 源码开发：Windows、macOS、Linux；安装包：Windows 10/11 |
| 维护人员/团队 | 待确认 |
| 仓库 | `https://github.com/Gitboy612/quant_okx.git`，当前分支 `master` |
| 适用对象 | 新开发人员、策略开发人员、测试人员、发布与本地运维人员 |

配套文档：

- [系统架构](architecture.md)
- [API 接口参考](api-reference.md)
- [数据结构与数据字典](data-dictionary.md)
- [本地开发、构建与部署](deployment-guide.md)
- [测试说明](testing-guide.md)
- [常见问题、已知问题与技术债务](troubleshooting.md)

## 2. 项目概述

QuantOKX 是面向 OKX 的本地优先量化交易平台。它把账户凭证、策略模板与实例、订单、PnL 和运维数据保存在本机 SQLite 中，通过 FastAPI 提供 REST/WebSocket API，以 React Web UI 为主界面，并提供可选的 PySide6/QML 桌面客户端。

核心目标和能力：

- 管理 OKX 模拟盘与实盘账户；凭证使用 Fernet 加密后落库。
- 运行 `grid`、`trend`、`arbitrage`、`advanced_grid_hedge` 和 `composable` 策略。
- 用 QS-Model/DSL 描述指标、条件、事件、动作、状态转换和风控参数。
- 提供历史回测、DSL dry-run 和不真实下单的实时沙箱。
- 进行策略级虚拟持仓、已实现/未实现 PnL、资金上限和仓位隔离核算。
- 提供订单、日志、通知、代理、维护、监控和归因分析界面。

目标用户以本机单用户为主；代码只有一个用户表和统一的已登录用户权限，没有多角色 RBAC。典型流程为：配置模拟账户 → 创建/导入模板 → 创建实例 → 可行性检查 → 回测或沙箱 → 启停策略 → 观察订单、PnL 和告警。

当前范围不包含：其他交易所、云端托管、多租户、细粒度权限、移动客户端、正式集群部署、自动化 CI/CD。项目状态为持续开发；Git 历史、现有 TODO 和本次测试均显示仍有回归问题待处理。

## 3. 技术栈

| 类别 | 技术/版本约束 | 用途 |
|---|---|---|
| 后端语言 | Python `>=3.10` | API、策略、回测、桌面桥接、脚本 |
| 后端框架 | FastAPI `>=0.115.0`、Uvicorn `>=0.30.0` | REST/WebSocket 和 ASGI 服务 |
| ORM/数据库 | SQLAlchemy `>=2.0.35`、SQLite；运行时还需要 `aiosqlite` | 本地持久化与启动迁移 |
| 模型校验 | Pydantic `>=2.10.0` | 请求体和 QS-Model/DSL 结构 |
| HTTP/WS | HTTPX `>=0.28.0`、websockets `>=12.0` | OKX REST/WS 和代理测试 |
| 认证/加密 | python-jose、bcrypt、cryptography/Fernet | JWT、密码哈希、API 凭证加密 |
| 调度 | APScheduler `>=3.10.4`、`asyncio` | 策略与周期性任务 |
| 前端 | React `^19.2.7`、TypeScript `~6.0.2`、Vite `^8.1.1` | Web 单页应用 |
| UI/图表 | Tailwind CSS 4、Framer Motion、Recharts、Three.js | 页面样式、动画、图表和背景 |
| 前端通信 | Axios `^1.18.1`、浏览器 WebSocket | REST/WS 客户端 |
| 桌面端 | PySide6 `>=6.6.0`、QML | 可选本地桌面 UI |
| 测试 | pytest、pytest-asyncio | 单元、集成、E2E 和性能测试 |
| 静态检查 | Oxlint `^1.71.0`、TypeScript compiler | 前端 lint 与类型构建 |
| 打包 | PyInstaller、Inno Setup 6 | Windows `onedir` 程序和安装包 |
| 外部系统 | OKX V5 REST/WS、Mihomo/Clash；SMTP/Webhook/Telegram | 行情交易、代理和通知 |

版本来源分别为 `backend/requirements.txt`、`frontend/package.json`、`desktop/requirements.txt` 和安装脚本。后端依赖文件只写下限，不能保证不同安装时间得到完全相同的环境；建议增加锁文件。

## 4. 系统架构

详见 [architecture.md](architecture.md)。关键事实：

- Web 前端开发时经 Vite 将 `/api` 和 `/ws` 代理到 `127.0.0.1:8000`；生产式本地构建由 FastAPI 挂载 `frontend/dist`。
- FastAPI 路由依赖同步 SQLAlchemy Session；策略与 OKX I/O 多为异步。
- `StrategyEngine` 在进程内维护策略任务、按账户复用的 OKX 客户端和 5 秒余额/持仓缓存。
- 回测历史、沙箱状态、WebSocket 连接和运行中策略任务均为内存状态，进程重启会丢失或重建。
- 未发现 Redis、独立消息队列或微服务间 RPC。

## 5. 项目目录结构

```text
quant_okx/
├── backend/
│   ├── main.py                 # FastAPI 入口、路由装配、启动/关闭事件
│   ├── launcher.py             # 单进程静态站点+API 启动器
│   ├── config.py               # 环境变量、数据目录和常量
│   ├── database.py             # Engine、Session、建表及兼容迁移
│   ├── routers/                # REST 与 WebSocket 路由
│   ├── models/                 # SQLAlchemy ORM 模型
│   ├── schemas/                # API Pydantic 模型
│   ├── services/               # 交易、核算、回测、通知、代理等服务
│   ├── strategies/             # 内置策略实现
│   ├── dsl/                    # QS-Model/DSL schema、校验、编译和执行
│   ├── research/               # QS-Model 研究与基因池生成
│   ├── migrations/             # 独立历史迁移/修复脚本
│   └── tests/                  # 单元、集成、E2E、性能测试
├── frontend/
│   ├── src/api/                # Axios API 封装
│   ├── src/types/              # TypeScript 数据类型
│   ├── src/pages/              # 业务页面
│   ├── src/components/         # 通用与业务组件
│   └── vite.config.ts          # 构建与开发代理
├── desktop/                    # PySide6/QML 客户端及 Python 桥接
├── scripts/                    # 清理、检查、报告、研究和测试数据工具
├── installer/                  # Inno Setup 脚本和 Windows 构建入口
├── docs/                       # 用户、策略、设计和本开发手册
├── data/                       # 本地 DB 与加密密钥（不应提交）
├── .env.example               # 环境变量模板
├── QuantOKX.spec              # Web/API PyInstaller 配置
├── install.bat / install_mac.sh
└── start.bat / start_mac.sh
```

缓存、虚拟环境、`node_modules`、构建产物、日志和真实数据不属于源码结构。

## 6. 核心模块说明

| 模块 | 路径/入口 | 职责 | 主要依赖 |
|---|---|---|---|
| API 应用 | `backend/main.py` | 路由、中间件、初始化、默认用户、重启状态修正 | routers、database、StrategyEngine |
| 认证 | `middleware/auth.py`、`services/auth_service.py` | Bearer JWT、bcrypt、账户锁定 | users、python-jose |
| 账户/OKX | `routers/accounts.py`、`services/okx_client.py` | 凭证验证、余额持仓、REST/WS 适配 | encryption、OKX V5 |
| 策略运行时 | `services/strategy_engine.py` | 策略映射、生命周期、任务和客户端缓存 | strategies、PnL engine |
| 策略基类 | `strategies/base_strategy.py` | 生命周期、杠杆、资金/仓位风控、订单/PnL 记录 | OrderManager、OKXClient |
| DSL | `dsl/schema.py`、`validator.py`、`compiler.py`、`executor.py` | 配置模型、五层校验、FSM 编译与执行 | block registries |
| 订单 | `services/order_manager.py` | 内存订单状态、WS 更新、异步落库、撤单 | orders、OKXClient |
| PnL | `services/pnl_accounting_engine.py` | 全量/增量核算、心跳快照、对账与孤儿订单 | orders、pnl_records、OKX |
| 回测 | `services/backtest_engine.py` | K 线获取、撮合、手续费、指标 | OKX market、内存历史 |
| 沙箱 | `services/sandbox_service.py` | 真实行情+Mock 写操作、内存结果 | ComposableStrategy |
| 市场数据 | `services/market_data_service.py` | 公共 WS 订阅、最新价和波动缓存 | OKXPublicWsClient |
| 通知 | `services/notification_service.py` | 邮件、Webhook、Telegram 分发 | notification_rules |
| 代理 | `services/proxy_service.py`、`proxy_core.py` | 配置导入、连通性、Mihomo 进程 | system_settings、文件系统 |
| 前端 | `frontend/src/App.tsx` | 登录保护与 11 个业务页面路由 | Axios、React Router |
| 桌面桥接 | `desktop/qml_bridge.py` | QML 直接读 SQLAlchemy 和调用认证服务 | backend models/services |

桌面桥接绕过 FastAPI 依赖链，读接口当前不强制 JWT；这是本地单进程设计，不等同于 Web 权限模型。

## 7. 核心类和函数

以下记录长期维护所需的公共入口；完整方法以源码为准。

### `StrategyEngine.start_strategy`

位置：`backend/services/strategy_engine.py:427`

```python
async def start_strategy(self, instance_id: int)
```

读取实例、模板和账户，创建/复用 `OKXClient`，实例化 `_strategy_map` 中的策略并启动异步任务。实例、账户、模板不存在，策略类型不支持，或参数/杠杆准备失败时可抛 `HTTPException`、`RuntimeError` 或底层异常。由策略启动接口调用；调用前应先执行 `check_feasibility`。

### `StrategyEngine.update_params`

位置：`backend/services/strategy_engine.py:577`

```python
async def update_params(self, instance_id: int, params: dict)
```

更新实例参数并计算 `logic_hash`。运行中实例不允许改变 DSL `logic`；允许的运行时参数更新会同步到内存策略。不存在或非法状态通过 `HTTPException` 返回。

### `BaseStrategy.place_order_with_capital_check`

位置：`backend/strategies/base_strategy.py:255`

```python
async def place_order_with_capital_check(
    self, symbol: str, side: str, ord_type: str, sz, px=None, **kwargs
) -> dict
```

先按 `investment_amount × lever`（现货杠杆按 1）检查当前与新增名义价值，超过上限时记录 `capital_limit` 事件并返回 `code=-1`，否则调用 OKX 下单。注意 `grid_strategy.py:475` 标注批量下单尚未接入同等的单笔资金校验。

### `BaseStrategy.check_position_conflict`

位置：`backend/strategies/base_strategy.py:273`

```python
async def check_position_conflict(self, symbol: str, close_qty: float) -> bool
```

聚合同账户同 symbol 其他运行/暂停策略的带符号虚拟持仓，与真实持仓做代数隔离计算；默认 10 秒复用上次检查结果。数据库或查询异常时当前实现放行交易并返回 `True`，应结合监控告警使用。

### `PnlAccountingEngine.recompute`

位置：`backend/services/pnl_accounting_engine.py:54`

```python
async def recompute(self, strategy_instance_id: int, client: OKXClient | None = None)
```

读取该策略全部已成交订单，按实际数量/合约元数据重建虚拟仓位和 PnL，写入 `pnl_records` 并将订单标为已核算。无成交时返回 `None`；数据库和 OKX 异常可能上抛。

### `PnlAccountingEngine.incremental_update`

位置：`backend/services/pnl_accounting_engine.py:198`

```python
async def incremental_update(self, strategy_instance_id: int, client: OKXClient | None = None)
```

从最新快照继续处理 `pnl_accounted=False` 的成交订单；不能安全增量推导时可委托全量重算。当前相关回归测试有失败，修改前应运行 `test_pnl_accounting_engine.py`、`test_pnl_curve_fix.py` 和性能测试。

### `DSLValidator.validate`

位置：`backend/dsl/validator.py:95`

```python
def validate(self, config: dict | StrategyDSL) -> ValidationResult
```

执行 structure、reference、type、semantic、resource 五层校验，返回 `valid` 和结构化错误，不以异常表示普通校验失败。

### `DryRunSimulator.run`

位置：`backend/dsl/dry_run.py:193`

```python
async def run(
    self, config: dict, symbol: str, bar: str = "1H",
    limit: int = 100, candles: list[list[str]] | None = None
)
```

把 DSL 在历史或模拟 K 线上回放，返回步骤、触发次数、状态变化和最终状态。配置错误抛 `ValueError`。

### `BacktestEngine.run_backtest`

位置：`backend/services/backtest_engine.py:387`

```python
def run_backtest(self, config: BacktestConfig) -> BacktestResult
```

同步拉取/读取 K 线并撮合策略信号，返回交易、权益曲线和指标。API 将历史结果最多 50 条保存在内存中。

### `OKXClient.place_order`

位置：`backend/services/okx_client.py:310`

```python
async def place_order(
    self, inst_id: str, side: str, ord_type: str, sz: str,
    px: str | None = None, pos_side: str | None = None,
    reduce_only: bool | None = None, tgt_ccy: str | None = None
)
```

委托 `TradeAPI` 调用 OKX V5；受私有 API 限流器、超时、代理、签名和模拟盘 Header 影响。调用者必须同时检查外层 `code` 和单笔 `sCode`。

## 8–10. API、JSON 与数据库

- 第 8 章：见 [api-reference.md](api-reference.md)。
- 第 9–10 章：见 [data-dictionary.md](data-dictionary.md)。

## 11. 业务规则

| 规则 | 实现位置 |
|---|---|
| 策略状态为 `stopped → running → paused/running → stopped`；异常任务写 `error` | `routers/strategies.py`、`services/strategy_engine.py` |
| 服务启动时把数据库中的 `running`/`paused` 实例重置为 `stopped`，并尝试重建 PnL 基准 | `backend/main.py` |
| 启动前执行账户、余额、网格和账户模式等可行性检查 | `StrategyEngine.check_feasibility` |
| QS-Model `meta.base_symbol` 非空时覆盖创建实例请求中的 `symbol` | `routers/strategies.py:create_instance` |
| 模板 `logic` 规范化 JSON 后取 SHA-256；重复逻辑默认仅返回提示，`force=true` 才创建 | `routers/strategies.py` |
| 内置模板不可删除；运行中改变 logic 被拒绝 | `routers/strategies.py`、`StrategyEngine.update_params` |
| PnL 汇总取最新有效时点，未实现 PnL 不跨快照求和 | `routers/pnl.py:get_pnl_summary` |
| 订单 `limit` 最大 1000；PnL `limit` 最大 5000；日志分页使用 `offset+limit` | 相应 routers |
| 时间主要以 UTC `datetime.now(timezone.utc)` 写入；SQLite 读出的 naive 时间在部分响应中视作 UTC | models、`to_utc_iso` |
| 无软删除：删除账户、模板、实例、事件和维护清理均为物理删除 | routers、maintenance service |
| 多步骤数据库写入多使用显式 `commit`，未发现跨服务统一事务边界 | routers/services |
| HTTP 写接口没有通用 Idempotency-Key；模板用名称/logic hash、订单用 `order_id` 唯一性局部去重 | routers/models |

## 12. 认证与权限

- 登录：`POST /api/auth/login`，用户名/密码换取 Bearer JWT。
- JWT：HS256，默认有效期 1440 分钟；没有 refresh token、登出端点或服务端 token 黑名单。
- 前端把 token 存在 `sessionStorage`，Axios 自动发送 `Authorization: Bearer ...`；401 时清理并跳转登录页。
- 密码：bcrypt；修改密码最少 6 个字符。
- 登录失败：最多 5 次，然后锁定 15 分钟。当前锁定时间通过 `datetime.replace` 计算，跨小时边界有专门分支但实现较脆弱。
- 权限：所有已认证用户权限相同；没有角色、资源归属或数据范围检查。
- 无认证接口：`/api/market/spot-tickers`、`/api/market/ticker/{symbol}`、`/api/dsl/blocks`、`/api/dsl/validate`、`/api/dsl/dry-run`，以及三个 `/ws/*`。
- 桌面 QML 桥接的查询接口不强制 JWT，认证 token 仅在内存中维护。

## 13. 错误处理和错误码

项目未定义统一业务错误码或全局异常处理器。FastAPI `HTTPException` 的标准形态为 `{"detail":"..."}`，Pydantic 校验失败为 422；部分 OKX 包装接口以 HTTP 200 返回 `{"code":"-1",...}`。

| HTTP | 业务代码 | 典型触发 | 客户端处理 |
|---:|---|---|---|
| 400 | 未统一 | 参数/状态不允许、模板/文件校验、OKX 凭证失败 | 显示 `detail`，修正请求 |
| 401 | 未统一 | token 无效/过期、密码错误 | 清 token，重新登录 |
| 403 | 代码中未发现显式返回 | 无 RBAC | 待确认 |
| 404 | 未统一 | 账户、模板、实例、规则、沙箱或日志不存在 | 刷新列表并检查 ID |
| 422 | FastAPI validation | Pydantic、path/query 范围校验 | 按 `detail[].loc/msg` 修正字段 |
| 423 | 未统一 | 登录账户处于锁定期 | 锁定期结束后重试 |
| 500 | 未统一 | 回测、沙箱、余额或第三方异常 | 查后端/API 日志，避免盲目重试写操作 |
| 200 | OKX `code != "0"` | 市场/交易第三方失败 | 同时检查响应内 `code/msg/sCode/sMsg` |

合法错误示例：

```json
{"detail":"Invalid or expired token"}
```

## 14. 配置项与环境变量

配置优先级为进程环境/`.env` → `backend/config.py` 默认值；`python-dotenv` 可选导入。修改后通常需要重启后端。

| 配置项 | 必填 | 默认/示例格式 | 用途 |
|---|---:|---|---|
| `JWT_SECRET_KEY` | 生产必填 | `<long-random-secret>` | JWT 签名；源码默认值不安全 |
| `HOST` | 否 | `127.0.0.1` | Uvicorn 监听地址 |
| `PORT` | 否 | `8000` | 后端端口 |
| `PRODUCTION` | 否 | `false` | 生产标记；当前未发现进一步行为分支 |
| `CORS_ORIGINS` | 分离部署时必填 | `https://app.example.com` | 逗号分隔允许来源 |
| `OKX_BASE_URL` | 否 | `https://openapi.okx.com` | OKX 主 REST 地址 |
| `OKX_ALT_URLS` | 否 | `https://host-a,https://host-b` | 网络检查备用地址 |
| `OKX_DNS_OVERRIDE` | 否 | `host:ip,host:ip` | 自定义 DNS 映射 |
| `OKX_PROXY` | 否 | `http://127.0.0.1:7897` | 外部 HTTP 代理 |
| `DESKTOP_BACKEND_HTTP` | 否 | `1` | 桌面进程内启用 FastAPI |
| `DESKTOP_BACKEND_HOST` | 否 | `127.0.0.1` | 桌面内嵌后端地址 |
| `DESKTOP_BACKEND_PORT` | 否 | `8000` | 桌面内嵌后端端口 |

应用内配置还保存在 `user_settings`（目前 `refresh_interval=30`）和 `system_settings`（代理设置）。真实凭证、`.env`、数据库和 `.encryption_key` 不应进入版本库。

## 15–17. 开发、部署与测试

- 第 15–16 章：见 [deployment-guide.md](deployment-guide.md)。
- 第 17 章：见 [testing-guide.md](testing-guide.md)。

## 18. 日志、监控与审计

- Uvicorn 输出标准服务日志；策略/服务混用 `logging` 和 `print`，未统一结构化格式。
- OKX API 文件日志：`backend/logs/{all,error,query,order}/api_YYYY-MM-DD.log`，UTC 按日滚动但没有保留期清理配置。
- 数据库 API 日志：`api_call_logs`；操作审计：`operation_logs`；策略事件：`strategy_events`。
- API 日志会截断请求/响应体到 500 字符，但代码未见通用敏感字段脱敏；账户相关日志必须避免写凭证。
- 监控接口提供策略延迟、资金使用率、保证金率和仓位隔离；阈值包括延迟 P95 > 2s、资金使用 > 80%、保证金 > 80%/95%。
- 未发现 Prometheus、OpenTelemetry、Sentry 或外部告警平台集成；通知支持 SMTP、Webhook、Telegram。
- 没有公开的无认证健康探针；`/api/monitoring/health` 是业务健康接口且需要账户 ID 和认证。

## 19. 安全要求与风险

已实现：Bearer JWT、bcrypt、Fernet 凭证加密、SQLAlchemy 参数化查询、Pydantic 基础校验、CORS allowlist、日志文件名路径穿越检查、OKX 读写限流、默认只绑定 `127.0.0.1`。

基于代码的风险与建议：

- 高：首次启动会创建带有代码内置初始口令的 `admin` 用户；本文不展示该口令，首次登录后必须立即修改。
- 高：`JWT_SECRET_KEY` 有公开默认值；安装脚本会生成随机值，但手动部署可能遗漏。
- 高：WebSocket、DSL dry-run/validate 和部分市场接口无认证；对外暴露前需增加策略与限流。
- 中：所有登录用户拥有全局数据与维护权限，维护接口可物理删除记录。
- 中：代理配置上传使用原始 `file.filename` 拼路径，未做大小、扩展名和完整路径净化；仅在可信本地使用。
- 中：API 调用日志可能包含请求/响应正文，未见对 key、token、passphrase 的通用脱敏。
- 中：没有 CSRF token；JWT 不是 Cookie，降低传统 CSRF 风险，但 WebSocket 和公开端点仍需独立保护。
- 中：未发现 Web API 级全局速率限制、安全响应头、TLS 终止或依赖漏洞扫描。
- 低/待确认：React 默认转义文本，未发现主动插入 HTML；仍应审计第三方内容渲染。

对外部署至少应：替换默认账号/密钥、启用 TLS 反向代理与防火墙、限制 CORS、保护 WebSocket、配置备份和进程监督，并禁用不需要的维护/代理上传功能。

## 20. 性能与容量

- 进程内缓存：市场现货 ticker 15 秒；Instrument 元数据命中后保持到进程结束或显式清空；账户余额/持仓 5 秒；仓位冲突默认 10 秒节流。
- OKX 连接池：主客户端最大 100 连接/20 keepalive；市场公共客户端最大 30/10。
- OKX 客户端限流：公开 20 次/2 秒，私有 60 次/2 秒；不是按用户的 Web API 限流。
- 数据分页/限制：订单 1000、日志 1000、PnL 5000、API 日志 500、事件 1000；模板和实例列表未分页。
- PnL 采样默认每 15 秒；无成交也写心跳快照，数据库会持续增长。
- 回测同步执行，前端超时放宽到 120 秒；长回测会占用请求工作线程。
- 回测历史最多 50 条、沙箱与运行任务在内存中；容量指标和长期压测结果待确认。
- 前端本次构建主 JS 约 1.1 MB、背景视频约 70.8 MB，存在首屏与安装包体积压力。

## 21. Git 与开发规范

现有事实：当前分支为 `master`；浅历史只有少量日期式提交；未发现贡献指南、PR 模板、分支/提交规范、pre-commit、Python formatter/type checker 或 CI 工作流；前端有 Oxlint 与 TypeScript 构建。

建议规范（不是现有规则）：功能分支 `feat/*`、修复 `fix/*`；Conventional Commits；PR 必须通过后端默认非 E2E 测试、前端 lint/build；Python 增加 Ruff/Black 和类型检查；依赖锁定并启用安全扫描；版本统一采用 SemVer 并维护发布标签。

## 22–23. 排障、已知问题和技术债务

详见 [troubleshooting.md](troubleshooting.md)。

## 24. 版本与变更记录

仓库是浅克隆，当前可确认的历史有限：

| 版本/提交 | 日期 | 主要变更 | 兼容性说明 |
|---|---|---|---|
| `1.0.0` / 当前工作区 | 2026-08-11 | 当前 API 声明版本；有未提交业务代码变更 | 待确认发布状态 |
| `259e190` | 2026-07-25 | `07.25` | 提交说明不足，待确认 |
| `90e2d56` | 2026-07-18 | 完善 macOS 环境与项目文档 | 安装脚本要求 Node 22.12+ |
| `96e8c63` | 2026-07-15 | PnL、策略基础、QSM、隔离和监控改进 | 需运行回归测试 |

更多专题变更见现有 `docs/CHANGELOG.md`；其内容存在 2026-07-26 等日期，而当前可见 Git 提交截止 2026-07-25，说明文档包含未提交或后补记录。

## 25. 文档维护规则

以下变化必须同步修改本手册：API 路由、认证、请求/响应 JSON、公共函数签名、数据库字段/索引/迁移、策略状态与风控、环境变量、依赖下限、构建部署流程、测试命令或发布版本。建议 PR 模板加入文档检查项；接口与 schema 优先从 `app.openapi()` 和 ORM metadata 复核。

## 26. 附录

### 术语

| 术语 | 含义 |
|---|---|
| QS-Model | `meta/params/logic/risk_filter` 四段式策略配置 |
| DSL | 可组合策略描述语言 |
| FSM | DSL 编译出的有限状态机 |
| virtual position | 按策略订单核算的虚拟持仓，不等同于交易所账户总持仓 |
| PnL | Profit and Loss，盈亏 |
| demo/live | OKX 模拟盘/实盘交易模式 |
| `ctVal` | 合约面值，用于张数与实际资产数量换算 |

### 重要文件索引

| 文件路径 | 用途 | 已分析 |
|---|---|---:|
| `README.md` | 项目概览、安装和限制 | 是 |
| `backend/main.py` | API 入口和生命周期 | 是 |
| `backend/config.py` | 配置 | 是 |
| `backend/database.py` | 建表和迁移 | 是 |
| `backend/routers/*.py` | 89 个路由声明 | 是 |
| `backend/models/*.py` | 12 张 ORM 表 | 是 |
| `backend/schemas/*.py`、`backend/dsl/schema.py` | 请求和 DSL 模型 | 是 |
| `backend/services/*.py` | 核心服务 | 是（公共入口与关键规则） |
| `backend/strategies/*.py` | 策略与风控 | 是（公共入口与关键规则） |
| `frontend/src/api/*`、`frontend/src/types/*` | 前端契约 | 是 |
| `frontend/src/App.tsx` | 页面路由 | 是 |
| `desktop/main.py`、`desktop/qml_bridge.py` | 桌面入口与桥接 | 是 |
| `backend/tests/`、`backend/pytest.ini` | 测试与执行配置 | 是 |
| `QuantOKX.spec`、`installer/` | 打包 | 是 |
| `.env.example`、安装/启动脚本 | 环境和命令 | 是 |

### 待确认事项

| 编号 | 待确认内容 | 原因 | 建议确认人员 |
|---:|---|---|---|
| 1 | 正式维护团队和代码所有者 | 仓库无 CODEOWNERS/维护说明 | 项目负责人 |
| 2 | `1.0.0` 是否已正式发布 | 无 Git tag，前端仍为 `0.0.0` | 发布负责人 |
| 3 | 生产部署拓扑、域名、TLS、备份 RPO/RTO | 代码仅覆盖本地/Windows 打包 | 运维负责人 |
| 4 | 多用户与权限规划 | 当前只有统一登录权限 | 产品/安全负责人 |
| 5 | 数据保留期和容量目标 | 日志、PnL、订单无统一保留策略 | 运维/业务负责人 |
| 6 | E2E 使用的隔离模拟盘账号和执行审批 | 测试可能访问或修改 OKX 状态 | 测试负责人 |

### 文档与代码不一致项

| 文档内容 | 实际代码 | 影响 | 建议处理 |
|---|---|---|---|
| README 通用要求 Node 18+ | Vite 8 本次提示需 Node 20.19+ 或 22.12+；macOS 脚本要求 22.12+ | 旧 Node 构建不受支持 | README 统一为 22.12+ |
| `backend/requirements.txt` 看似完整 | 代码/安装脚本还使用 `aiosqlite`、`python-dotenv`、`PyYAML`，测试需 pytest | 手动安装可能启动失败 | 补充并锁定依赖 |
| README 说默认 `pytest.ini` 排除 E2E | 正确，但 `tests/perf` 未排除，默认命令会运行性能测试 | 默认套件受性能断言影响 | 明确 marker 选择或调整配置 |
| OpenAPI 仅显示 15 个 schema | 多数路由请求/响应使用裸 `dict` | API 文档契约不完整 | 为路由补 response/request model |
| README 中项目主要为可信单用户本地环境 | 安装文档提供公网暴露方式 | 安全控制不足时风险高 | 对公网部署增加硬化清单或删除简化指引 |

### 文档完整度检查

| 检查项 | 状态 | 说明 |
|---|---|---|
| 项目概述 | 完成 | 以 README、入口和页面为依据 |
| 系统架构 | 完成 | 含三张 Mermaid 图 |
| API 接口 | 完成 | 全路由清单、通用契约和关键示例；裸 dict 响应标记为代码定义 |
| 数据结构 | 完成 | Pydantic、DSL、前端类型和核心 JSON |
| 数据库 | 完成 | 12 张 ORM 表、关系、索引和迁移 |
| 环境变量 | 完成 | 只记录名称和占位格式 |
| 测试 | 完成 | 已执行并记录真实结果 |
| 部署 | 不完整 | 本地和 Windows 安装完整；无容器/CI/正式生产配置 |
| 安全 | 完成 | 区分已实现措施、风险和待确认项 |
