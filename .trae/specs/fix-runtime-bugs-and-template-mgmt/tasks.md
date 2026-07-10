# Tasks

## 阶段一：后端致命 Bug 与事件循环修复（问题 1 / 6，最高优先级）

- [x] Task 1: Windows ProactorEventLoop 与启动脚本（问题 1）
  - [x] SubTask 1.1: 修改 [launcher.py](file:///e:/New%20folder%20(2)/quant_okx/backend/launcher.py) 在模块顶部 `if sys.platform == "win32": asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())`
  - [x] SubTask 1.2: 检查 [start.bat](file:///e:/New%20folder%20(2)/quant_okx/start.bat) 启动走 `python -m backend.launcher` 或等价入口（而非直接 uvicorn main:app 用默认 loop）
  - [x] SubTask 1.3: 编写测试验证 Windows 平台事件循环策略被正确设置（mock sys.platform）

- [x] Task 2: 修复 OKXClient 连接泄漏与按账户共享（问题 1）
  - [x] SubTask 2.1: 修改 [strategy_engine.py](file:///e:/New%20folder%20(2)/quant_okx/backend/services/strategy_engine.py) `check_feasibility` 中 `OKXClient` 用 `try/finally` 包裹，finally 中 `await client.aclose()`
  - [x] SubTask 2.2: 在 `StrategyEngine` 中新增 `_account_clients: dict[str, OKXClient]` 缓存，`_get_client_for_account(account_id)` 复用同账户 client
  - [x] SubTask 2.3: 实例启动时通过 `_get_client_for_account` 获取 client 而非 `OKXClient()` 直接 new
  - [x] SubTask 2.4: 引擎关闭时遍历 `_account_clients` 调用 `aclose()` 清理

- [x] Task 3: 修复 executor 状态自环触发 on_resume（问题 6 - 致命 Bug 第 1 处）
  - [x] SubTask 3.1: 修改 [executor.py](file:///e:/New%20folder%20(2)/quant_okx/backend/dsl/executor.py) `_enter_state(new_state)`：记录 `old_state = self._current_state`，仅在 `old_state != new_state` 时执行 on_pause/on_resume/on_stop 等回调
  - [x] SubTask 3.2: 自环转换（old_state == new_state）仅执行 transition 上绑定的 actions，不触发生命周期钩子
  - [x] SubTask 3.3: 编写测试：无 recover_when 的规则每 tick 评估不触发 on_resume

- [x] Task 4: 修复 GridBlock.on_start 重复挂单（问题 6 - 致命 Bug 第 2 处）
  - [x] SubTask 4.1: 修改 [bases.py](file:///e:/New%20folder%20(2)/quant_okx/backend/dsl/blocks/bases.py) `GridBlock.on_start` 循环内：`if i in self.active_buy: continue`（买单），`if i in self.active_sell: continue`（卖单）
  - [x] SubTask 4.2: 修改 `GridBlock.on_resume` 不再调 `self.on_start()`，改为遍历 levels 找出 `i not in active_buy` 和 `i not in active_sell` 的层级，只补挂这些
  - [x] SubTask 4.3: 编写测试：on_start 被调用 2 次后总挂单数仍等于 grid_count（不翻倍）

- [x] Task 5: 接通 on_order_filled 反向挂单回调（问题 6 - 致命 Bug 第 3 处）
  - [x] SubTask 5.1: 修改 [executor.py](file:///e:/New%20folder%20(2)/quant_okx/backend/dsl/executor.py) OrderManager "filled" 回调中，当 `self._base_block is not None` 时调用 `await self._base_block.on_order_filled(order, ctx)`
  - [x] SubTask 5.2: 修改 [bases.py](file:///e:/New%20folder%20(2)/quant_okx/backend/dsl/blocks/bases.py) `GridBlock.on_order_filled` 的 grid_idx 匹配容差从 `tick_size * 0.6` 改为 `tick_size * 0.5`
  - [x] SubTask 5.3: 增加最近层级兜底：若无精确匹配，选择 `abs(price - level_price)` 最小的 level
  - [x] SubTask 5.4: 编写测试：模拟订单成交触发 on_order_filled，验证反向订单被挂出

## 阶段二：FSM 编译缓存与运行时参数更新（问题 4）

- [x] Task 6: FSM 编译缓存
  - [x] SubTask 6.1: 修改 [executor.py](file:///e:/New%20folder%20(2)/quant_okx/backend/dsl/executor.py) 新增模块级 `_fsm_cache: dict[str, FSM] = {}`
  - [x] SubTask 6.2: `_resolve_dsl_config` 后计算 logic_hash，若 `_fsm_cache` 命中则直接赋值 `self._fsm = cached`，否则 compile 后存入 cache
  - [x] SubTask 6.3: 编写测试：两个相同 logic_hash 的实例启动只触发 1 次 compile

- [x] Task 7: 运行中改 logic 触发重编译
  - [x] SubTask 7.1: 修改 [strategy_engine.py](file:///e:/New%20folder%20(2)/quant_okx/backend/services/strategy_engine.py) `update_params` 中检测 `qs_model_config.logic` 段 hash 变化
  - [x] SubTask 7.2: hash 变化时若实例 running，拒绝并返回 400 "运行中不能修改 logic 结构，请停止后更新"
  - [x] SubTask 7.3: 实例 stopped 时允许更新 qs_model_config 并重新计算 logic_hash
  - [x] SubTask 7.4: 编写测试覆盖三种场景：仅改 params / 改 logic（运行中拒绝）/ 改 logic（已停止允许）

## 阶段三：QS-Model 模板编辑与删除管理（问题 2）

- [x] Task 8: 后端 PUT /templates/{id} 端点
  - [x] SubTask 8.1: 修改 [routers/strategies.py](file:///e:/New%20folder%20(2)/quant_okx/backend/routers/strategies.py) 新增 `PUT /api/strategies/templates/{id}` 路由
  - [x] SubTask 8.2: 接收 `StrategyTemplateUpdate` schema（name/qs_model_config/dsl_config/default_params/param_schema/description 可选字段）
  - [x] SubTask 8.3: 更新对应模板字段；若 qs_model_config.logic 变化，重新计算 logic_hash
  - [x] SubTask 8.4: 返回更新后的模板对象；模板不存在返回 404
  - [x] SubTask 8.5: 编写测试：更新模板 / 更新不存在的模板 / logic_hash 重算

- [x] Task 9: 前端 updateTemplate API
  - [x] SubTask 9.1: 修改 [api/strategies.ts](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/api/strategies.ts) 新增 `updateTemplate(id: number, body: Partial<StrategyTemplateCreate>): Promise<StrategyTemplate>`
  - [x] SubTask 9.2: 调用 `PUT /api/strategies/templates/${id}`

- [x] Task 10: DslEditor 编辑模式
  - [x] SubTask 10.1: 修改 [DslEditor.tsx](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/components/DslEditor.tsx) props 新增 `editingTemplateId?: number | null`
  - [x] SubTask 10.2: `useEffect` 监听 `editingTemplateId` 变化：非空时从 templates 列表查找并填充 META/PARAMS/LOGIC/RISK_FILTER 各区
  - [x] SubTask 10.3: `handleSave` 根据 `editingTemplateId` 决定调 `updateTemplate(id, body)` 还是 `createTemplate(body)`
  - [x] SubTask 10.4: 保存按钮文案：编辑模式 "更新模板"，新建模式 "保存模板"
  - [x] SubTask 10.5: `handleClose` 重置 `editingTemplateId` 相关状态

- [x] Task 11: StrategiesPage 模板管理 UI
  - [x] SubTask 11.1: 修改 [StrategiesPage.tsx](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/pages/StrategiesPage.tsx) 顶部新增"模板管理"按钮，打开模板管理 Modal
  - [x] SubTask 11.2: Modal 内展示自定义模板列表（名称 / strategy_type / logic_hash 前 8 位）
  - [x] SubTask 11.3: 每项含"编辑"和"删除"按钮
  - [x] SubTask 11.4: "删除"调 `deleteTemplate(id)`（已 import），删除前 confirm 弹窗
  - [x] SubTask 11.5: "编辑"打开 DslEditor 并传 `editingTemplateId={id}`
  - [x] SubTask 11.6: 编辑/删除后刷新模板列表（`loadData`）

## 阶段四：QS-Model 币对锁定（问题 3）

- [x] Task 12: 前端创建实例 symbol 锁定
  - [x] SubTask 12.1: 修改 [StrategiesPage.tsx](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/pages/StrategiesPage.tsx) 创建实例弹窗读取 `selectedTemplate.qs_model_config?.meta?.base_symbol`
  - [x] SubTask 12.2: 非空时 symbol 输入框 `readOnly` + `value={baseSymbol}` + 视觉提示（灰色背景或"已锁定"标签）
  - [x] SubTask 12.3: 为空时保持当前可编辑行为
  - [x] SubTask 12.4: 内置硬编码策略模板（grid/trend 等）无 qs_model_config，symbol 仍可编辑

- [x] Task 13: 后端 create_instance 强制 symbol
  - [x] SubTask 13.1: 修改 [routers/strategies.py](file:///e:/New%20folder%20(2)/quant_okx/backend/routers/strategies.py) `create_instance`：若 `template.qs_model_config.meta.base_symbol` 非空，强制 `body.symbol = base_symbol`
  - [x] SubTask 13.2: 编写测试：模板设 base_symbol="BTC-USDT"，前端传 "ETH-USDT"，最终实例 symbol="BTC-USDT"

## 阶段五：order_qty 小数输入修复（问题 5）

- [x] Task 14: 前端 step 修复
  - [x] SubTask 14.1: 修改 [StrategiesPage.tsx](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/pages/StrategiesPage.tsx) 实例参数编辑区 `step={field?.step ?? 1}` 改为根据 `field?.type` 判断：int 用 1，float/number 用 'any'
  - [x] SubTask 14.2: 修改 [DslEditor.tsx](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/components/DslEditor.tsx) `flattenParamsToSchema` 为 float/number 类型设置 `step: 'any'`，int 类型 `step: 1`

- [x] Task 15: 后端 order_qty param_schema 补 step
  - [x] SubTask 15.1: 修改 [bases.py](file:///e:/New%20folder%20(2)/quant_okx/backend/dsl/blocks/bases.py) GridBlock 的 `order_qty` param_schema 增加 `"step": 0.001`
  - [x] SubTask 15.2: 编写测试：GET /api/dsl/blocks 返回的 grid 基础策略 order_qty 含 step=0.001

## 阶段六：端到端验证

- [x] Task 16: 端到端验证
  - [x] SubTask 16.1: 验证 Windows 启动后端无 `too many file descriptors` 错误（代码审查：launcher.py L17-18 设置 WindowsProactorEventLoopPolicy）
  - [x] SubTask 16.2: 验证 check_feasibility 调用后 httpx 连接数不累积（代码审查：check_feasibility try/finally + aclose）
  - [x] SubTask 16.3: 验证同账户多实例共享 OKXClient（代码审查：_account_clients 缓存 + _get_client_for_account）
  - [x] SubTask 16.4: 验证 12 格网格策略运行 5 分钟后委托订单数 ≤ 24（初始 12 + 反向挂单 12，无重复）（代码审查：executor 自环去重 + GridBlock 去重 + on_resume 增量补挂）
  - [x] SubTask 16.5: 验证模板管理 Modal 列表/编辑/删除流程（代码审查：TemplateMgmtModal 组件完整）
  - [x] SubTask 16.6: 验证 DslEditor 编辑模式加载模板并保存为更新（代码审查：editingTemplateId + handleSave 分支）
  - [x] SubTask 16.7: 验证设了 base_symbol 的模板创建实例时 symbol 锁定（代码审查：lockedBaseSymbol + readOnly + 后端强制）
  - [x] SubTask 16.8: 验证未设 base_symbol 的模板创建实例时 symbol 可输入（代码审查：为空时 readOnly=false）
  - [x] SubTask 16.9: 验证 order_qty 输入 0.01 可保存（代码审查：前端 step 修复 + 后端 step=0.001）
  - [x] SubTask 16.10: 验证同 logic_hash 模板启动复用 FSM 缓存（代码审查：executor _fsm_cache 模块级 dict）

# Task Dependencies

- Task 1 / Task 2（问题 1）可并行，无依赖
- Task 3 / Task 4 / Task 5（问题 6 致命 Bug 三处）有顺序依赖：Task 3（executor 状态去重）→ Task 4（GridBlock 去重）→ Task 5（on_order_filled 接通），但可由同一 sub-agent 顺序完成
- Task 6 / Task 7（问题 4）依赖 Task 3（executor 改动完成）
- Task 8（后端 PUT 端点）独立
- Task 9 / Task 10 / Task 11（前端模板管理）依赖 Task 8
- Task 12 / Task 13（问题 3 币对锁定）独立
- Task 14 / Task 15（问题 5 step 修复）独立
- Task 16（端到端）依赖全部上游

可并行批次：
- 批次 A（后端致命 Bug）：Task 1 + Task 2 + Task 3+4+5
- 批次 B（FSM 缓存）：Task 6 + Task 7（依赖 A 完成）
- 批次 C（模板管理）：Task 8 + Task 9 + Task 10 + Task 11
- 批次 D（币对锁定）：Task 12 + Task 13
- 批次 E（step 修复）：Task 14 + Task 15
- 批次 C/D/E 可与批次 A/B 并行
