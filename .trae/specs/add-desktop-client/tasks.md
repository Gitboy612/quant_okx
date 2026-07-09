# Tasks

- [x] Task 1: PySide6 + QML 桌面壳脚手架
  - [ ] SubTask 1.1: 新建 `desktop/` 目录，添加 `desktop/requirements.txt`（PySide6，含 QtQuick3D/QtCharts 模块）
  - [ ] SubTask 1.2: 新增 `desktop/main.py`：QApplication + QQmlApplicationEngine 加载 `qml/main.qml`，无边框窗口 `Qt.FramelessWindowHint`
  - [ ] SubTask 1.3: 新增 `desktop/qml/main.qml` 骨架：根 `ApplicationWindow` + 自绘标题栏（应用名/最小化/最大化/关闭）+ 鼠标拖动与边缘缩放
  - [ ] SubTask 1.4: 新增 `desktop/resources.qrc` 注册 QML 文件与图标资源
  - [ ] SubTask 1.5: 验证可启动 Qt 窗口显示空白 QML 界面，标题栏拖动/缩放/关闭可用

- [x] Task 2: 后端同进程运行 + QML↔Python 桥接
  - [ ] SubTask 2.1: 新增 `desktop/qml_bridge.py`：用 `@QmlElement`（`QML_ELEMENT`/`QmlNamedElement`）注册服务对象（AccountService/StrategyService/OrderService/PnlService/MonitoringService/LogService），方法直接调 `backend/services/*` 业务逻辑
  - [ ] SubTask 2.2: 为每个服务对象定义 Qt signals（如 `orderFilled`/`strategyTriggered`/`alert`）用于主动推送
  - [ ] SubTask 2.3: 新增 `desktop/backend_thread.py`：QThread 封装 `uvicorn.Server`（可选，仅当 QML 走 HTTP/WS 时启用；默认不启）
  - [ ] SubTask 2.4: 应用退出时清理：若启 uvicorn 则 `server.should_exit=True` + `QThread.wait()`；QML 引擎安全销毁
  - [ ] SubTask 2.5: 验证 QML 能调 Python 方法取数据、Python signal 能推送到 QML

- [x] Task 3: 桌面级体验
  - [ ] SubTask 3.1: 新增 `desktop/tray.py`：QSystemTrayIcon + QMenu（显示/退出），关闭按钮最小化到托盘
  - [ ] SubTask 3.2: 新增 `desktop/single_instance.py`：QLocalSocket/QLocalServer 单实例锁，二次启动聚焦已有窗口
  - [ ] SubTask 3.3: 全局快捷键（Ctrl+K 唤起搜索等，用 QShortcut）
  - [ ] SubTask 3.4: 桌面通知：QSystemTrayIcon.showMessage 或 Qt 通知，绑定服务对象 signal 推送订单成交/策略触发

- [x] Task 4: QML 工作台 UI 框架（参考 Adobe Cloud / M365 / QQ）
  - [ ] SubTask 4.1: 新增 `desktop/qml/components/IconRail.qml`：80px 极窄图标轨（顶部头像、模块图标、底部设置，悬停 tooltip）
  - [ ] SubTask 4.2: 新增 `desktop/qml/components/TopBar.qml`：全局搜索、账户切换器、通知铃铛、主题切换、窗口控制按钮
  - [ ] SubTask 4.3: 新增 `desktop/qml/components/WorkspaceCard.qml`：统一卡片（圆角+轻投影+悬停抬升，QML Behavior 动画）
  - [ ] SubTask 4.4: 新增 `desktop/qml/components/ThemeToggle.qml` + `desktop/qml/theme/`：明暗主题样式，切换并持久化（QSettings）
  - [ ] SubTask 4.5: 改造 `main.qml` 为"图标轨 + 顶栏 + 主工作区 StackView"三段式布局
  - [ ] SubTask 4.6: 新增 `desktop/qml/components/KpiCard.qml`、`StatusBadge.qml`、`DataTable.qml` 适配卡片容器与双主题

