# 一个月连续开发与完善计划 Spec

## Why

项目当前整体完成度约 78%，spec 检查点完成度 95%，在 DSL 策略引擎、PnL 核算、网络韧性、桌面分发四个维度已达生产级水准。但与成熟竞品（FMZ/Coinrule）对比仍有明显短板：真实历史回测缺失、P1/P2 积木库未交付、告警通知仅入库、策略模板无分享机制、44 项 spec 检查点未落地、10 项潜在 Bug 待修复、前端存在 5 万行巨型文件技术债。

用户希望在模拟盘 API（已存数据库）支持下，进行一个月连续不间断的「测试→发现漏洞→修复→补全功能→功能完备」闭环开发，使项目达到可与 FMZ/Coinrule 正面竞争的产品成熟度。

## What Changes

### 第一周：稳定化与债务清理（Week 1 - Stabilization）
- **修复**：10 项已识别潜在 Bug（arbitrage 无 PnL 核算、trend 异常静默、网格匹配容差、daily_pnl_baseline 重启丢失、_get_account_equity 重复调用等）
- **补齐**：44 项未完成 spec 检查点（okx-api-wrapper-upgrade 31 项、fix-pnl-realized-unrealized-consistency 9 项、bootstrap-mihomo-mmdb 3 项、add-data-maintenance 1 项）
- **新增**：模拟盘自动化测试套件（基于已存数据库的 demo API），覆盖策略启停、订单成交、PnL 核算、WebSocket 推送全链路
- **重构**：拆分 StrategiesPage.tsx（54116 行）和 DashboardPage.tsx（20813 行）为子组件

### 第二周：核心功能补全（Week 2 - Core Features）
- **新增**：真实历史回测引擎（基于 OKX 历史 K 线 API，支持滑点/手续费模拟）
- **新增**：P1 积木库交付（cross_above/cross_below/in_range 条件；MACD/EMA/KDJ/Volatility 指标；stop_loss/take_profit/set_var/get_var 动作）
- **新增**：WebSocket 公共行情频道订阅（ticker/candle/books），替代前端轮询
- **补全**：arbitrage_strategy 完整 PnL 核算与 DB 恢复；advanced_grid_hedge 真实网格逻辑
- **新增**：API 限流配额监控与前端展示

### 第三周：高级功能扩展（Week 3 - Advanced）
- **新增**：告警通知系统（邮件 / Webhook / Telegram 三渠道，策略事件触发）
- **新增**：PnL 归因分析（按时间段/币种/策略类型分解盈亏）
- **新增**：策略模板分享机制（导出/导入 JSON，本地模板库）
- **新增**：on_balance_change / on_funding_rate / on_position_close 事件积木
- **新增**：多策略并行执行优化（同账户多策略 API 调用合并）

### 第四周：打磨与产品化（Week 4 - Polish）
- **新增**：CI/CD 流水线（GitHub Actions：lint + test + build）
- **新增**：性能基准测试与优化（策略 tick 吞吐、PnL 核算耗时、WebSocket 延迟）
- **完善**：前端响应式布局与移动端适配优化
- **新增**：自动化回归测试套件（每日模拟盘跑批，生成测试报告）
- **完善**：用户文档与策略编写指南
- **新增**：策略沙箱模式（模拟盘 dry-run，不触发真实下单）

## Impact

