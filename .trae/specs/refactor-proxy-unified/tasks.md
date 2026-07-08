# Tasks

- [x] Task 1: 修复 get_proxy_url() 端口 bug + 后端代理设置整理
  - [ ] 修改 `services/proxy_service.py` 的 `get_proxy_url()`：
    - 移除根据节点名查找节点端口的错误逻辑（原 line 170-178）
    - 嵌入式代理启动后返回 `http://127.0.0.1:{proxy_embedded_port}`（从设置读取，默认 7890）
    - 未启动嵌入式代理时，若 `proxy_enabled=true` 且 `proxy_url` 非空，返回 `proxy_url`（手动代理）
    - 否则返回 None
  - [ ] 新增 `proxy_embedded_port` 设置项（默认 7890），`get_proxy_settings()` 返回该字段
  - [ ] `save_proxy_settings()` 增加保存 `proxy_embedded_port` 参数
  - [ ] 保留 `parse_clash_config`、`import_clash_config_from_content` 不变

- [x] Task 2: 增强多目标连通性测试（核心）
  - [ ] 修改 `services/proxy_core.py` 的 `_test_connectivity(proxy_url, port)`：
    - 依次通过代理测试三个目标：
      - Google: `https://www.google.com/generate_204`（status 204 或 200 视为 ok）
      - GitHub: `https://github.com`（status 200 或 301 视为 ok）
      - OKX: `https://www.okx.com/api/v5/public/time`（status 200 且 code=0 视为 ok）
    - 每个目标超时 8 秒
    - 返回结构：`{google: {ok, latency_ms}, github: {ok, latency_ms}, okx: {ok, latency_ms, message}}`
    - 移除启动后 sleep 2 秒（代理已 sleep 1.5s 启动）
  - [ ] 修改 `services/proxy_service.py` 的 `test_proxy(proxy_url)` 同样返回多目标结构
  - [ ] `start_proxy()` 返回值的 `connectivity` 字段使用新结构

- [x] Task 3: 后端 API 路由调整
  - [ ] 修改 `routers/settings.py`：
    - `GET /api/settings/proxy` 返回 `proxy_enabled`、`proxy_url`、`proxy_embedded_port`、`proxy_config_path`、`nodes`
    - `PUT /api/settings/proxy` 接受 `proxy_enabled`、`proxy_url`、`proxy_embedded_port`、`proxy_config_path` 并保存
    - `POST /api/settings/proxy/test` 返回多目标连通性结果
    - `POST /api/settings/proxy/start` 启动后返回 `connectivity` 多目标结果
    - 新增 `GET /api/settings/proxy/sample-configs`：扫描 `backend/` 目录下 `*.yml`、`*.net` 文件，返回 `[{name, path}]` 列表（排除 `proxy_config_*.yml` 重写文件）
    - 新增 `POST /api/settings/proxy/sample-configs/import`：接收 `{path}`，读取该文件并导入（复用 `import_clash_config_from_content`）

- [x] Task 4: 前端类型与 API 调整
  - [ ] 修改 `frontend/src/types/index.ts`：
    - `ProxyStatus` 的 `connectivity` 改为多目标结构：`{google: {ok, latency_ms}, github: {ok, latency_ms}, okx: {ok, latency_ms, message}}`
    - `ProxySettings` 增加 `proxy_embedded_port` 字段
    - 新增 `SampleConfig` 接口：`{name, path}`
    - 新增 `ConnectivityResult` 接口
  - [ ] 修改 `frontend/src/api/settings.ts`：
    - `getProxySettings` 返回类型对齐
    - `saveProxySettings` 参数含 `proxy_embedded_port`
    - 新增 `getSampleConfigs()` 调用 `GET /api/settings/proxy/sample-configs`
    - 新增 `importSampleConfig(path)` 调用 `POST /api/settings/proxy/sample-configs/import`

- [x] Task 5: 前端代理面板重构（SettingsPage.tsx）
  - [ ] 合并"手动代理"和"嵌入式代理"两个 motion.div 面板为单一"代理"面板
  - [ ] 面板顶部：机场配置导入区
    - "导入 Clash 配置"上传按钮（保留原逻辑）
    - "使用示例配置"按钮组：调用 `getSampleConfigs()`，检测到示例配置时显示按钮，点击调用 `importSampleConfig(path)` 自动导入
  - [ ] 嵌入式代理控制区：
    - 端口输入框（默认 7890，保存到 `proxy_embedded_port`）
    - 启动/停止按钮
    - 运行状态指示（端口、运行时长）
    - 三目标连通性指示器（Google / GitHub / OKX），每个显示绿/红圆点 + 延迟 + 状态文案
    - Google 不可达时显示"代理未真正翻墙，请检查节点"提示
  - [ ] 折叠的"高级：手动指定外部代理"区（默认折叠，点击展开）：
    - 启用开关 + 代理地址输入 + 测试连通性按钮
    - 启动嵌入式代理时此区禁用并提示"嵌入式代理运行中，请先停止"
  - [ ] 可用节点列表保留，增加提示文案"节点选择由配置文件中的代理组规则决定"
  - [ ] 保存设置按钮保存 `proxy_enabled`、`proxy_url`、`proxy_embedded_port`

- [x] Task 6: 集成测试与验证
  - [ ] Python 语法检查：`python -m py_compile backend/services/proxy_service.py backend/services/proxy_core.py backend/routers/settings.py`
  - [ ] 前端构建：`cd frontend && npm run build`，确认无报错（exit code 0）
  - [ ] 配置解析测试：用 `backend/魔戒.net` 和 `backend/1772848370833.yml` 测试 `parse_clash_config` 能正确返回节点列表
  - [ ] 示例配置扫描验证：`getSampleConfigs` 能返回 `魔戒.net` 和 `1772848370833.yml` 两个文件
  - [ ] 连通性测试逻辑验证：三目标测试函数能正确返回 `{google, github, okx}` 结构（代理未真正启动时 Google 应返回 ok=false，代码逻辑正确即可）

# Task Dependencies
- Task 1（端口修复）是 Task 2、Task 3 的基础
- Task 2（连通性测试）可与 Task 1 并行（修改不同函数）
- Task 3（路由）依赖 Task 1、Task 2
- Task 4（前端类型/API）依赖 Task 3
- Task 5（前端面板）依赖 Task 4
- Task 6（测试）依赖所有前序任务
