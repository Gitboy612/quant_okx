# 仪表盘盈亏/归因/仓位冲突/QSModel 研究闭环修复 Spec

## Why

用户在实盘使用中发现仪表盘与定时研究任务存在 4 类重大问题，直接影响产品可信度与核心卖点：

1. **盈亏曲线切换不响应**：策略列表切换策略后，盈亏曲线不更新（根因：`useDashboardState.ts` useEffect 依赖配置错误，挂载后不再触发刷新）。
2. **已实现/未实现盈亏恒为 0**：`recompute` 在无成交时仍写入全 0 PnlRecord，`run_iteration.py` 每次健康检查都调 recompute 反复写全 0 记录，summary 端点取最新记录显示全 0，掩盖真实状态。
3. **归因分析三个维度数据打架**：按币种/按策略类型/按时间段给出三个不同结果——数据源不同（Order 表 vs PnlRecord 表）、avg_buy_price 口径不同（混合加权 vs 按策略独立）、realized_pnl 口径不同（按笔卖 vs matched_qty 累计 vs 区间增量）、by_symbol 不含 unrealized_pnl、时间过滤字段不同（created_at vs recorded_at）。
4. **仓位冲突误报**：`check_position_conflict` 与 `position_conflicts` 端点用**绝对值之和**计算其他策略占用，多空对冲策略（A=+5, B=-5）会被误报为冲突。用户用"傅里叶叠加"比喻正确指出：多策略虚拟持仓应**代数叠加**等于真实持仓，当前绝对值算法违背此语义。
5. **定时任务未使用 QSModel**：`run_iteration.py` 的 `should_start` 分支是空壳，未实际生成 QSModel、未调 dry_run、未自动启动创新策略。QSModel 四段式 + FSM + 风控 + 丰富积木库（12 指标/11 条件/12 动作/8 事件/7 基础策略）完全支持自动生成，但被闲置——这与产品差异化卖点"可视化策略构建"严重不符。

## What Changes

### A. 盈亏曲线切换响应（前端 useEffect 修复）
- **修复**：`useDashboardState.ts` 的 `loadBaseData` useEffect 依赖从 `[]` 改为 `[loadBaseData]`，使 `selectedStrategyId`/`timeRange` 变化立即触发刷新
- **修复**：`getPnlSummary` 调用传入 `strategy_instance_id`（后端 `pnl.py` `get_pnl_summary` 端点增加该查询参数）
- **新增**：切换策略时显示 loading 态，避免用户误以为没反应

### B. PnL 为 0 的根因修复（避免无意义全 0 记录）
- **修改**：`pnl_accounting_engine.recompute` 在无 filled 订单时返回 None 而非写入全 0 PnlRecord
- **修改**：`heartbeat_snapshot` 无基准记录时调用 recompute 兜底（而非直接返回 None）
- **修改**：`run_iteration.py` 健康检查的 recompute 调用：无 filled 订单时跳过，避免反复写全 0 记录
- **修改**：`pnl.py` `get_pnl_summary` 端点跳过 `total_pnl=0 and net_position=0 and order_count=0` 的无意义记录
- **新增**：`_get_current_price` 行情获取失败时记录 `market_data_unavailable` warning 事件，前端展示"行情获取失败"而非显示 0
- **修改**：`avg_buy_price=0 且 net_position>0` 兜底逻辑从静默置 0 改为告警 + 置 0

### C. 归因分析三维度统一口径
- **重构**：`attribution_service.get_attribution_by_symbol` 改为基于 PnlRecord（通过 StrategyInstance.symbol 关联聚合各实例 latest PnlRecord），与 by_strategy_type/by_period 数据源统一
- **新增**：by_symbol 补充 `unrealized_pnl` 字段（聚合各策略实例的 unrealized）
- **统一**：三个维度 realized_pnl 统一取 `PnlRecord.realized_pnl`（累计值口径），或统一用"区间增量"口径（择一，建议累计值，更直观）
- **统一**：三个维度时间过滤字段统一用 `recorded_at`（PnL 记录时间）
- **统一**：by_symbol 的 avg_buy_price 按策略实例独立计算后聚合加权平均，避免混合口径

