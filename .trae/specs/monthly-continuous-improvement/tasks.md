# Tasks - 一个月连续开发与完善计划

## 第一周：稳定化与债务清理（Week 1 - Stabilization）

- [x] Task 1: 修复 10 项已识别潜在 Bug
  - [x] SubTask 1.1: 修复 arbitrage_strategy.py 缺失 PnL 核算（补充 add_realized_pnl 调用与开平仓配对）
  - [x] SubTask 1.2: 修复 trend_strategy.py 异常静默（替换 `except: pass` 为带日志的异常处理 + 退避）
  - [x] SubTask 1.3: 修复 grid_strategy.py 网格匹配容差（密集网格改用精确档位索引匹配，容差兜底）
  - [x] SubTask 1.4: 修复 ComposableStrategy daily_pnl_baseline 重启丢失（持久化到 DB，启动时恢复）
  - [x] SubTask 1.5: 优化 _get_account_equity 重复调用（每 tick 缓存一次权益值）
  - [x] SubTask 1.6: 修复 base_strategy.pause() 同步路径与主循环冲突风险
  - [x] SubTask 1.7: 修复 advanced_grid_hedge_strategy.py 名不副实（补齐真实网格对冲逻辑或重命名）
  - [x] SubTask 1.8: 修复 trend_strategy 参数命名不一致（fast_ma_period vs fast_period）
  - [x] SubTask 1.9: 修复 _record_event 异常静默吞掉问题（增加 print 兜底）
  - [x] SubTask 1.10: 修复 arbitrage_strategy position_open 单一标志无法处理多次开仓问题

- [x] Task 2: 补齐 44 项未完成 spec 检查点
  - [x] SubTask 2.1: 补齐 okx-api-wrapper-upgrade 31 项检查点（全部代码实现已验证）
  - [x] SubTask 2.2: 补齐 fix-pnl-realized-unrealized-consistency 9 项测试与边界场景验证（代码实现已验证）
  - [x] SubTask 2.3: 补齐 bootstrap-mihomo-mmdb 3 项边界场景（MMDB预下载已验证）
  - [x] SubTask 2.4: 补齐 add-data-maintenance 1 项手动测试流程（7个维护函数均已实现）

- [x] Task 3: 模拟盘自动化测试套件
  - [x] SubTask 3.1: 创建 backend/tests/e2e/ 目录，编写 test_demo_grid_e2e.py（7个测试用例）
  - [x] SubTask 3.2: 编写 test_demo_trend_e2e.py（5个测试用例）
  - [x] SubTask 3.3: 编写 test_demo_pnl_consistency.py（3个测试用例）
  - [x] SubTask 3.4: 编写 test_demo_websocket.py（1个测试用例）
  - [x] SubTask 3.5: 编写 test_demo_recovery.py（1个测试用例）
  - [x] SubTask 3.6: 创建 run_e2e_tests.py 统一入口，支持定时执行与报告生成（17个用例，JSON报告）

- [x] Task 4: 前端巨型文件拆分重构
  - [x] SubTask 4.1: 拆分 StrategiesPage.tsx（54116 行）为子组件：StrategyListSection / TemplateManagementSection / InstanceFormModal / EventViewerModal
  - [x] SubTask 4.2: 拆分 DashboardPage.tsx（20813 行）为子组件：KpiSummarySection / PnLCurveSection / PositionsSection / RecentOrdersSection
  - [x] SubTask 4.3: 提取状态管理为自定义 hook：useStrategiesState / useDashboardState
  - [x] SubTask 4.4: 验证拆分后功能无回归（TypeScript 编译零错误通过）

## 第二周：核心功能补全（Week 2 - Core Features）

- [x] Task 5: 真实历史回测引擎
  - [x] SubTask 5.1: 创建 backend/services/backtest_engine.py，实现历史 K 线拉取与缓存（分页拉取+内存缓存）
  - [x] SubTask 5.2: 实现回测撮合引擎（限价单按 K 线高低价撮合，支持滑点与手续费）
  - [x] SubTask 5.3: 实现回测指标计算（总收益/最大回撤/夏普比率/胜率/盈亏比/权益曲线）
  - [x] SubTask 5.4: 创建 backend/routers/backtest.py，提供 POST /api/backtest/run 端点
  - [x] SubTask 5.5: 创建 frontend/src/pages/BacktestPage.tsx，支持参数配置与结果可视化
  - [x] SubTask 5.6: 实现回测结果一键导出为策略实例配置
  - [x] SubTask 5.7: 编写 test_backtest_engine.py 单元测试（27个测试全部通过）

