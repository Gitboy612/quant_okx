# QS-Model 策略构建问题修复 Spec

## Why

`rebrand-strategy-builder-qsm` spec 已完成实现，但实际使用中暴露出 9 个问题：QS-Model 构建强制默认交易币对、参数类型下拉框溢出容器、枚举类型无法定义选项、整数参数允许输入小数、运行频率是死字段、基础策略不能为空、风控既无开关也无止损止盈、基于 QS-Model 模板新建实例时参数配置空白、操作日志时间因时区处理不一致而显示偏差。这些问题直接影响投资人员的可用性，需统一修复。

## What Changes

### 问题 1：QS-Model 构建不默认交易币对
- **修改**：[DslEditor.tsx](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/components/DslEditor.tsx) `initialMeta()` 中 `base_symbol` 由 `'BTC-USDT'` 改为空字符串 `''`
- **修改**：[DslEditor.tsx](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/components/DslEditor.tsx) `baseSymbol` 回退链移除末尾的 `'BTC-USDT'` 兜底，改为返回空字符串
- **修改**：[DslEditor.tsx](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/components/DslEditor.tsx) 保存校验增加对 `meta.base_symbol` 必填的提示（若 LOGIC 区有规则或基础策略需要 symbol，则 base_symbol 必填）

### 问题 2：可变参数 / 规则 / 条件 / 事件下拉框溢出容器
- **修改**：[Dropdown.tsx](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/components/Dropdown.tsx) 下拉面板支持 `panelWidth` / `minPanelWidth` 属性，使面板宽度可独立于触发器宽度
- **修改**：[Dropdown.tsx](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/components/Dropdown.tsx) 下拉面板使用 Portal 渲染到 `document.body`，避免被父容器 `overflow-hidden` / `overflow-y-auto` 裁剪
- **修改**：[DslEditor.tsx](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/components/DslEditor.tsx) `ParamsEditor` 类型下拉、`BlockPicker`、规则/条件/事件下拉统一使用增强后的 Dropdown，并传入足够的 `minPanelWidth`
- **修改**：[DslEditor.tsx](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/components/DslEditor.tsx) 可折叠分区容器在展开时不使用 `overflow-hidden`，避免裁剪内部下拉面板（已用 Portal 后此问题应自然解决）

