# Checklist - 策略资金·杠杆·仓位隔离与响应性重构

## 第一周：策略资金与杠杆管理

### 投入资金上限验证
- [x] BaseStrategy 含 investment_amount / max_position_value 参数与校验
- [x] 下单前资金约束校验生效（超限拒单 + `capital_limit` 事件）
- [x] InstanceFormModal 含投入资金输入字段
- [x] 旧实例参数迁移默认值并记录 `param_migrated` 事件
- [x] 单元测试覆盖资金约束、迁移、边界场景

### 杠杆设置验证
- [x] okx/trade.py 含 set_leverage 方法
- [x] 策略启动按 lever/td_mode 调用 set_leverage，失败阻断并记录 `leverage_set_failed`
- [x] 合约下单数量 = investment_amount × lever / price
- [x] InstanceFormModal 含 lever / td_mode 字段（仅合约品种显示）
- [x] 单元测试覆盖 set_leverage 调用与失败阻断

### 保证金监控验证
- [x] okx/account.py 含 get_position_risk 返回 margin ratio / liq_px
- [x] 保证金占用率 > 80% 记录 `margin_warning`，> 95% 拒单 `margin_critical`
- [x] 保证金告警接入通知服务
- [x] 单元测试覆盖阈值触发

## 第二周：仓位隔离与多策略归因验证

### 虚拟仓位账本验证
- [x] BaseStrategy 维护 per-strategy 虚拟持仓（净持仓/均价/已实现）
- [x] PnlAccountingEngine 含 reconcile_positions(account_id, symbol) 对账接口
- [x] 虚拟持仓之和 vs 真实持仓差异 > 容差记录 `position_mismatch` + 告警
- [x] 单元测试覆盖虚拟账本累加与对账差异

### 持仓冲突检测验证
- [x] 平仓前校验真实可用仓位，不足时拒绝/告警 `position_conflict`
- [x] 前端仓位看板标注冲突策略
- [x] 单元测试覆盖冲突拒绝路径

### 多策略隔离 E2E 验证
- [x] test_demo_multi_strategy_isolation.py 跑 2 策略同品种（网格+趋势 ETH-SWAP）
- [x] 各策略 PnL 独立可核对（订单归各策略）
- [x] 虚拟持仓之和 = 真实持仓（对账通过）
- [x] 一策略停止不影响另一策略 PnL 连续性
- [x] 集成至 run_e2e_tests.py 并生成报告

## 第三周：网格响应性重构

### 成交→补单响应性验证
- [x] grid_strategy `_on_order_filled` 改批量预挂模式
- [x] 主循环 sleep 可配（默认 1s），WebSocket fill 为快速路径
- [x] REST 兜底轮询间隔可配（默认 5s）
- [x] OrderManager 记录 fill_ts / place_ts，计算补单延迟
- [x] 延迟 > 阈值（默认 2s）记录 `order_latency` 事件
- [ ] 补单延迟 P95 < 2s（模拟盘实测）<!-- 需运行时验证 -->

### 突发行情快速响应验证
- [x] market_data_service 计算短时波动率（5s 窗口）
- [x] 波动 > 阈值触发 `volatility_spike` 事件，主循环 sleep 临时降至 0.5s
- [x] 快速路径触发批量撤单+重挂
- [x] 单元测试覆盖波动检测与快速路径

### maker-only 选项验证
- [x] 策略参数含 post_only 选项，下单 ordType=post_only
- [x] post_only 被拒时自动重挂
- [x] 单元测试覆盖 post_only 下单与重挂

## 第四周：差异化定位与连续测试闭环

### 差异化定位验证
- [x] docs/product-positioning.md 含 vs FMZ/Coinrule 差异化矩阵
- [x] 核心卖点提炼清晰（本地隐私/仓位隔离/可视化/回测即实盘）
- [x] 前端关于页/登录页展示差异化卖点

### 连续回归闭环验证
- [x] scripts/daily_regression.py 覆盖 W1-W3 全部能力
- [x] 报告含延迟 P50/P95、保证金占用率、隔离差异、资金使用率
- [x] 退化检测：与前一日对比，退化超阈值标记并自动追加 tasks.md
- [x] 报告支持 7/30 天趋势图
- [x] 配置为可长期不间断运行

### 健康看板验证
- [x] MonitoringPage 含延迟面板（补单延迟 P50/P95 实时图）
- [x] 含资金健康面板（投入资金使用率、保证金占用率）
- [x] 含仓位隔离面板（虚拟 vs 真实差异、冲突策略列表）
- [x] 阈值告警卡片超限高亮

## 月度总体验收

- [x] 策略可设置投入资金上限，超限拒单生效
- [x] 合约杠杆可设置并通过 OKX set_leverage 生效
- [x] 保证金占用率监控与告警可用
- [x] 多策略同品种各自 PnL 可独立核对（E2E 通过）
- [x] 虚拟持仓 vs 真实持仓对账差异在容差内
- [ ] 网格补单延迟 P95 < 2s（模拟盘实测）<!-- 需运行时验证 -->
- [x] 突发行情快速响应路径可用
- [x] 差异化定位文档完成
- [x] 连续回归套件可每日运行并生成报告
- [x] 退化检测可自动派生修复任务
- [x] 健康看板各项指标可视化
- [x] 连续回归套件配置为长期不间断运行
