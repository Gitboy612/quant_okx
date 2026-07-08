# 嵌入式代理配置重写 + 端口管理修复 Spec

## Why
当前嵌入式代理存在多个问题：
1) 有两套代理设置（系统代理+嵌入式代理），用户困惑；
2) 嵌入式代理直接使用用户配置文件中的 `mixed-port`，但该端口已经被占用导致代理无法启动；
3) 未重写用户 Clash 配置文件的端口和 external-controller，导致冲突；
4) 嵌入式代理启动后用户凭证处理不正确，导致 [WinError 10054] 连接被强制关闭。

## What Changes
- 将两套代理设置合并：嵌入式代理面板保留，原"代理设置"面板改为手动指定代理地址（供外部 VPN/代理使用）
- 嵌入式代理启动时自动重写用户 Clash 配置：
  - 将 `mixed-port` 设置为用户指定的端口（默认 7890）
  - 将 `external-controller` 设置为 `127.0.0.1:<random port>` 不冲突
  - 将 `mode` 保持用户设置不变
  - 将重写后的配置写入 `backend/data/` 目录
- 删除两套冲突逻辑：嵌入式代理只使用重写后的配置，不会直接使用用户上传的配置
- 嵌入式代理启动后验证连通性，详细错误信息反馈到前端
- 使用用户上传配置中已有的节点信息，完整保留用户凭证和节点选择

## Impact
- Affected specs: `fix-pnl-positions-proxy`, `fix-proxy-import`
- Affected code:
  - 后端: `proxy_core.py`, `proxy_service.py`, `routers/settings.py`
  - 前端: `SettingsPage.tsx`

## ADDED Requirements

### Requirement: 配置文件自动重写
系统 SHALL 在嵌入式代理启动时自动重写用户上传的 Clash 配置文件。

#### Scenario: 重写配置
- **WHEN** 用户点击"启动代理"
- **THEN** 系统读取用户上传的配置
- **AND** 将 `mixed-port` 修改为用户在前端指定的端口（默认 7890）
- **AND** 将 `external-controller` 修改为 `127.0.0.1:随机端口` 避免端口冲突
- **AND** 写入重写后的配置到 `backend/data/proxy_config_rewrite.yaml`
- **AND** 使用重写后的配置启动 mihomo

#### Scenario: 保持原配置
- **WHEN** 用户配置已有其他端口设置（如 `socks-port`、`redir-port`）
- **THEN** 保留原设置不变，只修改冲突的端口

### Requirement: 两套代理共存
系统 SHALL 保留两套代理使用方式：
1. **手动指定代理** - 用户使用外部系统 VPN/代理，手动填写代理地址
2. **嵌入式代理** - 系统启动本地 mihomo 进程，使用用户导入的 Clash 配置，仅对 OKX API 生效

#### Scenario: 用户查看设置
- **WHEN** 用户进入系统设置页面
- **THEN** 第一个面板是"手动代理"（原"代理设置"）
- **AND** 第二个面板是"嵌入式代理"（新增）

### Requirement: 完整处理用户凭证
系统 SHALL 完整保留用户 Clash 配置中的节点信息和凭证。

#### Scenario: 用户导入机场配置
- **WHEN** 用户导入包含 vmess/hysteria2/anytls 等节点的 Clash 配置
- **THEN** mihomo 核心完整处理这些节点协议和凭证
- **AND** OKX API 请求通过选中的节点代理发出
- **AND** 连接成功不会报 10054 强制关闭

### Requirement: 错误反馈
系统 SHALL 在代理启动失败时提供详细错误信息。

#### Scenario: 端口被占用
- **WHEN** 用户指定的端口已被占用
- **THEN** 返回错误信息：`端口 7890 已被占用，请修改端口后重试`

#### Scenario: 配置文件无效
- **WHEN** 用户配置文件解析失败
- **THEN** 返回详细错误信息（行号、原因）

## MODIFIED Requirements
无。

## REMOVED Requirements
无。
