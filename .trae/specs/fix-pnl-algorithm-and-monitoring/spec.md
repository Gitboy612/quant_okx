# 盈亏算法与策略监控修复 Spec

## Why
当前盈亏（PnL）计算存在多处算法错误与监控缺陷：未实现盈亏基于「挂单」而非「持仓」计算（失真）、PnL Summary 对时点浮动值跨记录求和（数字放大数百倍）、WebSocket 订单通道未注册回调（实时性退化为 15s 轮询）、每 3s 写一条 PnL 记录导致表膨胀、已实现盈亏未扣手续费、OrderManager 在 asyncio 中混用裸线程（线程不安全）、停止时未实现盈亏强制清零导致曲线断崖、多策略共享账户时权益重复计算、GridStrategy 与 ComposableStrategy 两套未实现盈亏口径不一致。这些问题使盈亏数据完全失真，需统一修复。

## What Changes
- **未实现盈亏算法重构**：改为基于「净持仓」计算，OrderManager 维护累计买入量/卖出量/加权均价，`unrealized_pnl = (current_price - avg_buy_price) × net_position`
- **PnL Summary 汇总修正**：`total_unrealized` 取最新一条记录（与 `total_realized` 口径一致），不再跨记录求和
- **WebSocket 订单回调接入**：`BaseStrategy.start()` 注册 `ws_client.on_order_update` 回调，回调内调用 `order_manager.update_order()`，WS 实时优先、REST 15s 兜底
- **PnL 采样降频**：主循环改为每 60s 写一条 PnL 记录（原 3s/条），并在变化超阈值时才记录；为 `pnl_records` 表的 `(strategy_instance_id, recorded_at)` 增加复合索引
- **已实现盈亏扣手续费**：`cycle_pnl = (卖价 - 买价) × 数量 - 卖单fee - 买单fee`，从 `OrderInfo.fee` 读取并累加到 `realized_pnl`
- **OrderManager 线程安全重构**：移除裸 `threading.Thread`，持久化改为 `asyncio.to_thread`；`_trigger_callbacks` 用 `asyncio.create_task` 替代 `ensure_future`（避免非主线程无 event loop）
- **停止时未实现盈亏保留**：PnlRecord 新增 `is_final` 字段，停止时保留最后 unrealized_pnl 值（不再强制清零），仅标记终态
- **grid_idx=0 边界防护**：grid_idx=0 出现卖单成交时拒绝计算 realized_pnl 并记录告警事件
- **多策略权益隔离**：`_initial_equity` 改为策略启动时账户权益快照，PnL 仅记录该策略增量，`/api/pnl/summary` 支持按 `strategy_instance_id` 聚合
- **未实现盈亏口径统一**：GridStrategy 本地计算改用持仓口径（与 ComposableStrategy 风控的 `get_positions().upl` 一致），合约用 OKX 接口、现货用本地净持仓
- **BREAKING**: `PnlRecord` 表新增 `is_final` 列（需迁移）；`/api/pnl/summary` 响应结构新增 `by_strategy` 字段

## Impact
- Affected specs: `fix-pnl-positions-proxy`（盈亏曲线前端展示依赖此处的后端数据修正）、`revamp-pnl-curve-and-splash`（曲线连续性依赖停止时保留 unrealized）
- Affected code:
  - 后端核心: `backend/strategies/base_strategy.py`, `backend/strategies/grid_strategy.py`, `backend/strategies/trend_strategy.py`, `backend/strategies/advanced_grid_hedge_strategy.py`
  - 订单管理: `backend/services/order_manager.py`
  - WebSocket: `backend/services/okx_ws_client.py`, `backend/strategies/base_strategy.py`
  - 数据模型: `backend/models/pnl.py`（新增 `is_final` 字段）
  - API: `backend/routers/pnl.py`（修正 summary 逻辑）
  - DSL: `backend/dsl/executor.py`（风控口径统一）

## ADDED Requirements

### Requirement: 基于持仓的未实现盈亏计算
系统 SHALL 基于实际持仓（非挂单）计算未实现盈亏，OrderManager SHALL 维护净持仓状态。

#### Scenario: 网格买单成交后未平仓
- **WHEN** 网格买单成交（买入 0.01 BTC @ 40000），当前价 41000
- **THEN** 净持仓 = 0.01，加权均价 = 40000
- **AND** unrealized_pnl = (41000 - 40000) × 0.01 = 10 USDT

#### Scenario: 网格卖单成交后平仓
- **WHEN** 网格卖单成交（卖出 0.01 BTC @ 41000），此前持仓 0.01 @ 40000
- **THEN** 净持仓归零，unrealized_pnl = 0
- **AND** realized_pnl += (41000 - 40000) × 0.01 - 买fee - 卖fee

#### Scenario: 挂单未成交不计入浮盈
- **WHEN** 存在 live 状态买单但未成交
- **THEN** 该挂单不参与 unrealized_pnl 计算
- **AND** 仅已成交未平仓的持仓参与计算

#### Scenario: 合约持仓用 OKX 接口
- **WHEN** 交易对含 `-SWAP`（合约）
- **THEN** unrealized_pnl 优先取 `get_positions().upl`
- **AND** 本地净持仓作为兜底

### Requirement: PnL Summary 汇总修正
系统 SHALL 对未实现盈亏取最新时点值，不再跨记录求和。