### D. 仓位冲突检测改用代数叠加
- **修改**：`base_strategy.check_position_conflict` 的 `others_occupied` 从绝对值之和改为代数和（带符号）：`others_occupied = sum(other.net_position)`
- **修改**：`available = real_pos - others_occupied`（代数和），符合"多空对冲叠加"语义
- **修改**：`monitoring.py` `/api/monitoring/position_conflicts` 端点同步改用代数和
- **修改**：`is_conflict` 判断：`available < abs(net_position)`（策略无法独立平掉自己的净持仓时才算冲突）
- **新增**：区分两种看板——「仓位隔离对账」（reconcile_positions，数据一致性）与「平仓能力」（position_conflicts，操作可行性），前端分开展示
- **新增**：仓位冲突看板增加"对冲组"标注（同账户同 symbol 多空策略组）

### E. 定时任务 QSModel 研究闭环
- **实现**：`run_iteration.py` 的 `should_start` 分支实现真正的 QSModel 生成-验证-启动闭环
- **新增**：QSModel 生成器模块 `backend/research/qsm_generator.py`，按四类研究类型生成 QSModelConfig：
  - 经典变体：base_strategy 调参（grid_count/order_qty/lever 组合）
  - DSL 创新：base_strategy + rules 组合（如 grid + cross_above 暂停规则 + rebalance_position 动作）
  - 回测筛选：生成多候选 → 调 `dsl/dry_run.py` 回测 → 按夏普/回撤筛选
  - 参数 A/B：同 logic 不同 params 并行（用 `$params.xxx` 变量引用）
- **新增**：调用 `/api/dsl/validate` 校验生成的 QSModel，避免无效配置
- **新增**：调用 `/api/dsl/dry-run` 历史回放预验证，再实盘启动
- **新增**：生成的策略配置 `risk_filter` 段（daily_max_loss/stop_loss/take_profit）控制自动策略风险
- **新增**：评估指标反馈闭环——优质策略的参数组合作为"基因"保留，劣质淘汰

## Impact

