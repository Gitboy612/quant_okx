# Tasks

- [x] Task 1: 增强 Order DB 模型
  - [x] 1.1 在 `backend/models/order.py` 中增加字段：`cl_ord_id`、`state`、`fill_px`、`fill_sz`、`fee`、`update_time`
  - [x] 1.2 在 `order_id` 上添加唯一索引，防止重复记录
  - [x] 1.3 创建 Alembic 迁移脚本或自动建表

- [x] Task 2: 实现 OrderManager 核心模块
  - [x] 2.1 创建 `backend/services/order_manager.py`
  - [x] 2.2 实现内存订单队列（`dict[str, OrderInfo]`），以 ordId 为 key
  - [x] 2.3 实现 `OrderInfo` 数据类：包含 ordId、clOrdId、symbol、side、px、sz、state、fillPx、fillSz、fee、cTime、uTime
  - [x] 2.4 实现 `add_order()` 方法：下单成功后入队 + 异步写 DB
  - [x] 2.5 实现 `update_order()` 方法：更新内存状态 + 异步写 DB（upsert 逻辑）
  - [x] 2.6 实现 `cancel_all()` 方法：批量撤单
  - [x] 2.7 实现 `get_active_orders()` 方法：返回所有活跃订单
  - [x] 2.8 实现 `get_order()` 方法：按 ordId 查询
  - [x] 2.9 实现 `load_from_db()` 方法：重启时从 DB 恢复
  - [x] 2.10 实现回调注册机制：`on_order_filled(callback)` 等

- [x] Task 3: 实现 OKX WebSocket 客户端
  - [x] 3.1 创建 `backend/services/okx_ws_client.py`
  - [x] 3.2 实现 WebSocket 连接管理（`websockets` 库）
  - [x] 3.3 实现 OKX V5 私密频道登录（签名认证）
  - [x] 3.4 实现 `orders` 频道订阅
  - [x] 3.5 实现消息解析与分发（state → callback）
  - [x] 3.6 实现自动重连 + 指数退避
  - [x] 3.7 实现降级 REST 轮询（WebSocket 断开时）

- [x] Task 4: 重构 BaseStrategy 集成 OrderManager
  - [x] 4.1 在 `BaseStrategy.__init__` 中创建 `OrderManager` 实例
  - [x] 4.2 移除 `_active_orders` dict 及相关方法（`track_order`/`untrack_order`/`_cancel_all_active_orders`）
  - [x] 4.3 重构 `record_order()` 为 `OrderManager` 的代理方法
  - [x] 4.4 重构 `sync_orders()` 使用 `OrderManager.load_from_db()`
  - [x] 4.5 在 `start()` 中启动 WebSocket 连接
  - [x] 4.6 在 `stop()`/`pause()` 中通过 OrderManager 撤单 + 关闭 WebSocket

- [x] Task 5: 重构网格策略使用 OrderManager
  - [x] 5.1 初始化下单改为 `self.client.batch_place_orders()` + `self.order_manager.add_order()`
  - [x] 5.2 注册成交回调：`on_filled` 中补对面方向单
  - [x] 5.3 移除主循环中的逐单 REST 轮询（`get_order` 调用）
  - [x] 5.4 主循环改为事件驱动：等待 WebSocket 回调触发
  - [x] 5.5 保留价格监控循环（ticker 查询 + PnL 计算），与订单管理分离

- [x] Task 6: 更新 API 路由和前端
  - [x] 6.1 更新 `backend/routers/orders.py`：支持从 OrderManager 内存读取活跃订单
  - [x] 6.2 增加订单状态筛选参数（`status` filter）
  - [x] 6.3 更新 `frontend/src/pages/OrdersPage.tsx`：增加新列（成交均价、手续费等）
  - [x] 6.4 增加状态筛选下拉框

- [x] Task 7: 更新 StrategyEngine 集成
  - [x] 7.1 在 `start_strategy` 中创建 OrderManager 和 OKXWsClient 并传递给策略
  - [x] 7.2 在 `stop_strategy` 中确保 WebSocket 正确关闭