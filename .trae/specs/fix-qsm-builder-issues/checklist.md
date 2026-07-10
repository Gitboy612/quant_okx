# Checklist

## 问题 1：QS-Model 构建不默认交易币对

- [x] DslEditor `initialMeta()` 中 `base_symbol` 初始为空字符串 `''`
- [x] `baseSymbol` 回退链末尾返回 `''` 而非 `'BTC-USDT'`
- [x] 保存校验：LOGIC 区有基础策略或规则且 `meta.base_symbol` 为空时提示「请先选择基准交易对」
- [x] 后端 `StrategyMeta.base_symbol` 默认空字符串，与前端一致

## 问题 2：下拉面板 Portal 渲染与宽度独立

- [x] Dropdown 下拉面板通过 `createPortal` 渲染到 `document.body`
- [x] Dropdown 支持 `minPanelWidth` / `panelWidth` 可选属性
- [x] Portal 面板正确定位（getBoundingClientRect 计算触发器位置）
- [x] PARAMS 区「类型」下拉（col-span-2 窄列）面板宽度足够展示中文选项
- [x] 规则列表最后一条规则的条件/事件下拉不被裁剪
- [x] 现有 Dropdown 调用不破坏（默认行为保持）

## 问题 3：枚举类型自定义选项

- [x] PARAMS 区参数类型选「枚举(select)」时展开「枚举选项编辑器」
- [x] 枚举选项编辑器支持增删「值 + 中文标签」对
- [x] 枚举参数默认值从已定义选项中下拉选择
- [x] 组装 `qs_model_config.params` 时 select 类型输出 `options` / `option_labels`
- [x] 后端 `ParamDefinition` 已支持 options/option_labels（无需改动，验证即可）

## 问题 4：整数参数输入校验

- [x] `normalizeParamDef` 不再把 `integer`/`int` 归一化为 `number`
- [x] `BlockArgsForm` int 类型输入 `step=1`，float/number 类型 `step='any'` 或 `param.step`
- [x] int 类型输入 onChange 校验拒绝小数
- [x] `ParamsEditor` 自定义 int 参数默认值输入 `step=1`
- [x] 后端 grid 的 `grid_count` schema 类型改为 `"integer"`
- [x] grid_count 输入 3.5 被拒绝或截断为 3

## 问题 5：运行频率移交策略 bar 参数

- [x] `TrendBlock` / `RsiBlock` / `BollingerBlock` / `DonchianBlock` 的 param_schema 增加 `bar` 参数（select，默认 `1H`，label="K线周期"）
- [x] 上述 4 个策略构造函数读取 `bar` 存到 `self.bar`
- [x] 上述 4 个策略 `on_tick` 中 `bar="1H"` 改为 `bar=self.bar`
- [x] META 区「运行频率」字段下方有说明文案「此字段为元信息，实际 K 线周期请在基础策略参数中配置」
- [x] `meta.frequency` 字段保留存储（向后兼容）
- [x] `$meta.frequency` 变量引用仍可解析

## 问题 6：基础策略可以为「无」

- [x] DslEditor 基础策略 BlockPicker 增加「无（纯规则驱动）」选项
- [x] 选中「无」后清空 `base_strategy`，隐藏基础策略参数表单
- [x] 基础策略为「无」时规则级 symbol 参数显示 SymbolPicker（不再继承）
- [x] 后端 `BaseStrategyRef.kind` 改为 `str | None = None`
- [x] 后端 `StrategyDSL.base_strategy` 改为 `BaseStrategyRef | None = None`
- [x] validator 中 kind 为 None 时跳过注册表校验，但要求 rules 至少一条
- [x] executor 中 base_strategy 为 None 时跳过基础策略生命周期调用
- [x] 纯规则策略（无基础策略 + 至少一条规则）可保存与执行

## 问题 7：风控开关 + 止损止盈

- [x] RISK_FILTER 区顶部有「启用风控」开关
- [x] 开关关闭时 `risk_filter` 为 null，字段折叠
- [x] 开关启用时展开字段含 max_position_ratio / daily_max_loss / min_trade_size / stop_loss / take_profit
- [x] 初始状态默认风控关闭
- [x] 前端 `RiskFilter` 类型增加 `stop_loss?` / `take_profit?` / `blacklist_hours?`
- [x] 后端 `RiskFilter` 增加 `stop_loss` / `take_profit` 字段
- [x] executor 主循环每 tick 检查 daily_max_loss，触发时 close_all + stop_strategy + log_event
- [x] executor 每 tick 检查 stop_loss / take_profit，触发时 close_all + stop_strategy + log_event
- [x] executor 下单前校验 max_position_ratio / min_trade_size
- [x] risk_filter 为 None 时跳过所有风控检查

## 问题 8：新建实例读取 QS-Model 可变参数

- [x] StrategiesPage 新建 Modal 参数 schema 取值：`param_schema` 为空但 `qs_model_config.params` 非空时从后者构建
- [x] 参数渲染按 type 分类型：int(step=1) / float(step=any) / string / bool / select(下拉)
- [x] 创建实例请求的 params 含用户输入的参数值
- [x] DslEditor 保存模板时同步把 `qs_model_config.params` 拍平写入 `param_schema` 字段
- [x] 选择 QS-Model 模板新建实例时参数配置区显示可变参数（非空）

## 问题 9：操作日志时间基准标注

- [x] `routers/logs.py` 序列化 `created_at` 时输出带 `Z` 后缀（naive 视为 UTC）
- [x] `routers/strategies.py` 实例时间字段序列化标注 UTC
- [x] `services/log_service.py` 日志文件命名用 `datetime.now(timezone.utc)`
- [x] `services/log_service.py` 文件 mtime 读取用带 tz 的 UTC
- [x] `LogsPage.tsx` 时间显示标注「(本地时间 UTC+8)」
- [x] `ApiLogsPage.tsx` 时间显示补全日期
- [x] `ApiLogsPage.tsx` 页面顶部标注「OKX API 返回时间为 UTC，已转换为本地时间」
- [x] 前端时间显示与后端 UTC 存储无 8 小时偏差

## 兼容性

- [x] 旧 `dsl_config` 模板仍可正常加载运行
- [x] 旧 `dsl_config` 模板创建的实例仍可启动
- [x] 现有 4 种硬编码策略模板不受影响
- [x] 现有「自定义模板」（参数定义式）按钮保留可用
- [x] 已有 QS-Model 模板（含默认 BTC-USDT）加载时不报错（base_symbol 为空时兼容提示）

## 端到端验证

- [x] QS-Model 编辑器初始无默认交易对
- [x] PARAMS 区类型下拉、规则条件下拉、事件下拉完整展示不被裁剪
- [x] 枚举参数可自定义选项，默认值从选项中选择
- [x] grid_count 不允许输入小数
- [x] trend 策略 bar 参数可修改且执行时生效
- [x] 基础策略可选「无」，纯规则策略可保存与执行
- [x] 风控开关关闭时 risk_filter 为 null；启用时含 stop_loss/take_profit 且执行器触发
- [x] 基于 QS-Model 模板新建实例时参数配置区显示可变参数
- [x] 操作日志时间显示无 8 小时偏差，标注时区基准
- [x] 旧模板（dsl_config）仍可正常加载运行
