# Tasks

- [x] Task 1: 后端配置重写 + 端口管理
  - [x] 修改 `proxy_core.py` 的 `start_proxy()` 函数，启动前自动重写 Clash 配置：
    - 读取用户上传的配置文件
    - 使用 `yaml.load` 解析，修改 `mixed-port` 为传入的 port 参数
    - 设置 `external-controller: 127.0.0.1:0`（随机端口）避免冲突
    - 将重写后的 YAML 写入 `backend/data/proxy_config_rewrite_{port}.yaml`
    - 使用重写后的配置文件启动 mihomo
  - [x] 新增 `_rewrite_config()` 辅助函数，处理 YAML 读写和端口修改
  - [x] 启动前检查端口是否被占用，若占用则返回错误

- [x] Task 2: 前端两套代理面板优化
  - [x] 修改 `SettingsPage.tsx`，将"代理设置"面板标题改为"手动代理"
  - [x] 将"嵌入式代理"面板移到"手动代理"面板下方
  - [x] 保留"手动代理"的启用/禁用开关、代理地址输入、测试连通性按钮
  - [x] 保留"嵌入式代理"的端口输入、启动/停止按钮、状态显示、连通性显示
  - [x] 更新导入配置按钮的提示文案，说明导入后需要在嵌入式代理中启动

- [x] Task 3: 完整测试与验证
  - [x] Python 语法检查通过（proxy_core.py, proxy_service.py, settings.py）
  - [x] 前端构建无报错（exit code 0）
  - [x] YAML 重写逻辑已实现（_rewrite_config + _check_port_available）

# Task Dependencies
- Task 1 和 Task 2 可并行执行
- Task 3 依赖 Task 1 和 Task 2