# 数据维护菜单 Spec

## Why
当前系统缺少数据维护入口：历史遗留的交易记录、PnL 记录、策略事件无法批量清理；策略停止后未实现盈亏不清零导致仪表盘显示陈旧数据；总权益/盈亏出现偏差时无校正手段。错误日志还暴露了网络异常时策略循环疯狂重试（一分钟内查询几十个订单）无退避的系统逻辑问题。

## What Changes
- 新增"数据维护"菜单（前端面板 + 后端 `/api/maintenance/*` 端点），提供数据清理与数据校正两类操作
- **数据清理**：盈亏清零、清理 PnL 记录、清理订单记录、清理策略事件（支持按策略/时间范围筛选）
- **数据校正**：总权益校正（拉 OKX 真实余额）、未实现盈亏校正（已停止策略清零）、已实现盈亏校正（按历史成交订单重算）
- **系统逻辑修复**（一并处理日志暴露的问题）：
  - 策略停止/暂停/错误退出时写一条 `unrealized_pnl=0` 的最终 PnL 记录
  - 服务重启孤儿清理时为被重置的实例写 `unrealized_pnl=0` 的 PnL 记录
  - 策略主循环网络异常时指数退避（上限 60s），避免疯狂重试
- 所有维护操作写入 `strategy_events` 表留痕（`event_type="manual_correction"` / `"data_cleanup"`）

## Impact
- Affected specs: `fix-pnl-positions-proxy`（PnL 写入语义扩展）、`refactor-order-management`（订单清理）
- Affected code:
  - 后端新增: `backend/routers/maintenance.py`, `backend/services/maintenance_service.py`
  - 后端修改: `backend/strategies/base_strategy.py`（停止时写清零记录）、`backend/strategies/grid_strategy.py`（网络退避）、`backend/main.py`（孤儿清理写 PnL）
  - 前端新增: `frontend/src/api/maintenance.ts`
  - 前端修改: `frontend/src/pages/SettingsPage.tsx`（增加数据维护面板）

## ADDED Requirements

### Requirement: 数据维护菜单
系统 SHALL 在设置页面提供"数据维护"面板，包含数据清理与数据校正两组操作。

#### Scenario: 用户进入数据维护面板
- **WHEN** 用户进入设置页面
- **THEN** 在代理面板与密码修改面板之间显示"数据维护"面板
- **AND** 面板分为"数据清理"与"数据校正"两个区块
- **AND** 每个操作前显示策略/账户选择器与可选时间范围
- **AND** 清理类操作显示红色危险按钮，校正类操作显示青色按钮
- **AND** 所有破坏性操作需二次确认

### Requirement: 盈亏清零
系统 SHALL 支持为指定账户或策略写入一条"清零"PnL 记录。

#### Scenario: 用户对账户盈亏清零
- **WHEN** 用户选择账户并点击"盈亏清零"
- **THEN** 系统从 OKX 拉取该账户真实 `totalEq`
- **AND** 写入一条 `PnlRecord`：`unrealized_pnl=0, realized_pnl=0, equity=真实totalEq, account_id=该账户, strategy_instance_id=NULL`
- **AND** 写入一条 `StrategyEvent`（`event_type="manual_correction"`, `message="盈亏清零"`）
- **AND** 返回清零后的状态

#### Scenario: 用户对策略盈亏清零
- **WHEN** 用户选择已停止的策略并点击"盈亏清零"
- **THEN** 系统写入一条 `PnlRecord`：`unrealized_pnl=0, realized_pnl=0, equity=该策略最新记录的equity, strategy_instance_id=该策略`
- **AND** 若策略正在运行则拒绝并提示"请先停止策略"

### Requirement: 清理历史 PnL 记录
系统 SHALL 支持按策略或时间范围批量删除 PnL 记录。

#### Scenario: 用户清理指定策略的 PnL 记录
- **WHEN** 用户选择策略并点击"清理 PnL 记录"
- **THEN** 系统删除该策略的所有 `PnlRecord`（按 `strategy_instance_id` 过滤）
- **AND** 返回删除的记录数量
- **AND** 写入一条 `StrategyEvent`（`event_type="data_cleanup"`）

