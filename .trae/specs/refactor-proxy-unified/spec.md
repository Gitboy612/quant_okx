# 代理功能重构 Spec

## Why
当前代理功能有两套并列面板（"手动代理"+"嵌入式代理"），状态互相覆盖导致混乱；`get_proxy_url()` 误把远程节点端口当作本地代理端口；连通性测试仅验证 OKX API，无法确认是否真正翻墙。用户需要的是：像普通代理软件一样，在界面内导入机场配置并开启代理后，软件后端就能直接访问墙外（如 Google），并能在界面上看到墙外可达的验证结果。

## What Changes
- **合并为单一"代理"面板**：移除"手动代理"和"嵌入式代理"两个并列面板，合并为一个，主流程为"导入机场配置 → 启动代理 → 软件访问外网"
- **保留手动代理地址作为折叠的高级选项**：供已有外部 VPN/Clash Verge 的用户填写外部代理地址，与嵌入式代理二选一（启动嵌入式时禁用手动输入）
- **修复 `get_proxy_url()` 端口 bug**：嵌入式代理的本地端口固定取自 mihomo 的 `mixed-port`（默认 7890），不再错误使用远程节点端口
- **增强连通性测试（核心）**：启动代理后对多个目标测试，**重点验证墙外可达**：
  - `https://www.google.com/generate_204`（Google 墙外验证，期望 204）
  - `https://github.com`（GitHub 墙外验证）
  - `https://www.okx.com/api/v5/public/time`（OKX API 可用性）
  - 三个目标分别返回延迟与是否连通，前端独立显示
- **后端统一代理入口**：`OKXClient` 在嵌入式代理启动后自动通过 `http://127.0.0.1:{mixed-port}` 访问外网；停止后清除代理
- **示例配置快捷导入**：后端检测到 `backend/魔戒.net`、`backend/1772848370833.yml` 等机场配置时，前端导入区显示"使用示例配置"按钮，一键导入

## Impact
- Affected specs: `fix-proxy-import`, `fix-embedded-proxy-config`, `fix-pnl-positions-proxy`
- Affected code:
  - 后端: `services/proxy_service.py`, `services/proxy_core.py`, `routers/settings.py`, `services/okx_client.py`
  - 前端: `pages/SettingsPage.tsx`, `api/settings.ts`, `types/index.ts`

## ADDED Requirements

### Requirement: 多目标连通性测试（核心）
系统 SHALL 在代理启动或手动测试时，对多个目标地址进行连通性验证，确认墙外真正可达。

#### Scenario: 启动嵌入式代理后测试
- **WHEN** 嵌入式代理启动成功
- **THEN** 系统依次通过代理测试以下目标：
  - `https://www.google.com/generate_204`（Google 墙外验证）
  - `https://github.com`（GitHub 墙外验证）
  - `https://www.okx.com/api/v5/public/time`（OKX API 可用性）
- **AND** 返回每个目标的延迟（ms）与是否连通
- **AND** 前端展示三个目标的独立状态指示（绿/红圆点 + 延迟）

#### Scenario: Google 不可达（未真正翻墙）
- **WHEN** 代理启动后 Google 测试失败
- **THEN** 前端显示"Google 不可达：代理未真正翻墙，请检查节点是否可用"
- **AND** 若 OKX 可达则不影响 OKX API 使用；若 OKX 也不可达则提示"代理无效"

#### Scenario: 手动测试按钮
- **WHEN** 用户在代理面板点击"测试连通性"
- **THEN** 系统使用当前代理地址对三目标进行测试并返回结果

### Requirement: 修复本地代理端口逻辑
系统 SHALL 将嵌入式代理的本地端口固定为 mihomo 的 `mixed-port`，不再错误使用远程节点端口。

#### Scenario: 获取代理地址
- **WHEN** 系统需要 OKXClient 的代理地址且嵌入式代理已启动
- **THEN** 返回 `http://127.0.0.1:{mixed_port}`（默认 7890）
- **AND** 不再读取远程节点端口作为本地代理端口

### Requirement: 示例配置快捷导入
系统 SHALL 检测 backend 目录下的机场配置文件并提供快捷导入入口。

#### Scenario: 存在示例配置
- **WHEN** backend 目录下存在 `魔戒.net`、`1772848370833.yml` 等配置文件
- **THEN** 前端导入区显示"使用示例配置"按钮组
- **AND** 点击后自动导入对应配置文件并解析节点

## MODIFIED Requirements

### Requirement: 前端代理面板（单一面板）
原"手动代理"和"嵌入式代理"两个面板合并为单一"代理"面板。

#### Scenario: 面板结构
- **WHEN** 用户进入设置页面
- **THEN** 看到"代理"面板，包含：
  - 机场配置导入区：上传按钮 + "使用示例配置"快捷按钮（检测到示例配置时显示）
  - 嵌入式代理控制区：端口输入 + 启动/停止按钮 + 运行状态 + 三目标连通性指示
  - 折叠的"高级：手动指定外部代理"区：代理地址输入 + 测试按钮（启动嵌入式代理时此区禁用）
  - 可用节点列表（导入后显示，仅查看用，提示"节点选择由配置文件中的代理组规则决定"）

#### Scenario: 启动嵌入式代理
- **WHEN** 用户已导入机场配置并点击"启动代理"
- **THEN** mihomo 使用重写后的配置启动
- **AND** OKXClient 全局代理设为 `http://127.0.0.1:{port}`
- **AND** 自动执行三目标连通性测试并展示结果

## REMOVED Requirements
无。
