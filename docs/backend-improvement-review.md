# Backend Improvement Review

This review is based on the current backend implementation. It focuses on changes that most improve safety, correctness, operability, and maintainability for a system capable of placing live trades.

## SS Project 专项：策略执行、PnL、订单与归因

本专项已与现有 PnL、归因、订单恢复规格进行去重，并整理为可执行开发计划：[`ss-project-pnl-order-attribution-development.md`](./ss-project-pnl-order-attribution-development.md)。当前需要优先处理的结论如下：

1. **策略状态必须区分“数据库期望状态”和“运行时真实状态”**。手动修改 `strategy_instances.status` 只改变展示字段，不代表对应协程、挂单和行情订阅已经启动或停止；接口需要返回状态来源、任务存活、心跳时间和状态漂移告警。
2. **单策略 PnL 统一为成交驱动口径**：`total_pnl = realized_pnl + unrealized_pnl`。已实现盈亏只由已配对的实际成交产生，未实现盈亏只针对仍持有的虚拟净仓位，并使用当前价、实际持仓成本和统一手续费口径。
3. **新建策略必须从独立零基线开始**。无成交的新策略不应写入污染曲线的全零 `PnlRecord`，不得继承同账户、同币种或同模板的历史订单与 PnL；首笔成交前 API 可以返回展示用零值，但不持久化伪快照。
4. **账户总盈亏必须聚合每个策略的最新快照**。当前 `backend/routers/pnl.py:get_pnl_summary` 在未指定策略时使用全局最近一条有效记录作为总值，不是 `sum(latest_by_strategy)`；这会导致多策略或新建策略场景下总盈亏口径错误。
5. **策略中断恢复需要持久化状态机和对账流程**。恢复顺序应为：读取策略期望状态 → 对账 OKX 活跃订单与成交 → 恢复虚拟仓位和 realized 基线 → 重算 unrealized → 恢复行情订阅与执行循环；所有步骤必须可重复执行且不能重复下单或重复记账。
6. **订单主键语义必须固定**。`orders.id` 是数据库内部主键；`orders.order_id` 必须保存 OKX 返回的 `ordId` 并保持唯一；`orders.cl_ord_id` 保存客户端订单号。成交、撤单、恢复、去重与 PnL 核算统一使用该映射。
7. **行情并非逐个实时查询所有币种**。展示层每 20 秒请求一次选定币种，后端 REST 接口拉取 OKX 全部 SPOT tickers 后缓存 15 秒，再只返回请求币种；策略执行层按实际订阅/持仓品种使用 WebSocket 缓存或单品种查询。需要增加行情时间戳、陈旧阈值和降级标记。
8. **归因分析必须与 PnL 汇总共享同一快照选择器和时间口径**。按币种、策略类型、时间段三个维度应满足 realized、unrealized 和 total 的交叉汇总一致性，并避免把累计值误当区间增量。

专项上线门槛：多策略总盈亏恒等式、新策略零基线、重启恢复幂等、`ordId` 去重、行情陈旧标记、三维归因交叉核对均须有自动化测试；现有 PnL/研究相关失败测试清零后再进入实盘验证。

## Priority 0 — address before exposing the service or using meaningful live funds

### 1. Remove insecure bootstrap credentials and fail closed in production

**Current state**

- `backend/main.py` automatically creates `admin` with password `admin123`.
- `backend/config.py` falls back to a known JWT secret.
- `PRODUCTION` is parsed but does not enforce secure startup requirements.

**Risk**

Any deployment reachable by another machine can be taken over if the operator forgets to change the defaults. A known JWT secret also allows token forgery.

**Recommended change**

- Require `JWT_SECRET_KEY` when `PRODUCTION=true` and reject known/default values.
- Replace the fixed initial password with a one-time random bootstrap password printed once, or require explicit `ADMIN_PASSWORD` on first startup.
- Force a password change on first login and raise the minimum password requirements.
- Document a supported secret-rotation procedure.

### 2. Stop logging credential fragments and authentication material

**Current state**

`backend/services/okx_client.py` builds `req_meta` containing the first 12 characters of the API key, the first four passphrase characters, and a signature fragment. That metadata is persisted in the database and file logs.

**Risk**

Logs become sensitive assets, are retained in multiple locations, and can leak identifying or authentication-related information through diagnostics, exports, backups, or bug reports.