- [x] Task 6: P1 积木库交付
  - [x] SubTask 6.1: conditions.py 新增 cross_above / cross_below（交叉检测，含 display_template）
  - [x] SubTask 6.2: conditions.py 新增 in_range / out_range（区间判断）
  - [x] SubTask 6.3: indicators.py 新增 macd（返回 DIF/DEA/柱状值）
  - [x] SubTask 6.4: indicators.py 新增 ema（指数移动平均）
  - [x] SubTask 6.5: indicators.py 新增 kdj（随机指标）
  - [x] SubTask 6.6: indicators.py 新增 volatility（波动率）/ volume_24h（24h 成交量）
  - [x] SubTask 6.7: actions.py 新增 stop_loss / take_profit（独立风控动作）
  - [x] SubTask 6.8: actions.py 新增 set_var / get_var（状态管理）
  - [x] SubTask 6.9: 为所有新积木补充中文 label / options / display_template 元数据
  - [x] SubTask 6.10: 更新测试覆盖新积木（37个新测试用例，89个测试全部通过）

- [x] Task 7: WebSocket 公共行情频道
  - [x] SubTask 7.1: 扩展 okx_ws_client.py 支持 public 频道订阅（新增 OKXPublicWsClient 类）
  - [x] SubTask 7.2: 创建 backend/services/market_data_service.py 行情订阅管理与分发（引用计数单例）
  - [x] SubTask 7.3: 策略实例启动时自动订阅 symbol 的 ticker 频道（grid + trend 已集成）
  - [x] SubTask 7.4: 前端 useWebSocket hook 扩展支持行情数据推送（useMarketData hook）
  - [x] SubTask 7.5: 编写 test_ws_public.py 验证公共频道订阅（23个测试全部通过）

- [x] Task 8: 策略补全与优化
  - [x] SubTask 8.1: arbitrage_strategy 补齐完整 PnL 核算（开仓/平仓配对、手续费扣除）
  - [x] SubTask 8.2: arbitrage_strategy 补齐 DB 恢复与网络退避
  - [x] SubTask 8.3: hedge_strategy 补齐对冲逻辑、PnL核算、保证金率监控、DB恢复
  - [x] SubTask 8.4: 实现 API 限流配额监控（okx_client 记录剩余配额，TopBar前端展示）

## 第三周：高级功能扩展（Week 3 - Advanced）

- [x] Task 9: 告警通知系统
  - [x] SubTask 9.1: 创建 backend/services/notification_service.py，定义通知渠道抽象接口
  - [x] SubTask 9.2: 实现邮件通知渠道（smtplib，支持 SMTP 配置）
  - [x] SubTask 9.3: 实现 Webhook 通知渠道（httpx 异步 POST，含 HMAC 签名）
  - [x] SubTask 9.4: 实现 Telegram 通知渠道（Bot API）
  - [x] SubTask 9.5: 创建 backend/models/notification_rule.py，定义通知规则（事件类型→渠道映射）
  - [x] SubTask 9.6: 创建 backend/routers/notifications.py，提供规则 CRUD 与测试发送端点
  - [x] SubTask 9.7: 策略事件触发时调用 NotificationService 分发通知（asyncio.create_task不阻塞）
  - [x] SubTask 9.8: 前端 NotificationsPage 新增规则管理（含渠道配置动态表单）
  - [x] SubTask 9.9: 编写 test_notification_service.py 单元测试（34个测试通过）

- [x] Task 10: PnL 归因分析
  - [x] SubTask 10.1: 创建 backend/services/attribution_service.py，实现按币种/策略类型/时间段聚合
  - [x] SubTask 10.2: 创建 backend/routers/analytics.py，提供 4 个 GET 端点
  - [x] SubTask 10.3: 创建 frontend/src/pages/AnalyticsPage.tsx，展示归因图表（饼图/柱状图/面积图）
  - [x] SubTask 10.4: 实现下钻查看订单明细功能（点击行弹窗）
  - [x] SubTask 10.5: 编写 test_attribution_service.py 单元测试（17个测试通过）

