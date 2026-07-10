# Checklist

## 问题 1：Windows asyncio 文件描述符超限

- [x] launcher.py 在 Windows 平台启动早期设置 WindowsProactorEventLoopPolicy
- [x] start.bat 启动走 launcher.py 入口（带事件循环策略设置）
- [x] check_feasibility 中 OKXClient 用 try/finally 包裹，finally 调 aclose()
- [x] StrategyEngine 新增 _account_clients 缓存按账户共享 OKXClient
- [x] 实例启动通过 _get_client_for_account 获取 client
- [x] 引擎关闭时清理所有 _account_clients
- [x] 测试：Windows 平台事件循环策略被正确设置
- [x] 测试：check_feasibility 不泄漏连接
- [x] 测试：同账户多实例共享 OKXClient

## 问题 2：QS-Model 模板编辑/删除管理

- [x] 后端新增 PUT /api/strategies/templates/{id} 端点
- [x] PUT 端点接收 StrategyTemplateUpdate schema（可选字段）
- [x] PUT 端点更新 qs_model_config.logic 时重新计算 logic_hash
- [x] PUT 端点模板不存在返回 404
- [x] 前端 api/strategies.ts 新增 updateTemplate 函数
- [x] DslEditor props 新增 editingTemplateId
- [x] DslEditor 编辑模式打开时加载模板配置填充各区
- [x] DslEditor handleSave 根据 editingTemplateId 决定调 update/create
- [x] DslEditor 保存按钮文案编辑模式 "更新模板"
- [x] StrategiesPage 顶部新增"模板管理"按钮
- [x] 模板管理 Modal 展示自定义模板列表（名称/类型/logic_hash 简写）
- [x] 每项含"编辑"和"删除"按钮
- [x] 删除调 deleteTemplate 并 confirm 确认
- [x] 编辑打开 DslEditor 传 editingTemplateId
- [x] 编辑/删除后刷新模板列表
- [x] 测试：更新模板 / 更新不存在 / logic_hash 重算

## 问题 3：QS-Model 币对可选 + 锁定

- [x] 前端创建实例弹窗读取 selectedTemplate.qs_model_config?.meta?.base_symbol
- [x] base_symbol 非空时 symbol 输入框 readOnly + 视觉提示
- [x] base_symbol 为空时 symbol 可编辑（当前行为保留）
- [x] 内置硬编码策略模板（无 qs_model_config）symbol 仍可编辑
- [x] 后端 create_instance 检测 template.qs_model_config.meta.base_symbol 非空时强制 body.symbol
- [x] 测试：模板设 base_symbol="BTC-USDT"，前端传 "ETH-USDT"，实例 symbol="BTC-USDT"
- [x] 测试：模板无 base_symbol，前端传值透传

## 问题 4：模板存储与编译缓存

- [x] executor.py 新增模块级 _fsm_cache: dict[str, FSM]
- [x] _resolve_dsl_config 后计算 logic_hash，命中缓存直接赋值 self._fsm
- [x] 未命中缓存 compile 后存入 _fsm_cache
- [x] strategy_engine.py update_params 检测 qs_model_config.logic hash 变化
- [x] 实例 running 时改 logic 拒绝并返回 400
- [x] 实例 stopped 时允许更新 qs_model_config 并重算 logic_hash
- [x] 测试：两个相同 logic_hash 实例启动只触发 1 次 compile
- [x] 测试：仅改 params 不触发重编译
- [x] 测试：改 logic（运行中拒绝）
- [x] 测试：改 logic（已停止允许）

## 问题 5：order_qty 输入 0.01 被阻断

- [x] StrategiesPage 实例参数编辑区 step 根据 field.type 判断（int 用 1，float/number 用 'any'）
- [x] DslEditor flattenParamsToSchema 为 float/number 类型设置 step: 'any'
- [x] DslEditor flattenParamsToSchema 为 int 类型设置 step: 1
- [x] bases.py GridBlock order_qty param_schema 补 step: 0.001
- [x] 测试：GET /api/dsl/blocks 返回的 grid order_qty 含 step=0.001
- [x] 手动验证：实例参数编辑区输入 0.01 可保存（代码审查：StrategiesPage step 按 type 判断，float/number 用 'any'；后端 order_qty step=0.001）
- [x] 手动验证：DslEditor 参数表单输入小数正常（代码审查：flattenParamsToSchema float/number step='any'，int step=1）

