# 策略运行后前端卡顿性能修复 Spec

## Why
策略启动后，`okx_client.py` 使用同步 `httpx.Client` 在 asyncio 事件循环中发起阻塞 HTTP 请求。每次策略调用 `get_ticker()`、`get_balance()`、`batch_place_orders()` 等都会阻塞整个事件循环，导致前端的 FastAPI 请求排队等待，界面卡顿严重。

## What Changes
- **修改** `okx_client.py`：将所有同步 HTTP 调用包装为 `asyncio.to_thread()` 异步执行，不阻塞事件循环
- **修改** 策略中调用 `self.client.xxx()` 的地方：改为 `await self.client.xxx()`（方法签名改为 async）
- **修改** `OrderManager._persist_to_db()`：DB 写入已在独立线程中，无需改动
- **修改** DashboardPage 自动刷新：策略运行中时翻倍刷新间隔，减少无效请求

## Impact
- Affected specs: `refactor-order-management`
- Affected code:
  - `backend/services/okx_client.py`（核心修改）
  - `backend/strategies/grid_strategy.py`（调用方改为 await）
  - `backend/strategies/base_strategy.py`（调用方改为 await）
  - `backend/services/strategy_engine.py`（feasibility 检查中调用方改为 await）
  - `backend/services/order_manager.py`（cancel_all 中的调用）
  - `frontend/src/pages/DashboardPage.tsx`（刷新间隔优化）

## ADDED Requirements

### Requirement: OKXClient 异步化
系统 SHALL 将 `okx_client.py` 中所有公开方法改为异步，内部使用 `asyncio.to_thread()` 将同步 HTTP 请求提交到线程池执行，不阻塞事件循环。

#### Scenario: 策略调用 get_ticker 不阻塞前端
- **WHEN** 策略在 asyncio 事件循环中调用 `await client.get_ticker("ETH-USDT-SWAP")`
- **THEN** HTTP 请求在线程池中执行，事件循环继续处理其他任务（前端 API 请求）
- **AND** 请求完成后结果返回给策略

#### Scenario: 策略初始化批量下单不阻塞
- **WHEN** 策略调用 `await client.batch_place_orders([...])` 批量下单
- **THEN** 批量下单在线程池中执行，期间前端请求正常响应

#### Scenario: 策略主循环 ticker 查询
- **WHEN** 策略每 3 秒调用 `await client.get_ticker()`
- **THEN** 查询耗时 ~500ms 期间，事件循环仍可处理 10+ 个前端请求

### Requirement: 策略方法签名统一为 async
所有策略中的 `execute()` 方法已为 async，但内部调用 `self.client.xxx()` 需改为 `await self.client.xxx()`。

#### Scenario: 网格策略主循环
- **WHEN** 网格策略主循环执行
- **THEN** 所有 `self.client.xxx()` 调用均为 `await` 形式
- **AND** `asyncio.sleep(3)` 保持不动

### Requirement: 前端刷新间隔优化
策略运行中时，DashboardPage 自动刷新间隔应翻倍，减少无效 API 竞争。

#### Scenario: 存在运行中策略时
- **WHEN** DashboardPage 检测到有 status="running" 的策略实例
- **THEN** 自动刷新间隔翻倍（如 30s → 60s）

## MODIFIED Requirements
无。

## REMOVED Requirements
无。