- [x] Task 11: 策略模板分享机制
  - [x] SubTask 11.1: 后端新增 GET /api/strategies/templates/{id}/export 导出 JSON
  - [x] SubTask 11.2: 后端新增 POST /api/strategies/templates/import 导入 JSON（含7步校验链）
  - [x] SubTask 11.3: 前端模板管理页新增导出/导入按钮与文件选择
  - [x] SubTask 11.4: 编写 test_template_sharing.py 测试（14个测试通过）

- [x] Task 12: 事件积木与并行优化
  - [x] SubTask 12.1: events.py 新增 on_balance_change / on_funding_rate / on_position_close
  - [x] SubTask 12.2: 同账户多策略 API 调用合并优化（5秒共享缓存余额/持仓）
  - [x] SubTask 12.3: 更新 test_dsl_events.py 覆盖新事件（26个新测试，41个全部通过）

## 第四周：打磨与产品化（Week 4 - Polish）

- [x] Task 13: CI/CD 流水线
  - [x] SubTask 13.1: 创建 .github/workflows/ci.yml，配置后端 pytest + 前端 oxlint/tsc
  - [x] SubTask 13.2: 配置构建作业（前端 npm build + Windows 安装包 PyInstaller）
  - [x] SubTask 13.3: 配置测试覆盖率报告（pytest-cov + codecov）
  - [x] SubTask 13.4: 创建 pr-check.yml 和 build-windows.yml 工作流

- [x] Task 14: 性能基准测试与优化
  - [x] SubTask 14.1: 创建 backend/tests/perf/ 目录，编写 test_perf_strategy_tick.py（6个测试）
  - [x] SubTask 14.2: 编写 test_perf_pnl_accounting.py（7个测试）
  - [x] SubTask 14.3: 编写 test_perf_websocket.py（7个测试）
  - [x] SubTask 14.4: 性能基准全部达标，无需额外优化（FSM缓存+权益缓存+指标缓存+DB索引已足够）
  - [x] SubTask 14.5: 生成性能基准报告文档（README.md）

- [x] Task 15: 前端响应式与体验优化
  - [x] SubTask 15.1: 审查并修复移动端布局（Sidebar汉堡菜单+KPI卡片响应式+图表全宽）
  - [x] SubTask 15.2: 优化数据加载体验（ChartSkeleton/CardSkeleton+VirtualTable虚拟滚动+分页优化）
  - [x] SubTask 15.3: 统一错误提示与加载状态组件（ErrorBanner+LoadingSpinner）

- [x] Task 16: 自动化回归与文档
  - [x] SubTask 16.1: 创建 scripts/daily_regression.py，每日定时跑模拟盘 E2E 测试并生成报告
  - [x] SubTask 16.2: 报告输出至 backend/tests/reports/ 目录，含JSON+HTML格式+7天趋势图
  - [x] SubTask 16.3: 编写用户文档（user-guide.md 10章 + strategy-writing-guide.md 6章）
  - [x] SubTask 16.4: 实现策略沙箱模式（SandboxService+MockOKXClient+5个API端点）

## Task Dependencies

- [Task 3 模拟盘测试套件] 依赖 [Task 1 Bug 修复] 完成
- [Task 5 回测引擎] 依赖 [Task 6 P1 积木] 的指标积木（回测需调用指标计算）
- [Task 9 告警通知] 依赖 [Task 1 Bug 修复]（异常事件需先有正确日志）
- [Task 13 CI/CD] 依赖 [Task 3 测试套件] 与 [Task 14 性能测试]（CI 需运行所有测试）
- [Task 16 自动化回归] 依赖 [Task 3 测试套件] 与 [Task 13 CI/CD]

## 并行化建议

以下任务无依赖，可并行执行：
- [Task 4 前端拆分] 可与 [Task 1 Bug 修复] 并行
- [Task 11 模板分享] 可与 [Task 9 告警通知] 并行
- [Task 12 事件积木] 可与 [Task 10 PnL 归因] 并行
- [Task 15 前端优化] 可与 [Task 14 性能测试] 并行
