# Checklist - 仪表盘盈亏/归因/仓位冲突/QSModel 研究闭环修复

## A. 盈亏曲线切换响应

- [x] useDashboardState.ts loadBaseData useEffect 依赖改为 [loadBaseData]
- [x] getPnlSummary 调用传入 strategy_instance_id
- [x] 后端 get_pnl_summary 端点支持 strategy_instance_id 过滤
- [x] 切换策略时显示 loading 态
- [x] 验证：切换策略后 PnL 曲线立即变化
- [x] 验证：KPI 卡片显示选中策略数据而非全局汇总

## B. PnL 为 0 根因修复

### recompute 无成交不写全 0
- [x] recompute 在 orders 为空时返回 None
- [x] heartbeat_snapshot 无基准时调 recompute 兜底
- [x] run_iteration.py 健康检查处理 recompute None 返回值
- [x] pnl.py recompute 端点处理 None 返回值

### summary 与行情告警
- [x] get_pnl_summary 跳过 total_pnl=0 and net_position=0 and order_count=0 记录
- [x] _get_current_price 失败记录 market_data_unavailable warning 事件
- [x] avg_buy_price=0 且 net_position>0 兜底改为告警 + 置 0
- [x] 单元测试：recompute 无成交返回 None
- [x] 单元测试：heartbeat 兜底
- [x] 单元测试：summary 跳过全 0
- [x] 单元测试：行情失败告警

## C. 归因分析三维度统一口径

### by_symbol 重构
- [x] get_attribution_by_symbol 改为基于 PnlRecord（通过 StrategyInstance.symbol 关联）
- [x] avg_buy_price 按策略实例独立计算后聚合加权平均
- [x] 补充 unrealized_pnl 字段
- [x] realized_pnl 取 PnlRecord.realized_pnl（累计口径）
- [x] 时间过滤字段改为 recorded_at

### 三维度一致性与验证
- [x] by_strategy_type 与 by_period 均基于 PnlRecord.realized_pnl（累计口径）
- [x] by_period 的 unrealized 取期末值
- [x] 单元测试：同账户同时间段三维度总 realized/unrealized 一致
- [x] 前端归因看板增加口径说明提示

## D. 仓位冲突改代数叠加

### check_position_conflict 算法
- [x] others_occupied 从绝对值之和改为代数和（带符号）
- [x] available = real_pos - others_occupied（代数和）
- [x] is_conflict = available < abs(net_position)
- [x] 单元测试：多空对冲不误报（A=+5, B=-5, A 平 5 通过）
- [x] 单元测试：单向持仓正常（A=+10, B=+5, A 平 10 通过）
- [x] 单元测试：超真实持仓才冲突（A=+10, B=+5, A 平 12 冲突）

### 端点与看板
- [x] position_conflicts 端点同步改用代数和
- [x] 前端 MonitoringPage 分拆「仓位隔离对账」与「平仓能力」看板
- [x] 增加"对冲组"标注（同账户同 symbol 多空策略组）
- [x] 单元测试：端点返回代数和

## E. 定时任务 QSModel 研究闭环

### QSModel 生成器
- [x] 新建 backend/research/qsm_generator.py
- [x] 经典变体生成器（base_strategy 调参）
- [x] DSL 创新生成器（base_strategy + rules 组合）
- [x] 回测筛选生成器（多候选 + dry_run 回测筛选）
- [x] 参数 A/B 生成器（$params.xxx 变量引用）
- [x] 所有生成器配置 risk_filter 段

### should_start 分支实现
- [x] 研究类型轮换 N=0-3 调用对应生成器
- [x] 调用 /api/dsl/validate 校验
- [x] 调用 /api/dsl/dry-run 历史回放预验证
- [x] 通过后创建 StrategyTemplate + StrategyInstance 并启动
- [x] 失败时记录原因到 execution.log

### 基因反馈闭环
- [x] 优质策略参数存入 gene_pool.json
- [x] 生成器优先从 gene_pool 取基因
- [x] 劣质策略参数加入黑名单
- [x] 单元测试：生成器输出合法 QSModel、validate 通过
- [x] 单元测试：gene_pool 读写

## 月度总体验收

- [x] 切换策略后盈亏曲线立即响应
- [x] KPI 卡片显示选中策略数据
- [x] 无成交策略不再产生全 0 PnlRecord
- [x] summary 跳过全 0 记录
- [x] 行情失败时告警而非显示 0
- [x] 归因三维度总 realized/unrealized 一致
- [x] by_symbol 含 unrealized_pnl
- [x] 多空对冲策略不再误报仓位冲突
- [x] 仓位隔离对账与平仓能力看板分拆
- [x] 定时任务真正生成 QSModel 创新策略
- [x] 生成的策略经 validate + dry_run 预验证
- [x] 优质策略基因保留与反馈闭环可用
