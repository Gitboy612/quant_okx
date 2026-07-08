# 代理配置导入修复 + 代理核心安装 + 连通性测试 Spec

## Why
1) 导入 Clash 配置文件时 YAML 解析可能因文件过大或特殊格式失败；2) 系统未安装 mihomo/clash 二进制，嵌入式代理无法启动；3) 需要验证代理启动后能否连通 OKX API。

## What Changes
- 修复 `proxy_service.py` 中 YAML 解析，使用 `yaml.CSafeLoader` 加速大文件解析，增加错误详情返回
- 改进 `proxy_core.py` 自动下载安装 mihomo 二进制（从 GitHub Release 下载 Windows amd64 版本）
- 代理启动后自动进行连通性测试（ping OKX API），结果反馈到前端
- 前端导入失败时显示详细错误信息，帮助用户排查问题

## Impact
- Affected specs: `fix-pnl-positions-proxy`
- Affected code:
  - 后端: `services/proxy_service.py`, `services/proxy_core.py`, `routers/settings.py`
  - 前端: `SettingsPage.tsx`

## ADDED Requirements

### Requirement: 大文件 YAML 解析兜底
系统 SHALL 使用 `yaml.CSafeLoader`（失败时回退 `yaml.SafeLoader`）解析 Clash 配置文件，支持 128KB+ 的大文件。

#### Scenario: 正常解析
- **WHEN** 用户上传有效 Clash YAML 文件
- **THEN** 系统解析并返回节点列表
- **AND** 解析耗时 < 2 秒

#### Scenario: 解析失败反馈
- **WHEN** YAML 解析失败
- **THEN** 返回详细错误信息（包含行号和具体原因）
- **AND** 前端显示该错误信息

### Requirement: 自动安装 mihomo 代理核心
系统 SHALL 在启动嵌入式代理时自动检测并安装 mihomo 二进制。

#### Scenario: mihomo 未安装
- **WHEN** 用户点击"启动代理"且系统未找到 mihomo
- **THEN** 自动从 GitHub 下载 mihomo-windows-amd64 最新版本
- **AND** 保存到 `backend/bin/mihomo.exe`
- **AND** 下载完成后自动启动代理

#### Scenario: mihomo 已安装
- **WHEN** 系统找到已安装的 mihomo
- **THEN** 直接使用现有二进制，无需重新下载

### Requirement: 代理启动后连通性验证
系统 SHALL 在代理启动后自动测试 OKX API 连通性。

#### Scenario: 代理连通正常
- **WHEN** 代理启动完成
- **THEN** 自动调用 `test_proxy("http://127.0.0.1:{port}")` 验证连通性
- **AND** 返回连通状态和延迟到前端

#### Scenario: 代理连通失败
- **WHEN** 代理启动后连通性测试失败
- **THEN** 前端显示"代理已启动但连通性测试失败"及具体原因

## MODIFIED Requirements
无。

## REMOVED Requirements
无。