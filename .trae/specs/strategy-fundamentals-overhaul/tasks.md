# Tasks - 策略资金·杠杆·仓位隔离与响应性重构

## 第一周：策略资金与杠杆管理（Capital & Leverage）

- [x] Task 1: 策略投入资金上限
  - [x] SubTask 1.1: BaseStrategy 新增 `investment_amount` / `max_position_value` 参数与校验逻辑
  - [x] SubTask 1.2: 下单前资金约束校验：当前持仓名义价值 + 新单 ≤ investment_amount × lever，超限拒单并记录 `capital_limit` 事件
  - [x] SubTask 1.3: 策略实例表单（InstanceFormModal）新增投入资金输入字段
  - [x] SubTask 1.4: 旧实例参数迁移逻辑（缺字段时迁移默认值并记录 `param_migrated` 事件）
  - [x] SubTask 1.5: 单元测试：资金约束拒单、迁移默认值、边界场景

- [x] Task 2: 合约杠杆设置
  - [x] SubTask 2.1: backend/services/okx/trade.py 新增 `set_leverage(inst_id, lever, mgn_mode, pos_side)` 方法
  - [x] SubTask 2.2: BaseStrategy 启动时按 `lever` / `td_mode` 参数调用 set_leverage，失败阻止启动并记录 `leverage_set_failed`
  - [x] SubTask 2.3: 下单数量计算改为 `qty = investment_amount × lever / price`（合约）
  - [x] SubTask 2.4: 策略实例表单新增 lever / td_mode 字段（仅合约品种显示）
  - [x] SubTask 2.5: 单元测试：set_leverage 调用、失败阻断、数量计算

- [x] Task 3: 保证金与强平价监控
  - [x] SubTask 3.1: backend/services/okx/account.py 新增 `get_position_risk(inst_id)` 返回 margin ratio / liq_px
  - [x] SubTask 3.2: 策略 tick 内查询保证金占用率，> 80% 记录 `margin_warning`，> 95% 拒单 `margin_critical`
  - [x] SubTask 3.3: 保证金告警接入通知服务
  - [x] SubTask 3.4: 单元测试：保证金阈值触发

## 第二周：仓位隔离与多策略归因验证（Position Isolation）

- [x] Task 4: 虚拟仓位账本
  - [x] SubTask 4.1: BaseStrategy 新增 `_virtual_position`（per-strategy 净持仓、均价、累计已实现），与 PnL 引擎对齐
  - [x] SubTask 4.2: PnlAccountingEngine 新增 `reconcile_positions(account_id, symbol)`：聚合该账户该品种所有策略虚拟持仓，对比交易所 `get_position` 真实持仓
  - [x] SubTask 4.3: 差异 > 容差（默认 0.0001）记录 `position_mismatch` 事件 + 告警
  - [x] SubTask 4.4: 单元测试：虚拟账本累加、对账差异检测

- [x] Task 5: 多策略同品种持仓冲突检测
  - [x] SubTask 5.1: 平仓前校验真实可用仓位（真实持仓 - 其他策略虚拟持仓占用），不足时拒绝/告警 `position_conflict`
  - [x] SubTask 5.2: 前端仓位看板标注冲突策略
  - [x] SubTask 5.3: 单元测试：冲突检测拒绝路径

- [x] Task 6: 多策略同品种 PnL 隔离 E2E 验证
  - [x] SubTask 6.1: 编写 test_demo_multi_strategy_isolation.py：2 个策略实例跑同一 ETH-SWAP（一网格一趋势）
  - [x] SubTask 6.2: 验证各自 PnL 独立可核对（订单归各策略、虚拟持仓独立）
  - [x] SubTask 6.3: 验证虚拟持仓之和 = 真实持仓（对账通过）
  - [x] SubTask 6.4: 验证一策略停止不影响另一策略 PnL 连续性
  - [x] SubTask 6.5: 集成至 run_e2e_tests.py 并生成报告

## 第三周：网格响应性重构（Grid Responsiveness）

- [x] Task 7: 成交→补单响应性重构
  - [x] SubTask 7.1: grid_strategy `_on_order_filled` 改为批量预挂模式（买单成交时若卖单尚未挂出则批量补挂相邻档位）
  - [x] SubTask 7.2: 主循环 `await asyncio.sleep(3)` 改为可配（默认 1s），WebSocket fill 事件为快速路径不依赖循环
  - [x] SubTask 7.3: REST 兜底轮询间隔从 15s 降至可配（默认 5s）
  - [x] SubTask 7.4: OrderManager 记录 `fill_ts` 与 `place_ts`，计算补单延迟
  - [x] SubTask 7.5: 延迟 > 阈值（默认 2s）记录 `order_latency` 事件

