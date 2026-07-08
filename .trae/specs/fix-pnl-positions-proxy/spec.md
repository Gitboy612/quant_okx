# 盈亏曲线修复 + 持仓优化 + 嵌入式代理 Spec

## Why
1) 盈亏曲线1分钟/1小时时间粒度无数据（数据点间隔约2分钟，1分钟窗口过短）；2) 当前持仓列表缺少表头且交易对显示原始名称（如ETH-USDT-SWAP）不便阅读；3) 当前代理方案需要系统级VPN，用户希望软件内部嵌入代理，仅对OKX API调用生效。

## What Changes
- 盈亏曲线时间粒度调整为更合理的窗口大小（5分钟/30分钟/1天/1周/全部），并支持数据密集时水平滚动
- 当前持仓列表添加表头行，交易对名称使用 `formatInstId` 转换为友好名称（如"ETH 永续"）
- 系统设置新增嵌入式代理管理：启动/停止本地代理核心、配置端口、查看代理状态和日志
- 后端新增代理核心管理服务，通过子进程管理本地 Clash 代理
- **BREAKING**: 无

## Impact
- Affected specs: `fix-dashboard-auth-ux`
- Affected code: 
  - 前端: `PnLChart.tsx`, `DashboardPage.tsx`, `SettingsPage.tsx`, `api/settings.ts`, `types/index.ts`
  - 后端: `services/proxy_service.py`, `routers/settings.py`, `services/okx_client.py`

## ADDED Requirements

### Requirement: 盈亏曲线时间粒度修正
系统 SHALL 提供合理的时间粒度选项，确保各粒度均有数据展示。

#### Scenario: 合理时间粒度
- **WHEN** 盈亏曲线渲染
- **THEN** 时间粒度选项为：5分钟、30分钟、1天、1周、全部
- **AND** 默认选中"1天"

#### Scenario: 数据密集时水平滚动
- **WHEN** 盈亏曲线数据点超过50个
- **THEN** 图表支持水平滚动查看全部数据

### Requirement: 持仓列表优化
系统 SHALL 在持仓列表中展示表头，并将交易对名称转换为用户友好格式。

#### Scenario: 持仓表头
- **WHEN** 持仓列表渲染
- **THEN** 显示表头行：交易对、方向、数量、标记价格、未实现盈亏

#### Scenario: 交易对友好名称
- **WHEN** 持仓列表展示交易对
- **THEN** ETH-USDT-SWAP 显示为"ETH 永续"，BTC-USDT-SWAP 显示为"BTC 永续"
- **AND** 未知交易对使用 `formatInstId` 自动转换为友好格式

### Requirement: 嵌入式代理管理
系统 SHALL 在设置页面提供嵌入式代理的启动/停止控制，以及状态监控。

#### Scenario: 代理未启动
- **WHEN** 用户首次进入代理设置
- **THEN** 显示"代理未启动"状态，提供"启动代理"按钮
- **AND** 可配置代理监听端口（默认 7890）

#### Scenario: 启动代理
- **WHEN** 用户点击"启动代理"
- **THEN** 后端启动本地代理核心进程
- **AND** 前端显示代理运行状态（运行中、端口、运行时长）
- **AND** 所有 OKX API 调用自动通过该代理

#### Scenario: 代理配置导入
- **WHEN** 用户上传 Clash 配置文件
- **THEN** 系统使用该配置启动代理
- **AND** 代理节点列表可查看和选择

#### Scenario: 代理状态显示
- **WHEN** 代理运行中
- **THEN** 显示代理状态指示器（绿色运行中）、监听端口、启动时间、当前选中节点

#### Scenario: 代理自动关联
- **WHEN** 嵌入式代理启动后
- **THEN** 系统自动设置 `OKXClient` 全局代理为 `http://127.0.0.1:${port}`
- **AND** 所有 OKX API 请求通过嵌入式代理发出

## MODIFIED Requirements
无。

## REMOVED Requirements
无。