# QuantOKX 测试说明

## 1. 测试体系

| 类型 | 位置 | 框架/入口 | 外部依赖 |
|---|---|---|---|
| 后端单元/回归 | `backend/tests/test_*.py` | pytest、pytest-asyncio | 多数使用 mock/临时 SQLite |
| DSL | `backend/tests/test_dsl_*.py` | pytest | 注册表、编译器、dry-run |
| API/集成 | `test_dsl_api.py` 等 | FastAPI TestClient | 本地应用/测试 DB |
| E2E | `backend/tests/e2e/` | `tests/run_e2e_tests.py` | OKX demo，可能改变账户状态 |
| 性能 | `backend/tests/perf/` | pytest marker `perf` | 时间阈值，对机器负载敏感 |
| 研究/审计 | 多个 `test_*runner*`、reports | pytest/脚本 | 文件输出被 fixture 重定向 |
| 前端静态检查 | `frontend/` | Oxlint | node_modules |
| 前端类型/构建 | `frontend/` | `tsc -b`、Vite | Node 版本与前端资源 |

当前有 68 个 `test_*.py` 文件。`backend/pytest.ini` 设置 `asyncio_mode=auto`，定义 `slow/integration/perf/demo` markers，并排除 `tests/e2e`；它没有默认排除 `tests/perf`。

## 2. 安装测试依赖

```bash
cd backend
source .venv/bin/activate
python -m pip install pytest pytest-asyncio
```

安装脚本还会安装 `aiosqlite`、`python-dotenv` 和 `PyYAML`。测试应使用临时 DB、mock 或专用 OKX demo 账户，绝不能使用实盘凭证。

## 3. 推荐执行命令

### 默认后端套件

```bash
cd backend
.venv/bin/python -m pytest -q
```

由于默认配置包含性能目录且若干 OKX 接口风格测试需要自定义 runner，日常纯回归可先显式排除：

```bash
cd backend
.venv/bin/python -m pytest -q --ignore=tests/e2e --ignore=tests/perf \
  --ignore=tests/test_account.py \
  --ignore=tests/test_backward_compat.py \
  --ignore=tests/test_funding.py \
  --ignore=tests/test_market.py \
  --ignore=tests/test_public.py \
  --ignore=tests/test_trade.py
```

第二条是建议的隔离命令，不代表项目现有 CI 标准；具体跳过清单应由维护者确认并最终通过 marker/目录重构固化。

### 指定风险域

```bash
cd backend
.venv/bin/python -m pytest -q \
  tests/test_pnl_accounting_engine.py \
  tests/test_pnl_curve_fix.py \
  tests/test_strategy_state_sync.py \
  tests/test_trend_strategy_runtime.py
```

### E2E（仅隔离 demo 环境）

```bash
cd backend
.venv/bin/python tests/run_e2e_tests.py --report
```

先阅读 `backend/tests/e2e` 和 runner 配置，确认 API Key 无提现权限、账户为 demo、初始挂单/持仓可清理，并得到执行授权。E2E 可能下单、撤单、改杠杆或划转，不应在普通回归自动运行。

### 性能

```bash
cd backend
.venv/bin/python -m pytest tests/perf -m perf
```

当前部分 perf 测试可能未实际标记但仍被目录收集。应在空闲机器重复运行并记录硬件/负载，不用单次毫秒断言判断业务正确性。

### 前端

```bash
cd frontend
npm run lint
npm run build
```

`npm run build` 同时执行 TypeScript project build 和 Vite 生产构建。

## 4. 2026-08-11 实际验证记录

执行环境：macOS，工作区存在用户未提交的策略/PnL 相关修改；测试结果仅代表当时工作区。

### 后端

有效命令：

```bash
cd backend
.venv/bin/python -m pytest -q
```

| 项目 | 结果 |
|---|---:|
| 通过 | 870 |
| 失败 | 13 |
| 跳过 | 4 |
| setup 错误 | 4 |
| warnings | 10 |
| 用时 | 18.48 秒（工具墙钟约 18.95 秒） |
| 结论 | 未全部通过 |

失败/错误摘要：

- `tests/perf/test_perf_pnl_accounting.py`：2 个增量核算订单数断言失败。
- `tests/test_pnl_accounting_engine.py`、`test_pnl_curve_fix.py`：增量净持仓得到 0，而预期为 1。
- `tests/test_function_checker.py`：事件未写入/rollback 未调用等 5 个失败。
- `tests/test_leverage.py`：实现抛 `RuntimeError`，测试预期未抛。
- `tests/test_run_iteration_should_start.py`：3 个研究启动分支得到 `START_FAILED`。
- `test_backward_compat.py`、`test_funding.py`、`test_market.py`、`test_public.py`：缺少 `runner` fixture，setup error。
- warnings 包括 `TestRunner` 无法收集、Starlette/httpx 弃用提示和 coroutine 未 await。

