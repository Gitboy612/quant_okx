# Tasks - 仪表盘盈亏/归因/仓位冲突/QSModel 研究闭环修复

## A. 盈亏曲线切换响应（P0）

- [x] Task 1: 修复 useDashboardState useEffect 依赖与 summary 传参
  - [x] SubTask 1.1: `useDashboardState.ts` loadBaseData 的 useEffect 依赖从 `[]` 改为 `[loadBaseData]`
  - [x] SubTask 1.2: `getPnlSummary` 调用传入 `strategy_instance_id`（selectedStrategyId || undefined）
  - [x] SubTask 1.3: 后端 `pnl.py` `get_pnl_summary` 端点增加 `strategy_instance_id: int | None = Query(None)` 参数并过滤
  - [x] SubTask 1.4: 切换策略时显示 loading 态（pnlRecords 为空或请求中）
  - [x] SubTask 1.5: 验证：切换策略后 PnL 曲线立即变化，KPI 卡片显示该策略数据

## B. PnL 为 0 根因修复（P0）

- [x] Task 2: recompute 无成交不写全 0 记录
  - [x] SubTask 2.1: `pnl_accounting_engine.recompute` 在 `orders` 为空时返回 None 而非写入全 0 PnlRecord
  - [x] SubTask 2.2: `heartbeat_snapshot` 无基准记录时调用 recompute 兜底（而非直接返回 None）
  - [x] SubTask 2.3: `run_iteration.py` 健康检查的 recompute 调用：处理 None 返回值，不写全 0
  - [x] SubTask 2.4: `pnl.py` recompute 端点处理 None 返回值（返回 404 或空响应）

- [x] Task 3: summary 跳过全 0 记录与行情告警
  - [x] SubTask 3.1: `pnl.py` `get_pnl_summary` 跳过 `total_pnl=0 and net_position=0 and order_count=0` 的无意义记录（向前找最近的有效记录）
  - [x] SubTask 3.2: `_get_current_price` 失败时记录 `market_data_unavailable` warning 事件
  - [x] SubTask 3.3: `avg_buy_price=0 且 net_position>0` 兜底逻辑从静默置 0 改为告警 + 置 0（记录 `pnl_anomaly_zero_avg_buy` 事件）
  - [x] SubTask 3.4: 单元测试：recompute 无成交返回 None、heartbeat 兜底、summary 跳过全 0、行情失败告警

## C. 归因分析三维度统一口径（P1）

- [x] Task 4: by_symbol 重构为基于 PnlRecord
  - [x] SubTask 4.1: `attribution_service.get_attribution_by_symbol` 改为查 PnlRecord，通过 StrategyInstance.symbol 关联聚合各实例 latest PnlRecord
  - [x] SubTask 4.2: avg_buy_price 按策略实例独立计算后聚合加权平均（qty 加权）
  - [x] SubTask 4.3: 补充 unrealized_pnl 字段（聚合各策略实例 unrealized）
  - [x] SubTask 4.4: realized_pnl 取 PnlRecord.realized_pnl（累计口径，与 by_strategy_type 一致）
  - [x] SubTask 4.5: 时间过滤字段改为 recorded_at

- [x] Task 5: 三维度口径统一与验证
  - [x] SubTask 5.1: 确认 by_strategy_type 与 by_period 均基于 PnlRecord.realized_pnl（累计口径）
  - [x] SubTask 5.2: by_period 的 unrealized 取期末值（已是），确认与 by_strategy_type 一致
  - [x] SubTask 5.3: 单元测试：同账户同时间段三维度总 realized/unrealized 一致
  - [x] SubTask 5.4: 前端归因看板增加"口径说明"提示（累计口径）

## D. 仓位冲突改代数叠加（P1）

- [x] Task 6: check_position_conflict 改代数和
  - [x] SubTask 6.1: `base_strategy.check_position_conflict` 的 `others_occupied` 从绝对值之和改为代数和（带符号）
  - [x] SubTask 6.2: `available = real_pos - others_occupied`（代数和）
  - [x] SubTask 6.3: `is_conflict = available < abs(net_position)`（策略无法独立平掉自己净持仓时才算冲突）
  - [x] SubTask 6.4: 单元测试：多空对冲不误报、单向持仓正常、超真实持仓才冲突

