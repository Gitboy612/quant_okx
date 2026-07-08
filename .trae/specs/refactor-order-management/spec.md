# 策略订单队列管理重构 Spec

## Why
当前订单管理分散在三层（策略内 dict、BaseStrategy._active_orders、SQLite DB），每笔订单操作都直接写 DB，主循环对每个活跃订单逐个 REST 轮询状态，100 个网格订单每次 tick 产生 100+ 次 API 调用。需要统一订单队列管理，引入 WebSocket 实时更新，降低 DB 开销。

## What Changes
- **新增** `OrderManager` 模块：统一管理策略下所有订单的完整生命周期
- **新增** OKX WebSocket 客户端：订阅订单频道，实时接收成交/撤销/部分成交推送
- **修改** 策略主循环：取消逐单 REST 轮询，改为 WebSocket 事件驱动
- **修改** 订单持久化策略：内存热数据 + 状态变更时写 DB（而非每次操作都写）
- **修改** 基础策略类：移除分散的 `_active_orders`/`track_order`/`untrack_order`，委托给 OrderManager
- **修改** 网格策略：`active_buy_orders`/`active_sell_orders` 改为通过 OrderManager 查询

## Impact
- Affected specs: 无现有 spec
- Affected code:
  - `backend/services/order_manager.py`（新增）
  - `backend/services/okx_ws_client.py`（新增）
  - `backend/strategies/base_strategy.py`（修改）
  - `backend/strategies/grid_strategy.py`（修改）
  - `backend/models/order.py`（修改，加字段）
  - `backend/routers/orders.py`（修改）
  - `backend/services/strategy_engine.py`（修改）
  - `frontend/src/pages/OrdersPage.tsx`（修改）

## ADDED Requirements

### Requirement: OrderManager 统一订单队列
系统 SHALL 提供 `OrderManager` 类，每个策略实例持有一个，负责该策略所有订单的完整生命周期管理。

#### Scenario: 下单成功后入队
- **WHEN** 策略通过 OKX API 成功下单（收到 `sCode: "0"` 和 `ordId`）
- **THEN** OrderManager 将订单加入内存队列（dict 以 ordId 为 key），包含完整委托信息（价格、数量、方向、时间戳、状态）
- **AND** 异步写入 DB 持久化（不阻塞主流程）

#### Scenario: WebSocket 推送成交
- **WHEN** OKX WebSocket 推送订单状态变为 `filled`
- **THEN** OrderManager 更新内存中的订单状态为 `filled`
- **AND** 触发策略回调（如网格策略收到回调后补对面方向的单）
- **AND** 异步更新 DB 对应记录

#### Scenario: 前端查询订单列表
- **WHEN** 前端请求 `/api/orders?strategy_instance_id=N`
- **THEN** 优先从 OrderManager 内存返回活跃订单（热数据），历史订单从 DB 查询

#### Scenario: 策略暂停/停止时撤单
- **WHEN** 策略收到暂停或停止指令
- **THEN** OrderManager 遍历所有活跃订单，调用 OKX 撤单 API
- **AND** 更新内存状态为 `canceled`，异步写 DB

#### Scenario: 服务器重启后恢复
- **WHEN** 服务器重启，策略重新启动
- **THEN** OrderManager 从 DB 加载所有 `status='live'` 的订单
- **AND** 通过 OKX WebSocket 订阅这些订单的最新状态（而非逐单 REST 查询）
- **AND** 根据实际状态同步内存和 DB

### Requirement: OKX WebSocket 订单频道
系统 SHALL 建立 OKX WebSocket 连接，订阅 `orders` 频道，实时接收订单状态变更。

#### Scenario: 连接建立
- **WHEN** 策略启动
- **THEN** 建立到 OKX WebSocket 的加密连接（wss://ws.okx.com:8443/ws/v5/private）
- **AND** 使用 API Key 签名登录
- **AND** 订阅 `orders` 频道（指定 instType 和 instId）

#### Scenario: 收到订单更新
- **WHEN** 收到 WebSocket `orders` 频道推送
- **THEN** 解析 `state` 字段（live / partially_filled / filled / canceled）
- **AND** 转发给对应策略的 OrderManager 处理

#### Scenario: 连接断开重连
- **WHEN** WebSocket 连接意外断开
- **THEN** 自动重连（指数退避，最大 30s 间隔）
- **AND** 重连后重新登录并订阅
- **AND** 重连期间降级到 REST 轮询（30s 间隔）

### Requirement: 策略执行层与订单管理解耦
策略的 `execute()` 方法 SHALL 不再直接操作订单字典或 DB，全部通过 OrderManager 接口。

#### Scenario: 网格策略初始化下单
- **WHEN** 网格策略计算完所有网格价位
- **THEN** 调用 `OrderManager.submit_batch(orders)` 批量下单
- **AND** OrderManager 返回成功下单的 ordId 列表
- **AND** 策略仅保留网格索引 → ordId 的映射关系

#### Scenario: 网格策略收到成交回调
- **WHEN** OrderManager 回调通知某 ordId 已成交
- **THEN** 策略通过网格索引映射找到对应价位
- **AND** 计算对面方向价格，调用 `OrderManager.submit_single()` 补单

## MODIFIED Requirements

### Requirement: 订单 DB 模型增强
**原**: Order 表只有基本字段，每次操作新建记录  
**改**: 增加 `cl_ord_id`（客户自定义ID）、`state`（OKX 原始状态）、`fill_px`（成交均价）、`fill_sz`（已成交数量）、`fee`（手续费）、`update_time`（OKX 更新时间）字段；`order_id` 加唯一索引

#### Scenario: 订单状态更新
- **WHEN** 订单状态发生变更（live → filled）
- **THEN** 更新现有 DB 记录（通过 ordId 匹配），而非新建记录

### Requirement: 前端订单展示增强
**原**: 仅展示基本字段  
**改**: 订单列表增加成交均价、已成交数量、手续费、状态更新时间列；支持按状态筛选（全部/活跃/已成交/已撤销）

## REMOVED Requirements
无移除项。