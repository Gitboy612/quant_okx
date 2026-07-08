# 仪表盘权益修复 + 持仓展示 + 盈亏曲线优化 + 密码修改 + 启动登录验证 Spec

## Why
仪表盘存在多个严重问题：1) 总权益核算错误且进入页面时不自动获取实际资产，必须手动刷新；2) 账户资产不展示持仓情况；3) 盈亏曲线缺少时间粒度选择；4) 系统设置缺少密码修改功能；5) 每次启动应进行登录验证，当前直接记住 token 进入系统不安全。

## What Changes
- 仪表盘首次加载时改为调用实时余额接口（非缓存），确保总权益正确
- 账户资产区域新增持仓展示（position），显示各交易对的多空方向、数量、未实现盈亏
- 盈亏曲线组件新增时间粒度选择器（1分钟/1小时/1天/1周），优化渲染性能
- 系统设置新增密码修改功能（旧密码 + 新密码 + 确认新密码）
- 登录 token 从 localStorage 改为 sessionStorage，关闭浏览器后自动清除，强制重新登录
- **BREAKING**: token 存储方式变更，用户需重新登录

## Impact
- Affected specs: 无现有 spec 受影响
- Affected code: 
  - 前端: `DashboardPage.tsx`, `PnLChart.tsx`, `SettingsPage.tsx`, `useAuth.tsx`, `client.ts`, `accounts.ts`, `auth.ts`, `types/index.ts`
  - 后端: `routers/auth.py`, `routers/accounts.py`, `schemas/auth.py`

## ADDED Requirements

### Requirement: 仪表盘首次加载实时资产
系统 SHALL 在仪表盘首次加载时调用 OKX 实时余额接口获取总权益，而非使用缓存数据。

#### Scenario: 用户进入仪表盘
- **WHEN** 用户打开仪表盘页面
- **THEN** 系统自动调用 `/accounts/{id}/balance`（非 cached）获取实时资产数据
- **AND** 总权益 KPI 卡片显示正确的实时权益值

#### Scenario: 自动刷新使用实时接口
- **WHEN** 定时刷新触发
- **THEN** 系统调用实时余额接口（非缓存）

### Requirement: 账户持仓展示
系统 SHALL 在仪表盘账户资产区域展示当前持仓情况，包括持仓币种、多空方向、持仓数量、标记价格、未实现盈亏。

#### Scenario: 有持仓时展示
- **WHEN** 账户存在持仓
- **THEN** 在资产列表下方展示持仓表格，包含：交易对、方向（多/空）、数量、标记价格、未实现盈亏
- **AND** 未实现盈亏正数显示绿色，负数显示红色

#### Scenario: 无持仓时
- **WHEN** 账户无持仓
- **THEN** 显示"暂无持仓"提示

### Requirement: 盈亏曲线时间粒度选择
系统 SHALL 在盈亏曲线图表上方提供时间粒度选择器，支持按不同时间范围过滤盈亏数据。

#### Scenario: 用户选择时间粒度
- **WHEN** 用户点击"1小时"时间粒度按钮
- **THEN** 盈亏曲线仅展示最近1小时的数据点
- **AND** 图表自动更新

#### Scenario: 默认时间粒度
- **WHEN** 盈亏曲线首次渲染
- **THEN** 默认显示"1天"的数据

#### Scenario: 可用时间粒度
- **WHEN** 时间粒度选择器渲染
- **THEN** 提供选项：1分钟、1小时、1天、1周、全部

### Requirement: 密码修改
系统 SHALL 在系统设置页面提供密码修改功能，要求用户输入旧密码、新密码和确认新密码。

#### Scenario: 成功修改密码
- **WHEN** 用户输入正确的旧密码、新密码和确认新密码一致
- **THEN** 系统更新密码并显示"密码修改成功"提示

#### Scenario: 旧密码错误
- **WHEN** 用户输入的旧密码不正确
- **THEN** 系统返回错误提示"旧密码不正确"

#### Scenario: 新密码不一致
- **WHEN** 新密码和确认新密码不匹配
- **THEN** 前端表单验证阻止提交，提示"两次输入的密码不一致"

#### Scenario: 新密码过短
- **WHEN** 新密码长度少于6位
- **THEN** 前端表单验证阻止提交，提示"密码至少需要6位"

### Requirement: 启动登录验证
系统 SHALL 在每次浏览器会话启动时要求用户重新登录，不应持久化 token 跨会话。

#### Scenario: 关闭浏览器后重新打开
- **WHEN** 用户关闭浏览器后重新打开系统
- **THEN** 系统跳转到登录页面，要求输入用户名和密码

#### Scenario: 刷新页面
- **WHEN** 用户在同一浏览器会话中刷新页面
- **THEN** 系统保持登录状态，无需重新登录

#### Scenario: Token 过期
- **WHEN** token 过期（或被手动清除）
- **THEN** 系统自动跳转到登录页面

## REMOVED Requirements
无。