- [x] Task 8: 突发行情快速响应
  - [x] SubTask 8.1: market_data_service 计算短时价格波动率（5s 窗口）
  - [x] SubTask 8.2: 波动 > 阈值（默认 1%）触发 `volatility_spike` 事件，主循环 sleep 临时降至 0.5s 持续 N 秒
  - [x] SubTask 8.3: 快速路径触发批量撤单+重挂（对齐新价位）
  - [x] SubTask 8.4: 单元测试：波动检测、快速路径触发

- [x] Task 9: maker-only 下单选项
  - [x] SubTask 9.1: 策略参数新增 `post_only` 选项，下单时 `ordType=post_only`（OKX 支持）
  - [x] SubTask 9.2: post_only 单被拒时自动重挂（避免空档）
  - [x] SubTask 9.3: 单元测试：post_only 下单与重挂

## 第四周：差异化定位与连续测试闭环（Positioning & Continuous Test Loop）

- [x] Task 10: 产品差异化定位文档
  - [x] SubTask 10.1: 撰写 docs/product-positioning.md：vs FMZ/Coinrule 差异化矩阵
  - [x] SubTask 10.2: 提炼核心卖点（本地优先隐私 / 真实仓位隔离归因 / 可视化策略构建 / 回测即实盘参数对齐）
  - [x] SubTask 10.3: 前端关于页/登录页展示差异化卖点

- [x] Task 11: 连续回归测试闭环
  - [x] SubTask 11.1: 扩展 scripts/daily_regression.py：覆盖 W1-W3 全部能力（资金/杠杆/隔离/延迟）
  - [x] SubTask 11.2: 报告新增指标：延迟 P50/P95、保证金占用率、仓位隔离差异、资金使用率
  - [x] SubTask 11.3: 退化检测：与前一日报告对比，退化超阈值标记并自动追加任务至 tasks.md
  - [x] SubTask 11.4: 报告支持 7/30 天趋势图
  - [x] SubTask 11.5: 配置为可长期不间断运行（cron 或常驻进程）

- [x] Task 12: 延迟与资金健康看板
  - [x] SubTask 12.1: MonitoringPage 新增延迟面板（补单延迟 P50/P95 实时图）
  - [x] SubTask 12.2: 新增资金健康面板（各策略投入资金使用率、保证金占用率）
  - [x] SubTask 12.3: 新增仓位隔离面板（虚拟 vs 真实持仓差异、冲突策略列表）
  - [x] SubTask 12.4: 阈值告警卡片（超限高亮）

- [x] Task 13: 月度验收与持续优化
  - [x] SubTask 13.1: 运行完整 E2E 套件验收 W1-W4 全部检查点
  - [x] SubTask 13.2: 生成月度总结报告
  - [x] SubTask 13.3: 将连续回归套件配置为长期运行（月度计划结束后仍持续）

## Task Dependencies

- [Task 3 保证金监控] 依赖 [Task 2 杠杆设置] 完成
- [Task 5 冲突检测] 依赖 [Task 4 虚拟仓位账本] 完成
- [Task 6 隔离 E2E] 依赖 [Task 4 + Task 5] 完成
- [Task 7 响应性重构] 依赖 [Task 1 资金约束]（下单数量计算对齐）
- [Task 8 突发行情] 依赖 [Task 7] 的事件驱动循环
- [Task 11 连续回归] 依赖 [Task 1-9 全部完成]
- [Task 12 健康看板] 依赖 [Task 7 延迟度量 + Task 4 对账]
- [Task 13 验收] 依赖 [Task 1-12 全部完成]

## 并行化建议

以下任务无依赖，可并行执行：
- [Task 1 资金上限] 可与 [Task 2 杠杆设置] 部分并行（参数 schema 同期设计）
- [Task 4 虚拟仓位账本] 可与 [Task 7 响应性重构] 并行（不同模块）
- [Task 10 差异化文档] 可与 [Task 9 maker-only] 并行
- [Task 12 健康看板] 可与 [Task 11 连续回归] 部分并行