首次误用了从 `backend/` 工作目录出发的 `backend/.venv/bin/python`，shell 立即返回 127，未运行测试；该次不计入测试结果。

### 前端

有效命令：

```bash
cd frontend
npm run lint && npm run build
```

| 项目 | 结果 |
|---|---|
| Oxlint | 成功退出，20 条 warning |
| TypeScript/Vite build | 成功，2858 modules transformed |
| Node 提示 | 当前 20.18.0；Vite 8 要求 20.19+ 或 22.12+ |
| CSS | 3 条任意值 selector 优化 warning |
| 产物 | 主 JS 约 1,108 kB；背景视频约 70,839 kB |
| 结论 | 构建成功，但警告和体积需治理 |

主要 lint warning：未使用变量、React hook 缺依赖、Fast Refresh 文件混合导出、冗余 Boolean。没有因 warning 阻断构建。

## 5. 测试数据与隔离

- `backend/tests/conftest.py` 提供测试基础 fixture；多个模块会创建临时 SQLite 或替换 Session。
- 研究、审计和功能检查测试用 `tmp_path` 重定向输出，避免污染真实 reports/logs。
- 仓库根 `data/quant_okx.db` 是用户运行数据；测试不得清空、迁移或写入它。
- E2E 必须显式提供 demo 配置，不应从真实 `.env` 自动继承 live 凭证。
- 文件型 encryption key 与数据库配套；测试凭证应使用临时 key/目录。

## 6. Mock 使用方式

代码广泛使用 `unittest.mock.MagicMock`、`AsyncMock` 和 `patch`：

- patch `SessionLocal` 隔离 PnL/策略数据库路径。
- mock `OKXClient`、trade/account/market API，避免网络与真实下单。
- 为回测通过 `set_klines_for_test` 注入 K 线。
- 沙箱使用 `MockOKXClient` 拦截写操作，但仍可能读取真实行情。

异步 mock 必须返回实际实现期望的结构；本次 PnL 回归显示 MagicMock 查询链与实现变化容易脱节。

## 7. 覆盖率

仓库未声明 `pytest-cov` 依赖或覆盖率阈值，未发现现成 coverage 命令。建议规范（非现有命令）：安装 `pytest-cov` 后对隔离的默认套件运行 `python -m pytest --cov=backend --cov-report=term-missing`，并在 CI 固化阈值。建立阈值前先排除 E2E、生成文件和外部接口 runner。

## 8. 主要测试场景

- 认证、账户、公开/私有 OKX wrapper 兼容性。
- DSL schema、积木注册、条件/动作/事件、编译、执行、dry-run 和 API。
- 内置策略参数、状态同步、启动/暂停/恢复/停止、下单响应校验。
- 资金上限、杠杆、保证金、仓位冲突和对账。
- PnL 全量/增量、稀疏曲线、异常数据、UTC 序列化和归因一致性。
- WebSocket public、市场缓存、通知渠道。
- SPA fallback、桌面 launcher event loop。
- QSM 生成、基因池、模板分享、研究 runner 和审计报告。

## 9. 当前测试缺口

- 没有前端组件/页面单元测试、浏览器 E2E 或视觉回归配置。
- 没有桌面 QML 自动化测试。
- 没有统一 CI，默认套件当前失败且测试分类不彻底。
- 裸 dict API 缺少契约/快照测试，OpenAPI 无法覆盖多数响应。
- 缺少迁移版本矩阵和从历史 DB 升级的自动化测试。
- 缺少备份恢复、安装包升级/卸载和公网安全配置测试。
- WebSocket 未覆盖认证/授权（实现本身也缺失）。
- 通知真实渠道、代理下载/进程和网络降级主要依赖 mock，生产行为待专项验证。

## 10. 提交前建议门禁

1. 运行修改模块的精确测试。
2. 运行排除外部 runner/E2E/perf 的稳定后端回归集。
3. 运行 `npm run lint` 和 `npm run build`，不新增 warning。
4. 数据库字段变化用旧 DB 副本验证启动迁移。
5. 交易路径变化用 demo 账户做受控冒烟，确认挂单/持仓已清理。
6. 在 PR 中记录执行命令、通过/失败/跳过数和已知豁免；不得只写“测试通过”。
