# Tasks

## 阶段一：Dropdown 组件 Portal 化（问题 2 基础设施）

- [x] Task 1: 增强 Dropdown 组件支持 Portal 渲染与宽度独立
  - [ ] SubTask 1.1: [Dropdown.tsx](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/components/Dropdown.tsx) 下拉面板改为通过 `createPortal` 渲染到 `document.body`
  - [ ] SubTask 1.2: Dropdown 增加 `minPanelWidth` / `panelWidth` 可选属性，面板宽度可独立于触发器
  - [ ] SubTask 1.3: Portal 面板定位用 `getBoundingClientRect` 计算触发器位置，支持滚动跟随（或使用浮动 UI 库/flavor）
  - [ ] SubTask 1.4: 验证现有 Dropdown 调用不破坏（默认行为保持），新增属性可选

## 阶段二：后端模型与策略调整（问题 4/5/6/7 后端部分）

- [x] Task 2: 后端 schema 模型调整（[schema.py](file:///e:/New%20folder%20(2)/quant_okx/backend/dsl/schema.py)）
  - [ ] SubTask 2.1: `BaseStrategyRef.kind` 改为 `str | None = None`，`params` 默认 `{}`
  - [ ] SubTask 2.2: `StrategyDSL.base_strategy` 改为 `BaseStrategyRef | None = None`
  - [ ] SubTask 2.3: `RiskFilter` 增加 `stop_loss: float | None = None` / `take_profit: float | None = None`
  - [ ] SubTask 2.4: 编写/更新测试覆盖 base_strategy 可空、risk_filter 新字段

- [x] Task 3: 基础策略 bar 参数化与 grid_count 类型修复（[bases.py](file:///e:/New%20folder%20(2)/quant_okx/backend/dsl/blocks/bases.py)）
  - [ ] SubTask 3.1: `grid` 的 `grid_count` schema 类型由 `"number"` 改为 `"integer"`
  - [ ] SubTask 3.2: `TrendBlock` / `RsiBlock` / `BollingerBlock` / `DonchianBlock` 的 `param_schema` 增加 `bar` 参数（select，options=[1m/5m/15m/1H/4H/1D]，默认 `1H`，label="K线周期"）
  - [ ] SubTask 3.3: 上述 4 个策略构造函数读取 `bar` 参数存到 `self.bar`，`on_tick` 中 `bar="1H"` 改为 `bar=self.bar`
  - [ ] SubTask 3.4: 编写测试验证 bar 参数生效

- [ ] Task 4: 校验器与执行器适配基础策略可空（[validator.py](file:///e:/New%20folder%20(2)/quant_okx/backend/dsl/validator.py) + [executor.py](file:///e:/New%20folder%20(2)/quant_okx/backend/dsl/executor.py)）
  - [ ] SubTask 4.1: validator 中 `base_strategy.kind` 为 None 时跳过注册表校验，但要求 `rules` 至少一条
  - [ ] SubTask 4.2: executor 中 `base_strategy` 为 None 时跳过基础策略实例化与 on_start/on_tick/on_pause/on_resume/on_stop 调用，仅运行 FSM 规则循环
  - [ ] SubTask 4.3: 编写测试覆盖纯规则策略的校验与执行

- [ ] Task 5: 执行器风控逻辑落地（[executor.py](file:///e:/New%20folder%20(2)/quant_okx/backend/dsl/executor.py)）
  - [ ] SubTask 5.1: 主循环每 tick 检查 `daily_max_loss`：累计已实现亏损达阈值则 close_all + stop_strategy + log_event
  - [ ] SubTask 5.2: 每 tick 检查 `stop_loss` / `take_profit`：未实现盈亏率触发阈值则 close_all + stop_strategy + log_event
  - [ ] SubTask 5.3: 下单前校验 `max_position_ratio` / `min_trade_size`，超限则拒绝下单 + log_event
  - [ ] SubTask 5.4: `risk_filter` 为 None 时跳过所有风控检查
  - [ ] SubTask 5.5: 编写测试覆盖风控触发场景

## 阶段三：前端类型与 DslEditor 调整（问题 1/2/3/4/5/6/7 前端部分）

- [ ] Task 6: 前端类型扩展（[dsl.ts](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/types/dsl.ts)）
  - [ ] SubTask 6.1: `ParamDefinition.type` 增加 `'int'` 与 `'float'` 区分（保留 `'number'` 别名）
  - [ ] SubTask 6.2: `RiskFilter` 增加 `stop_loss?: number` / `take_profit?: number` / `blacklist_hours?: string[]`
  - [ ] SubTask 6.3: `BaseStrategyRef` 的 `kind` 改为 `string | null`

- [x] Task 7: QS-Model 构建不默认交易币对（[DslEditor.tsx](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/components/DslEditor.tsx)）
  - [ ] SubTask 7.1: `initialMeta()` 中 `base_symbol` 改为 `''`
  - [ ] SubTask 7.2: `baseSymbol` 回退链移除 `'BTC-USDT'` 兜底，改为返回 `''`
  - [ ] SubTask 7.3: 保存校验增加：若 LOGIC 区有基础策略或规则且 `meta.base_symbol` 为空，提示「请先选择基准交易对」

- [x] Task 8: 下拉框溢出修复（[DslEditor.tsx](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/components/DslEditor.tsx)）
  - [ ] SubTask 8.1: `ParamsEditor` 类型下拉、`BlockPicker`、规则/条件/事件下拉统一使用增强后的 Dropdown，传入 `minPanelWidth`（如 180px）
  - [ ] SubTask 8.2: 验证 PARAMS 区类型下拉、规则条件下拉、事件下拉在 Modal 内不被裁剪

- [x] Task 9: 枚举类型自定义选项（[DslEditor.tsx](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/components/DslEditor.tsx)）
  - [ ] SubTask 9.1: `ParamsEditor` 当类型选「枚举(select)」时展开「枚举选项编辑器」（值+中文标签对的增删列表）
  - [ ] SubTask 9.2: 枚举参数的默认值输入改为从已定义选项中下拉选择
  - [ ] SubTask 9.3: 组装 `qs_model_config.params` 时 select 类型参数输出 `options` / `option_labels`

- [x] Task 10: 整数参数输入校验（[DslEditor.tsx](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/components/DslEditor.tsx)）
  - [ ] SubTask 10.1: `normalizeParamDef` 不再把 `integer`/`int` 归一化为 `number`，保留 `int` 类型
  - [ ] SubTask 10.2: `BlockArgsForm` 数字输入按类型设置 `step`：int → `step=1`，float/number → `step='any'` 或 `param.step`
  - [ ] SubTask 10.3: int 类型输入增加 `onChange` 校验，拒绝小数（或截断为整数）
  - [ ] SubTask 10.4: `ParamsEditor` 自定义 int 参数默认值输入 `step=1`

- [x] Task 11: 运行频率说明文案（[DslEditor.tsx](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/components/DslEditor.tsx)）
  - [ ] SubTask 11.1: META 区「运行频率」字段下方增加说明文案「此字段为元信息，实际 K 线周期请在基础策略参数中配置」
  - [ ] SubTask 11.2: 保持 `meta.frequency` 字段存储不变（向后兼容）

- [x] Task 12: 基础策略可以为「无」（[DslEditor.tsx](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/components/DslEditor.tsx)）
  - [ ] SubTask 12.1: `BlockPicker` 基础策略选择增加「无（纯规则驱动）」选项（特殊 kind 值如 `__none__` 或 null）
  - [ ] SubTask 12.2: 选中「无」后清空 `base_strategy`，隐藏基础策略参数表单
  - [ ] SubTask 12.3: 基础策略为「无」时，规则级 symbol 参数不再继承，显示 SymbolPicker 让用户显式选择
  - [ ] SubTask 12.4: 组装保存时「无」对应 `base_strategy: null`

- [x] Task 13: 风控开关 + 止损止盈（[DslEditor.tsx](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/components/DslEditor.tsx)）
  - [ ] SubTask 13.1: RISK_FILTER 区顶部增加「启用风控」开关
  - [ ] SubTask 13.2: 开关关闭时 `risk_filter` 为 null，字段折叠
  - [ ] SubTask 13.3: 开关启用时展开字段，增加「止损(stop_loss)」「止盈(take_profit)」字段（单位 %）
  - [ ] SubTask 13.4: 初始状态默认风控关闭（`riskFilter: null`），与「不默认」理念一致

## 阶段四：新建实例参数渲染（问题 8）

- [ ] Task 14: 新建策略 Modal 读取 QS-Model 可变参数（[StrategiesPage.tsx](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/pages/StrategiesPage.tsx)）
  - [ ] SubTask 14.1: 参数 schema 取值逻辑：`param_schema` 为空但 `qs_model_config.params` 非空时，从 `qs_model_config.params` 构建参数 schema
  - [ ] SubTask 14.2: 参数渲染按 `ParamDefinition.type` 分类型：int → 数字输入 step=1、float/number → 数字输入 step=any、string → 文本、bool → 开关、select → 下拉（options/option_labels）
  - [ ] SubTask 14.3: 创建实例请求时把用户输入的参数值作为 `params` 传给后端

- [x] Task 15: DslEditor 保存模板时同步 param_schema（[DslEditor.tsx](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/components/DslEditor.tsx)）
  - [ ] SubTask 15.1: 保存 QS-Model 模板时，把 `qs_model_config.params` 拍平写入 `param_schema` 字段（双保险，兼容现有读取逻辑）
  - [ ] SubTask 15.2: 拍平格式与 StrategiesPage 现有 param_schema 读取格式一致（`{key: {label, type, default, ...}}`）

## 阶段五：日志时间时区标注（问题 9）

- [x] Task 16: 后端时间序列化标注 UTC（[routers/logs.py](file:///e:/New%20folder%20(2)/quant_okx/backend/routers/logs.py) + [routers/strategies.py](file:///e:/New%20folder%20(2)/quant_okx/backend/routers/strategies.py)）
  - [ ] SubTask 16.1: `logs.py` 序列化 `created_at` 时若 naive 则视为 UTC，输出 isoformat + `Z`
  - [ ] SubTask 16.2: `strategies.py` 实例时间字段序列化同样标注 UTC
  - [ ] SubTask 16.3: 编写测试验证时间序列化带 Z 后缀

- [x] Task 17: log_service 时间统一 UTC（[services/log_service.py](file:///e:/New%20folder%20(2)/quant_okx/backend/services/log_service.py)）
  - [ ] SubTask 17.1: 日志文件命名 `datetime.now()` 改为 `datetime.now(timezone.utc)`
  - [ ] SubTask 17.2: 文件 mtime 读取 `datetime.fromtimestamp(...)` 改为带 tz 的 UTC

- [x] Task 18: 前端日志时间显示标注时区（[LogsPage.tsx](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/pages/LogsPage.tsx) + [ApiLogsPage.tsx](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/pages/ApiLogsPage.tsx)）
  - [ ] SubTask 18.1: `LogsPage.tsx` 时间显示确保 `new Date()` 解析带 Z 后缀字符串，显示标注「(本地时间 UTC+8)」
  - [ ] SubTask 18.2: `ApiLogsPage.tsx` 时间显示补全日期，页面顶部标注「OKX API 返回时间为 UTC，已转换为本地时间」
  - [ ] SubTask 18.3: 验证前端时间显示与后端 UTC 存储无偏差

## 阶段六：端到端验证

- [x] Task 19: 端到端验证
  - [ ] SubTask 19.1: 验证 QS-Model 编辑器初始无默认交易对
  - [ ] SubTask 19.2: 验证 PARAMS 区类型下拉、规则条件下拉、事件下拉完整展示不被裁剪
  - [ ] SubTask 19.3: 验证枚举参数可自定义选项，默认值从选项中选择
  - [ ] SubTask 19.4: 验证 grid_count 不允许输入小数
  - [ ] SubTask 19.5: 验证 trend 策略 bar 参数可修改且执行时生效
  - [ ] SubTask 19.6: 验证基础策略可选「无」，纯规则策略可保存与执行
  - [ ] SubTask 19.7: 验证风控开关关闭时 risk_filter 为 null；启用时含 stop_loss/take_profit 且执行器触发
  - [ ] SubTask 19.8: 验证基于 QS-Model 模板新建实例时参数配置区显示可变参数
  - [ ] SubTask 19.9: 验证操作日志时间显示无 8 小时偏差，标注时区基准
  - [ ] SubTask 19.10: 验证旧模板（dsl_config）仍可正常加载运行（兼容）

# Task Dependencies

- Task 1（Dropdown Portal）→ Task 8（DslEditor 下拉使用增强 Dropdown）
- Task 2（后端 schema）→ Task 4（validator/executor 适配）→ Task 5（风控执行）
- Task 2（后端 schema）→ Task 6（前端类型）→ Task 7-13（DslEditor 各修复）
- Task 3（bases bar 参数）独立可并行
- Task 14-15（新建实例参数渲染）依赖 Task 6（前端类型）
- Task 16-17（后端时间）独立可并行
- Task 18（前端时间显示）依赖 Task 16（后端时间序列化带 Z）
- Task 19（端到端）依赖全部上游

可并行：
- Task 1 / Task 2 / Task 3 / Task 16 / Task 17 互不依赖
- Task 7-13 前端各子任务部分可并行（如 7/9/10/11/12/13 互不依赖，8 依赖 1）
- Task 14 / Task 15 可并行
