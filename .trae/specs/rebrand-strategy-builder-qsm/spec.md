# QS-Model 策略构建 优化改造 Spec

## Why

当前系统的"DSL 拼接模板"功能虽然后端引擎已完整实现（181 个测试通过），但前端编辑器对投资人员极不友好：交易对要手敲字符串、`gt`/`lt`/`position_pnl` 等代码字段名直接暴露、时间窗口无单位约束易解析出错、买卖方向等固定选项也要手敲、基础策略仅有 `grid` 一种、网格策略参数过多限制用户、模板无复用机制。这套能力本应是产品亮点，却因体验问题难以推广。

本 spec 将其重塑为 **QS-Model 策略构建**：引入四段式复合结构（META/PARAMS/LOGIC/RISK_FILTER）、隐藏代码细节用业务语言呈现、扩充基础策略库、建立模板哈希复用机制，让投资人员真正"所见即所得"地构建策略。

## What Changes

### 命名与品牌
- **修改**：前端 [StrategiesPage.tsx](file:///e:/quant_okx/frontend/src/pages/StrategiesPage.tsx) 按钮文案 `DSL 拼接模板` → `QS-Model 策略构建`
- **修改**：[DslEditor.tsx](file:///e:/quant_okx/frontend/src/components/DslEditor.tsx) Modal 标题、组件名、相关文案统一改为 QS-Model 语境

### QS-Model 四段式复合结构 **BREAKING**
- **新增**：QS-Model v2.0 复合结构，包含四段：`meta`（策略基本信息）/ `params`（可变参数定义）/ `logic`（策略逻辑，即原 dsl_config）/ `risk_filter`（可选风控）
- **修改**：后端 `StrategyDSL` Pydantic 模型扩展为 `QSModelConfig`，包裹原 `StrategyDSL` 为 `logic` 字段
- **修改**：`StrategyTemplate.dsl_config` 字段语义升级为存储完整 QS-Model 配置（兼容旧 dsl_config，读取时自动适配）

### 积木元数据中文化 **BREAKING**
- **修改**：后端所有积木（indicators/conditions/actions/events/bases）的 `param_schema` 增加 `label`（中文显示名）和 `options`+`option_labels`（枚举选项及中文标签）
- **修改**：`BlockMeta` 增加 `label` 字段（如 `position_pnl` → label="持仓盈亏"），`kind` 仅作内部标识不再直接展示
- **修改**：前端 [types/dsl.ts](file:///e:/quant_okx/frontend/src/types/dsl.ts) `BlockMeta` / `BlockParamSchema` 增加 `label` / `option_labels` / `unit` 字段

### 编辑器交互优化
- **修改**：交易对（symbol）字段改为下拉搜索（复用 StrategiesPage 已有的交易对预设+搜索逻辑），不再手敲
- **修改**：规则列表中的交易对字段自动继承基础策略的 symbol，不再重复编辑
- **修改**：买卖方向（side）/订单类型（type）/模式（mode）等固定选项改为下拉/单选，中文标签展示
- **修改**：时间窗口（window）改为下拉选择（1m/5m/15m/1h/4h/1d）或单位选择器，杜绝格式错误
- **修改**：条件编辑器可视化——`gt`/`lt` 等显示为"大于"/"小于"中文运算符，嵌套 and/or/not 支持分组可视化

### 基础策略库扩充
- **新增**：将传统 `trend` 策略改造并注册为 DSL 基础策略
- **新增**：基于 [deepseek_strategy_skill.md](file:///e:/quant_okx/backend/deepseek_strategy_skill.md) 蒸馏实现 `rsi_strategy` / `bollinger_bands` / `donchian` / `dca` / `martingale` 五个基础策略
- **修改**：`grid` 基础策略精简必填参数，非核心参数改为可选并设合理默认值

### 模板哈希与复用机制
- **新增**：`StrategyTemplate` 增加 `logic_hash` 字段，存储 `logic` 段的内容哈希（SHA-256）
- **新增**：创建模板时自动计算 `logic_hash`，相同 logic 的模板去重提示
- **新增**：`StrategyInstance` 增加 `logic_hash` 字段，记录创建时所基于的逻辑版本
- **新增**：实例执行时通过 `template_id` 引用模板的 QS-Model 配置 + 实例参数覆盖，实现"一模板多实例"

## Impact

### 受影响代码
- **后端**：
  - [backend/dsl/schema.py](file:///e:/quant_okx/backend/dsl/schema.py)（新增 QSModelConfig 模型）
  - [backend/dsl/blocks/](file:///e:/quant_okx/backend/dsl/blocks/)（全部积木补 label/options 元数据）
  - [backend/dsl/blocks/bases.py](file:///e:/quant_okx/backend/dsl/blocks/bases.py)（扩充基础策略）
  - [backend/dsl/registry.py](file:///e:/quant_okx/backend/dsl/registry.py)（list() 输出增加 label 字段）
  - [backend/dsl/executor.py](file:///e:/quant_okx/backend/dsl/executor.py)（读取 QS-Model 结构）
  - [backend/models/strategy.py](file:///e:/quant_okx/backend/models/strategy.py)（增加 logic_hash 字段）
  - [backend/routers/strategies.py](file:///e:/quant_okx/backend/routers/strategies.py)（模板创建计算 hash）
- **前端**：
  - [frontend/src/components/DslEditor.tsx](file:///e:/quant_okx/frontend/src/components/DslEditor.tsx)（全面重构交互）
  - [frontend/src/types/dsl.ts](file:///e:/quant_okx/frontend/src/types/dsl.ts)（类型扩展）
  - [frontend/src/pages/StrategiesPage.tsx](file:///e:/quant_okx/frontend/src/pages/StrategiesPage.tsx)（按钮改名）

### 受影响 specs
- `add-composable-strategy-dsl`（DSL 引擎已实现，本 spec 在其上扩展结构）
- `add-dsl-template-frontend`（前端编辑器已实现，本 spec 重构其交互）

## QS-Model 复合结构设计

### 顶层结构

```json
{
  "qs_model_version": "2.0",
  "meta": {
    "name": "双均线趋势跟踪策略",
    "version": "v1.0.0",
    "author": "QuantTeam",
    "description": "基于15分钟K线的BTC趋势跟踪，金叉买入死叉卖出",
    "asset_class": "CRYPTO",
    "frequency": "15min",
    "base_symbol": "BTC-USDT"
  },
  "params": {
    "fast_ma": {
      "label": "快均线周期",
      "value": 5,
      "type": "int",
      "range": [1, 50],
      "description": "快速移动平均线的计算周期"
    },
    "slow_ma": {
      "label": "慢均线周期",
      "value": 20,
      "type": "int",
      "range": [10, 200],
      "description": "慢速移动平均线的计算周期"
    }
  },
  "logic": {
    "version": "1.0",
    "base_strategy": {
      "kind": "trend",
      "params": { "fast_period": "$params.fast_ma", "slow_period": "$params.slow_ma", "symbol": "$meta.base_symbol" }
    },
    "rules": []
  },
  "risk_filter": {
    "max_position_ratio": 0.25,
    "daily_max_loss": 0.05,
    "min_trade_size": 0.001
  }
}
```

### 四段说明

| 段 | 作用 | 是否必填 | 对应 deepseek_text_sample.txt |
|---|---|---|---|
| `meta` | 策略基本信息（名称/作者/描述/资产类别/频率/基准交易对） | 是 | `[STRATEGY_META]` |
| `params` | 可变参数定义（label/value/type/range/description），用户可在创建实例时调整 | 是 | `[STRATEGY_PARAMS]` |
| `logic` | 策略逻辑（原 dsl_config 的 base_strategy + rules），支持 `$params.xxx` / `$meta.xxx` 变量引用 | 是 | `[STRATEGY_LOGIC]` |
| `risk_filter` | 可选风控（最大持仓比例/每日最大亏损/最小交易量等） | 否 | `[RISK_FILTER]` |

### 变量引用机制

`logic` 段中的参数值支持引用 `params` 和 `meta`：

- `$params.fast_ma` → 取 params.fast_ma.value
- `$meta.base_symbol` → 取 meta.base_symbol
- 纯字面量（如 `0.05`）直接使用

这样设计的好处：
1. **参数与逻辑分离**：用户在 `params` 段定义可调参数，`logic` 段引用，修改参数不影响逻辑结构
2. **实例参数覆盖**：创建实例时只需覆盖 `params` 段的 value，`logic` 自动生效
3. **复用友好**：同一 `logic` 可被不同 `params` 配置复用，`logic_hash` 一致

## 模板哈希与复用机制

### 设计方案

```
┌─────────────────────────────────────────────────────────────┐
│  StrategyTemplate                                           │
│  ├── id, name, strategy_type                                │
│  ├── qs_model_config (JSON)  ← 完整 QS-Model 结构           │
│  ├── logic_hash (SHA-256)    ← logic 段内容哈希             │
│  └── default_params (JSON)   ← params 段拍平（兼容旧逻辑）  │
└─────────────────────────────────────────────────────────────┘
                           │ create_instance
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  StrategyInstance                                           │
│  ├── id, template_id (FK)                                   │
│  ├── symbol (覆盖 meta.base_symbol)                         │
│  ├── params (覆盖 template.default_params)                  │
│  └── logic_hash (快照，记录创建时基于的逻辑版本)            │
└─────────────────────────────────────────────────────────────┘
```

### 执行时解析

`ComposableStrategy.execute()` 流程：
1. 从 `self.params["template_id"]` 或 `self.params["qs_model_config"]` 加载 QS-Model 配置
2. 用实例 `params` 覆盖模板 `params` 段的 value
3. 解析 `logic` 段中的 `$params.xxx` / `$meta.xxx` 变量引用，得到最终 DSL 配置
4. 用 `DSLCompiler` 编译为 FSM 并执行

### 哈希用途

- **去重提示**：创建模板时若 `logic_hash` 已存在，提示"已有相同逻辑的模板 XXX，是否仍要创建"
- **复用统计**：可查询"有多少实例基于此逻辑运行"
- **不变性**：实例的 `logic_hash` 是创建时快照，模板后续修改不影响已运行实例

## 积木元数据中文化规范

### BlockMeta 扩展

```python
# 后端 BlockMeta 输出
{
  "kind": "position_pnl",           # 内部标识，不再直接展示
  "label": "持仓盈亏",              # 新增：中文显示名
  "category": "账户·持仓",
  "description": "获取指定交易对持仓的未实现盈亏",
  "param_schema": {...},
  "output_type": "float",
  "priority": "P0"
}
```

### BlockParamSchema 扩展

```python
# 枚举型参数
{
  "side": {
    "type": "select",
    "label": "买卖方向",            # 新增：中文字段名
    "required": True,
    "options": ["buy", "sell"],
    "option_labels": ["买入", "卖出"],  # 新增：选项中文标签
    "default": "buy",
    "description": "订单买卖方向"
  }
}

# 时间窗口参数
{
  "window": {
    "type": "select",
    "label": "时间窗口",
    "required": True,
    "options": ["1m", "5m", "15m", "1h", "4h", "1d"],
    "option_labels": ["1分钟", "5分钟", "15分钟", "1小时", "4小时", "1天"],
    "default": "1h",
    "description": "K线/计算的时间窗口"
  }
}

# 数值型参数
{
  "threshold": {
    "type": "number",
    "label": "阈值",
    "required": True,
    "unit": "%",                    # 新增：单位（展示用）
    "min": 0,
    "max": 1,
    "step": 0.01,
    "description": "触发阈值"
  }
}
```

### 条件可视化模板

条件积木增加 `display_template` 字段，前端据此渲染人类可读文案：

| kind | display_template | 渲染示例 |
|---|---|---|
| `gt` | `"{indicator} 大于 {threshold}"` | "RSI 大于 70" |
| `lt` | `"{indicator} 小于 {threshold}"` | "持仓盈亏 小于 -100" |
| `abs_gt` | `"{indicator} 绝对值 大于 {threshold}"` | "涨跌幅 绝对值 大于 5%" |
| `abs_lt` | `"{indicator} 绝对值 小于 {threshold}"` | "涨跌幅 绝对值 小于 5%" |
| `and` | `"同时满足：{conditions}"` | "同时满足：RSI>70, MA下穿" |
| `or` | `"任一满足：{conditions}"` | "任一满足：RSI>70, MA下穿" |

## 基础策略库扩充

基于 [deepseek_strategy_skill.md](file:///e:/quant_okx/backend/deepseek_strategy_skill.md) 蒸馏，新增以下 DSL 基础策略：

| kind | 中文名 | 来源 | 核心参数 | 说明 |
|---|---|---|---|---|
| `grid` | 网格策略 | 已有（精简） | upper_price, lower_price, grid_count, order_qty | 精简非核心参数为可选 |
| `trend` | 双均线趋势 | deepseek 2.1 | fast_period, slow_period, direction | 金叉做多死叉做空 |
| `rsi_strategy` | RSI 超买超卖 | deepseek 2.4 | period, oversold, overbought, direction | 超卖买入超买卖出 |
| `bollinger_bands` | 布林带 | deepseek 2.3 | period, std_multiplier, direction | 触下轨买入触上轨卖出 |
| `donchian` | 唐奇安通道 | deepseek 2.5 | entry_period, exit_period, direction | 海龟交易突破 |
| `dca` | 定投策略 | deepseek 3.4 | amount, frequency, day_of_week | 固定时间固定金额 |
| `martingale` | 马丁格尔 | deepseek 3.2 | initial_size, multiplier, max_levels, direction | 亏损加倍加仓 |

### grid 策略参数精简

当前 grid 5 个必填参数，改为：

| 参数 | 必填 | 默认值 | 说明 |
|---|---|---|---|
| `upper_price` | 是 | - | 网格上限 |
| `lower_price` | 是 | - | 网格下限 |
| `grid_count` | 是 | 10 | 网格数量 |
| `order_qty` | 否 | 0.001 | 单格数量（可后续调整） |
| `symbol` | 是 | - | 交易对 |
| `grid_mode` | 否 | arithmetic | 等差/等比 |
| `direction` | 否 | neutral | 方向（新增 select） |

## ADDED Requirements

### Requirement: QS-Model 四段式复合结构

系统 SHALL 提供 QS-Model v2.0 复合结构，包含 `meta` / `params` / `logic` / `risk_filter` 四段，作为策略模板的标准载体。

#### Scenario: 创建 QS-Model 策略模板
- **WHEN** 投资人员在 QS-Model 编辑器中填写策略名称、作者、描述，定义可变参数，拼接规则逻辑，可选配置风控
- **AND** 点击保存
- **THEN** 系统生成 QS-Model 配置并存入 `StrategyTemplate.qs_model_config`
- **AND** 自动计算 `logic` 段的 SHA-256 哈希存入 `logic_hash`
- **AND** 模板列表出现新模板

#### Scenario: 变量引用解析
- **WHEN** 策略逻辑中引用 `$params.fast_ma`
- **THEN** 执行时自动解析为 `params.fast_ma.value` 的实际值
- **AND** 若实例覆盖了该参数，使用覆盖值

### Requirement: 积木元数据中文化

系统 SHALL 为所有积木提供中文 `label`，前端展示时使用 `label` 而非 `kind`；枚举型参数 SHALL 声明 `options` + `option_labels`，前端渲染为下拉选择。

#### Scenario: 用户选择指标不看到代码字段名
- **WHEN** 用户在编辑器中选择持仓盈亏指标
- **THEN** 下拉项显示"持仓盈亏"而非"position_pnl"
- **AND** 参数表单显示"交易对"而非"symbol"

#### Scenario: 枚举参数下拉选择
- **WHEN** 用户编辑 place_order 动作的买卖方向
- **THEN** 渲染为下拉选项"买入"/"卖出"
- **AND** 不允许手敲文本

### Requirement: 交易对下拉搜索

系统 SHALL 在 QS-Model 编辑器中，交易对字段使用下拉搜索（复用 StrategiesPage 已有的交易对预设列表），不允许手敲。

#### Scenario: 选择交易对
- **WHEN** 用户点击交易对字段
- **THEN** 展开下拉，含常用交易对（BTC-USDT/ETH-USDT 等）+ 搜索功能
- **AND** 选中后填入标准格式交易对

### Requirement: 规则交易对自动继承

系统 SHALL 在规则编辑中自动继承基础策略的 `symbol`，规则级指标/动作的 `symbol` 参数自动填充，不再要求用户重复输入。

#### Scenario: 规则自动继承交易对
- **WHEN** 基础策略设置了 symbol=BTC-USDT
- **THEN** 规则中的 `price_change_pct` 等指标的 symbol 参数自动为 BTC-USDT
- **AND** 编辑器中不展示 symbol 字段（或显示为只读继承提示）

### Requirement: 时间窗口下拉选择

系统 SHALL 将时间窗口类参数（window/interval 等）改为下拉选择，预设标准选项（1m/5m/15m/1h/4h/1d），杜绝用户手敲格式错误。

#### Scenario: 选择时间窗口
- **WHEN** 用户编辑 price_change_pct 指标的 window 参数
- **THEN** 渲染为下拉：1分钟/5分钟/15分钟/1小时/4小时/1天
- **AND** 选中后填入对应标准格式值

### Requirement: 条件可视化展示

系统 SHALL 将条件积木以人类可读方式展示，使用 `display_template` 渲染中文文案，运算符显示为"大于"/"小于"等。

#### Scenario: 查看规则触发条件
- **WHEN** 用户查看一条含 `gt(rsi(period=14), 70)` 的规则
- **THEN** 展示为"RSI 大于 70"（其中 RSI 来自指标 label，70 来自阈值）
- **AND** 不展示 `gt` / `rsi` 等代码标识

### Requirement: 基础策略库扩充

系统 SHALL 提供至少 7 种基础策略（grid/trend/rsi_strategy/bollinger_bands/donchian/dca/martingale），每种均有中文 label、参数 label、合理的默认值。

#### Scenario: 选择基础策略
- **WHEN** 用户在 QS-Model 编辑器中选择基础策略
- **THEN** 下拉含"网格策略"/"双均线趋势"/"RSI 超买超卖"/"布林带"/"唐奇安通道"/"定投策略"/"马丁格尔"
- **AND** 选中后动态渲染该策略的参数表单（含中文 label）

### Requirement: 模板哈希复用

系统 SHALL 为每个模板计算 `logic` 段的 SHA-256 哈希，存入 `logic_hash` 字段；创建模板时若已有相同 `logic_hash` 的模板，提示用户。

#### Scenario: 创建重复逻辑模板
- **WHEN** 用户保存一个 logic 段与已有模板"网格+单边暂停"完全相同的新模板
- **THEN** 系统提示"检测到已有相同逻辑的模板『网格+单边暂停』，是否仍要创建？"
- **AND** 用户确认后允许创建

#### Scenario: 一模板多实例复用
- **WHEN** 用户基于模板 A 创建实例 X（symbol=BTC-USDT）和实例 Y（symbol=ETH-USDT）
- **THEN** 两个实例共享 template_id 引用同一 QS-Model 配置
- **AND** 各自的 symbol 覆盖独立生效
- **AND** 两个实例的 logic_hash 一致

## MODIFIED Requirements

### Requirement: 策略模板存储结构

[原] `StrategyTemplate.dsl_config` 存储 `{base_strategy, rules}` 格式的 DSL 配置
[新] `StrategyTemplate.qs_model_config` 存储 QS-Model v2.0 完整结构（meta/params/logic/risk_filter），`logic_hash` 存储 logic 段哈希。读取时兼容旧 `dsl_config`（自动包装为 QS-Model：meta 取默认值，params 为空，logic=旧 dsl_config，risk_filter 为空）。

### Requirement: DSL 编辑器交互

[原] 积木选择展示 kind，参数表单为纯文本输入，交易对手敲，枚举字段手敲
[新] 积木选择展示 label，参数表单按类型渲染（select 下拉/number 数字/unit 单位），交易对下拉搜索，枚举字段下拉选择，条件可视化展示中文文案

## REMOVED Requirements

### Requirement: 规则级交易对手动输入
**Reason**: 基础策略已设置交易对，规则级重复输入易不一致
**Migration**: 规则级 symbol 参数自动继承基础策略，已有 DSL 配置中规则级 symbol 保留但不再编辑（兼容）

## 范围说明

本 spec 覆盖：
- QS-Model 四段式复合结构设计与实现
- 积木元数据中文化（label/options/option_labels/unit/display_template）
- 编辑器交互全面优化（交易对下拉/枚举选择/条件可视化/时间窗口下拉）
- 基础策略库扩充至 7 种
- 模板哈希复用机制

本 spec 不覆盖：
- 文本 DSL 语法（Lark，二期）
- P2 积木库扩展
- 策略模板的编辑/版本管理（仅新建+哈希去重，不支持模板后续编辑）
- Dry-Run 模拟器增强（已有功能，交互优化即可）
