# 修复 mihomo MMDB 启动死锁 Spec

## Why
mihomo 启动时硬依赖 GeoIP 数据库文件（`geoip.metadb` / `geosite.dat` / `GeoIP.dat` / `GeoSite.dat`），需从 `github.com/MetaCubeX/meta-rules-dat` 下载。国内访问 GitHub 受限导致下载卡死，mihomo 在 MMDB 就绪前不会监听 7890 端口，最终 `_wait_for_port_listening` 返回 `timeout`，代理永远启动不起来。

这是典型的死锁：
- 要启动嵌入式代理 → 需要 mihomo 监听端口 → 需要 MMDB 文件
- 要下载 MMDB 文件 → 需要能访问 GitHub → 需要代理已经跑起来

用户已开启 FlClash 系统代理时通信正常，说明节点本身没问题，仅是 mihomo 自举阶段的引导文件缺失。

## What Changes
- 新增 `_download_mmdb_files()`：在启动 mihomo 之前，使用前一轮已实现的 GitHub 镜像兜底（`gh-proxy.com` / `ghproxy.net` / `mirror.ghproxy.com` 等）预下载 GeoIP 文件到 `backend/data/`
- 新增 `_get_mmdb_files()`：聚合"本地已存在 / 镜像下载 / 手动放置"三级查找逻辑，返回缺失文件清单
- `start_proxy()` 启动前调用预下载，确保 MMDB 就绪后再拉起 mihomo
- 新增"引导代理"可选参数：用户已开 FlClash 时，将 `HTTP_PROXY` / `HTTPS_PROXY` 环境变量传给 mihomo 子进程，让其借用系统代理下载 MMDB
- 失败时通过 `_print_manual_install_hint()` 风格的中文提示，告知用户手动放置 MMDB 的目录与下载地址
- 前端 `SettingsPage.tsx` 增加可选"引导代理地址"输入框，并展示 MMDB 就绪状态

## Impact
- Affected specs: `fix-embedded-proxy-config`（扩展其重写配置流程，增加 MMDB 预下载阶段）
- Affected code:
  - 后端: `backend/services/proxy_core.py`（新增 MMDB 下载与引导代理逻辑）
  - 后端: `backend/routers/settings.py`（新增 MMDB 状态查询接口）
  - 前端: `frontend/src/pages/SettingsPage.tsx`（增加引导代理输入与 MMDB 状态显示）

## ADDED Requirements

### Requirement: MMDB 文件预下载
系统 SHALL 在启动 mihomo 之前自动下载所需的 GeoIP 数据库文件。

#### Scenario: 首次启动且本地无 MMDB
- **WHEN** 用户首次点击"启动代理"，且 `backend/data/` 目录下不存在 `geoip.metadb` / `geosite.dat`
- **THEN** 系统依次尝试直连 GitHub 与各镜像（gh-proxy / ghproxy.net / mirror.ghproxy.com / hub.gitmirror.com / download.fastgit.org）
- **AND** 将下载的文件放置到 `backend/data/` 目录
- **AND** 启动 mihomo 时 mihomo 直接读取本地文件，不再尝试联网下载

#### Scenario: MMDB 文件已存在
- **WHEN** 用户再次启动代理，且本地 MMDB 文件已存在
- **THEN** 系统跳过下载，直接启动 mihomo
- **AND** 启动延迟显著降低

#### Scenario: 所有镜像均下载失败
- **WHEN** 直连与所有镜像都无法下载 MMDB 文件
- **THEN** 系统打印中文手动放置指引，列出可访问的下载地址与目标目录 `backend/data/`
- **AND** 返回错误信息中包含缺失文件清单，便于前端展示
- **AND** 不尝试启动 mihomo（避免再次进入死锁）

### Requirement: 引导代理支持
系统 SHALL 支持用户在已运行外部代理（FlClash / Clash Verge / 系统 VPN）时，将该代理作为 mihomo 启动阶段的引导代理。

#### Scenario: 用户已有外部代理
- **WHEN** 用户在前端填写引导代理地址（如 `http://127.0.0.1:7890`）并启动嵌入式代理
- **THEN** 系统将 `HTTP_PROXY` / `HTTPS_PROXY` 环境变量传递给 mihomo 子进程
- **AND** mihomo 通过引导代理下载 MMDB 文件
- **AND** MMDB 就绪后 mihomo 正常监听嵌入式代理端口

#### Scenario: 用户未填写引导代理
- **WHEN** 用户未填写引导代理地址
- **THEN** 系统仅依赖本地 MMDB 预下载机制
- **AND** 若本地 MMDB 已存在则正常启动；否则依赖镜像下载

### Requirement: MMDB 状态查询
系统 SHALL 提供接口查询 MMDB 文件的就绪状态。

#### Scenario: 前端查询 MMDB 状态
- **WHEN** 前端调用 `GET /api/settings/proxy/mmdb-status`
- **THEN** 返回各 MMDB 文件的存在状态、文件大小、最后修改时间
- **AND** 前端可在嵌入式代理面板中展示 MMDB 就绪指示器

## MODIFIED Requirements

### Requirement: 嵌入式代理启动流程
原 `fix-embedded-proxy-config` 中的启动流程修改为：
1. 检查端口可用性
2. 查找 mihomo 二进制
3. 获取 Clash 配置路径
4. **新增**：预下载 MMDB 文件（或在引导代理可用时由 mihomo 自行下载）
5. 重写 Clash 配置（清理冲突端口）
6. 启动 mihomo 子进程（可选传入 `HTTP_PROXY` 环境变量）
7. 端口轮询等待监听
8. 测试连通性

## REMOVED Requirements
无。
