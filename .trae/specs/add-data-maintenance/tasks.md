# Tasks

- [x] Task 1: 后端数据维护服务（maintenance_service.py）
  - [x] 创建 `backend/services/maintenance_service.py`，实现以下函数：
    - `reset_pnl(db, account_id=None, strategy_instance_id=None)`：盈亏清零，写清零 PnlRecord + 事件
    - `cleanup_pnl_records(db, strategy_instance_id=None, before_date=None)`：删除 PnL 记录，返回删除数量
    - `cleanup_order_records(db, strategy_instance_id=None, status_list=None)`：删除订单记录，返回删除数量
    - `cleanup_strategy_events(db, strategy_instance_id=None)`：删除策略事件，返回删除数量
    - `correct_equity(db, account_id)`：拉 OKX 真实 totalEq，写校正 PnlRecord + 事件
    - `correct_unrealized_pnl(db, strategy_instance_id)`：校验策略已停止，写 unrealized=0 校正记录 + 事件
    - `correct_realized_pnl(db, strategy_instance_id)`：按成交订单重算 realized，写校正记录 + 事件
  - [x] 所有函数校验目标策略 `status != 'running'`，运行中则拒绝
  - [x] 所有写操作配套写 `StrategyEvent`（`manual_correction` 或 `data_cleanup`），无关联策略时改用 print 日志

- [x] Task 2: 后端数据维护路由（maintenance.py）
  - [x] 创建 `backend/routers/maintenance.py`，前缀 `/api/maintenance`
  - [x] `POST /reset-pnl`：body 含 `account_id` 或 `strategy_instance_id`
  - [x] `POST /cleanup/pnl-records`：body 含 `strategy_instance_id` 或 `before_date`
  - [x] `POST /cleanup/order-records`：body 含 `strategy_instance_id` 或 `status_list`
  - [x] `POST /cleanup/strategy-events`：body 含 `strategy_instance_id`
  - [x] `POST /correct/equity`：body 含 `account_id`
  - [x] `POST /correct/unrealized-pnl`：body 含 `strategy_instance_id`
  - [x] `POST /correct/realized-pnl`：body 含 `strategy_instance_id`
  - [x] 在 `backend/main.py` 注册该路由

- [x] Task 3: 策略停止时写清零 PnL 记录
  - [x] 修改 `backend/strategies/base_strategy.py`，新增 `record_final_pnl()` 方法：写一条 `unrealized_pnl=0` 的 PnlRecord + stopped 事件
  - [x] 修改 `backend/strategies/grid_strategy.py` 的 `stop()` / `pause()` / 主循环异常退出路径，调用 `record_final_pnl()`

- [x] Task 4: 服务重启孤儿清理写 PnL
  - [x] 修改 `backend/main.py` 启动时的孤儿清理逻辑：重置 `running/paused` → `stopped` 后，为每个被重置实例写 `unrealized_pnl=0` 的 PnlRecord

- [x] Task 5: 策略主循环网络异常退避
  - [x] 修改 `backend/strategies/grid_strategy.py` 的 `execute()` 主循环：捕获网络异常后指数退避（初始 2s，倍增，上限 60s）
  - [x] 连续失败超过 10 次时记录 `error` 事件并自动停止策略

- [x] Task 6: 前端数据维护 API（maintenance.ts）
  - [x] 创建 `frontend/src/api/maintenance.ts`，导出上述 7 个端点的调用函数

- [x] Task 7: 前端数据维护面板（SettingsPage.tsx）
  - [x] 在代理面板与密码面板之间插入"数据维护"面板（`transition={{ delay: 0.15 }}`，原密码面板改 0.2，说明改 0.25）
  - [x] "数据清理"区块：策略选择器、操作按钮（红色危险样式）、二次确认
  - [x] "数据校正"区块：账户/策略选择器、操作按钮（青色样式）、结果展示
  - [x] 操作结果用 inline message 展示（成功/失败 + 详情）
  - [x] 复用现有 `glass-panel` 样式与暗色主题令牌

- [x] Task 8: 测试与验证
  - [x] Python 语法检查所有修改的后端文件
  - [x] TypeScript 编译通过（`npx tsc --noEmit` exit code 0）
  - [ ] 手动测试盈亏清零、清理记录、校正权益流程（需用户实际测试）

# Task Dependencies
- Task 2 依赖 Task 1
- Task 3、Task 4、Task 5 互相独立，可并行
- Task 7 依赖 Task 6
- Task 8 依赖所有前序任务