### 问题 3：枚举类型允许用户自定义选项
- **修改**：[DslEditor.tsx](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/components/DslEditor.tsx) `ParamsEditor` 当类型选「枚举(select)」时，展开「枚举选项编辑器」：可增删的「值 + 中文标签」对列表
- **修改**：[DslEditor.tsx](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/components/DslEditor.tsx) 枚举参数的「默认值」输入改为从已定义选项中下拉选择
- **修改**：[DslEditor.tsx](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/components/DslEditor.tsx) 组装 `qs_model_config.params` 时，select 类型参数输出 `options` / `option_labels` 字段
- **修改**：[dsl.ts](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/types/dsl.ts) `ParamDefinition` 类型字段中 `options` / `option_labels` 在编辑器内可编辑（已存在字段，仅 UI 补充）
- 后端 `ParamDefinition`（[schema.py](file:///e:/New%20folder%20(2)/quant_okx/backend/dsl/schema.py)）已支持 `options` / `option_labels`，无需改动

### 问题 4：输入格式校验（int 不允许小数）
- **修改**：[DslEditor.tsx](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/components/DslEditor.tsx) `normalizeParamDef` 不再把 `integer`/`int` 归一化为 `number`，保留 `int` 与 `float`/`number` 区分
- **修改**：[DslEditor.tsx](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/components/DslEditor.tsx) `BlockArgsForm` 数字输入按类型设置 `step`：`int` → `step=1` 且 `min`/`max` 取整；`float`/`number` → 保留 `step='any'` 或 `param.step`
- **修改**：[DslEditor.tsx](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/components/DslEditor.tsx) 数字输入增加 `onChange` 校验：int 类型若输入小数则拒绝/截断并提示
- **修改**：[DslEditor.tsx](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/components/DslEditor.tsx) `ParamsEditor` 自定义参数的 int 类型默认值输入同样 `step=1`
- **修改**：[bases.py](file:///e:/New%20folder%20(2)/quant_okx/backend/dsl/blocks/bases.py) `grid` 的 `grid_count` schema 类型由 `"number"` 改为 `"integer"`，与构造时 `int()` 一致

### 问题 5：运行频率移交策略消费
- **修改**：[bases.py](file:///e:/New%20folder%20(2)/quant_okx/backend/dsl/blocks/bases.py) `TrendBlock` / `RsiBlock` / `BollingerBlock` / `DonchianBlock` 的 `on_tick` 中 `bar="1H"` 改为读取 `self.bar`（来自 params 的 `bar` / `frequency` 参数）
- **修改**：[bases.py](file:///e:/New%20folder%20(2)/quant_okx/backend/dsl/blocks/bases.py) 上述 4 个策略的 `param_schema` 增加 `bar` 参数（select，options=[1m/5m/15m/1H/4H/1D]，默认 `1H`），label="K线周期"
- **修改**：[DslEditor.tsx](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/components/DslEditor.tsx) META 区「运行频率」字段保留作为元信息展示，但增加说明文案「此字段为元信息，实际 K 线周期请在基础策略参数中配置」
- **修改**：[schema.py](file:///e:/New%20folder%20(2)/quant_okx/backend/dsl/schema.py) `resolve_variables` 保持不变（用户仍可手动用 `$meta.frequency` 引用）
- 不删除 `meta.frequency` 字段，保留为元数据，避免破坏已有模板

### 问题 6：基础策略可以为「无」（纯规则驱动）
- **修改**：[DslEditor.tsx](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/components/DslEditor.tsx) `BlockPicker` 基础策略选择增加「无（纯规则驱动）」选项；选中后清空 `base_strategy`，LOGIC 区只显示规则列表
- **修改**：[schema.py](file:///e:/New%20folder%20(2)/quant_okx/backend/dsl/schema.py) `BaseStrategyRef` 的 `kind` 改为可选（`kind: str | None = None`），`params` 默认空 dict
- **修改**：[schema.py](file:///e:/New%20folder%20(2)/quant_okx/backend/dsl/schema.py) `StrategyDSL.base_strategy` 改为可选（`base_strategy: BaseStrategyRef | None = None`）
- **修改**：[validator.py](file:///e:/New%20folder%20(2)/quant_okx/backend/dsl/validator.py) 基础策略校验：`kind` 为空时跳过注册表校验，但要求 `rules` 至少一条（纯规则必须有规则）
- **修改**：[executor.py](file:///e:/New%20folder%20(2)/quant_okx/backend/dsl/executor.py) `base_strategy` 为 None 时跳过基础策略实例化与生命周期调用，仅运行 FSM 规则循环
- **修改**：[DslEditor.tsx](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/components/DslEditor.tsx) 当基础策略为「无」时，规则级 symbol 不再继承（因为无基础策略），规则级 symbol 参数需用户在规则中显式选择（显示 SymbolPicker）

### 问题 7：风控开关 + 止损止盈
- **修改**：[DslEditor.tsx](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/components/DslEditor.tsx) RISK_FILTER 区顶部增加「启用风控」开关；关闭时 `risk_filter` 为 null，不展开字段
- **修改**：[DslEditor.tsx](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/components/DslEditor.tsx) RISK_FILTER 区增加「止损(stop_loss)」「止盈(take_profit)」字段，单位 `%`，支持按比例
- **修改**：[dsl.ts](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/types/dsl.ts) `RiskFilter` 增加 `stop_loss?: number` / `take_profit?: number` / `blacklist_hours?: string[]` 字段
- **修改**：[schema.py](file:///e:/New%20folder%20(2)/quant_okx/backend/dsl/schema.py) `RiskFilter` 增加 `stop_loss: float | None = None` / `take_profit: float | None = None`
- **修改**：[executor.py](file:///e:/New%20folder%20(2)/quant_okx/backend/dsl/executor.py) 在主循环中实际执行风控检查：下单前校验 max_position_ratio / min_trade_size；每 tick 检查 daily_max_loss / stop_loss / take_profit，触发时调用 `close_all` + `stop_strategy` + `log_event`

### 问题 8：基于 QS-Model 模板新建实例时读取可变参数
- **修改**：[StrategiesPage.tsx](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/pages/StrategiesPage.tsx) 新建策略 Modal 的参数渲染逻辑：当 `selectedTemplate.param_schema` 为空但 `qs_model_config.params` 非空时，从 `qs_model_config.params` 构建参数 schema 并渲染输入控件
- **修改**：[StrategiesPage.tsx](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/pages/StrategiesPage.tsx) 参数渲染按 `ParamDefinition.type` 分类型渲染：int/float → 数字输入（int step=1）、string → 文本、bool → 开关、select → 下拉（用 options/option_labels）
- **修改**：[StrategiesPage.tsx](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/pages/StrategiesPage.tsx) 创建实例请求时，把用户输入的参数值作为 `params` 传给后端（后端 create_instance 已支持合并到 `param_overrides`）
- **修改**：[DslEditor.tsx](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/components/DslEditor.tsx) 保存 QS-Model 模板时，同步把 `qs_model_config.params` 拍平写入 `param_schema` 字段（保持与新建 Modal 的现有读取逻辑兼容，双保险）

### 问题 9：操作日志时间基准标注
- **修改**：[logs.py](file:///e:/New%20folder%20(2)/quant_okx/backend/routers/logs.py) 序列化 `created_at` 时显式附加时区：`l.created_at.isoformat() + "Z"`（若 naive 则视为 UTC）或用 `datetime` 的 `astimezone` 标注
- **修改**：[strategies.py](file:///e:/New%20folder%20(2)/quant_okx/backend/routers/strategies.py) 实例时间序列化同样显式标注 UTC（`+ "Z"`）
- **修改**：[log_service.py](file:///e:/New%20folder%20(2)/quant_okx/backend/services/log_service.py) 日志文件命名与 mtime 改用 `datetime.now(timezone.utc)` 统一 UTC
- **修改**：[LogsPage.tsx](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/pages/LogsPage.tsx) 时间显示增加「UTC+8 本地时间」标注，并确保 `new Date()` 解析带 Z 后缀的字符串
- **修改**：[ApiLogsPage.tsx](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/pages/ApiLogsPage.tsx) 时间显示补全日期 + 时区标注
- **修改**：后端日志写入时（OKX API 请求/响应日志）增加「时间基准：UTC」标注字段或在前端统一显示「OKX 返回时间为 UTC，已转换为本地时间」

## Impact

### 受影响代码
- **前端**：
  - [DslEditor.tsx](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/components/DslEditor.tsx)（问题 1/2/3/4/5/6/7/8 核心）
  - [Dropdown.tsx](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/components/Dropdown.tsx)（问题 2 Portal+宽度）
  - [StrategiesPage.tsx](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/pages/StrategiesPage.tsx)（问题 8 新建实例参数渲染）
  - [dsl.ts](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/types/dsl.ts)（问题 3/7 类型扩展）
  - [LogsPage.tsx](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/pages/LogsPage.tsx)（问题 9 时间显示）
  - [ApiLogsPage.tsx](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/pages/ApiLogsPage.tsx)（问题 9 时间显示）
- **后端**：
  - [schema.py](file:///e:/New%20folder%20(2)/quant_okx/backend/dsl/schema.py)（问题 5/6/7 模型扩展）
  - [bases.py](file:///e:/New%20folder%20(2)/quant_okx/backend/dsl/blocks/bases.py)（问题 4/5 grid_count 类型 + bar 参数）
  - [validator.py](file:///e:/New%20folder%20(2)/quant_okx/backend/dsl/validator.py)（问题 6 基础策略可空校验）
  - [executor.py](file:///e:/New%20folder%20(2)/quant_okx/backend/dsl/executor.py)（问题 6/7 基础策略可空 + 风控执行）
  - [routers/strategies.py](file:///e:/New%20folder%20(2)/quant_okx/backend/routers/strategies.py)（问题 9 时间序列化）
  - [routers/logs.py](file:///e:/New%20folder%20(2)/quant_okx/backend/routers/logs.py)（问题 9 时间序列化）
  - [services/log_service.py](file:///e:/New%20folder%20(2)/quant_okx/backend/services/log_service.py)（问题 9 时间统一 UTC）

### 受影响 specs
- `rebrand-strategy-builder-qsm`（本 spec 是对其实现的问题修复）
- `add-composable-strategy-dsl`（基础策略可空影响 DSL 模型）
- `add-dsl-template-frontend`（新建实例参数渲染）

## ADDED Requirements

### Requirement: QS-Model 构建不预设交易币对

系统 SHALL 在 QS-Model 编辑器初始化时将 `meta.base_symbol` 置空，不预设任何交易币对；用户必须显式选择交易对后才能保存含基础策略或规则的模板。

#### Scenario: 打开 QS-Model 编辑器初始无交易对
- **WHEN** 用户点击「QS-Model 策略构建」打开编辑器
- **THEN** META 区「基准交易对」字段为空
- **AND** 不预填 BTC-USDT 或任何默认值

#### Scenario: 未选交易对保存被拦截
- **WHEN** 用户未选择基准交易对即点击保存
- **AND** LOGIC 区含基础策略或规则
- **THEN** 校验失败，提示「请先选择基准交易对」

### Requirement: 下拉面板 Portal 渲染与宽度独立

系统 SHALL 让 Dropdown 下拉面板通过 Portal 渲染到 `document.body`，且面板宽度可独立于触发器宽度（支持 `minPanelWidth`），避免被父容器 `overflow` 裁剪。

#### Scenario: 参数类型下拉在窄列中完整展示
- **WHEN** 用户在 PARAMS 区的「类型」下拉（col-span-2 窄列）中点开下拉
- **THEN** 下拉面板宽度足够展示「整数/浮点/字符串/布尔/枚举」完整文案
- **AND** 面板不被 Modal 或可折叠分区的 `overflow` 裁剪

#### Scenario: 规则条件下拉完整展示
- **WHEN** 用户在规则列表最后一条规则的条件选择下拉中点开
- **THEN** 下拉面板完整展示所有条件积木的中文 label
- **AND** 不被规则卡片底部边界裁剪

### Requirement: 枚举参数支持用户自定义选项

系统 SHALL 在 PARAMS 区当参数类型选「枚举」时，提供「值 + 中文标签」对的增删编辑器，并将结果写入 `options` / `option_labels`；枚举参数的默认值从已定义选项中下拉选择。

#### Scenario: 用户定义枚举参数
- **WHEN** 用户在 PARAMS 区新增一个参数，类型选「枚举」
- **AND** 在展开的枚举选项编辑器中添加「buy→买入」「sell→卖出」两项
- **AND** 默认值下拉选择「买入」
- **THEN** 保存的 `qs_model_config.params` 中该参数含 `options=["buy","sell"]` / `option_labels=["买入","卖出"]` / `value="buy"`

#### Scenario: 枚举默认值只能从选项中选择
- **WHEN** 用户编辑枚举参数的默认值
- **THEN** 渲染为下拉，选项为已定义的枚举值
- **AND** 不允许手敲文本

### Requirement: 整数参数输入格式校验

系统 SHALL 区分 `int` 与 `float`/`number` 类型：int 类型输入框 `step=1` 且拒绝小数；float/number 类型允许小数。

#### Scenario: grid_count 不允许输入小数
- **WHEN** 用户在 grid 基础策略参数表单中编辑 grid_count
- **THEN** 输入框 `step=1`，输入 3.5 被拒绝或截断为 3
- **AND** 输入框不出现小数点

#### Scenario: 自定义 int 参数同样约束
- **WHEN** 用户在 PARAMS 区定义一个 int 类型参数
- **THEN** 默认值输入框 `step=1`，不允许小数

### Requirement: 运行频率移交策略 bar 参数

系统 SHALL 让基础策略的 K 线周期由策略自身的 `bar` 参数控制（默认 `1H`），META 区 `frequency` 字段保留为元信息但增加说明文案；用户可在基础策略参数中修改 bar。

#### Scenario: 用户修改趋势策略 K 线周期
- **WHEN** 用户选择 trend 基础策略
- **AND** 在参数表单中把 bar 参数改为 `15m`
- **THEN** 执行时 TrendBlock 用 `bar="15m"` 拉 K 线
- **AND** 不再硬编码 `1H`

#### Scenario: META frequency 仍可被引用
- **WHEN** 用户在 LOGIC 区某参数值写 `$meta.frequency`
- **THEN** 仍能解析为 `meta.frequency` 的值

### Requirement: 基础策略可以为「无」

系统 SHALL 允许基础策略为空（纯规则驱动），此时 `base_strategy` 为 null，策略仅靠 rules + actions 驱动；校验器要求纯规则策略至少有一条规则。

#### Scenario: 用户选择无基础策略
- **WHEN** 用户在 LOGIC 区基础策略下拉选择「无（纯规则驱动）」
- **THEN** 基础策略参数表单消失
- **AND** 规则列表保留
- **AND** 规则级 symbol 参数需要用户显式选择（不再继承）

#### Scenario: 纯规则策略至少一条规则
- **WHEN** 用户基础策略选「无」且未添加任何规则即保存
- **THEN** 校验失败，提示「无基础策略时至少需要一条规则」

#### Scenario: 执行器跳过基础策略生命周期
- **WHEN** 策略启动且 `base_strategy` 为 null
- **THEN** 执行器不调用任何基础策略钩子
- **AND** 仅运行 FSM 规则循环

### Requirement: 风控开关与止损止盈

系统 SHALL 在 RISK_FILTER 区提供「启用风控」开关；启用后展开字段含 `max_position_ratio` / `daily_max_loss` / `min_trade_size` / `stop_loss` / `take_profit`；关闭时 `risk_filter` 为 null。执行器 SHALL 在主循环中实际执行风控检查。

#### Scenario: 关闭风控
- **WHEN** 用户在 RISK_FILTER 区关闭「启用风控」开关
- **THEN** 风控字段折叠，保存的 `risk_filter` 为 null
- **AND** 执行器跳过所有风控检查

#### Scenario: 配置止损止盈
- **WHEN** 用户启用风控并设置 stop_loss=5%、take_profit=10%
- **THEN** 保存的 `risk_filter` 含 `stop_loss=0.05` / `take_profit=0.1`
- **AND** 执行时未实现亏损达 5% 触发 close_all + stop_strategy

#### Scenario: 风控实际生效
- **WHEN** 策略运行中 daily_max_loss 触发
- **THEN** 执行器调用 close_all + stop_strategy + log_event
- **AND** 不再继续下单

### Requirement: 基于 QS-Model 模板新建实例读取可变参数

系统 SHALL 在新建策略实例 Modal 中，当模板含 `qs_model_config.params` 时，从中读取参数定义并渲染输入控件（按 type 分类型），用户输入的值作为 `params` 传给后端覆盖模板默认值。

#### Scenario: QS-Model 模板新建实例显示参数
- **WHEN** 用户选择一个含 `qs_model_config.params`（含 fast_ma/slow_ma 两个参数）的 QS-Model 模板
- **THEN** 新建实例 Modal 的参数配置区显示「快均线周期」「慢均线周期」两个输入框（按 type 渲染）
- **AND** 默认值为模板中 params 的 value

#### Scenario: 用户覆盖参数创建实例
- **WHEN** 用户在新建实例 Modal 中把 fast_ma 从 5 改为 10
- **AND** 点击创建
- **THEN** 创建实例请求的 params 含 `fast_ma=10`
- **AND** 执行器用 fast_ma=10 覆盖模板默认值

### Requirement: 操作日志时间基准标注

系统 SHALL 在后端序列化时间字段时显式标注 UTC（`+ "Z"` 后缀），前端显示时统一转换为本地时间并标注「本地时间(UTC+8)」；OKX API 日志的时间基准在 UI 上明确标注。

#### Scenario: 日志时间正确显示
- **WHEN** 后端存储一条 UTC 时间 `2026-07-10T04:00:00Z` 的操作日志
- **AND** 前端在 Asia/Shanghai 时区显示
- **THEN** 显示为「2026-07-10 12:00:00 (本地时间 UTC+8)」
- **AND** 不出现 8 小时偏差

#### Scenario: API 日志标注时间基准
- **WHEN** 用户查看 API 调用日志
- **THEN** 页面顶部或时间列标注「OKX API 返回时间为 UTC，已转换为本地时间」
- **AND** 时间显示含完整日期 + 时分秒

## MODIFIED Requirements

### Requirement: QS-Model 基础策略选择

[原] 基础策略必填，从 7 种已注册策略中选择
[新] 基础策略可选，增加「无（纯规则驱动）」选项；选「无」时 `base_strategy` 为 null，规则列表至少一条

### Requirement: QS-Model 风控段

[原] risk_filter 含 max_position_ratio/daily_max_loss/min_trade_size，始终发送
[新] risk_filter 顶部增加启用开关；启用后含 max_position_ratio/daily_max_loss/min_trade_size/stop_loss/take_profit；关闭时为 null；执行器实际执行风控检查

### Requirement: QS-Model 参数类型渲染

[原] int/integer/float/double 全部归一化为 number，输入框 step='any' 允许小数
[新] 保留 int 与 float/number 区分；int 输入 step=1 拒绝小数；float/number 允许小数

## 范围说明

本 spec 覆盖：
- 9 个问题的前后端修复
- Dropdown 组件 Portal 化与宽度独立化
- 基础策略可空带来的 schema/validator/executor 调整
- 风控开关 + 止损止盈 + 执行器风控逻辑落地
- 新建实例参数渲染从 qs_model_config.params 读取
- 日志时间时区统一标注

本 spec 不覆盖：
- 重新设计 QS-Model 四段式结构（已在前序 spec 完成）
- 新增基础策略（已 7 种足够）
- 文本 DSL 语法（二期）