**Recommended change**

- Never log API keys, passphrases, secrets, signatures, authorization headers, or request bodies that may contain them.
- Add a central structured-log redaction filter with an allowlist of safe fields.
- Review existing log/export endpoints and purge old sensitive records.
- Add tests that assert known secrets never appear in logs.

### 3. Authenticate WebSocket connections

**Current state**

The endpoints in `backend/routers/ws.py` accept connections without validating a JWT. Strategy and dashboard sockets expose runtime state; the market socket can also consume upstream resources.

**Risk**

When the backend is reachable beyond localhost, unauthenticated clients can observe operational state and create resource pressure.

**Recommended change**

- Validate a short-lived token during the WebSocket handshake.
- Authorize access to the requested account/strategy, not only authentication.
- Enforce origin checks, connection limits, heartbeat timeouts, bounded queues, and per-client backpressure.
- Remove dead connections during broadcast failures.

### 4. Harden file and path handling in proxy configuration endpoints

**Current state**

- `backend/routers/settings.py` joins the client-provided upload filename directly into a server path.
- The sample-config import endpoint accepts a client-provided filesystem path.
- Upload size is not bounded before `await file.read()` loads the full body into memory.

**Risk**

Crafted filenames can escape the intended directory, arbitrary local paths can be selected, and large uploads can exhaust memory.

**Recommended change**

- Discard directory components with `Path(filename).name`, generate a server-side identifier, and verify the resolved destination remains inside the configured data directory.
- Replace arbitrary paths with opaque IDs returned by a server-generated allowlist.
- Set request and file-size limits and stream uploads to disk.
- Validate YAML structure before saving or starting the proxy process.

## Priority 1 — correctness and reliability

### 5. Replace ad-hoc schema upgrades with versioned migrations

**Current state**

`backend/database.py` combines `create_all()` with multiple hand-written `ALTER TABLE` and index functions. Additional one-off migration scripts live under `backend/migrations/`, but there is no migration version table or transactional migration history.

**Risk**

Schema state can drift between installations, partial upgrades are hard to diagnose, and migrations that fail because of duplicate data can prevent startup.

**Recommended change**

- Introduce Alembic with a baseline revision and ordered, idempotent migrations.
- Back up the SQLite database before migration.
- Validate data before adding unique constraints.
- Test upgrades from every supported released schema, not only fresh database creation.

### 6. Separate synchronous persistence from async trading loops

**Current state**

The backend uses synchronous SQLAlchemy sessions throughout async strategy, monitoring, notification, and accounting code. API-call logging also opens and commits database sessions synchronously in request paths.

**Risk**

SQLite locks or slow disk writes can block the event loop, delay ticker/order handling, and amplify failures during volatile markets—the exact time latency matters most.

**Recommended change**

- Choose one explicit model: SQLAlchemy async sessions end-to-end, or move synchronous DB operations to bounded worker threads.
- Send logs and PnL writes through a bounded persistence queue with batching and retry policy.
- Define SQLite WAL, busy-timeout, and transaction boundaries explicitly.
- Measure event-loop lag and database commit latency under load.

### 7. Make order processing idempotent and recovery-oriented

**Current state**

The code has extensive PnL recomputation and restart cleanup, but many trading and accounting paths catch broad exceptions, sometimes silently. Runtime strategy tasks live in a process-local singleton.

**Risk**

Network retries, duplicate exchange events, process crashes, or partial commits can produce duplicate actions, stale local state, or PnL inconsistencies.

**Recommended change**

- Use stable client order IDs and persist an order-intent state machine before calling OKX.
- Make fill ingestion and PnL accounting idempotent with explicit deduplication keys.
- Persist strategy lifecycle transitions and reconcile them on startup.
- Classify retryable versus terminal errors and use capped exponential backoff with jitter.
- Convert silent exception handlers into structured errors, metrics, and alerts.

### 8. Fix authentication lockout time arithmetic

**Current state**

`backend/routers/auth.py` computes `locked_until` with `datetime.replace(minute=minute + N)` and a manual hour fallback.

**Risk**

The calculation is fragile at hour/day boundaries and can raise another `ValueError` near midnight.

**Recommended change**

Use `datetime.now(timezone.utc) + timedelta(minutes=LOGIN_LOCKOUT_MINUTES)`, add boundary tests, and consider IP/account rate limiting outside the application process.

