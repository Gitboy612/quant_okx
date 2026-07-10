# Tasks

- [x] Task 1: PnlRecord 数据模型迁移（新增 is_final 字段）
  - [x] SubTask 1.1: 在 `backend/models/pnl.py` 的 PnlRecord 增加 `is_final = Column(Boolean, default=False)` 字段
  - [x] SubTask 1.2: 为 `pnl_records` 表增加 `(strategy_instance_id, recorded_at)` 复合索引
  - [x] SubTask 1.3: 确认 SQLAlchemy `create_all` 自动迁移或提供迁移脚本说明

- [x] Task 2: OrderManager 维护净持仓状态
  - [x] SubTask 2.1: 在 OrderManager 新增 `_net_position: float`（累计买入量 - 累计卖出量）、`_avg_buy_price: float`（加权均价）、`_total_buy_qty: float`、`_total_buy_value: float` 字段
  - [x] SubTask 2.2: 在 `update_order` 中检测 `state` 变为 `filled` 时更新净持仓：买单累加买入量与价值、卖单扣减持仓量；更新加权均价 = 总买入价值 / 总买入量
  - [x] SubTask 2.3: 新增 `get_position_summary()` 方法返回 `(net_position, avg_buy_price)`，供策略查询
  - [x] SubTask 2.4: 新增 `restore_position(net_position, avg_buy_price)` 方法，供策略重启时从 DB 恢复持仓状态

- [x] Task 3: OrderManager 线程安全重构
  - [x] SubTask 3.1: 移除 `_async_persist` 中的 `threading.Thread`，改为 `asyncio.to_thread(self._persist_to_db, order)`
  - [x] SubTask 3.2: 将 `_async_persist` 改为 `async def`，调用方（`add_order`/`update_order`）改为异步或用 `asyncio.create_task` 调度
  - [x] SubTask 3.3: `_trigger_callbacks` 中 `asyncio.ensure_future(result)` 改为 `asyncio.create_task(result)`，并捕获 `RuntimeError`（无 event loop 时跳过）

- [x] Task 4: 已实现盈亏扣手续费
  - [x] SubTask 4.1: GridStrategy `_on_order_filled` 卖单分支：从对应买单 OrderInfo 查询 `fee`，加上当前卖单 `fee`，`cycle_pnl = (px - buy_px) * sz - buy_fee - sell_fee`
  - [x] SubTask 4.2: 在 OrderManager 新增 `get_order_fee(ordId)` 辅助方法返回订单手续费
  - [x] SubTask 4.3: grid_idx=0 卖单成交边界防护：拒绝计算 realized_pnl，记录 `order_warn` 事件

- [x] Task 5: 未实现盈亏算法重构（基于持仓）
  - [x] SubTask 5.1: GridStrategy 主循环移除「遍历 _active_buy_orders」的 unrealized 计算
  - [x] SubTask 5.2: 改为从 `order_manager.get_position_summary()` 取净持仓与均价，`unrealized = (current_price - avg_buy_price) * net_position`
  - [x] SubTask 5.3: 合约（symbol 含 `-SWAP`）优先用 `client.get_positions()` 的 `upl` 字段，本地净持仓兜底
  - [x] SubTask 5.4: 现货用本地净持仓计算
  - [x] SubTask 5.5: ComposableStrategy `_get_unrealized_pnl_ratio` 保持现有 OKX positions 口径，与 GridStrategy 一致

- [x] Task 6: WebSocket 订单回调接入
  - [x] SubTask 6.1: BaseStrategy `start()` 中在 WS 连接与订阅后，调用 `self._ws_client.on_order_update(self._on_ws_order_update)` 注册回调
  - [x] SubTask 6.2: 新增 `_on_ws_order_update(self, ordId, state, order_data)` 方法：解析 fillPx/fillSz/fee，调用 `order_manager.update_order(ordId, state=state, fillPx=..., fillSz=..., fee=...)`
  - [x] SubTask 6.3: WS 回调内异常捕获并记录事件，不抛出（避免阻塞 WS message_loop）

- [x] Task 7: PnL 采样降频
  - [x] SubTask 7.1: GridStrategy 主循环新增 `_last_pnl_record_ts` 字段，记录上次写 PnL 的时间
  - [x] SubTask 7.2: 循环内判断 `now - _last_pnl_record_ts >= 60` 或 `total_pnl 变化 > 1%` 时才调用 `record_pnl`
  - [x] SubTask 7.3: TrendStrategy、AdvancedGridHedgeStrategy 同步采用 60s 采样（原每 tick 写）
  - [x] SubTask 7.4: ComposableStrategy 主循环增加 PnL 记录逻辑（原无显式 record_pnl，每 tick 调用 on_tick 时由基础策略记录）

- [x] Task 8: 停止时保留未实现盈亏
  - [x] SubTask 8.1: `record_final_pnl` 读取最新 PnlRecord 的 `unrealized_pnl`，写入终态记录时保留该值（非 0）
  - [x] SubTask 8.2: 终态记录 `is_final=True`
  - [x] SubTask 8.3: 策略重启恢复时从最新记录（含 is_final）恢复 realized_pnl 与持仓状态

- [x] Task 9: PnL Summary API 修正
  - [x] SubTask 9.1: `/api/pnl/summary` 的 `total_unrealized` 改为 `latest.unrealized_pnl`（不再求和）
  - [x] SubTask 9.2: 新增 `by_strategy` 字段：按 strategy_instance_id 分组，每组取最新记录的 realized/unrealized
  - [x] SubTask 9.3: `/api/pnl` 列表接口响应新增 `is_final` 字段

- [x] Task 10: 多策略权益隔离
  - [x] SubTask 10.1: GridStrategy `execute()` 中 `_initial_equity` 保持账户总权益快照（已有逻辑确认）
  - [x] SubTask 10.2: `record_pnl` 增加校验：equity 字段记录策略级增量（realized + unrealized + initial_equity），避免直接写账户总权益
  - [x] SubTask 10.3: TrendStrategy/AdvancedGridHedgeStrategy 原 `record_pnl(total_equity, 0, 0)` 改为记录策略级增量（需维护 _initial_equity）

- [x] Task 11: 单元测试与验证
  - [x] SubTask 11.1: 测试净持仓计算（买单成交累加、卖单成交扣减、均价更新）
  - [x] SubTask 11.2: 测试 unrealized_pnl 基于持仓（非挂单）
  - [x] SubTask 11.3: 测试 realized_pnl 扣手续费
  - [x] SubTask 11.4: 测试 PnL Summary 取最新值（非求和）
  - [x] SubTask 11.5: 测试 WS 回调接入 order_manager
  - [x] SubTask 11.6: 测试停止时 is_final 标记与 unrealized 保留
  - [x] SubTask 11.7: 测试 grid_idx=0 边界防护

# Task Dependencies
- Task 2（净持仓状态）→ Task 5（未实现盈亏重构）依赖净持仓接口
- Task 2 → Task 4（扣手续费）依赖 OrderInfo.fee 查询
- Task 3（线程安全）独立，可与 Task 2 并行
- Task 6（WS 回调）独立，可与 Task 2/3 并行
- Task 1（模型迁移）→ Task 8（is_final）依赖新字段
- Task 5 → Task 10（权益隔离）依赖持仓口径统一
- Task 7（采样降频）独立，可与 Task 5/6 并行
- Task 9（API 修正）依赖 Task 1（is_final 字段）
- Task 11（测试）依赖所有功能 Task 完成
