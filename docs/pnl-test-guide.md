# 本地 PnL 测试与逻辑排查指南

## 1. 测试数据说明

项目提供 `scripts/seed_pnl_test_data.py`，用于在现有 SQLite 数据库中创建一组确定性的本地测试数据。

安全边界：

- 不连接 OKX。
- 不启动策略，不发送真实或模拟盘订单。
- 测试账户处于停用状态，三个策略实例均为 `stopped`。
- 只清理名称以 `[PNL-TEST]` 开头的数据，不影响已有业务账户。
- 默认在 `data/` 下备份修改前的数据库。

生成的数据：

| 策略 | 成交与行情 | 预期已实现 | 预期未实现 | 预期总盈亏 |
| --- | --- | ---: | ---: | ---: |
| `[PNL-TEST] 持仓浮盈` | 买入 1 @ 100，固定现价依次为 100、105、110 | 0.00 | 10.00 | 10.00 |
| `[PNL-TEST] 闭环盈利` | 买入 2 @ 100，卖出 2 @ 115，手续费 0.43 | 29.57 | 0.00 | 29.57 |
| `[PNL-TEST] 闭环亏损` | 买入 1 @ 200，卖出 1 @ 190，手续费 0.39 | -10.39 | 0.00 | -10.39 |

正确的账户总盈亏应为：

```text
10.00 + 29.57 - 10.39 = 29.18
```

## 2. 运行和清理

在项目根目录执行：

```bash
backend/.venv/bin/python scripts/seed_pnl_test_data.py
```

清理本脚本创建的全部测试数据：

```bash
backend/.venv/bin/python scripts/seed_pnl_test_data.py --remove
```

脚本可重复运行。再次运行时会先删除旧的 `[PNL-TEST]` 数据，再重新创建。

## 3. 前端检查步骤

1. 刷新前端。
2. 顶部账户下拉框选择 `[PNL-TEST] 本地盈亏测试账户`。
3. 进入“策略管理”，确认三个实例均为 `stopped`；不要点击启动。
4. 返回“仪表盘”，依次在右侧策略列表选择三个测试策略。
5. 对照上表核对已实现、未实现和总盈亏。
6. 选择“全部策略”，检查账户级总盈亏是否为 `29.18`。

账户资产区域无法从 OKX 获取余额是预期行为，因为测试账户没有真实 API 凭证。PnL 曲线、最近成交和策略级汇总来自本地数据库，可独立用于核算逻辑调试。

## 4. 当前应优先验证的问题

### 4.1 单策略恒等式

每条快照必须满足：

```text
total_pnl = realized_pnl + unrealized_pnl
```

建议在 PnL 写入前断言该恒等式，并在测试中使用小数容差，例如 `0.01`。

### 4.2 多策略账户汇总

账户总盈亏不能取全局最近一条 `PnlRecord`，必须：

1. 先按账户过滤。
2. 每个 `strategy_instance_id` 选择最新有效快照。
3. 分别求和 `realized_pnl` 和 `unrealized_pnl`。
4. 最后计算 `account_total = account_realized + account_unrealized`。

当前 `backend/routers/pnl.py:get_pnl_summary` 的“全部策略”路径仍以全局最近有效记录作为总值。本测试数据的正确总值是 `29.18`，而当前页面很可能显示最新策略的 `10.00`，这正是需要修复的回归场景。

### 4.3 前端账户过滤

`frontend/src/hooks/useDashboardState.ts` 当前获取 PnL 汇总、曲线、策略和订单时没有统一传入顶部选中的 `account_id`。拥有多个账户后，页面可能混入其他账户的数据。

修复顺序建议：

1. 后端先修正 `sum(latest_by_strategy)`。
2. 增加后端“同账户多策略”回归测试。
3. 前端所有仪表盘请求统一传入 `selectedAccountId`。
4. 增加两个账户的数据隔离测试。

### 4.4 已实现盈亏

- 只使用 `filled` 成交。
- 使用 `fill_px`、`actual_qty/fill_sz` 和实际手续费。
- 按成交时间 `update_time` 做 FIFO 配对。
- WebSocket、REST 对账和恢复重复返回同一成交时只能记账一次。

### 4.5 未实现盈亏

- 只计算尚未平仓的净仓位。
- 使用剩余仓位成本，不得使用已被 FIFO 配对消耗的买入均价。
- 行情缺失或陈旧时不能静默写 0，应标记数据不可用或 `stale`。
- 现货与合约必须使用完全一致的 `instId` 和合约面值口径。

## 5. 推荐的代码处理流程

1. 先用当前测试数据记录页面实际值。
2. 在 `backend/tests/` 添加失败的多策略汇总测试，期望总值为 `29.18`。
3. 修改 `backend/routers/pnl.py:get_pnl_summary`，让账户级结果聚合每个策略的最新有效快照。
4. 运行 PnL 单元测试与多策略隔离测试。
5. 重新运行种数脚本并刷新前端，确认“全部策略”为 `29.18`。
6. 再测试新建无成交策略：它应贡献 0，但不能覆盖已有账户总盈亏。

建议执行的测试命令：

```bash
cd backend
.venv/bin/python -m pytest tests/test_pnl_accounting_engine.py tests/test_pnl_algorithm_fix.py tests/test_summary_skip_zero.py -q
.venv/bin/python -m pytest tests/e2e/test_demo_multi_strategy_isolation.py -q
```

## 6. 本次实际验证结果

种数完成后的数据库检查结果：

- SQLite `PRAGMA integrity_check` 返回 `ok`。
- 1 个停用测试账户、3 个 `stopped` 策略实例、5 笔已成交测试订单、5 条 PnL 快照。
- 每条快照均满足 `realized_pnl + unrealized_pnl = total_pnl`。
- 三个策略最新快照之和为 `29.18`，当前账户汇总接口返回 `10.00`，已稳定复现多策略汇总问题。

针对 PnL 的现有单元测试执行结果为 `33 passed, 1 failed`。失败用例：

```text
tests/test_pnl_accounting_engine.py::
TestIncrementalUpdate::test_incremental_sells_match_new_buys_only
```

该失败与本次种数脚本无关。当前 `incremental_update` 在发现任何新增成交时都会直接委托 `recompute`，导致原先验证增量分支的测试预期与实现不一致。处理时需要先明确产品决策：保留“始终全量重算”并更新测试及方法命名，或者恢复真正的增量路径并验证 FIFO 精度；不能让不可达代码和旧测试长期并存。