## 问题 6：网格 12 格下 390+ 单（致命 Bug）

### 6.1 executor 状态自环修复
- [x] _enter_state 记录 old_state = self._current_state
- [x] 仅在 old_state != new_state 时执行 on_pause/on_resume/on_stop 回调
- [x] 自环转换（old_state == new_state）仅执行 transition actions
- [x] 测试：无 recover_when 的规则每 tick 不触发 on_resume

### 6.2 GridBlock.on_start 去重
- [x] on_start 循环内 `if i in self.active_buy: continue`（买单）
- [x] on_start 循环内 `if i in self.active_sell: continue`（卖单）
- [x] 测试：on_start 被调用 2 次后总挂单数仍等于 grid_count

### 6.3 GridBlock.on_resume 增量补挂
- [x] on_resume 不再调 self.on_start()
- [x] on_resume 遍历 levels 补挂 active_buy/active_sell 中缺失的层级
- [x] 测试：on_resume 只补挂缺失层级

### 6.4 on_order_filled 接通
- [x] executor OrderManager "filled" 回调中调用 base_block.on_order_filled
- [x] 仅当 self._base_block is not None 时调用
- [x] 测试：订单成交触发 on_order_filled 反向挂单

### 6.5 grid_idx 匹配容差
- [x] on_order_filled 容差从 tick_size * 0.6 改为 tick_size * 0.5
- [x] 无精确匹配时回退到最近层级
- [x] 测试：容差优化后 grid_idx 匹配正确

## 端到端验证

- [x] Windows 启动后端无 `too many file descriptors` 错误（代码审查：launcher.py L17-18 在 win32 设置 WindowsProactorEventLoopPolicy）
- [x] check_feasibility 调用后 httpx 连接数不累积（代码审查：strategy_engine.py check_feasibility try/finally + await client.aclose()）
- [x] 同账户多实例共享 OKXClient（代码审查：_account_clients 缓存 + _get_client_for_account + aclose 清理）
- [x] 12 格网格策略运行 5 分钟后委托订单数 ≤ 24（代码审查：executor._enter_state 自环去重 + _place_grid_orders active_buy/sell 去重 + on_resume 复用去重逻辑不调 on_start）
- [x] 模板管理 Modal 列表/编辑/删除流程正常（代码审查：TemplateMgmtModal 渲染名称/类型/logic_hash 简写 + 编辑/删除按钮 + confirm + loadData 刷新）
- [x] DslEditor 编辑模式加载模板并保存为更新（代码审查：editingTemplateId prop + useEffect 加载 + handleSave 分支 doUpdate/doCreate + 按钮"更新模板"/"保存模板"）
- [x] 设了 base_symbol 的模板创建实例时 symbol 锁定（代码审查：lockedBaseSymbol + readOnly + 后端 create_instance 强制 body.symbol）
- [x] 未设 base_symbol 的模板创建实例时 symbol 可输入（代码审查：lockedBaseSymbol 为空时 readOnly=false，回退 symbolSearch 可编辑）
- [x] order_qty 输入 0.01 可保存（代码审查：前端 step 按 type 判断 + 后端 order_qty step=0.001）
- [x] 同 logic_hash 模板启动复用 FSM 缓存（代码审查：executor.py 模块级 _fsm_cache dict + 命中赋值/未命中编译入缓存）

## 回归验证

- [x] 现有硬编码策略（grid/trend/arbitrage/advanced_grid_hedge）不受影响（test_dsl_base_strategies.py 通过，含于 335 passed）
- [x] 现有自定义模板（参数定义式）仍可创建/删除（test_dsl_template_api.py + test_qs_model_template_api.py 通过，含于 335 passed）
- [x] 旧 dsl_config 模板仍可正常加载运行（test_dsl_e2e.py + test_dsl_executor.py 覆盖 dsl_config 加载运行，含于 335 passed）
- [x] 现有策略实例启动/停止/暂停/恢复正常（test_strategy_engine_clients.py + test_strategy_engine_update_params.py 通过，含于 335 passed）
- [x] 后端所有原有测试通过（无回归）（335 passed, 0 failed，排除 6 个需 live OKX 凭据的文件）
- [x] 前端 tsc 编译无错误（npx tsc --noEmit exit code 0）
