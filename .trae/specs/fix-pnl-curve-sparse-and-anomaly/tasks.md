# Tasks

- [ ] Task 1: 修复增量核算 avg_buy_price=0 导致的异常 unrealized_pnl
  - [ ] SubTask 1.1: 在 `pnl_accounting_engine.py` 的 `incremental_update` 中，检测无基准 PnlRecord 时转执行 `recompute` 逻辑（而非用 0 作为基准增量）
  - [ ] SubTask 1.2: 计算 unrealized_pnl 时，若 `avg_buy_price=0` 且 `net_position>0`，将 unrealized_pnl 设为 0（避免极端负值兜底）
  - [ ] SubTask 1.3: 提取 `recompute` 和 `incremental_update` 的公共计算逻辑为 `_compute_pnl_from_orders` 辅助方法，避免重复

- [ ] Task 2: 实现心跳快照（无成交时写 PnlRecord）
  - [ ] SubTask 2.1: 在 `PnlAccountingEngine` 新增 `async heartbeat_snapshot(strategy_instance_id, client) -> PnlSnapshot | None` 方法
    - 读取最新 PnlRecord 的 realized_pnl、net_position、avg_buy_price、total_fee、order_count
    - 获取当前价计算 unrealized_pnl = (current_price - avg_buy_price) × net_position - 预估手续费
    - 若 avg_buy_price=0 且 net_position>0，unrealized_pnl=0
    - 写入 PnlRecord（is_final=False），不更新订单 pnl_accounted
    - 返回 PnlSnapshot
  - [ ] SubTask 2.2: 修改 `StrategyEngine._pnl_sampling_loop`：
    - 60s 间隔调用 `incremental_update`
    - 返回 None 时，检查距上次写库是否 ≥ 5 分钟，若是则调用 `heartbeat_snapshot`
    - 维护 `_last_heartbeat_ts: dict[int, float]` 记录每策略上次心跳时间

- [ ] Task 3: PnL API 支持 start_time/end_time 参数
  - [ ] SubTask 3.1: `backend/routers/pnl.py` 的 `GET /api/pnl` 新增 `start_time: str | None` 和 `end_time: str | None` 查询参数
  - [ ] SubTask 3.2: 用 `PnlRecord.recorded_at >= start_time` 和 `<= end_time` 过滤（ISO 格式解析）
  - [ ] SubTask 3.3: 默认 limit 从 100 改为 1000（Query default=1000, le=5000）
  - [ ] SubTask 3.4: 前端 `api/pnl.ts` 的 `listPnlRecords` 参数类型新增 `start_time?` 和 `end_time?`

- [ ] Task 4: PnLChart 自适应分桶重构
  - [ ] SubTask 4.1: 在 `PnLChart.tsx` 新增 `computeBucketInterval(timeRange, dataSpanMs) -> number` 函数
    - all 模式：span≤6h→60s，≤24h→300s，≤7d→1800s，≤30d→7200s，>30d→21600s
    - 24h 模式：300s（5分钟）
    - 7d 模式：1800s（30分钟）
    - 30d 模式：7200s（2小时）
  - [ ] SubTask 4.2: 重写 `buildBuckets` 函数，用 bucketInterval 动态生成桶（起始时间=窗口开始，结束=窗口结束，步长=bucketInterval）
  - [ ] SubTask 4.3: all 模式不再直接返回原始数据点，改为用 dataSpan（最早记录到最晚记录）计算桶
  - [ ] SubTask 4.4: 数据填充保持"lastValue 沿用"逻辑
  - [ ] SubTask 4.5: 水平滚动阈值从 50 改为 400

- [ ] Task 5: DashboardPage 按时间窗口请求 PnL 数据
  - [ ] SubTask 5.1: 根据 timeRange 计算 start_time：
    - 24h：now - 24h
    - 7d：今日 00:00 - 7天
    - 30d：今日 00:00 - 30天
    - all：不传 start_time（获取全部）
  - [ ] SubTask 5.2: `listPnlRecords` 调用时传入 start_time（all 模式不传）

- [ ] Task 6: 清理历史异常数据
  - [ ] SubTask 6.1: 新增迁移脚本 `backend/migrations/fix_pnl_anomaly_records.py`
    - 查询 unrealized_pnl 绝对值 > 1000 且 avg_buy_price=0 的记录
    - 删除这些异常记录（或修正 unrealized_pnl=0）
  - [ ] SubTask 6.2: 脚本可独立运行，幂等

- [x] Task 7: 单元测试与验证
  - [x] SubTask 7.1: 测试 incremental_update 无基准时转 recompute：构造无 PnlRecord 的场景，验证不产生 avg_buy_price=0 的异常
  - [x] SubTask 7.2: 测试 heartbeat_snapshot：mock 最新 PnlRecord 和当前价，验证心跳快照写入正确
  - [x] SubTask 7.3: 测试 avg_buy_price=0 兜底：构造 net_position>0 但 avg_buy_price=0，验证 unrealized_pnl=0
  - [x] SubTask 7.4: 测试 PnLChart 分桶：验证 24h 模式生成 288 桶，all 模式按跨度自适应
  - [x] SubTask 7.5: 测试 start_time/end_time 过滤：验证只返回时间窗口内记录

# Task Dependencies
- Task 1（修正增量核算）独立
- Task 2（心跳快照）依赖 Task 1（heartbeat_snapshot 复用 avg_buy_price 兜底逻辑）
- Task 3（API 参数）独立
- Task 4（PnLChart 分桶）独立，可与 Task 3 并行
- Task 5（DashboardPage）依赖 Task 3（需 start_time 参数）
- Task 6（清理历史数据）独立
- Task 7（测试）依赖 Task 1-5 完成