#### Scenario: 单账户多记录汇总
- **WHEN** 调用 `/api/pnl/summary?account_id=X`
- **THEN** `total_realized_pnl` = 最新记录的 realized_pnl（累计值）
- **AND** `total_unrealized_pnl` = 最新记录的 unrealized_pnl（时点值）
- **AND** `total_pnl` = total_realized_pnl + total_unrealized_pnl
- **AND** 不再对 500 条记录的 unrealized_pnl 求和

#### Scenario: 按策略聚合
- **WHEN** 响应包含 `by_strategy` 字段
- **THEN** 每个策略实例独立汇总其 realized/unrealized
- **AND** 多策略 PnL 之和 = 账户总 PnL

### Requirement: WebSocket 订单回调接入
系统 SHALL 在策略启动时注册 WebSocket 订单更新回调，实现实时订单状态同步。

#### Scenario: WS 推送订单成交
- **WHEN** OKX WS 推送订单 state=filled
- **THEN** 回调调用 `order_manager.update_order(ordId, state="filled", fillPx, fillSz, fee)`
- **AND** 触发 `_on_order_filled` 处理反向挂单与 realized_pnl 累加
- **AND** 不等待 REST 15s 轮询

#### Scenario: WS 断线回退 REST
- **WHEN** WS 连接断线超过 30s
- **THEN** `fallback_to_rest` 返回 True
- **AND** 主循环 REST 轮询继续兜底订单状态同步

### Requirement: PnL 采样降频
系统 SHALL 降低 PnL 记录写入频率，避免表膨胀。

#### Scenario: 定时采样
- **WHEN** 策略主循环运行
- **THEN** 每 60s 写一条 PnlRecord（原 3s/条）
- **AND** 单策略单日记录数 ≤ 1440 条（原 ~28800 条）

#### Scenario: 变化阈值触发
- **WHEN** 距上次记录不足 60s 但 total_pnl 变化超过 1%
- **THEN** 额外写入一条 PnlRecord
- **AND** 避免重要波动遗漏

### Requirement: 已实现盈亏扣除手续费
系统 SHALL 在计算已实现盈亏时扣除双边手续费。

#### Scenario: 网格闭环扣费
- **WHEN** 卖单成交完成网格闭环
- **THEN** `cycle_pnl = (卖价 - 买价) × 数量 - 卖单fee - 买单fee`
- **AND** 买单fee 从该闭环对应买单的 OrderInfo.fee 读取
- **AND** 卖单fee 从当前卖单的 OrderInfo.fee 读取

### Requirement: OrderManager 线程安全
系统 SHALL 移除裸线程持久化，改为 asyncio 原生方式。

#### Scenario: 订单持久化
- **WHEN** `add_order` 或 `update_order` 触发持久化
- **THEN** 使用 `asyncio.to_thread(self._persist_to_db, order)` 调度
- **AND** 不再创建 `threading.Thread`

#### Scenario: 回调协程调度
- **WHEN** 订单状态变化触发回调且回调返回协程
- **THEN** 使用 `asyncio.create_task(result)` 调度
- **AND** 不使用 `asyncio.ensure_future`（避免非主线程无 event loop）

### Requirement: 停止时保留未实现盈亏
系统 SHALL 在策略停止时保留最后的未实现盈亏值，不再强制清零。

#### Scenario: 停止记录
- **WHEN** 策略停止
- **THEN** 写入终态 PnlRecord，`is_final=True`
- **AND** `unrealized_pnl` 保留最后一次 tick 的值（非 0）
- **AND** `realized_pnl` 取最新累计值

#### Scenario: 重启恢复
- **WHEN** 策略重启
- **THEN** 从最近一条 `is_final=True` 或最新记录恢复 realized_pnl
- **AND** PnL 曲线无断崖

### Requirement: grid_idx 边界防护
系统 SHALL 对 grid_idx=0 的卖单成交做边界防护。

#### Scenario: grid_idx=0 卖单成交
- **WHEN** 卖单成交且匹配到 grid_idx=0
- **THEN** 拒绝计算 realized_pnl
- **AND** 记录 `order_warn` 事件：「grid_idx=0 出现卖单成交，跳过 realized 计算」
- **AND** 仍执行反向买单挂单

### Requirement: 未实现盈亏口径统一
系统 SHALL 统一 GridStrategy 与 ComposableStrategy 的未实现盈亏计算口径。

#### Scenario: GridStrategy 本地计算
- **WHEN** GridStrategy 主循环计算 unrealized_pnl
- **THEN** 合约用 `get_positions().upl`
- **AND** 现货用本地净持仓 × (当前价 - 加权均价)

#### Scenario: ComposableStrategy 风控
- **WHEN** ComposableStrategy 执行 `_get_unrealized_pnl_ratio`
- **THEN** 与 GridStrategy 本地口径一致（均用 OKX positions 接口或本地净持仓）

## MODIFIED Requirements

### Requirement: 多策略权益隔离
系统 SHALL 按策略实例隔离 PnL 计算，避免共享账户时权益重复。

- `_initial_equity` 改为策略启动时账户权益快照
- PnL 仅记录该策略产生的增量（realized + unrealized）
- `/api/pnl/summary` 响应新增 `by_strategy` 字段，按 strategy_instance_id 聚合

#### Scenario: 两策略共享账户
- **WHEN** 账户 A 同时运行策略 X 和策略 Y
- **THEN** 策略 X 的 PnL 仅反映 X 的交易盈亏
- **AND** 策略 Y 的 PnL 仅反映 Y 的交易盈亏
- **AND** X.PnL + Y.PnL ≈ 账户 A 总盈亏变化

## REMOVED Requirements
无。
