# 盈亏核算引擎重构 Spec

## Why

当前盈亏（PnL）计算完全下放到每个策略的 `execute()` 循环里"自治"：GridStrategy / TrendStrategy / AdvancedGridHedgeStrategy 各自计算三口径并写库，而 **ComposableStrategy（QS-Model 可拼接策略）完全没有调用 `record_pnl`**，导致运行一晚盈亏曲线不绘制。ArbitrageStrategy 则是占位传 0。同时合约下单时 `sz` 单位（张数 vs 目标币 vs 稳定币）未在系统层显式表达，数据库里 `quantity=10` 实际只成交了 1 ETH，用户在 OKX App 看到的交易量与系统预期不符。

本次重构将 PnL 核算从"策略自治"升级为"系统层统一核算引擎"，支持全量核算（掌柜算法，基于 order 表精确对账）与增量核算（基于已核算标记快速处理新增成交），并修正合约交易量单位在数据模型、下单、核算三处的统一表达。

## What Changes

### A. 新增 PnL 核算引擎（系统视角）
- 新增 `backend/services/pnl_accounting_engine.py`，独立于策略运行
- 实现**全量核算**：基于 order 表，过滤 canceled，只看 filled，按 buy/sell 分类计算总盈亏、已实现盈亏、未实现盈亏
- 实现**增量核算**：仅处理上次核算后新增的 filled 订单，避免全表扫描
- 实现**定时快照**：StrategyEngine 启动后台任务，按固定间隔对 running 策略采样写 PnlRecord

### B. Order 表扩展（核算支撑 + 合约单位）
- Order 表新增字段：`pnl_accounted: Boolean`（是否已被增量核算处理，默认 False）
- Order 表新增字段：`ct_val: Float`（合约面值，如 0.01 BTC/张，现货为 1）
- Order 表新增字段：`ct_type: String`（合约类型：swap/forward/option，现货为 null）
- Order 表新增字段：`settle_ccy: String`（结算币种，如 USDT）
- Order 表新增字段：`actual_qty: Float`（实际交易量 = sz × ct_val，核算时直接使用）
- 新增索引：`(strategy_instance_id, status, pnl_accounted)` 支撑增量查询

### C. 合约交易量单位优化
- 新增 instrument 缓存服务：首次下单时调用 `get_instruments` 获取 `ctVal`/`ctType`/`settleCcy`/`tickSz`，按 instId 缓存
- 下单路径统一注入：`OrderManager.add_order` 自动从缓存填充 ct_val/ct_type/settle_ccy/actual_qty
- 前端策略设置：合约类型增加"交易量单位"选择器（张数 / 目标币 / 稳定币），提交时统一转换为 OKX sz（张数）

### D. 策略层 PnL 调用迁移
- 移除各策略 `execute()` 循环中的 `record_pnl` / `_should_record_pnl` 调用（保留 `record_final_pnl` 用于停止时写终值）
- ComposableStrategy 主循环移除 PnL 计算职责（本就无此逻辑，明确声明）
- 策略仅需维护 `add_realized_pnl`（成交回调时累加），供实时显示用；权威值以核算引擎为准

### E. API 与前端调整
- `/api/pnl/recompute/{strategy_id}` POST：手动触发全量核算（对账用）
- `/api/pnl/snapshot` POST：手动触发一次快照写入
- 前端仪表盘 PnL 曲线轮询保持不变（仍读 PnlRecord 表）
- 前端策略设置页合约交易量单位选择器

## Impact

- **Affected specs**：
  - `fix-pnl-algorithm-and-monitoring`（采样降频逻辑迁移到引擎层）
  - `fix-pnl-realized-unrealized-consistency`（口径由引擎统一定义）
  - `refactor-order-management`（OrderManager 增加 instrument 注入）
  - `add-composable-strategy-dsl`（ComposableStrategy 不再需要自己算 PnL）

- **Affected code**：
  - `backend/services/pnl_accounting_engine.py`（新增）
  - `backend/services/instrument_cache.py`（新增）
  - `backend/models/order.py`（新增字段）
  - `backend/services/strategy_engine.py`（启动采样后台任务）
  - `backend/services/order_manager.py`（add_order 注入合约元数据）
  - `backend/strategies/base_strategy.py`（移除 record_pnl，保留 record_final_pnl）
  - `backend/strategies/grid_strategy.py`（移除主循环 PnL 计算）
  - `backend/strategies/trend_strategy.py`（同上）
  - `backend/strategies/advanced_grid_hedge_strategy.py`（同上）
  - `backend/routers/pnl.py`（新增 recompute/snapshot 端点）
  - `frontend/src/pages/StrategiesPage.tsx`（交易量单位选择器）

## ADDED Requirements

### Requirement: PnL 核算引擎
系统 SHALL 提供独立于策略运行的 PnL 核算引擎 `PnlAccountingEngine`，负责所有策略实例的盈亏计算与 PnlRecord 写入。

#### Scenario: 全量核算（掌柜算法）
- **GIVEN** 某策略实例已有 N 笔 filled 订单
- **WHEN** 调用 `recompute(strategy_instance_id)`
- **THEN** 查询该策略所有 status='filled' 的订单（忽略 canceled）
- **AND** 按实际成交价计算：sell_total = Σ(sell.fillPx × sell.actual_qty)，buy_total = Σ(buy.fillPx × buy.actual_qty)
- **AND** total_fee = Σ(所有 filled 订单的 fee)
- **AND** total_pnl = sell_total - buy_total - total_fee
- **AND** matched_qty = min(Σbuy.actual_qty, Σsell.actual_qty)
- **AND** realized_pnl = matched_qty × (avg_sell_px - avg_buy_px) - matched_qty × avg_fee_per_unit
- **AND** unrealized_pnl = total_pnl - realized_pnl
- **AND** 写入一条 PnlRecord，并将该策略所有 filled 订单标记 pnl_accounted=True

