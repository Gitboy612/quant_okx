# 运行时 Bug 修复与模板管理 Spec

## Why

实际运行中暴露出 6 个问题：(1) Windows 下 asyncio `select()` 文件描述符超限崩溃；(2) QS-Model 模板无编辑/删除管理 UI；(3) QS-Model 设定币对后新建实例未锁定；(4) 担心 JSON 解析开销（实测每 tick 不重解析，但运行时改参不重编译）；(5) order_qty 输入 0.01 被阻断；(6) **致命 Bug**：12 格网格却下 390+ 单，根因是 RUNNING→RUNNING 自环每 tick 触发 `on_resume→on_start` 全量重挂且无去重。

## What Changes

### 问题 1：Windows asyncio 文件描述符超限

- **修改**：[launcher.py](file:///e:/New%20folder%20(2)/quant_okx/backend/launcher.py) 在 Windows 平台启动早期设置 `asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())`（ProactorEventLoop 无 FD 上限）
- **修改**：[strategy_engine.py](file:///e:/New%20folder%20(2)/quant_okx/backend/services/strategy_engine.py) `check_feasibility` 中创建的 `OKXClient` 用完后调用 `await client.aclose()` 修复连接泄漏
- **修改**：[strategy_engine.py](file:///e:/New%20folder%20(2)/quant_okx/backend/services/strategy_engine.py) 按账户共享 `OKXClient`（同账户多实例复用一个 httpx 连接池），避免每实例独占 100 连接上限
- **修改**：[start.bat](file:///e:/New%20folder%20(2)/quant_okx/start.bat) 启动脚本确保走 launcher.py（已设事件循环策略）

### 问题 2：QS-Model 模板编辑/删除管理

- **修改**：[routers/strategies.py](file:///e:/New%20folder%20(2)/quant_okx/backend/routers/strategies.py) 新增 `PUT /api/strategies/templates/{id}` 端点更新自定义模板
- **修改**：[api/strategies.ts](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/api/strategies.ts) 新增 `updateTemplate` 函数
- **修改**：[StrategiesPage.tsx](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/pages/StrategiesPage.tsx) 新增模板管理区（列表 + 编辑/删除按钮），调用 `deleteTemplate`（已 import 但未使用）
- **修改**：[DslEditor.tsx](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/components/DslEditor.tsx) 支持编辑模式：接收 `editingTemplateId` prop，打开时加载该模板配置填充表单，保存时按有无 id 调 create/update

### 问题 3：QS-Model 币对可选 + 锁定

- **修改**：[StrategiesPage.tsx](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/pages/StrategiesPage.tsx) 创建实例弹窗读取 `selectedTemplate.qs_model_config?.meta?.base_symbol`：非空时 symbol 字段只读展示该值；为空时 symbol 字段可编辑（当前行为）
- **修改**：[routers/strategies.py](file:///e:/New%20folder%20(2)/quant_okx/backend/routers/strategies.py) `create_instance` 中若模板 `qs_model_config.meta.base_symbol` 非空，强制 `body.symbol = base_symbol`（忽略用户输入）

### 问题 4：模板存储与编译缓存

- 不改为本地文件存储（当前数据库存储 + 启动时一次性解析 FSM 已合理，每 tick 不重解析）
- **修改**：[executor.py](file:///e:/New%20folder%20(2)/quant_okx/backend/dsl/executor.py) 按 `logic_hash` 缓存编译后的 FSM（进程级 dict），同逻辑模板复用编译产物，减少启动开销
- **修改**：[strategy_engine.py](file:///e:/New%20folder%20(2)/quant_okx/backend/services/strategy_engine.py) `update_params` 检测 `qs_model_config` 变化时触发 FSM 重编译（或拒绝运行中改 logic 结构）

### 问题 5：order_qty 输入 0.01 被阻断

- **修改**：[StrategiesPage.tsx](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/pages/StrategiesPage.tsx) 实例参数编辑区 `step={field?.step ?? 1}` 改为 `step={field?.step ?? (isNumeric ? 'any' : 1)}`，float/number 类型回退 `'any'`
- **修改**：[DslEditor.tsx](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/components/DslEditor.tsx) `flattenParamsToSchema` 为 `float`/`number` 类型设置 `step: 'any'`（int 仍 `step: 1`）
- **修改**：[bases.py](file:///e:/New%20folder%20(2)/quant_okx/backend/dsl/blocks/bases.py) GridBlock 的 `order_qty` param_schema 补充 `step: 0.001`（与内置网格模板一致）

### 问题 6：网格 12 格下 390+ 单（致命 Bug）

- **修改**：[executor.py](file:///e:/New%20folder%20(2)/quant_okx/backend/dsl/executor.py) `_enter_state` 仅在状态**实际变化**（`old_state != new_state`）时调用 `on_pause`/`on_resume`，避免 RUNNING→RUNNING 自环每 tick 触发 `on_resume`
- **修改**：[bases.py](file:///e:/New%20folder%20(2)/quant_okx/backend/dsl/blocks/bases.py) `GridBlock.on_start` 循环内增加去重：`if i in self.active_buy: continue`（卖单同理），避免重复挂单
- **修改**：[bases.py](file:///e:/New%20folder%20(2)/quant_okx/backend/dsl/blocks/bases.py) `GridBlock.on_resume` 不再盲目调 `on_start` 全量重挂，改为只补挂 `active_buy`/`active_sell` 中缺失的层级
- **修改**：[executor.py](file:///e:/New%20folder%20(2)/quant_okx/backend/dsl/executor.py) 在 OrderManager "filled" 回调中调用 `self._base_block.on_order_filled(order, ctx)`（当 base_block 非 None 时），接通网格反向挂单逻辑
- **修改**：[bases.py](file:///e:/New%20folder%20(2)/quant_okx/backend/dsl/blocks/bases.py) `GridBlock.on_order_filled` 的 `grid_idx` 匹配容差从 `tick_size * 0.6` 改为 `tick_size * 0.5` 并增加最近层级兜底匹配

## Impact

### 受影响代码
- **后端**：
  - [launcher.py](file:///e:/New%20folder%20(2)/quant_okx/backend/launcher.py)（问题 1 事件循环）
  - [strategy_engine.py](file:///e:/New%20folder%20(2)/quant_okx/backend/services/strategy_engine.py)（问题 1 连接泄漏 + 问题 4 重编译）
  - [routers/strategies.py](file:///e:/New%20folder%20(2)/quant_okx/backend/routers/strategies.py)（问题 2 PUT 端点 + 问题 3 symbol 锁定）
  - [executor.py](file:///e:/New%20folder%20(2)/quant_okx/backend/dsl/executor.py)（问题 4 FSM 缓存 + 问题 6 状态去重 + on_order_filled 接通）
  - [bases.py](file:///e:/New%20folder%20(2)/quant_okx/backend/dsl/blocks/bases.py)（问题 5 order_qty step + 问题 6 网格去重/补挂/on_order_filled 容差）
- **前端**：
  - [StrategiesPage.tsx](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/pages/StrategiesPage.tsx)（问题 2 模板管理 UI + 问题 3 symbol 锁定 + 问题 5 step 修复）
  - [DslEditor.tsx](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/components/DslEditor.tsx)（问题 2 编辑模式 + 问题 5 flattenParamsToSchema step）
  - [api/strategies.ts](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/api/strategies.ts)（问题 2 updateTemplate）

### 受影响 specs
- `fix-qsm-builder-issues`（问题 2/3/5 是其后续完善）
- `rebrand-strategy-builder-qsm`（网格执行逻辑修复）
- `add-composable-strategy-dsl`（executor 状态机自环处理）

## ADDED Requirements

### Requirement: Windows ProactorEventLoop 支持

系统 SHALL 在 Windows 平台启动早期将事件循环策略切换为 `WindowsProactorEventLoopPolicy`，避免 `select.select()` 的 512 FD 上限导致崩溃。

#### Scenario: Windows 多策略实例不崩溃
- **WHEN** 后端在 Windows 启动并运行多个策略实例
- **THEN** 事件循环使用 ProactorEventLoop
- **AND** 不出现 `ValueError: too many file descriptors in select()`

### Requirement: OKXClient 连接泄漏修复与按账户共享

系统 SHALL 在 `check_feasibility` 等临时使用 `OKXClient` 的地方用完后调用 `aclose()`，避免连接泄漏；并按账户共享 `OKXClient` 以减少连接数。

#### Scenario: check_feasibility 不泄漏连接
- **WHEN** `check_feasibility` 创建临时 `OKXClient` 用于查询
- **THEN** 使用完毕后调用 `await client.aclose()` 释放连接池
- **AND** 不出现 httpx 连接数累积

#### Scenario: 同账户多实例共享 OKXClient
- **WHEN** 同一账户下启动多个策略实例
- **THEN** 这些实例共享同一个 `OKXClient`（连接池）
- **AND** 总连接数不超过单个 client 的 max_connections 上限

### Requirement: QS-Model 模板编辑与删除管理

系统 SHALL 提供模板管理 UI 与后端接口，支持对自定义模板进行编辑和删除操作。

#### Scenario: 后端支持更新模板
- **WHEN** 前端调用 `PUT /api/strategies/templates/{id}` 传入更新字段
- **THEN** 后端更新对应模板的 `qs_model_config` / `dsl_config` / `default_params` 等字段
- **AND** 重新计算 `logic_hash`（若 logic 段变化）
- **AND** 返回更新后的模板对象

#### Scenario: 前端模板管理列表
- **WHEN** 用户进入策略管理页打开"模板管理"区
- **THEN** 展示所有自定义模板列表（名称 / 类型 / logic_hash 简写）
- **AND** 每项含"编辑"和"删除"按钮
- **AND** 点击"删除"调用 `deleteTemplate(id)` 并刷新列表
- **AND** 点击"编辑"打开 DslEditor 加载该模板配置

#### Scenario: DslEditor 编辑模式
- **WHEN** DslEditor 接收 `editingTemplateId` prop 非空
- **THEN** 打开时从模板列表中加载该 id 的配置
- **AND** 填充 META/PARAMS/LOGIC/RISK_FILTER 各区字段
- **AND** 保存按钮文案改为"更新"，调用 `updateTemplate(id, body)` 而非 `createTemplate(body)`

### Requirement: QS-Model 币对可选与实例创建锁定

系统 SHALL 支持 QS-Model 的 `meta.base_symbol` 为可选字段：为空时创建实例由用户输入；非空时实例创建时锁定该值。

#### Scenario: 模板未设 base_symbol 时实例可输入
- **WHEN** 用户基于 `meta.base_symbol` 为空的 QS-Model 模板创建实例
- **THEN** 创建实例弹窗中 symbol 字段可编辑
- **AND** 用户输入的 symbol 透传到后端

#### Scenario: 模板设了 base_symbol 时实例锁定
- **WHEN** 用户基于 `meta.base_symbol="BTC-USDT"` 的模板创建实例
- **THEN** 创建实例弹窗中 symbol 字段只读，展示 "BTC-USDT"
- **AND** 后端 `create_instance` 强制 `body.symbol = base_symbol`（忽略前端传值）

### Requirement: FSM 编译缓存与参数更新重编译

系统 SHALL 按 `logic_hash` 缓存编译后的 FSM，避免相同逻辑重复编译；当实例 `qs_model_config` 的 logic 段在运行中变化时触发重编译。

#### Scenario: 同逻辑模板复用 FSM
- **WHEN** 两个实例的 `logic_hash` 相同
- **THEN** 启动时复用进程级缓存中已编译的 FSM
- **AND** 不重复执行 FSMCompiler.compile()

#### Scenario: 运行中改 logic 触发重编译
- **WHEN** `update_params` 检测到 `qs_model_config.logic` 段变化（logic_hash 变更）
- **THEN** 触发 FSM 重编译并替换 `self._fsm`
- **AND** 若新 FSM 与旧 FSM 状态不兼容，拒绝更新并返回错误

### Requirement: order_qty 等浮点参数支持小数输入

系统 SHALL 让 `order_qty` 等浮点参数支持小数输入（如 0.01），不因前端 step 默认值阻断。

#### Scenario: 实例参数编辑区输入 0.01
- **WHEN** 用户在实例参数编辑区输入 order_qty=0.01
- **THEN** 输入框接受该值（step 不强制对齐）
- **AND** 保存后后端正确接收 0.01

#### Scenario: DslEditor 参数表单输入小数
- **WHEN** 用户在 DslEditor 的 BlockArgsForm 中输入浮点参数小数值
- **THEN** float/number 类型参数 step 为 'any'，可任意小数
- **AND** int 类型参数 step 仍为 1，不允许小数

### Requirement: 网格执行不重复挂单（修复 390+ 单 Bug）

系统 SHALL 确保 RUNNING→RUNNING 状态自环不触发 `on_resume`，且 `on_start`/`on_resume` 不重复挂已存在的层级订单，避免每 tick 全量重挂。

#### Scenario: 无 recover_when 的规则不触发 on_resume
- **WHEN** 策略含一条规则无 `recover_when`（编译为 RUNNING→RUNNING 自环）
- **AND** 每个 tick 评估该规则
- **THEN** `_enter_state(RUNNING)` 检测到 `old_state == RUNNING` 时跳过 `on_resume` 调用
- **AND** 不重新挂单

#### Scenario: on_start 不重复挂已存在层级
- **WHEN** `GridBlock.on_start` 被调用（首次启动）
- **THEN** 循环每个 grid level 前 `if i in self.active_buy: continue`
- **AND** 已有挂单的层级被跳过

#### Scenario: on_resume 增量补挂
- **WHEN** `GridBlock.on_resume` 被调用（从 PAUSED 恢复）
- **THEN** 不再调用 `on_start` 全量重挂
- **AND** 只补挂 `active_buy`/`active_sell` 中缺失的层级

#### Scenario: 订单成交触发反向挂单
- **WHEN** OrderManager 收到订单 filled 回调
- **AND** `executor._base_block` 非 None
- **THEN** 调用 `base_block.on_order_filled(order, ctx)`
- **AND** 网格根据成交层级补挂反向订单

#### Scenario: grid_idx 匹配容差优化
- **WHEN** `on_order_filled` 用订单价格匹配 grid level
- **THEN** 容差从 `tick_size * 0.6` 改为 `tick_size * 0.5`
- **AND** 若无精确匹配，回退到最近层级（避免反向挂单丢失）

## MODIFIED Requirements

### Requirement: 策略实例启动事件循环（来自 add-composable-strategy-dsl）

[原内容：策略实例在 asyncio 事件循环中运行，使用 OKXClient 进行 API 调用]

**修改**：Windows 平台启动早期设置 ProactorEventLoopPolicy；OKXClient 按账户共享，临时使用后 aclose()。

### Requirement: QS-Model 模板生命周期（来自 rebrand-strategy-builder-qsm）

[原内容：StrategyTemplate 含 qs_model_config / logic_hash 字段，创建时计算 hash]

**修改**：新增 PUT 更新端点；更新时重新计算 logic_hash；前端提供模板管理 UI 支持编辑/删除。

## 范围说明

本 spec 仅覆盖 6 个运行时 Bug 与模板管理完善。以下不在本 spec 范围：

- 网格策略本身的核心逻辑（仅修复重复挂单 Bug，不改交易算法）
- 模板本地文件存储方案（实测 DB 存储 + 启动时一次性 FSM 编译已足够，不引入 .dat 文件）
- 前端模板拖拽排序（二期可选）