### 受影响代码
- **后端核心**：
  - [backend/strategies/](file:///e:/New%20folder%20(2)/quant_okx/backend/strategies/) — 全部策略修复与补全
  - [backend/dsl/blocks/](file:///e:/New%20folder%20(2)/quant_okx/backend/dsl/blocks/) — P1 积木库扩展
  - [backend/dsl/executor.py](file:///e:/New%20folder%20(2)/quant_okx/backend/dsl/executor.py) — 风控基线持久化、回测引擎集成
  - [backend/services/](file:///e:/New%20folder%20(2)/quant_okx/backend/services/) — WebSocket 公共频道、通知服务、回测服务
  - [backend/routers/](file:///e:/New%20folder%20(2)/quant_okx/backend/routers/) — 新增回测/通知/分析端点
- **前端**：
  - [frontend/src/pages/StrategiesPage.tsx](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/pages/StrategiesPage.tsx) — 拆分重构
  - [frontend/src/pages/DashboardPage.tsx](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/pages/DashboardPage.tsx) — 拆分重构
  - 新增 BacktestPage.tsx / NotificationsPage.tsx / AnalyticsPage.tsx
- **测试**：
  - [backend/tests/](file:///e:/New%20folder%20(2)/quant_okx/backend/tests/) — 新增回测/通知/归因测试
  - 新增 e2e 模拟盘自动化测试套件
- **基础设施**：
  - 新增 .github/workflows/ CI 配置
  - 新增 docker/ 容器化支持（可选）

### 受影响 specs
- `okx-api-wrapper-upgrade`（补齐 31 项检查点）
- `fix-pnl-realized-unrealized-consistency`（补齐 9 项检查点）
- `bootstrap-mihomo-mmdb`（补齐 3 项检查点）
- `add-data-maintenance`（补齐 1 项检查点）
- `rebrand-strategy-builder-qsm`（P1 积木扩展）
- `add-composable-strategy-dsl`（回测引擎集成）

## ADDED Requirements

### Requirement: 模拟盘自动化测试套件

系统 SHALL 提供基于 OKX 模拟盘 API 的端到端自动化测试套件，覆盖策略启动→挂单→成交→PnL 核算→WebSocket 推送→停止全链路，每日可自动执行并生成测试报告。

#### Scenario: 每日自动回归测试
- **WHEN** 每日定时触发模拟盘测试套件
- **THEN** 自动启动网格/趋势/套利策略实例（模拟盘）
- **AND** 验证订单挂出、成交回调、PnL 快照写入、WebSocket 推送
- **AND** 生成测试报告（通过率/失败项/截图）

#### Scenario: 策略异常自动捕获
- **WHEN** 测试过程中策略出现异常（订单失败/PnL 不一致/连接断开）
- **THEN** 自动记录异常详情与堆栈
- **AND** 不影响其他策略测试继续执行

### Requirement: 真实历史回测引擎

系统 SHALL 提供基于 OKX 历史 K 线数据的回测引擎，支持配置初始资金、滑点、手续费，输出收益曲线、最大回撤、夏普比率等指标。

#### Scenario: 回测网格策略
- **WHEN** 用户选择网格策略模板，配置回测时间范围与参数
- **THEN** 引擎拉取历史 K 线，模拟挂单成交
- **AND** 输出收益曲线、总收益、最大回撤、夏普比率、胜率
- **AND** 回测结果可在前端可视化展示

#### Scenario: 回测与实盘参数对齐
- **WHEN** 用户对回测结果满意
- **THEN** 可一键将回测参数导出为策略实例配置
- **AND** 实盘策略使用与回测一致的参数

### Requirement: P1 积木库交付

系统 SHALL 交付 P1 优先级积木库，包含交叉类条件、技术指标、风控动作、状态管理动作，使 DSL 表达力达到竞品水平。

#### Scenario: 使用交叉条件
- **WHEN** 用户在规则中使用 `cross_above(fast_ema, slow_ema)` 条件
- **THEN** 编辑器展示"快线上穿慢线"
- **AND** 执行时正确检测 EMA 交叉信号

#### Scenario: 使用 MACD 指标
- **WHEN** 用户在规则中使用 `macd(period_fast=12, period_slow=26, period_signal=9)` 指标
- **THEN** 返回 MACD 柱状值、信号线、DIF/DEA
- **AND** 可作为条件输入

#### Scenario: 使用 stop_loss 动作
- **WHEN** 用户在规则中配置 `stop_loss(threshold=-0.05)` 动作
- **THEN** 持仓亏损达 5% 时自动平仓
- **AND** 记录止损事件到策略事件表

### Requirement: 告警通知系统

系统 SHALL 提供多渠道告警通知（邮件/Webhook/Telegram），策略事件（订单成交/止损触发/异常停止）可配置触发通知。

#### Scenario: 策略异常停止通知
- **WHEN** 策略因连续网络异常自动停止
- **THEN** 触发已配置的通知渠道（邮件/Webhook/Telegram）
- **AND** 通知内容含策略名称、停止原因、最后 PnL

#### Scenario: 通知渠道配置
- **WHEN** 用户在设置页配置 Telegram Bot Token 与 Chat ID
- **THEN** 发送测试通知验证连通性
- **AND** 保存配置后策略事件可触发该渠道

### Requirement: PnL 归因分析

系统 SHALL 提供 PnL 归因分析，支持按时间段、币种、策略类型分解盈亏，帮助用户理解收益来源。

#### Scenario: 按币种归因
- **WHEN** 用户查看归因分析页，选择"按币种"维度
- **THEN** 展示各币种贡献的盈亏金额与占比
- **AND** 可下钻查看该币种的订单明细

#### Scenario: 按策略类型归因
- **WHEN** 用户选择"按策略类型"维度
- **THEN** 展示网格/趋势/套利各类策略的盈亏对比
- **AND** 含胜率、平均收益、最大回撤

### Requirement: 策略模板分享机制

系统 SHALL 支持策略模板的导出/导入（JSON 格式），用户可本地管理模板库。

#### Scenario: 导出策略模板
- **WHEN** 用户在模板管理页点击"导出"
- **THEN** 生成包含 QS-Model 完整配置的 JSON 文件
- **AND** 可分享给其他用户

#### Scenario: 导入策略模板
- **WHEN** 用户点击"导入"并选择 JSON 文件
- **THEN** 校验 QS-Model 结构合法性
- **AND** 导入成功后出现在模板列表

### Requirement: WebSocket 公共行情频道

系统 SHALL 订阅 OKX WebSocket 公共行情频道（ticker/candle/books），替代前端 REST 轮询，降低 API 调用与延迟。

#### Scenario: 订阅 ticker 频道
- **WHEN** 策略实例启动
- **THEN** 后端订阅该 symbol 的 ticker 频道
- **AND** 行情更新通过 WebSocket 推送至前端
- **AND** 不再每 3 秒轮询 REST API

### Requirement: CI/CD 流水线

系统 SHALL 配置 GitHub Actions CI 流水线，在每次提交时自动运行 lint + 单元测试 + 构建，保证代码质量。

#### Scenario: 提交触发 CI
- **WHEN** 开发者提交代码到仓库
- **THEN** GitHub Actions 自动运行后端 pytest + 前端 eslint + tsc
- **AND** 构建前端产物与 Windows 安装包
- **AND** 失败时阻止合并

## MODIFIED Requirements

### Requirement: 策略执行健壮性（来自 fix-runtime-bugs-and-template-mgmt）

[原内容：策略执行含状态去重、网络退避、连接共享]

**修改**：新增 daily_pnl_baseline 持久化（跨重启不丢失）、_get_account_equity 调用合并（每 tick 至多一次）、arbitrage/trend 策略补齐 PnL 核算与异常日志。

### Requirement: 前端页面架构（来自 fix-responsive-layout）

[原内容：响应式布局适配]

**修改**：StrategiesPage.tsx 与 DashboardPage.tsx 拆分为子组件（每个子组件不超过 1000 行），状态管理提取为自定义 hook。

## REMOVED Requirements

### Requirement: 策略模板在线市场
**Reason**: 在线市场需后端服务与用户体系，超出本地平台定位
**Migration**: 改为本地模板库 + JSON 导入导出分享机制

### Requirement: 多交易所支持
**Reason**: 架构深度耦合 OKX API，迁移成本过高，且项目定位为 OKX 量化平台
**Migration**: 保持 OKX 单交易所，但抽象 API 层接口为未来扩展预留

## 范围说明

### 本 spec 覆盖
- 一个月内可交付的功能补全与 Bug 修复
- 模拟盘自动化测试体系建立
- 与竞品核心能力对齐（回测/P1 积木/告警/归因）
- 前端技术债清理与 CI/CD 建立

### 本 spec 不覆盖
- 多交易所抽象（架构耦合过深，需独立大版本）
- 在线策略市场（需后端服务，超出本地定位）
- 移动端原生 App（响应式适配即可）
- AI 策略生成（独立研究方向）

## 月度交付里程碑

| 周次 | 主题 | 交付物 | 验收标准 |
|------|------|--------|----------|
| W1 | 稳定化 | Bug 修复 + 测试套件 + 前端拆分 | 0 已知致命 Bug，测试通过率 100% |
| W2 | 核心功能 | 回测引擎 + P1 积木 + WS 公共频道 | 回测可跑，P1 积木 12+ 个 |
| W3 | 高级功能 | 告警通知 + PnL 归因 + 模板分享 | 三渠道通知可用，归因图表展示 |
| W4 | 产品化 | CI/CD + 性能优化 + 文档 | CI 绿灯，性能基准达标 |
