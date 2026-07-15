# 策略资金·杠杆·仓位隔离与响应性重构 Spec

## Why

项目第一阶段（`monthly-continuous-improvement`，已完成）补齐了功能广度，但用户在实盘运行中发现**交易内核**仍有根本性短板，导致对产品竞争力产生迷茫：

1. **网格策略响应慢**：买单成交后卖单下单迟缓、突发大单后反应迟钝。根因：主循环 `await asyncio.sleep(3)` 过长 + 成交回调内串行 `client.place_order` 单笔下单经代理放大延迟 + WebSocket 成交事件未充分利用。
2. **仓位追踪算法薄弱**：
   - 策略无法设置投入资金上限（当前仅按账户总权益+固定 `order_qty`，无预算硬约束）；
   - 合约无杠杆设置（`set_leverage` API 未集成，`lever` 参数缺失）；
   - **多策略同品种（如多个 ETH-SWAP 策略）各自盈亏是否正确隔离从未被验证**——OKX 同账户同品种共享真实持仓，单策略 PnL 引擎按 `strategy_instance_id` 聚合订单算出的是「虚拟持仓」，但真实仓位是所有策略持仓之和，隔离从未对账，存在归因错误与强平风险。
3. **对竞品迷茫**：与 FMZ/Coinrule 对比缺乏清晰差异化卖点。

用户希望制定一个**可连续不间断执行**的月度计划，系统持续运行，持续「测试→发现漏洞→修复→补全→验证」闭环，账户内可执行任何需要的操作。

## What Changes

### 第一周：策略资金与杠杆管理（Capital & Leverage）
- **新增**：策略实例 `investment_amount`（投入资金上限）参数，前端可配置，作为策略可动用资金硬上限
- **新增**：合约 `lever`（杠杆倍数）与 `td_mode`（持仓模式 cross/isolated）参数，集成 OKX `set_leverage` API
- **新增**：下单数量自动计算 `qty = investment_amount × lever / price`，并受 `max_position_value` 硬约束（不超过投入资金×杠杆）
- **新增**：保证金占用率与强平价监控（`get_position` → `margin`/`liq_px`），逼近阈值时告警/拒单
- **BREAKING**：策略参数 schema 增加 `investment_amount` / `lever` / `td_mode` 字段；旧实例启动时迁移默认值（lever=1, td_mode=cross, investment_amount=账户可用余额）

### 第二周：仓位隔离与多策略归因验证（Position Isolation）
- **新增**：虚拟子仓位账本（per-strategy virtual position ledger），与交易所真实仓位对账
- **新增**：多策略同品种持仓上限冲突检测（A 想平仓但真实仓位已被 B 占用时拒绝/告警）
- **新增**：多策略同品种 PnL 隔离 E2E 验证套件（2+ 策略跑同一 ETH-SWAP，各自 PnL 可独立核对）
- **新增**：仓位对账报告（虚拟持仓之和 vs 真实持仓差异 > 容差时记录事件 + 告警）

### 第三周：网格响应性重构（Grid Responsiveness）
- **重构**：买单成交后卖单改为「预挂 + 批量」模式，减少串行 REST 往返
- **优化**：主循环 sleep 从 3s 降为事件驱动（WebSocket fill 为快速路径，REST 仅兜底，间隔可配且默认降至 1s）
- **新增**：成交→补单延迟度量（`fill_ts` → `place_ts`）与告警（latency > 阈值记录 `order_latency` 事件）
- **新增**：突发行情检测（短时价格波动 > 阈值）触发快速补单/撤单路径
- **新增**：maker-only / post-only 下单选项探索（减少被吃单后补单延迟）

### 第四周：差异化定位与连续测试闭环（Positioning & Continuous Test Loop）
- **新增**：产品差异化定位文档（vs FMZ/Coinrule：本地优先隐私 / 真实仓位隔离归因 / 可视化策略构建 / 回测即实盘参数对齐）
- **新增**：每日模拟盘连续回归套件（跑 W1-W3 全部能力，生成报告，检测退化），可长期不间断运行
- **新增**：延迟与资金健康看板（成交延迟 P50/P95、保证金占用率、仓位隔离差异、投入资金使用率）
- **完善**：基于每日测试报告持续优化（每周迭代修复回归项，形成长效闭环）

## Impact