#### Scenario: 增量核算
- **GIVEN** 某策略实例上次核算后新增了 M 笔 filled 订单
- **WHEN** 调用 `incremental_update(strategy_instance_id)`
- **THEN** 查询 status='filled' AND pnl_accounted=False 的订单
- **AND** 读取上次 PnlRecord 的累计值（realized_pnl, net_position, avg_buy_price）
- **AND** 仅用新增订单更新累计值
- **AND** 写入新 PnlRecord，并将新增订单标记 pnl_accounted=True
- **AND** 若无新增订单，不写入（避免空记录）

#### Scenario: 定时快照
- **GIVEN** StrategyEngine 已启动且有 running 策略
- **WHEN** 后台采样任务触发（间隔 60s）
- **THEN** 对每个 running 策略调用 incremental_update
- **AND** 若 unrealized_pnl 变化超过阈值或距离上次写入超过 60s，则写入 PnlRecord
- **AND** 策略停止时调用 record_final_pnl 写入终值

### Requirement: Instrument 元数据缓存
系统 SHALL 提供 instrument 元数据缓存，按 instId 缓存合约面值（ctVal）、合约类型（ctType）、结算币种（settleCcy）、tickSz。

#### Scenario: 首次下单获取元数据
- **GIVEN** 某 instId 首次出现在下单请求中
- **WHEN** OrderManager.add_order 被调用
- **THEN** 从缓存查询，未命中则调用 `get_instruments(instType, instId)`
- **AND** 缓存结果并填充到 Order 的 ct_val/ct_type/settle_ccy 字段
- **AND** 计算 actual_qty = float(sz) × ct_val（合约）或 float(sz)（现货）

#### Scenario: 合约面值缺失兜底
- **GIVEN** instrument 接口返回空或网络异常
- **WHEN** 填充 ct_val
- **THEN** ct_val 默认为 1.0（视为现货口径），记录 warn 事件
- **AND** 不阻断下单流程

### Requirement: 合约交易量单位选择
前端策略设置页 SHALL 在合约类型（symbol 含 -SWAP）时显示"交易量单位"选择器，支持张数 / 目标币 / 稳定币三种输入，提交时统一转换为 OKX sz（张数）。

#### Scenario: 以目标币输入
- **GIVEN** 用户选择 ETH-USDT-SWAP，输入交易量 1 ETH，单位选"目标币"
- **WHEN** 提交策略参数
- **THEN** 查询 instrument 获取 ctVal=0.1（假设）
- **AND** sz = 1 / 0.1 = 10 张
- **AND** 数据库 order_qty 存储原始输入 1，params.sz_fields 存储 {input: 1, unit: "target_ccy", ct_val: 0.1, sz: 10}

#### Scenario: 以稳定币输入
- **GIVEN** 用户选择 BTC-USDT-SWAP，输入交易量 100 USDT，单位选"稳定币"
- **WHEN** 提交策略参数
- **THEN** sz = 100 / current_price / ct_val（需实时价格）
- **AND** 若价格获取失败，返回错误提示"无法获取当前价格，请改用张数或目标币"

## MODIFIED Requirements

### Requirement: 策略 PnL 计算职责
策略类 SHALL 不再自行计算 unrealized_pnl / total_pnl / equity，仅保留 `add_realized_pnl` 供成交回调累加（用于实时显示，非权威值）。权威 PnL 数据由 PnlAccountingEngine 统一写入。

策略停止/暂停时 SHALL 调用 `record_final_pnl`（读取最新 PnlRecord 保留 realized 和 unrealized，标记 is_final=True）。

### Requirement: OrderManager 持仓跟踪
OrderManager 的净持仓跟踪 SHALL 基于 `actual_qty`（实际交易量）而非原始 `sz`，以正确处理合约张数与现货数量的差异。

### Requirement: PnL Summary API
`/api/pnl/summary` 的 unrealized_pnl 取值 SHALL 来自 PnlAccountingEngine 写入的最新 PnlRecord（基于订单全量核算），不再依赖策略运行时计算。

## REMOVED Requirements

### Requirement: 策略主循环 record_pnl 调用
**Reason**: PnL 计算职责已迁移到 PnlAccountingEngine 统一处理，策略主循环不再需要自行计算三口径并写库。
**Migration**: 
- GridStrategy: 移除 [grid_strategy.py:338-369] 的 unrealized 计算 + record_pnl 块
- TrendStrategy: 移除 [trend_strategy.py:143-161] 的同上块
- AdvancedGridHedgeStrategy: 移除 [advanced_grid_hedge_strategy.py:108-114] 的同上块
- BaseStrategy: 保留 `_should_record_pnl` / `record_pnl` / `record_final_pnl` 方法供引擎复用，但策略不再主动调用前两者

### Requirement: ComposableStrategy 期望 on_tick 写 PnL
**Reason**: ComposableStrategy 从未实现 PnL 写入，base_block.on_tick 默认空实现。此职责已由引擎层采样任务接管。
**Migration**: 无需修改 ComposableStrategy，引擎层采样任务会自动覆盖所有 running 策略。