### 9. Validate all request bodies with typed schemas

**Current state**

Several routes accept raw `dict` bodies, including settings, DSL, proxy, and sandbox-related operations. Numeric ranges and enum-like values are often validated inside services or not at all.

**Risk**

Invalid shapes fail late, API documentation is incomplete, and dangerous parameters can reach trading logic without consistent bounds.

**Recommended change**

- Define strict Pydantic request/response models for every endpoint.
- Forbid unexpected fields on security- and trading-sensitive requests.
- Add bounded numeric types for leverage, capital, order size, limits, and timeframes.
- Return stable error codes in addition to translated messages.

## Priority 2 — maintainability and operations

### 10. Break up oversized modules and define service boundaries

Several core files exceed 700–1,100 lines, including the PnL engine, DSL executor/base blocks, base strategy, grid strategy, strategy router, proxy core, and backtest engine.

Split orchestration from calculation and infrastructure. Prefer pure, deterministic domain functions for fills, virtual positions, metrics, and risk decisions; keep network/database adapters thin. This will reduce the amount of mocking required and make safety-critical logic easier to review.

### 11. Standardize logging, metrics, and health checks

The backend mixes `print`, Python logging, database logs, and swallowed exceptions. Move to structured logs with request/strategy correlation IDs and explicit redaction. Add counters and latency histograms for OKX calls, retries, order acknowledgements, fills, queue depth, DB locks, WebSocket reconnects, event-loop lag, PnL reconciliation differences, and notification failures.

The health endpoint should distinguish:

- process liveness;
- database readiness;
- OKX connectivity and clock skew;
- WebSocket freshness;
- persistence backlog;
- strategy heartbeat age.

### 12. Consolidate dependency and developer tooling

`backend/requirements.txt` uses broad lower bounds, while the Windows installer separately installs dependencies such as `python-dotenv`. Test tools are not declared in a reproducible development dependency set.

Recommended actions:

- Add `pyproject.toml` with runtime, test, lint, and packaging groups.
- Lock or constrain tested dependency versions and automate updates.
- Add Ruff (lint/format), mypy or Pyright, and security/dependency scanning.
- Remove unused or misleading dependencies and align source, installer, desktop, and PyInstaller specifications.

### 13. Add CI and stop ignoring workflow configuration

The root `.gitignore` currently ignores `.github/`, which prevents normal versioning of GitHub Actions workflows. Track CI configuration and run backend unit tests, frontend lint/build, migration checks, secret scanning, and a small deterministic backtest on every pull request. Keep demo/live credentials out of CI and gate exchange-dependent E2E tests behind an explicit protected environment.

### 14. Improve lifecycle and resource ownership

Move startup/shutdown logic from deprecated event decorators to a FastAPI lifespan context. Give HTTP clients, background tasks, proxy processes, schedulers, and database resources explicit owners. Ensure all temporary clients created for account verification and feasibility checks are closed deterministically rather than relying on destructors.

### 15. Define data retention, backup, and restore

Orders, PnL snapshots, API call bodies, operation logs, strategy events, and notification configuration accumulate in one SQLite database. Define retention by data type, automatic backup before migration/maintenance, integrity checks, encrypted backup handling, and a tested restore procedure. Avoid retaining full exchange responses unless needed for a specific audit purpose.

## Suggested implementation order

1. Secure bootstrap, JWT configuration, and log redaction.
2. Authenticate WebSockets and harden upload/path endpoints.
3. Fix lockout arithmetic and add strict request schemas.
4. Introduce Alembic and tested database upgrade paths.
5. Add idempotent order intents, fill deduplication, and recovery tests.
6. Move blocking persistence/logging out of async trading loops.
7. Add structured observability, CI, dependency locking, backup, and retention.
8. Refactor large modules incrementally behind characterization tests.

## Existing strengths to preserve

- Credentials are encrypted at rest with a per-installation Fernet key and the key file is permission-restricted where supported.
- Account API responses mask stored credentials.
- The code contains substantial unit, E2E, regression, and performance-test coverage.
- OKX clients use time synchronization, rate limiting, timeouts, retries, and explicit shutdown paths.
- Strategy-level PnL accounting, position reconciliation, and capital/margin controls provide a useful domain foundation.
- Demo mode, backtesting, dry-run, and sandbox workflows support a safer path toward live trading.
