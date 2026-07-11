# 盈亏曲线重构 Spec

## Why

数据库分析发现盈亏曲线存在三个核心问题：
1. **数据稀疏**：68 条 PnlRecord 集中在 04:13-05:41（1.5 小时），运行一晚大部分时间无数据。采样任务每 60s 一次但增量核算返回 None 时跳过写库，导致无成交时段无曲线点。
2. **ID=3 异常数据**：`unrealized_pnl=-8989.93095`，根因是首次增量核算时 `base_avg_buy_price=0.0`（基准 PnlRecord 无此字段），而 5 笔卖单以 `avg_buy_price=0` 计算得出 `(current_price - 0) × (-5) = -8989.93`（当前价约 1798 × 5）。
3. **数据点不足**：前端 PnLChart 在 `timeRange='all'` 时直接返回原始数据点（68 个），但桶模式（24h/7d/30d）固定 24/8/31 个桶，均不足 300 个数据点，曲线显得稀疏。

## What Changes

### A. 修复增量核算 avg_buy_price=0 导致的异常 unrealized_pnl
- 增量核算读取基准时，若 `base_avg_buy_price=0` 且 `base_net_position>0`，从新增 buy 订单重新计算均价（而非用 0 作为基准）
- 增量核算计算 unrealized_pnl 时，若 `avg_buy_price=0` 且有持仓，使用当前价作为兜底（避免极端负值）
- 首次核算（无基准 PnlRecord）时，强制执行全量 recompute 而非增量，确保基准正确

### B. 采样任务无成交时也写快照（解决数据稀疏）
- 采样循环中，即使 `incremental_update` 返回 None（无新成交），也写入一条"心跳快照" PnlRecord
- 心跳快照：复用最新 PnlRecord 的 realized_pnl，重新计算 unrealized_pnl（用当前价），total_pnl = realized + unrealized
- 心跳快照降频：无成交时每 5 分钟写一次（有成交时仍按 60s 增量写），避免 DB 暴写
- 前端 `timeRange='all'` 时，数据点应支持至少 300 个（见 D 部分）

### C. 前端 PnLChart 数据点密度优化
- `timeRange='all'` 模式：不再直接返回原始数据点，改为按时间跨度自适应分桶
  - 跨度 ≤ 6h：每 1 分钟一个桶（最多 360 桶）
  - 跨度 ≤ 24h：每 5 分钟一个桶（288 桶）
  - 跨度 ≤ 7d：每 30 分钟一个桶（336 桶）
  - 跨度 ≤ 30d：每 2 小时一个桶（360 桶）
  - 跨度 > 30d：每 6 小时一个桶（动态）
- 24h 模式：从 24 桶改为 288 桶（每 5 分钟）
- 7d 模式：从 8 桶改为 336 桶（每 30 分钟）
- 30d 模式：从 31 桶改为 360 桶（每 2 小时）
- 数据填充逻辑保持"lastValue 沿用"（桶内有记录则更新，无记录则沿用上一个值）
- 水平滚动阈值从 50 改为 400（超过 400 个数据点才滚动）

### D. 后端 listPnlRecords 支持 start_time/end_time 参数
- `GET /api/pnl` 新增 `start_time` 和 `end_time` 查询参数（ISO 格式）
- 前端根据 timeRange 计算时间窗口，只请求窗口内数据（减少传输量）
- 默认 limit 从 100 提升到 1000（支撑 300+ 数据点）

## Impact

- **Affected specs**：
  - `refactor-pnl-accounting-engine`（增量核算逻辑修正、采样任务心跳快照）
  - `revamp-pnl-curve-and-splash`（PnLChart 桶模式重构）

- **Affected code**：
  - `backend/services/pnl_accounting_engine.py`（修正 avg_buy_price=0、新增 heartbeat_snapshot 方法）
  - `backend/services/strategy_engine.py`（采样循环调用心跳快照）
  - `backend/routers/pnl.py`（新增 start_time/end_time 参数、提升 limit）
  - `frontend/src/components/PnLChart.tsx`（自适应分桶、桶数量调整）
  - `frontend/src/api/pnl.ts`（listPnlRecords 支持 start_time/end_time）
  - `frontend/src/pages/DashboardPage.tsx`（按 timeRange 计算时间窗口传参）

## ADDED Requirements

### Requirement: 心跳快照（无成交时写 PnlRecord）
系统 SHALL 在采样任务中，即使无新增成交订单，也定期写入心跳快照 PnlRecord，确保盈亏曲线在策略运行期间持续有数据点。

#### Scenario: 无成交时写心跳快照
- **GIVEN** 策略正在运行但 5 分钟内无新增成交
- **WHEN** 采样任务触发
- **THEN** 读取最新 PnlRecord 的 realized_pnl、net_position、avg_buy_price
- **AND** 获取当前价计算 unrealized_pnl = (current_price - avg_buy_price) × net_position - 预估手续费
- **AND** 若 avg_buy_price=0 且 net_position>0，unrealized_pnl=0（避免极端值）
- **AND** 写入 PnlRecord（is_final=False），不更新任何订单的 pnl_accounted
- **AND** 心跳快照降频为每 5 分钟一次（有成交时仍按 60s 增量写）

#### Scenario: 有成交时正常增量核算
- **GIVEN** 策略运行中有新增成交
- **WHEN** 采样任务触发（60s 间隔）
- **THEN** 执行增量核算，写入 PnlRecord
- **AND** 重置心跳计时器

### Requirement: 前端 PnLChart 自适应分桶
PnLChart SHALL 在所有时间模式下按时间跨度自适应分桶，确保至少 280 个数据点（支撑 300+ 目标的视觉密度）。

#### Scenario: all 模式跨度 ≤ 24h
- **GIVEN** timeRange='all' 且数据跨度 ≤ 24h
- **WHEN** 渲染图表
- **THEN** 按 5 分钟一个桶分桶（约 288 桶）

#### Scenario: all 模式跨度 > 30d
- **GIVEN** timeRange='all' 且数据跨度 > 30d
- **WHEN** 渲染图表
- **THEN** 按 6 小时一个桶分桶

## MODIFIED Requirements

### Requirement: 增量核算 avg_buy_price 基准修正
增量核算 SHALL 在读取基准 PnlRecord 时，若 `base_avg_buy_price=0` 且 `base_net_position>0`，从当前新增 buy 订单或历史 buy 订单重新推算 avg_buy_price，避免 unrealized_pnl 计算出极端负值。

#### Scenario: 首次增量核算无基准
- **GIVEN** 策略首次运行，无历史 PnlRecord，首批订单含 buy 和 sell
- **WHEN** 调用 incremental_update
- **THEN** 检测到无基准，转而执行全量 recompute 逻辑
- **AND** 确保 avg_buy_price 从 buy 订单正确计算
- **AND** unrealized_pnl 基于正确的 avg_buy_price

### Requirement: 采样任务循环
StrategyEngine 的 `_pnl_sampling_loop` SHALL 每 60s 对 running 策略执行增量核算，无新增成交时每 5 分钟写心跳快照。

### Requirement: PnL API 时间窗口过滤
`GET /api/pnl` SHALL 支持 `start_time` 和 `end_time` 查询参数过滤时间范围，默认 limit 提升至 1000。

## REMOVED Requirements

### Requirement: PnLChart all 模式直接返回原始数据点
**Reason**: 原始数据点数量不稳定（68 个），无法保证 300+ 数据点的视觉密度。改为自适应分桶。
**Migration**: all 模式改为按时间跨度自适应分桶，与其他模式统一。
