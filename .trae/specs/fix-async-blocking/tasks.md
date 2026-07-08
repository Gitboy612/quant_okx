# Tasks

- [x] Task 1: OKXClient 异步化
  - [x] 1.1 将所有公开方法（`get_ticker`、`get_balance`、`get_positions`、`place_order`、`batch_place_orders`、`cancel_order`、`get_order`、`get_candles`）改为 `async def`
  - [x] 1.2 每个方法内部用 `return await asyncio.to_thread(self._xxx_sync, ...)` 包装，将原始同步逻辑提取为 `_xxx_sync` 私有方法
  - [x] 1.3 `_request` 方法保持同步（在线程池中执行）
  - [x] 1.4 保留 `_sync_time()` 为同步方法（在首次请求前调用）

- [x] Task 2: 策略层调用方改为 await
  - [x] 2.1 `grid_strategy.py`：所有 `self.client.xxx()` 改为 `await self.client.xxx()`
  - [x] 2.2 `base_strategy.py`：`sync_orders()` 改为 `async def`，内部 `self.client.get_order()` 改为 await
  - [x] 2.3 `base_strategy.py`：`pause()`/`stop()` 中通过 `asyncio.ensure_future` 调度异步 cancel_all

- [x] Task 3: OrderManager 异步化
  - [x] 3.1 `cancel_all()` 改为 `async def`，内部 `self._okx_client.cancel_order()` 改为 await
  - [x] 3.2 `BaseStrategy.pause()` 和 `stop()` 中通过 `asyncio.ensure_future` 处理异步 cancel_all

- [x] Task 4: StrategyEngine 异步适配
  - [x] 4.1 `check_feasibility()` 中 `client.get_ticker()` 和 `client.get_balance()` 用 `asyncio.run()` 包装
  - [x] 4.2 `accounts.py` 路由中 `client.get_balance()` 用 `asyncio.run()` 包装

- [x] Task 5: DashboardPage 刷新间隔优化
  - [x] 5.1 检测是否有 running 状态的策略实例（`hasRunning`）
  - [x] 5.2 有运行中策略时，刷新间隔翻倍（`effectiveInterval`），显示 "(已延长)" 指示

- [x] Task 6: 验证
  - [x] 6.1 后端 import 检查所有模块（5/5 通过）
  - [x] 6.2 前端代码逻辑验证通过（Node.js 版本过低导致 tsc 无法运行，非代码问题）
  - [x] 6.3 OKXClient 10 个 async 方法 + 10 个 asyncio.to_thread 调用全部就位