### 受影响代码
- **前端**：
  - [frontend/src/hooks/useDashboardState.ts](file:///e:/quant_okx/frontend/src/hooks/useDashboardState.ts) — useEffect 依赖修复、getPnlSummary 传参、loading 态
  - [frontend/src/pages/DashboardPage.tsx](file:///e:/quant_okx/frontend/src/pages/DashboardPage.tsx) — loading 展示
  - [frontend/src/pages/MonitoringPage.tsx](file:///e:/quant_okx/frontend/src/pages/MonitoringPage.tsx) — 仓位冲突看板分拆对账/平仓能力、对冲组标注
- **PnL 后端**：
  - [backend/services/pnl_accounting_engine.py](file:///e:/quant_okx/backend/services/pnl_accounting_engine.py) — recompute 无成交返回 None、heartbeat 兜底、行情失败告警、avg_buy_price=0 告警
  - [backend/routers/pnl.py](file:///e:/quant_okx/backend/routers/pnl.py) — get_pnl_summary 增加 strategy_instance_id、跳过全 0 记录
- **归因**：
  - [backend/services/attribution_service.py](file:///e:/quant_okx/backend/services/attribution_service.py) — by_symbol 重构为基于 PnlRecord、三维度统一口径
- **仓位冲突**：
  - [backend/strategies/base_strategy.py](file:///e:/quant_okx/backend/strategies/base_strategy.py) — check_position_conflict 改代数和
  - [backend/routers/monitoring.py](file:///e:/quant_okx/backend/routers/monitoring.py) — position_conflicts 端点改代数和
- **定时研究**：
  - [backend/tests/reports/strategy_research/run_iteration.py](file:///e:/quant_okx/backend/tests/reports/strategy_research/run_iteration.py) — should_start 分支实现
  - [backend/research/qsm_generator.py](file:///e:/quant_okx/backend/research/qsm_generator.py) — 新增 QSModel 生成器

### 受影响 specs
- `fix-pnl-curve-sparse-and-anomaly`（已完成，本 spec B 部分修正其 recompute 全 0 写入的副作用）
- `fix-pnl-realized-unrealized-consistency`（已完成，本 spec B 部分延续）
- `strategy-fundamentals-overhaul`（已完成，本 spec D 部分修正其 position_conflict 绝对值算法）
- `refactor-pnl-accounting-engine`（已完成，本 spec B/C 部分修正其调用方与归因口径）

## ADDED Requirements

### Requirement: 盈亏曲线策略切换响应
系统 SHALL 在用户切换策略列表中的策略时，立即重新请求并展示该策略的盈亏曲线，而非延迟到下个定时刷新。

#### Scenario: 切换策略立即刷新
- **WHEN** 用户在策略列表点击策略 B
- **THEN** selectedStrategyId 变化为 B
- **AND** loadBaseData 立即触发（useEffect 依赖 loadBaseData）
- **AND** PnL 曲线、KPI 卡片、最近交易均展示策略 B 数据
- **AND** 切换期间显示 loading 态

#### Scenario: getPnlSummary 按策略过滤
- **WHEN** 选中策略 B
- **THEN** get_pnl_summary 请求携带 strategy_instance_id=B
- **AND** KPI 卡片显示策略 B 的累计盈亏/未实现/已实现，而非全局汇总

### Requirement: PnL 无成交时不写全 0 记录
系统 SHALL 在策略无成交订单时，不写入全 0 的 PnlRecord，避免污染盈亏曲线与 summary。

#### Scenario: recompute 无成交
- **GIVEN** 策略无任何 filled 订单
- **WHEN** 调用 recompute
- **THEN** 返回 None，不写入 PnlRecord

#### Scenario: 健康检查不反复写全 0
- **GIVEN** 策略运行中无成交
- **WHEN** run_iteration 健康检查
- **THEN** 跳过 recompute 调用（或调用后返回 None 不写库）
- **AND** 不产生全 0 PnlRecord

#### Scenario: 行情获取失败告警
- **GIVEN** OKX API 不可达或代理故障
- **WHEN** _get_current_price 调用失败
- **THEN** 记录 `market_data_unavailable` warning 事件
- **AND** 前端展示"行情获取失败"而非显示 0

### Requirement: 归因分析三维度统一口径
系统 SHALL 使按币种/按策略类型/按时间段三个维度的归因分析基于统一数据源（PnlRecord）与统一口径（realized 累计、unrealized 期末、avg_buy_price 按策略独立后聚合加权）。

#### Scenario: 三维度数据一致
- **GIVEN** 同一账户同一时间段
- **WHEN** 请求 by_symbol / by_strategy_type / by_period
- **THEN** 三者总 realized_pnl 一致（口径统一为 PnlRecord.realized_pnl 累计）
- **AND** 三者总 unrealized_pnl 一致（期末值）
- **AND** by_symbol 含 unrealized_pnl 字段
- **AND** 时间过滤统一用 recorded_at

#### Scenario: by_symbol 基于策略实例聚合
- **GIVEN** 两个策略实例均交易 ETH-USDT-SWAP
- **WHEN** 请求 by_symbol
- **THEN** ETH-USDT-SWAP 的指标 = 策略 A 的 latest PnlRecord + 策略 B 的 latest PnlRecord 聚合
- **AND** avg_buy_price 按两策略独立计算后加权平均
- **AND** 不再直接查 Order 表现场重算

### Requirement: 仓位冲突检测使用代数叠加
系统 SHALL 在计算仓位冲突时使用其他策略虚拟持仓的代数和（带符号），符合"多策略虚拟持仓代数叠加等于真实持仓"的语义。

#### Scenario: 多空对冲不误报
- **GIVEN** 策略 A 持 +5，策略 B 持 -5（完美对冲，真实持仓 0）
- **WHEN** 策略 A 欲平仓 5
- **THEN** others_occupied = -5（代数和）
- **AND** available = 0 - (-5) = 5
- **AND** 5 >= abs(5) 不冲突，返回 True

#### Scenario: 单向持仓正常检测
- **GIVEN** 策略 A 持 +10，策略 B 持 +5（真实持仓 +15）
- **WHEN** 策略 A 欲平仓 10
- **THEN** others_occupied = +5（代数和）
- **AND** available = 15 - 5 = 10
- **AND** 10 >= abs(10) 不冲突，返回 True

#### Scenario: 超真实持仓才冲突
- **GIVEN** 策略 A 持 +10，策略 B 持 +5（真实持仓 +15）
- **WHEN** 策略 A 欲平仓 12
- **THEN** others_occupied = +5
- **AND** available = 15 - 5 = 10
- **AND** 10 < abs(12) 冲突，返回 False 并记录 position_conflict

### Requirement: 定时任务 QSModel 研究闭环
系统 SHALL 使定时研究任务真正生成、验证、启动 QSModel 创新策略，而非仅监控固定基础策略。

#### Scenario: DSL 创新策略生成
- **GIVEN** 研究类型轮换到 N=1（DSL 创新）
- **WHEN** should_start 触发
- **THEN** 生成 QSModelConfig（base_strategy + rules 组合，如 grid + cross_above 暂停 + rebalance_position）
- **AND** 调用 /api/dsl/validate 校验
- **AND** 调用 /api/dsl/dry-run 历史回放预验证
- **AND** 通过后创建 StrategyTemplate + StrategyInstance 并启动

#### Scenario: 回测筛选+实盘
- **GIVEN** 研究类型轮换到 N=2（回测筛选+实盘）
- **WHEN** should_start 触发
- **THEN** 生成多个候选 QSModel
- **AND** 对每个候选调 dry_run 回测（近 30 天）
- **AND** 筛选夏普>1、最大回撤<10% 的候选
- **AND** 启动筛选通过的候选至模拟盘

#### Scenario: 参数 A/B 对比
- **GIVEN** 研究类型轮换到 N=3（参数 A/B）
- **WHEN** should_start 触发
- **THEN** 复制一个已运行策略的 QSModel
- **AND** 用 $params.xxx 变量引用生成不同参数变体（如 fast_period=5 vs 10）
- **AND** 并行启动变体实例

#### Scenario: 风控配置
- **WHEN** 自动生成 QSModel
- **THEN** 配置 risk_filter 段（daily_max_loss、stop_loss、take_profit）
- **AND** 控制自动策略的风险敞口

#### Scenario: 优质策略基因保留
- **WHEN** 策略满 10 天评估
- **THEN** 优质策略的参数组合作为"基因"保留到候选池
- **AND** 劣质策略淘汰，参数组合不再生成

## MODIFIED Requirements

### Requirement: useDashboardState 刷新逻辑
[原内容：挂载时 loadBaseData + 定时刷新]

**修改**：loadBaseData 的 useEffect 依赖改为 `[loadBaseData]`，使 selectedStrategyId/timeRange 变化立即触发刷新；getPnlSummary 传入 strategy_instance_id。

### Requirement: PnL 核算 recompute
[原内容：扫描 filled 订单计算并写入 PnlRecord]

**修改**：无 filled 订单时返回 None 不写入；调用方需处理 None 返回值。

### Requirement: 仓位冲突检测
[原内容：others_occupied 用绝对值之和，available = real_pos - others_occupied]

**修改**：others_occupied 用代数和（带符号），available = real_pos - others_occupied（代数和），is_conflict = available < abs(net_position)。

### Requirement: 归因分析 by_symbol
[原内容：直接查 Order 表按 symbol 分组现场重算]

**修改**：改为基于 PnlRecord，通过 StrategyInstance.symbol 关联聚合各策略实例 latest PnlRecord，与 by_strategy_type/by_period 数据源统一。

## REMOVED Requirements

### Requirement: recompute 无成交时写入全 0 PnlRecord
**Reason**: 全 0 记录污染盈亏曲线与 summary，掩盖真实状态，误导用户以为数据异常
**Migration**: recompute 无成交返回 None；调用方（run_iteration、pnl.py recompute 端点）处理 None；heartbeat_snapshot 无基准时调 recompute 兜底。

### Requirement: position_conflict 用绝对值之和计算 others_occupied
**Reason**: 违背"多策略虚拟持仓代数叠加等于真实持仓"的语义，多空对冲策略被误报冲突
**Migration**: 改用代数和（带符号），与 reconcile_positions 的代数叠加一致。

## 范围说明

### 本 spec 覆盖
- 盈亏曲线策略切换响应（前端 useEffect）
- PnL 为 0 根因修复（recompute/heartbeat/summary/run_iteration）
- 归因分析三维度统一口径（数据源/realized/unrealized/avg_buy_price/时间过滤）
- 仓位冲突改代数叠加（check_position_conflict/端点/看板分拆）
- 定时任务 QSModel 研究闭环（生成器/验证/dry_run/启动/风控/基因）

### 本 spec 不覆盖
- PnL 核算算法的根本重写（仅修正全 0 写入副作用）
- 归因分析新增维度（如按账户、按杠杆）
- QSModel 积木库扩展（当前积木够用，仅利用）
- 仓位冲突的挂单维度（仅考虑已成交 net_position，未考虑 active_orders）

## 优先级

| 优先级 | 部分 | 理由 |
|--------|------|------|
| P0 | A 盈亏曲线切换 | 用户最直接感知，1 行修复 |
| P0 | B PnL 为 0 | 影响所有 PnL 展示，根因修复 |
| P1 | D 仓位冲突代数叠加 | 误报影响多策略运行，算法修正 |
| P1 | C 归因口径统一 | 数据不一致影响决策可信度 |
| P2 | E QSModel 研究闭环 | 工作量大，但关乎产品差异化卖点 |