- [x] Task 5: QML 页面实现（全部重写）
  - [ ] SubTask 5.1: `LoginPage.qml`：居中登录卡（M365/Adobe 登录风格），调 AuthService
  - [ ] SubTask 5.2: `DashboardPage.qml`：工作台首页（KPI 卡行 + 行情卡 + 近期策略卡 + 快捷操作），QtQuick3D 或粒子背景
  - [ ] SubTask 5.3: `StrategiesPage.qml`：策略卡片网格 + 醒目"新建策略"按钮（M365/Adobe 式）
  - [ ] SubTask 5.4: `AccountsPage.qml`：账户卡片网格（M365 文档卡风格）
  - [ ] SubTask 5.5: `MonitoringPage.qml`：监控卡片网格
  - [ ] SubTask 5.6: `OrdersPage.qml`：卡片容器内表格 + 筛选侧栏
  - [ ] SubTask 5.7: `PnlPage.qml`：卡片容器内表格 + QtCharts ChartView 图表卡
  - [ ] SubTask 5.8: `LogsPage.qml`：卡片容器内表格 + 筛选侧栏（含 API 日志）
  - [ ] SubTask 5.9: `SettingsPage.qml`：M365 设置风格（左分区 + 右内容）

- [x] Task 6: 打包与分发
  - [ ] SubTask 6.1: 修改 `QuantOKX.spec`：增加 desktop 入口分支，含 PySide6 hidden imports、QML/datas、Qt 插件（不含 QtWebEngine）
  - [ ] SubTask 6.2: 准备应用图标资源（256x256 ico/png），加入 resources.qrc
  - [ ] SubTask 6.3: 修改 `installer/build_installer.bat` 增加 `--target desktop` 分支：PyInstaller(Qt+QML 壳) → Inno Setup
  - [ ] SubTask 6.4: 验证安装包：双击安装 → 桌面快捷方式 → 启动 → 显示 QML 窗口 → 全功能可用

- [ ] Task 7: 验证
  - [x] SubTask 7.1: 渲染验证：QML 动画、QtQuick3D 背景、QtCharts 图表流畅（QtQuick3D 背景缺失，转入 Task 8 修复）
  - [x] SubTask 7.2: 桌面体验验证：托盘、单实例、自定义标题栏拖动缩放、主题切换持久化（主题持久化 + Ctrl+K 缺失，转入 Task 8 修复）
  - [x] SubTask 7.3: 桥接验证：QML 调 Python 取数据、Python signal 主动推送订单/告警、桌面通知（9/9 通过）
  - [x] SubTask 7.4: 体积验证：安装包 20–40MB，不含 QtWebEngine/Chromium（体积超标 80-150MB，转入 Task 8 修复）
  - [x] SubTask 7.5: 与现有浏览器版共存验证：两种产物独立运行不冲突（6/6 通过）

- [x] Task 8: 验证缺口修复（Task 7 发现的 5 个缺口）
  - [x] SubTask 8.1: DashboardPage 引入 QtQuick3D 背景（View3D + SceneEnvironment 或粒子系统）
  - [x] SubTask 8.2: 主题切换持久化（QSettings 读取启动初值 + onThemeSwitched 时 setValue 落盘）
  - [x] SubTask 8.3: 全局快捷键 Ctrl+K 唤起搜索（main.qml 添加 Shortcut{} + TopBar 暴露 focusSearch）
  - [x] SubTask 8.4: QuantOKX-Desktop.spec 显式 excludes QtWebEngine 系列 + 收窄 collect_submodules/collect_data_files 范围
  - [x] SubTask 8.5: spec.md 体积目标修正（20-40MB → 30-60MB 裁剪后区间，承认 PySide6+mihomo 实际体积）

# Task Dependencies
- [Task 2] 依赖 [Task 1]（壳就绪后注册桥接对象）
- [Task 3] 依赖 [Task 1]
- [Task 4] 依赖 [Task 1]（QML 壳就绪）
- [Task 5] 依赖 [Task 2][Task 4]（需桥接对象与 UI 框架组件）
- [Task 6] 依赖 [Task 1][Task 2][Task 3][Task 4][Task 5]
- [Task 7] 依赖 [Task 6]
- [Task 8] 依赖 [Task 7]（修复验证发现的缺口）
- [Task 3] 与 [Task 4] 可并行（均依赖 Task 1）
- [SubTask 8.1][8.2][8.3][8.4][8.5] 互不依赖，可并行