- [x] Task 7: position_conflicts 端点与看板改代数和
  - [x] SubTask 7.1: `monitoring.py` `/api/monitoring/position_conflicts` 端点同步改用代数和
  - [x] SubTask 7.2: 前端 MonitoringPage 仓位冲突看板区分「仓位隔离对账」（reconcile_positions，数据一致性）与「平仓能力」（position_conflicts，操作可行性）
  - [x] SubTask 7.3: 增加"对冲组"标注（同账户同 symbol 多空策略组）
  - [x] SubTask 7.4: 单元测试：端点返回代数和、看板分拆展示

## E. 定时任务 QSModel 研究闭环（P2）

- [x] Task 8: QSModel 生成器模块
  - [x] SubTask 8.1: 新建 `backend/research/qsm_generator.py`，定义四类生成器函数
  - [x] SubTask 8.2: 经典变体生成器：base_strategy 调参（grid 的 grid_count/order_qty/lever 组合），生成 QSModelConfig
  - [x] SubTask 8.3: DSL 创新生成器：base_strategy + rules 组合（grid + cross_above 暂停 + rebalance_position 动作），生成真正 DSL 复合策略
  - [x] SubTask 8.4: 回测筛选生成器：生成多候选 QSModel，调 `dsl/dry_run.py` 回测，按夏普/回撤筛选
  - [x] SubTask 8.5: 参数 A/B 生成器：复制已运行策略 QSModel，用 `$params.xxx` 生成不同参数变体
  - [x] SubTask 8.6: 所有生成器配置 risk_filter 段（daily_max_loss/stop_loss/take_profit）

- [x] Task 9: run_iteration.py should_start 分支实现
  - [x] SubTask 9.1: 研究类型轮换 N=0-3 分别调用对应生成器
  - [x] SubTask 9.2: 调用 `/api/dsl/validate` 校验生成的 QSModel
  - [x] SubTask 9.3: 调用 `/api/dsl/dry-run` 历史回放预验证（近 30 天）
  - [x] SubTask 9.4: 通过后创建 StrategyTemplate（strategy_type="composable"）+ StrategyInstance（params 含 qs_model_config）并调 strategy_engine.start_strategy
  - [x] SubTask 9.5: 失败时记录原因到 execution.log，跳过，不影响其他

- [x] Task 10: 优质策略基因保留与反馈闭环
  - [x] SubTask 10.1: 策略满 10 天评估后，优质策略参数组合存入 `backend/tests/reports/strategy_research/gene_pool.json`
  - [x] SubTask 10.2: 生成器优先从 gene_pool.json 取基因组合，避免重复试错
  - [x] SubTask 10.3: 劣质策略参数组合加入黑名单，不再生成
  - [x] SubTask 10.4: 单元测试：生成器输出合法 QSModel、validate 通过、gene_pool 读写

# Task Dependencies

- [Task 1] 独立（前端 useEffect）
- [Task 2] 独立（后端 recompute）
- [Task 3] 依赖 [Task 2]（summary 跳过全 0 依赖 recompute 不再写全 0）
- [Task 4] 独立（归因重构）
- [Task 5] 依赖 [Task 4]（口径统一验证）
- [Task 6] 独立（仓位冲突算法）
- [Task 7] 依赖 [Task 6]（端点与看板跟随算法）
- [Task 8] 独立（生成器模块）
- [Task 9] 依赖 [Task 8]（should_start 调生成器）
- [Task 10] 依赖 [Task 9]（基因反馈闭环）

## 并行化建议

- [Task 1 前端]、[Task 2 后端 recompute]、[Task 4 归因]、[Task 6 仓位冲突]、[Task 8 生成器] 五者无依赖，可全部并行
- [Task 3] 等 [Task 2] 完成
- [Task 5] 等 [Task 4] 完成
- [Task 7] 等 [Task 6] 完成
- [Task 9] 等 [Task 8] 完成
- [Task 10] 等 [Task 9] 完成
