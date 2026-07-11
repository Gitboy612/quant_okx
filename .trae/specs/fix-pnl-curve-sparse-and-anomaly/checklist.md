# Checklist

## A. 增量核算 avg_buy_price 修正
- [x] incremental_update 检测无基准 PnlRecord 时转执行 recompute 逻辑
- [x] 计算 unrealized_pnl 时，avg_buy_price=0 且 net_position>0 则 unrealized_pnl=0
- [x] recompute 和 incremental_update 公共计算逻辑提取为辅助方法

## B. 心跳快照
- [x] PnlAccountingEngine 新增 heartbeat_snapshot 方法
- [x] heartbeat_snapshot 读取最新 PnlRecord 的 realized/net_position/avg_buy_price
- [x] heartbeat_snapshot 获取当前价计算 unrealized_pnl
- [x] heartbeat_snapshot 写入 PnlRecord（is_final=False），不更新 pnl_accounted
- [x] avg_buy_price=0 且 net_position>0 时 unrealized_pnl=0
- [x] _pnl_sampling_loop 增量返回 None 时每 5 分钟调用心跳快照
- [x] 维护 _last_heartbeat_ts 字典

## C. PnL API 时间窗口
- [x] GET /api/pnl 新增 start_time 查询参数
- [x] GET /api/pnl 新增 end_time 查询参数
- [x] 用 PnlRecord.recorded_at 过滤时间范围
- [x] 默认 limit 提升至 1000
- [x] 前端 listPnlRecords 参数类型支持 start_time/end_time

## D. PnLChart 自适应分桶
- [x] 新增 computeBucketInterval(timeRange, dataSpanMs) 函数
- [x] all 模式 span≤6h → 60s 间隔
- [x] all 模式 span≤24h → 300s 间隔
- [x] all 模式 span≤7d → 1800s 间隔
- [x] all 模式 span≤30d → 7200s 间隔
- [x] all 模式 span>30d → 21600s 间隔
- [x] 24h 模式改为 300s 间隔（288 桶）
- [x] 7d 模式改为 1800s 间隔（336 桶）
- [x] 30d 模式改为 7200s 间隔（360 桶）
- [x] all 模式不再直接返回原始数据点，改为自适应分桶
- [x] 数据填充保持 lastValue 沿用逻辑
- [x] 水平滚动阈值改为 400

## E. DashboardPage 时间窗口
- [x] 24h 模式传 start_time = now - 24h
- [x] 7d 模式传 start_time = 今日00:00 - 7天
- [x] 30d 模式传 start_time = 今日00:00 - 30天
- [x] all 模式不传 start_time

## F. 清理历史异常数据
- [x] 迁移脚本 fix_pnl_anomaly_records.py 已创建
- [x] 查询 unrealized_pnl 绝对值 > 1000 且 avg_buy_price=0 的记录
- [x] 删除或修正异常记录
- [x] 脚本幂等可重复运行

## G. 单元测试
- [x] 测试 incremental_update 无基准转 recompute
- [x] 测试 heartbeat_snapshot 写入正确
- [x] 测试 avg_buy_price=0 兜底 unrealized_pnl=0
- [x] 测试 PnLChart 24h 模式生成 288 桶
- [x] 测试 PnLChart all 模式自适应分桶
- [x] 测试 start_time/end_time 过滤
