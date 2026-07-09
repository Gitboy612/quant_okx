# Checklist

## 后端服务
- [x] `maintenance_service.py` 实现 `reset_pnl()`，写清零 PnlRecord + 事件（账户级用 print 日志）
- [x] `maintenance_service.py` 实现 `cleanup_pnl_records()`，按策略/时间删除并返回数量
- [x] `maintenance_service.py` 实现 `cleanup_order_records()`，按策略/状态删除并返回数量
- [x] `maintenance_service.py` 实现 `cleanup_strategy_events()`，按策略删除并返回数量
- [x] `maintenance_service.py` 实现 `correct_equity()`，拉 OKX 真实 totalEq 写校正记录
- [x] `maintenance_service.py` 实现 `correct_unrealized_pnl()`，校验已停止后写 unrealized=0
- [x] `maintenance_service.py` 实现 `correct_realized_pnl()`，按成交订单重算 realized
- [x] 所有维护函数校验目标策略 `status != 'running'`，运行中拒绝
- [x] 所有写操作配套写 `StrategyEvent`（`manual_correction` 或 `data_cleanup`），无关联策略时用 print 日志（StrategyEvent.strategy_instance_id 为 nullable=False）

## 后端路由
- [x] `maintenance.py` 注册 `POST /api/maintenance/reset-pnl`
- [x] `maintenance.py` 注册 `POST /api/maintenance/cleanup/pnl-records`
- [x] `maintenance.py` 注册 `POST /api/maintenance/cleanup/order-records`
- [x] `maintenance.py` 注册 `POST /api/maintenance/cleanup/strategy-events`
- [x] `maintenance.py` 注册 `POST /api/maintenance/correct/equity`
- [x] `maintenance.py` 注册 `POST /api/maintenance/correct/unrealized-pnl`
- [x] `maintenance.py` 注册 `POST /api/maintenance/correct/realized-pnl`
- [x] `main.py` 注册 maintenance 路由

## 系统逻辑修复
- [x] `base_strategy.py` 新增 `record_final_pnl()` 写 unrealized=0 最终记录
- [x] `grid_strategy.py` 的 stop/pause/异常退出路径调用 `record_final_pnl()`
- [x] `main.py` 孤儿清理后为每个被重置实例写 unrealized=0 的 PnlRecord
- [x] `grid_strategy.py` execute 主循环网络异常指数退避（2s 起，倍增，上限 60s）
- [x] 连续网络失败超过 10 次记录 error 事件并自动停止策略

## 前端
- [x] `maintenance.ts` 导出 7 个 API 调用函数
- [x] `SettingsPage.tsx` 在代理面板与密码面板之间插入数据维护面板
- [x] 数据清理区块含策略选择器与红色危险按钮
- [x] 数据校正区块含账户/策略选择器与青色按钮
- [x] 破坏性操作需二次确认（5 秒超时自动取消）
- [x] 操作结果用 inline message 展示
- [x] 复用 glass-panel 样式与暗色主题

## 验证
- [x] Python 语法检查通过
- [x] TypeScript 编译通过（exit code 0）
- [ ] 手动测试盈亏清零、清理记录、校正权益流程（需用户实际测试）
