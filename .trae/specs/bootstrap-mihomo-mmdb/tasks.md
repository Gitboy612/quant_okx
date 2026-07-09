# Tasks

- [x] Task 1: 实现 MMDB 文件预下载机制
  - [x] 在 `proxy_core.py` 中定义 `MMDB_FILES` 常量，列出所需的 GeoIP 文件名与下载 URL（来自 `MetaCubeX/meta-rules-dat` release）
    - `geoip.metadb` → `https://github.com/MetaCubeX/meta-rules-dat/releases/download/latest/geoip.metadb`
    - `geosite.dat` → `https://github.com/MetaCubeX/meta-rules-dat/releases/download/latest/geosite.dat`
    - `GeoIP.dat` → `https://github.com/MetaCubeX/meta-rules-dat/releases/download/latest/GeoIP.dat`
    - `GeoSite.dat` → `https://github.com/MetaCubeX/meta-rules-dat/releases/download/latest/GeoSite.dat`
  - [x] 实现 `_get_mmdb_dir()`：返回 `backend/data/` 目录路径（与 mihomo 工作目录一致）
  - [x] 实现 `_download_mmdb_files() -> dict`：复用现有 `_wrap_with_mirrors()` 镜像兜底逻辑，逐文件下载到 `backend/data/`
  - [x] 实现 `_check_mmdb_ready() -> dict`：返回各 MMDB 文件存在状态、大小、修改时间
  - [x] 实现 `_print_mmdb_manual_hint()`：中文提示手动放置目录与下载地址

- [x] Task 2: 改造 `start_proxy()` 流程
  - [x] 在重写配置后、启动 mihomo 前调用 `_check_mmdb_ready()`
  - [x] 若 MMDB 缺失，先调用 `_download_mmdb_files()` 预下载
  - [x] 若仍缺失且用户未配置引导代理，返回错误信息（含缺失文件清单与手动放置指引），不启动 mihomo
  - [x] 若用户配置了引导代理，将 `HTTP_PROXY` / `HTTPS_PROXY` 环境变量传入 `subprocess.Popen` 的 `env` 参数
  - [x] 调整错误返回结构，包含 `mmdb_status` 字段便于前端展示

- [x] Task 3: 新增 MMDB 状态查询接口
  - [x] 在 `routers/settings.py` 新增 `GET /api/settings/proxy/mmdb-status`
  - [x] 调用 `proxy_core._check_mmdb_ready()` 返回状态

- [x] Task 4: 前端引导代理与 MMDB 状态展示
  - [x] `SettingsPage.tsx` 增加"引导代理地址"输入框（可选），说明"已开 FlClash 等外部代理时填写以加速 MMDB 下载"
  - [x] 启动代理请求体增加 `bootstrap_proxy` 字段
  - [x] 嵌入式代理面板增加 MMDB 就绪指示器（4 个文件的存在状态）
  - [x] 启动失败时若返回 `mmdb_status`，展示缺失文件清单与手动放置指引

- [x] Task 5: 测试与验证
  - [x] Python 语法检查 `proxy_core.py` 与 `settings.py`
  - [x] TypeScript 编译通过（`npx tsc --noEmit` exit code 0）
  - [ ] 手动删除 `backend/data/` 下 MMDB 文件，启动代理验证预下载流程（需用户实际测试）
  - [ ] 配置引导代理后启动验证 mihomo 能借用引导代理下载 MMDB（需用户实际测试）
  - [ ] 验证 MMDB 已存在时启动流程跳过下载（需用户实际测试）

# Task Dependencies
- Task 2 依赖 Task 1
- Task 3 依赖 Task 1
- Task 4 依赖 Task 2 与 Task 3
- Task 5 依赖 Task 1-4