#### Scenario: 用户按时间范围清理 PnL 记录
- **WHEN** 用户选择时间范围并点击"清理 PnL 记录"
- **THEN** 系统删除该时间范围内的所有 `PnlRecord`
- **AND** 返回删除的记录数量

### Requirement: 清理历史订单记录
系统 SHALL 支持按策略或状态批量删除订单记录。

#### Scenario: 用户清理指定策略的订单记录
- **WHEN** 用户选择策略并点击"清理订单记录"
- **THEN** 系统删除该策略的所有 `Order`（按 `strategy_instance_id` 过滤）
- **AND** 返回删除的记录数量

#### Scenario: 用户清理已结束状态的订单
- **WHEN** 用户选择"清理已成交/已撤销订单"
- **THEN** 系统删除 `status in ('filled', 'canceled')` 的订单
- **AND** 保留 `live` 状态订单

### Requirement: 清理策略事件
系统 SHALL 支持按策略批量删除策略事件。

#### Scenario: 用户清理指定策略的事件
- **WHEN** 用户选择策略并点击"清理事件"
- **THEN** 系统删除该策略的所有 `StrategyEvent`（按 `strategy_instance_id` 过滤）
- **AND** 返回删除的记录数量

### Requirement: 总权益校正
系统 SHALL 支持从 OKX 拉取真实总权益并写入校正记录。

#### Scenario: 用户校正总权益
- **WHEN** 用户选择账户并点击"校正总权益"
- **THEN** 系统调用 OKX `/api/v5/account/balance` 获取真实 `totalEq`
- **AND** 读取该账户最新的 `PnlRecord`，保留其 `unrealized_pnl` 与 `realized_pnl`
- **AND** 写入新 `PnlRecord`：`equity=真实totalEq, unrealized_pnl=保留, realized_pnl=保留, account_id=该账户`
- **AND** 写入 `StrategyEvent`（`event_type="manual_correction"`, `message="总权益校正: 旧X → 新Y"`）
- **AND** 若 OKX 调用失败返回错误信息

### Requirement: 未实现盈亏校正
系统 SHALL 支持校正未实现盈亏。

#### Scenario: 策略已停止时校正未实现盈亏
- **WHEN** 用户选择已停止的策略并点击"校正未实现盈亏"
- **THEN** 系统写入新 `PnlRecord`：`unrealized_pnl=0, realized_pnl=最新保留, equity=最新保留, strategy_instance_id=该策略`
- **AND** 写入 `StrategyEvent`（`event_type="manual_correction"`）

#### Scenario: 策略运行中时拒绝校正
- **WHEN** 用户选择正在运行的策略并点击"校正未实现盈亏"
- **THEN** 系统拒绝并返回"请先停止策略再校正"

### Requirement: 已实现盈亏校正
系统 SHALL 支持根据历史成交订单重算已实现盈亏。

#### Scenario: 用户校正已实现盈亏
- **WHEN** 用户选择策略并点击"校正已实现盈亏"
- **THEN** 系统查询该策略所有 `status='filled'` 的卖单成交记录
- **AND** 按成交价与对应买单价差 × 数量重算累计 `realized_pnl`
- **AND** 写入新 `PnlRecord`：`realized_pnl=重算值, unrealized_pnl=最新保留, equity=最新保留, strategy_instance_id=该策略`
- **AND** 写入 `StrategyEvent`（`event_type="manual_correction"`, `message="已实现盈亏校正: 旧X → 新Y"`）

## MODIFIED Requirements

### Requirement: 策略停止流程
原停止/暂停/错误退出流程修改为：在退出主循环后、撤销订单后，额外写入一条 `unrealized_pnl=0` 的最终 `PnlRecord`，并记录 `StrategyEvent(event_type="stopped", message包含最终PnL)`。

### Requirement: 服务启动孤儿清理
原 `main.py` 启动时将 `running/paused` 重置为 `stopped` 的逻辑修改为：在重置状态后，为每个被重置的实例写入一条 `unrealized_pnl=0` 的 `PnlRecord`，避免仪表盘显示陈旧的未实现盈亏。

### Requirement: 策略主循环网络异常处理
`grid_strategy.execute()` 主循环修改为：捕获网络异常后采用指数退避（初始 2s，倍增，上限 60s），连续失败超过 10 次时记录 `error` 事件并自动停止策略，避免疯狂重试。

## REMOVED Requirements
无。
