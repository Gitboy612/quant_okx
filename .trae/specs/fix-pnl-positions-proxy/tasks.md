# Tasks

- [x] Task 1: 盈亏曲线时间粒度修正与水平滚动
  - [x] 修改 `PnLChart.tsx` 中的 `TIME_RANGE_DURATIONS`，将 `'1m': 60*1000` 改为 `'5m': 5*60*1000`，`'1h': 60*60*1000` 改为 `'30m': 30*60*1000`
  - [x] 更新 `TimeRange` 类型为 `'5m' | '30m' | '1d' | '1w' | 'all'`
  - [x] 更新 `DashboardPage.tsx` 中时间粒度按钮文字：5分、30分、1天、1周、全部
  - [x] 在 `PnLChart.tsx` 中，当数据点超过50个时，给 `AreaChart` 的 `ResponsiveContainer` 外层包裹一个 `overflow-x-auto` 容器，并设置 `minWidth` 为数据点数量 * 某个固定宽度（如每个数据点 8px），使图表可水平滚动

- [x] Task 2: 持仓列表表头与友好名称
  - [x] 在 `DashboardPage.tsx` 持仓区域添加表头行（交易对、方向、数量、标记价格、未实现盈亏）
  - [x] 将持仓数据行的 `p.instId` 改为 `formatInstId(p.instId)`，显示友好名称
  - [x] 导入 `formatInstId`（已存在，确认导入即可）

- [x] Task 3: 后端嵌入式代理核心管理
  - [x] 在 `backend/services/` 下新建 `proxy_core.py`，实现代理核心管理
  - [x] 功能：`start_proxy(config_path, port)` 启动本地代理子进程（使用系统安装的 mihomo/clash 或内置代理）
  - [x] 功能：`stop_proxy()` 停止代理子进程
  - [x] 功能：`get_proxy_status()` 返回代理运行状态（running/stopped, port, pid, started_at）
  - [x] 实现：使用 `subprocess.Popen` 管理代理进程，通过 `mihomo -d config_dir -f config.yaml` 或类似命令启动
  - [x] 代理启动后自动调用 `OKXClient.set_global_proxy(f"http://127.0.0.1:{port}")`
  - [x] 代理停止后自动调用 `OKXClient.set_global_proxy(None)`

- [x] Task 4: 后端代理管理 API 端点
  - [x] 在 `backend/routers/settings.py` 新增端点：
    - `POST /api/settings/proxy/start` — 启动代理
    - `POST /api/settings/proxy/stop` — 停止代理
    - `GET /api/settings/proxy/status` — 获取代理状态
  - [x] 端点需要认证（`Depends(get_current_user)`）

- [x] Task 5: 前端代理管理 UI
  - [x] 在 `SettingsPage.tsx` 代理设置区域新增嵌入式代理管理面板
  - [x] 显示代理状态：运行中（绿色）/ 已停止（灰色）
  - [x] 提供"启动代理"/"停止代理"按钮
  - [x] 配置代理端口输入框（默认 7890）
  - [x] 启动后显示运行时长、端口号
  - [x] 在 `frontend/src/api/settings.ts` 新增 `startProxy`、`stopProxy`、`getProxyStatus` API 函数
  - [x] 在 `types/index.ts` 新增 `ProxyStatus` 类型

# Task Dependencies
- Task 1 和 Task 2 独立，可并行执行
- Task 4 依赖 Task 3（API 端点需要代理核心管理服务）
- Task 5 依赖 Task 4（前端 UI 需要后端 API）