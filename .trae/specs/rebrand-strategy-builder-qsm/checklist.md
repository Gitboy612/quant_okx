# Checklist

## 命名与品牌

- [x] StrategiesPage 顶部按钮文案已改为"QS-Model 策略构建"
- [x] DslEditor Modal 标题、组件注释统一为 QS-Model 语境
- [x] 无残留"DSL 拼接模板"文案

## QS-Model 四段式复合结构

- [x] 后端 `QSModelConfig` Pydantic 模型定义完整（meta/params/logic/risk_filter 四段）
- [x] `StrategyMeta` 含 name/version/author/description/asset_class/frequency/base_symbol 字段
- [x] `ParamDefinition` 含 label/value/type/range/description/options/option_labels/unit 字段
- [x] `logic` 字段复用现有 `StrategyDSL` 模型（base_strategy + rules）
- [x] 变量引用解析函数 `resolve_variables` 能正确替换 `$params.xxx` / `$meta.xxx`
- [x] 单元测试覆盖序列化/反序列化与变量引用解析

## 积木元数据中文化

- [x] 所有 P0 指标（8 个）含 `label` 字段（如 position_pnl→"持仓盈亏"）
- [x] 所有 P0 条件（7 个）含 `label` + `display_template`（如 gt→"大于"，template="{indicator} 大于 {threshold}"）
- [x] 所有 P0 动作（7 个）含 `label`（如 place_order→"下单"）
- [x] 所有 P0 事件（5 个）含 `label`（如 on_tick→"行情更新"）
- [x] `Registry.list()` 输出包含 `label` / `display_template` 字段
- [x] `GET /api/dsl/blocks` 响应含新增字段
- [x] 前端 `BlockMeta` 类型含 `label` / `display_template`
- [x] 前端 `BlockParamSchema` 类型含 `label` / `option_labels` / `unit`

## 枚举参数与时间窗口下拉

- [x] `place_order` 的 `side` 声明为 select（options=[buy,sell], labels=[买入,卖出]）
- [x] `place_order` 的 `type` 声明为 select（options=[market,limit], labels=[市价,限价]）
- [x] `rebalance_position` 的 `mode` 声明为 select
- [x] `log_event` 的 `level` 声明为 select
- [x] 所有 `window` 参数声明为 select（options=[1m,5m,15m,1h,4h,1d], labels=[1分钟,5分钟,15分钟,1小时,4小时,1天]）
- [x] 数值型参数含 `unit` 字段（如 threshold 的 unit="%", seconds 的 unit="秒"）
- [x] 后端无任何积木的 side/type/mode/window 等字段仍为纯 string 类型

## 交易对下拉搜索

- [x] 抽取 `SymbolPicker` 独立组件，复用 StrategiesPage 已有的交易对预设+搜索逻辑
- [x] BlockArgsForm 遇到参数名为 `symbol` 时渲染 SymbolPicker
- [x] 基础策略区的 symbol 字段使用 SymbolPicker
- [x] 交易对字段不允许手敲文本输入（SymbolPicker 使用 Dropdown 搜索+预设校验，自定义输入为扩展预留，已规避空格/多小数点等解析风险）

## 规则交易对自动继承

- [x] 规则编辑器中指标/动作的 symbol 参数自动取基础策略的 symbol
- [x] 编辑器中 symbol 字段隐藏或显示为"继承基础策略交易对"只读提示
- [x] 保存时规则级 symbol 自动填入基础策略 symbol
- [x] 后端执行时规则级 symbol 与基础策略 symbol 一致

## 条件可视化展示

- [x] 简单条件（gt/lt/abs_gt/abs_lt）渲染为"[指标label] [运算符中文] [阈值]"水平布局
- [x] 运算符下拉展示中文（大于/小于/绝对值大于/绝对值小于）
- [x] 规则卡片头部用 display_template 渲染人类可读摘要
- [x] 嵌套 and/or/not 条件支持分组可视化（条件列表+添加子条件）
- [x] 编辑器中无 `gt` / `lt` / `rsi` / `position_pnl` 等英文标识符直接展示

## 基础策略库扩充

- [x] `grid` 基础策略参数精简：order_qty 改可选默认 0.001，新增 grid_mode/direction 可选参数
- [x] `trend` 基础策略已注册，label="双均线趋势"，含 fast_period/slow_period/direction/symbol
- [x] `rsi_strategy` 基础策略已注册，label="RSI 超买超卖"，含 period/oversold/overbought/direction/symbol
- [x] `bollinger_bands` 基础策略已注册，label="布林带"，含 period/std_multiplier/direction/symbol
- [x] `donchian` 基础策略已注册，label="唐奇安通道"，含 entry_period/exit_period/direction/symbol
- [x] `dca` 基础策略已注册，label="定投策略"，含 amount/frequency/day_of_week/symbol
- [x] `martingale` 基础策略已注册，label="马丁格尔"，含 initial_size/multiplier/max_levels/direction/symbol
- [x] 每个基础策略参数均有 `label` 和合理默认值
- [x] 前端基础策略下拉含 7 种策略，均展示中文 label

## 模板哈希与复用

- [x] `StrategyTemplate` 模型含 `qs_model_config` (JSON) 和 `logic_hash` (String, indexed) 字段
- [x] `StrategyInstance` 模型含 `logic_hash` 字段
- [x] `create_template` 时自动计算 logic 段 SHA-256 存入 logic_hash
- [x] 创建模板时若已有相同 logic_hash，响应含 `duplicate_hint` 字段
- [x] `create_instance` 时把模板 logic_hash 写入实例
- [x] 前端保存时若收到 duplicate_hint，弹窗提示用户确认
- [x] 用户确认后附加 force=true 强制创建
- [x] 同一模板可创建多个实例（不同 symbol/params），共享 template_id 引用

## 执行器适配

- [x] `ComposableStrategy.execute()` 优先读取 `qs_model_config`，回退 `dsl_config` 兼容
- [x] 调用 `resolve_variables` 解析变量引用得到最终 StrategyDSL
- [x] 实例 params 覆盖模板 params 段 value 后再解析
- [x] 测试覆盖 QS-Model 配置端到端执行

## QS-Model 四段式编辑界面

- [x] 主编辑器分为 META/PARAMS/LOGIC/RISK_FILTER 四区
- [x] META 区含名称/作者/描述/基准交易对/频率字段
- [x] PARAMS 区支持增删参数定义，每项含 label/value/type/range
- [x] LOGIC 区参数值支持下拉引用 $params.xxx / $meta.base_symbol 或填字面量
- [x] RISK_FILTER 区可折叠，含 max_position_ratio/daily_max_loss/min_trade_size

## 向后兼容

- [x] 旧 `dsl_config` 字段保留，读取时自动包装为 QS-Model（meta 默认/params 空/logic=旧值/risk_filter 空）
- [x] 旧 dsl_config 模板创建的实例仍可正常启动运行
- [x] 现有 4 种硬编码策略模板不受影响
- [x] 现有"自定义模板"（参数定义式）按钮保留可用

## 端到端验证

- [x] 点击"QS-Model 策略构建"按钮打开编辑器
- [x] 积木下拉展示中文 label，无代码字段名暴露
- [x] 交易对为下拉搜索，规则级自动继承
- [x] 时间窗口为下拉选择，买卖方向为下拉
- [x] 条件展示为人类可读中文文案
- [x] 基础策略下拉含 7 种策略
- [x] 保存模板时计算 logic_hash，重复逻辑有提示
- [x] 基于 QS-Model 模板创建实例并启动，策略按 FSM 逻辑运行
- [x] 旧 dsl_config 模板仍可正常加载运行