### 受影响代码
- **策略核心**：
  - [backend/strategies/base_strategy.py](file:///e:/quant_okx/backend/strategies/base_strategy.py) — 资金/杠杆参数、虚拟仓位账本、延迟度量基类
  - [backend/strategies/grid_strategy.py](file:///e:/quant_okx/backend/strategies/grid_strategy.py) — 响应性重构、批量补单、事件驱动循环
  - [backend/strategies/trend_strategy.py](file:///e:/quant_okx/backend/strategies/trend_strategy.py) — 资金/杠杆参数对齐
- **PnL 与归因**：
  - [backend/services/pnl_accounting_engine.py](file:///e:/quant_okx/backend/services/pnl_accounting_engine.py) — 虚拟仓位对账、多策略隔离校验
  - [backend/services/attribution_service.py](file:///e:/quant_okx/backend/services/attribution_service.py) — 多策略同品种归因验证
- **OKX 客户端**：
  - [backend/services/okx/trade.py](file:///e:/quant_okx/backend/services/okx/trade.py) — `set_leverage` 集成
  - [backend/services/okx/account.py](file:///e:/quant_okx/backend/services/okx/account.py) — 保证金/强平价查询
  - [backend/services/order_manager.py](file:///e:/quant_okx/backend/services/order_manager.py) — 成交时间戳记录
- **前端**：
  - [frontend/src/components/strategies/InstanceFormModal.tsx](file:///e:/quant_okx/frontend/src/components/strategies/InstanceFormModal.tsx) — 投入资金/杠杆表单
  - [frontend/src/pages/MonitoringPage.tsx](file:///e:/quant_okx/frontend/src/pages/MonitoringPage.tsx) — 延迟/资金健康看板
- **测试与脚本**：
  - [backend/tests/e2e/](file:///e:/quant_okx/backend/tests/e2e/) — 多策略同品种隔离验证套件
  - [scripts/daily_regression.py](file:///e:/quant_okx/scripts/daily_regression.py) — 扩展为连续回归闭环

### 受影响 specs
- `monthly-continuous-improvement`（已完成，本 spec 为其第二阶段延续）
- `refactor-pnl-accounting-engine`（虚拟仓位对账扩展其核算范围）
- `fix-grid-direction-and-fill-maintenance`（响应性重构在其基础上深化）

## ADDED Requirements

### Requirement: 策略投入资金上限
系统 SHALL 允许用户为每个策略实例设置 `investment_amount`（投入资金上限），策略下单总名义价值不得超过 `investment_amount × lever`。

#### Scenario: 投入资金硬约束
- **WHEN** 策略计算下单数量
- **THEN** qty = investment_amount × lever / price
- **AND** 当前持仓名义价值 + 新单名义价值 ≤ investment_amount × lever
- **AND** 超出时拒单并记录 `capital_limit` 事件

#### Scenario: 旧实例迁移
- **WHEN** 不含 investment_amount 的旧策略实例启动
- **THEN** 自动迁移默认值（investment_amount=账户可用余额，lever=1，td_mode=cross）
- **AND** 记录 `param_migrated` 事件

### Requirement: 合约杠杆设置
系统 SHALL 支持合约策略设置杠杆倍数与持仓模式，通过 OKX `set_leverage` API 生效。

#### Scenario: 设置杠杆
- **WHEN** 用户在策略实例表单选择 lever=10, td_mode=isolated
- **THEN** 策略启动时调用 OKX set_leverage(instId, lever=10, mgnMode=isolated, posSide 视策略)
- **AND** 失败时记录 `leverage_set_failed` 事件并阻止策略启动

#### Scenario: 保证金监控
- **WHEN** 策略运行中保证金占用率 > 80%
- **THEN** 记录 `margin_warning` 事件并触发通知
- **AND** 占用率 > 95% 时拒单并记录 `margin_critical`

### Requirement: 虚拟仓位隔离与对账
系统 SHALL 为每个策略实例维护独立的虚拟仓位账本，并定期与交易所真实仓位对账。

#### Scenario: 多策略同品种 PnL 隔离
- **WHEN** 两个策略实例 A、B 均交易 ETH-SWAP
- **THEN** A 的 PnL 仅基于 A 的订单计算，B 的 PnL 仅基于 B 的订单计算
- **AND** 各自虚拟持仓独立累加
- **AND** 两者虚拟持仓之和应等于交易所真实持仓（容差内）

#### Scenario: 仓位对账异常
- **WHEN** 虚拟持仓之和与真实持仓差异 > 容差（如 0.01 ETH）
- **THEN** 记录 `position_mismatch` 事件含差异详情
- **AND** 触发告警通知

#### Scenario: 持仓冲突检测
- **WHEN** 策略 A 欲平仓但真实仓位已被策略 B 占用导致无法平仓
- **THEN** 拒绝 A 的平仓操作或记录 `position_conflict` 事件
- **AND** 前端仓位看板标注冲突

### Requirement: 网格策略响应性
系统 SHALL 将网格策略成交→补单延迟降至可度量、可告警水平，主循环改为事件驱动。

#### Scenario: 快速补单
- **WHEN** 买单通过 WebSocket 成交事件触发
- **THEN** 对应卖单在 500ms 内完成下单（P95）
- **AND** 延迟超过阈值（默认 2s）记录 `order_latency` 事件

#### Scenario: 突发行情快速响应
- **WHEN** 短时（如 5s）价格波动 > 配置阈值（如 1%）
- **THEN** 触发快速补单/撤单路径
- **AND** 主循环 sleep 临时降至 0.5s 持续 N 秒

### Requirement: 连续测试闭环
系统 SHALL 提供可长期不间断运行的每日模拟盘回归套件，覆盖资金/杠杆/隔离/响应全部能力并检测退化。

#### Scenario: 每日连续回归
- **WHEN** 每日定时触发连续回归套件
- **THEN** 自动启动多策略实例（含同品种多策略）
- **AND** 验证资金约束、杠杆生效、仓位隔离、补单延迟
- **AND** 生成报告（通过率/延迟P95/隔离差异/资金使用率/退化项）

#### Scenario: 退化检测
- **WHEN** 某指标相较前一日退化超阈值（如延迟 P95 上升 50%）
- **THEN** 报告标记退化项
- **AND** 自动创建修复任务至 tasks.md

## MODIFIED Requirements

### Requirement: 网格策略主循环（来自 fix-grid-direction-and-fill-maintenance）
[原内容：网格匹配容差 + 状态恢复]

**修改**：主循环由固定 3s 轮询改为事件驱动（WebSocket fill 优先，REST 兜底间隔可配默认 1s），成交回调内补单改批量预挂模式。

### Requirement: PnL 核算引擎（来自 refactor-pnl-accounting-engine）
[原内容：recompute + incremental_update 按 strategy_instance_id 核算]

**修改**：新增虚拟仓位对账接口 `reconcile_positions(account_id, symbol)`，对比策略虚拟持仓之和与交易所真实持仓，差异超容差记录事件。

## REMOVED Requirements

### Requirement: 策略直接使用账户总权益下单
**Reason**: 无投入资金上限会导致单策略占用全部账户资金，多策略并存时资金冲突不可控
**Migration**: 改为 per-strategy investment_amount 硬约束 + 账户可用余额校验

## 范围说明

### 本 spec 覆盖
- 资金上限、杠杆、持仓模式参数化
- 虚拟仓位账本与真实仓位对账
- 多策略同品种 PnL 隔离验证
- 网格成交→补单响应性重构与延迟度量
- 差异化定位文档
- 可长期运行的连续测试闭环

### 本 spec 不覆盖
- 多账户聚合（当前单账户多策略即可验证隔离）
- 跨交易所仓位对冲
- AI 策略生成
- 移动端原生 App

## 月度交付里程碑

| 周次 | 主题 | 交付物 | 验收标准 |
|------|------|--------|----------|
| W1 | 资金与杠杆 | investment_amount + lever + set_leverage + 保证金监控 | 策略可设投入资金，合约可设杠杆，超限拒单 |
| W2 | 仓位隔离 | 虚拟仓位账本 + 对账 + 多策略隔离 E2E | 同品种多策略各自 PnL 可核对，差异告警 |
| W3 | 响应性 | 事件驱动循环 + 批量补单 + 延迟度量 | 补单延迟 P95 < 2s，突发行情快速路径 |
| W4 | 定位与闭环 | 差异化文档 + 连续回归套件 + 健康看板 | 每日报告可生成，退化可检测 |

## 连续运行说明

本 spec 设计为可**长期不间断执行**：W4 的连续回归套件在月度计划结束后仍持续每日运行，检测退化并自动派生修复任务，形成长效质量闭环。用户保持系统运行即可。
