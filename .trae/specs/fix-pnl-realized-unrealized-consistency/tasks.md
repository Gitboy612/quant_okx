# Tasks

- [x] Task 1: OrderManager 维护买单成交价映射
  - [x] SubTask 1.1: 新增 `get_order_fill_px(ordId)` 方法，返回指定订单 fillPx 浮点值
  - [x] SubTask 1.2: 确认买单成交时 `_update_position_on_filled` 已记录 fillPx
  - [ ] SubTask 1.3: 添加单元测试：查询买单成交价

- [x] Task 2: GridStrategy realized_pnl 改用实际成交价
  - [x] SubTask 2.1: 修改 `_on_order_filled` 卖单分支，`buy_fill_px = order_manager.get_order_fill_px(buy_ord_id)`
  - [x] SubTask 2.2: `cycle_pnl = (px - buy_fill_px) * sz - buy_fee - sell_fee`，fillPx 缺失时回退 grid_levels 档位价并记录 `order_warn`
  - [ ] SubTask 2.3: 添加单元测试：网格闭环用实际成交价计算 realized_pnl

- [x] Task 3: unrealized_pnl 扣除预估手续费
  - [x] SubTask 3.1: BaseStrategy 新增 `_fee_rate`（默认 0.001，从 params 读取）
  - [x] SubTask 3.2: 修改 grid_strategy.py unrealized 计算：扣 `abs(net_position) * current_price * fee_rate`
  - [ ] SubTask 3.3: 添加单元测试：unrealized_pnl 扣除预估手续费

- [x] Task 4: TrendStrategy 盈亏口径对齐
  - [x] SubTask 4.1: TrendStrategy 接入 OrderManager 持仓跟踪
  - [x] SubTask 4.2: 买单成交后计算 unrealized_pnl，反向平仓时累加 realized_pnl
  - [ ] SubTask 4.3: 添加单元测试：趋势策略 realized/unrealized 转换

- [x] Task 5: PnL 快照写入健壮性
  - [x] SubTask 5.1: `record_pnl` 增加 try/except，失败时记录日志不中断 tick
  - [x] SubTask 5.2: 修复 `_should_record_pnl` 的 `_last_pnl_total == 0` 逻辑：增加绝对变化量判断
  - [x] SubTask 5.3: `record_pnl` 改为 `asyncio.to_thread` 异步写入（保持同步，try/except 保护优先）
  - [x] SubTask 5.4: 移除 `record_pnl` 中的 `_record_event("pnl_recorded")` 冗余调用
  - [ ] SubTask 5.5: 添加单元测试：DB 写入失败不中断策略

- [x] Task 6: 订单 updated_at 维护
  - [x] SubTask 6.1: `_persist_to_db` 更新已存在订单时设置 `existing.updated_at = datetime.now(timezone.utc)`
  - [ ] SubTask 6.2: 添加单元测试：订单状态变更更新 updated_at

- [x] Task 7: 订单查询支持 sort_by 参数
  - [x] SubTask 7.1: `routers/orders.py` 新增 `sort_by` 参数（`created_at` 或 `updated_at`，默认 `created_at`）
  - [x] SubTask 7.2: 前端 `api/orders.ts` 的 `listOrders` params 增加 `sort_by`
  - [ ] SubTask 7.3: 添加单元测试：sort_by=updated_at 按更新时间排序

- [x] Task 8: 仪表盘分状态查询订单
  - [x] SubTask 8.1: DashboardPage 「最近交易」改为 `listOrders({ status: 'filled', limit: 10, sort_by: 'updated_at' })`
  - [x] SubTask 8.2: DashboardPage 「未成交委托」改为 `listOrders({ status: 'live', limit: 50 })`
  - [x] SubTask 8.3: 移除客户端 `filter(status === 'filled')` 逻辑

- [x] Task 9: 盈亏曲线 tooltip 三栏展示
  - [x] SubTask 9.1: PnLChart.tsx 的 PnlRecord 接口增加 realized_pnl、unrealized_pnl
  - [x] SubTask 9.2: tooltip formatter 展示总盈亏/实现盈亏/未实现盈亏
  - [ ] SubTask 9.3: 验证 实现 + 未实现 = 总盈亏

# Task Dependencies
- [Task 2] 依赖 [Task 1]（需要 get_order_fill_px）
- [Task 4] 依赖 [Task 1]（趋势策略需要 OrderManager 持仓跟踪）
- [Task 3] 独立
- [Task 5] 独立
- [Task 8] 依赖 [Task 7]（需要 sort_by 参数）
- [Task 6] 独立
- [Task 9] 独立（仅前端展示）
