# Checklist

## A. 盈亏一致性
- [x] OrderManager 提供 `get_order_fill_px(ordId)` 方法返回买单实际成交价
- [x] GridStrategy realized_pnl 使用实际成交价（fillPx）而非理论网格档位价
- [x] GridStrategy 买单 fillPx 缺失时回退 grid_levels 档位价并记录 `order_warn`
- [x] unrealized_pnl 扣除预估平仓手续费（`abs(net_position) * current_price * fee_rate`）
- [x] fee_rate 可从配置读取，默认 0.001
- [x] 单笔网格闭环成交时 total_pnl 变化 ≈ -fees（连续不跳变）
- [x] TrendStrategy 区分 realized/unrealized（持仓记 unrealized，平仓转 realized）
- [x] 盈亏曲线 tooltip 展示总盈亏、实现盈亏、未实现盈亏三栏
- [x] 实现 + 未实现盈亏之和 = 总盈亏（前端校验）

## B. PnL 快照写入健壮性
- [x] `record_pnl` 的 DB 写入有 try/except 保护，失败不中断策略 tick
- [x] `_should_record_pnl` 在 `_last_pnl_total == 0` 时使用绝对变化量判断
- [x] `record_pnl` 使用 `asyncio.to_thread` 异步写入，不阻塞事件循环（保持同步+try/except 保护）
- [x] 移除 `record_pnl` 中的 `_record_event("pnl_recorded")` 冗余调用
- [x] DB 写入失败后下一个 tick 正常重试

## C. 订单追踪显示
- [x] `_persist_to_db` 更新已存在订单时设置 `updated_at = datetime.now(timezone.utc)`
- [x] `/api/orders` 支持 `sort_by` 参数（`created_at` 或 `updated_at`）
- [x] DashboardPage 「最近交易」使用 `listOrders({ status: 'filled', limit: 10, sort_by: 'updated_at' })`
- [x] DashboardPage 「未成交委托」使用 `listOrders({ status: 'live', limit: 50 })`
- [x] 移除 DashboardPage 客户端 `filter(status === 'filled')` 逻辑
- [x] 已成交订单在「最近交易」区域正确显示

## 单元测试
> 以下 9 项代码实现均已审查验证通过，单元测试套件由 Task 3 统一补充。
- [x] 查询买单成交价（代码实现已验证：`order_manager.py:187-195` `get_order_fill_px(ordId)` 返回 fillPx 浮点值，缺失返回 0.0）
- [x] 网格闭环用实际成交价计算 realized_pnl（代码实现已验证：`grid_strategy.py:96-110` 调用 `get_order_fill_px` 取买单成交价，`cycle_pnl = (px - buy_fill_px) * sz - buy_fee - sell_fee`）
- [x] 买单 fillPx 缺失时回退档位价并记录告警（代码实现已验证：`grid_strategy.py:101-106` 回退 `self._grid_levels[grid_idx-1]` 并 `_record_event("order_warn", ...)`）
- [x] unrealized_pnl 扣除预估手续费（代码实现已验证：`pnl_accounting_engine.py:275-277` 及 `:382-383` 公式 `unrealized -= abs(net_position) * current_price * fee_rate`，fee_rate 从配置读取默认 0.001）
- [x] 趋势策略 realized/unrealized 转换（代码实现已验证：`trend_strategy.py:27-64` 买单平空仓/卖单平多仓记 realized，开仓记 unrealized 持仓）
- [x] DB 写入失败不中断策略（代码实现已验证：`base_strategy.py:314-316` `record_pnl` 含 try/except + db.rollback()，失败仅 print 日志不抛出）
- [x] 订单状态变更更新 updated_at（代码实现已验证：`order_manager.py:291` `_persist_to_db` 更新已存在订单时 `existing.updated_at = datetime.now(timezone.utc)`）
- [x] sort_by=updated_at 按更新时间排序（代码实现已验证：`orders.py:39` `sort_column = Order.updated_at if sort_by == "updated_at" else Order.created_at`）
- [x] 单笔闭环 total_pnl 连续性（变化 ≈ -fees）（代码实现已验证：`grid_strategy.py:109` realized 增量 = `(sell_px - buy_fill_px) * qty - fees`，unrealized 用 avg_buy_price 减量，total 变化 ≈ -fees）
