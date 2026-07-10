# 网络韧性修复与 QS-Model 交互优化 Spec

## Why

实际运行中暴露出 5 个问题，其中网络阻塞为致命缺陷：
1. **P0 网络阻塞**：策略启动后 WebSocket 连接被 GFW 频繁重置，`okx_ws_client.py` 存在双重重连 Bug 导致协程指数增长（2^N），8192 个并发重连协程撑爆事件循环，FastAPI 请求处理器被饿死，前端所有界面卡死。用户质疑是否需要换 Java，实际上这是实现缺陷而非 Python 限制。
2. **P1 QS-Model 保存强制交易对**：创建时允许 base_symbol 为空，但保存校验 `hasLogicContent` 因 `base_strategy.kind` 默认 `'grid'` 而恒为 true，强制要求选择交易对，与"模板不绑定交易对、实例创建时再选"的设计矛盾。
3. **P1 数字输入中间态被吞**：`onChange` 中立即 `Number(raw)` 归一化，`Number("0.")` = 0 → `String(0)` = "0"，小数点每次输入都被吞掉，用户必须先输 0.2 再把光标移到 2 前面改 0.02。
4. **P2 规则阈值无法引用变量**：`referenceOptions` 仅传递给基础策略的 `BlockArgsForm`，未下钻到 `SimpleConditionEditor` / `IndicatorRefEditor` / `ActionListEditor`，导致规则条件阈值只能是字面量。
5. **P2 引用不自动同步参数标签**：`RefPicker.onPick` 只设值不设标签，用户引用 `$params.xxx` 后仍需手动去 PARAMS 区改标签；期望引用时自动生成上下文化标签（如"规则1最新价触发阈值"）。

## What Changes

### 问题 1（P0）：网络阻塞根治

#### 1.1 WebSocket 代理支持
- **修改**：[okx_ws_client.py](file:///e:/New%20folder%20(2)/quant_okx/backend/services/okx_ws_client.py) `websockets.connect()` 调用增加 `proxy=` 参数，读取环境变量 `HTTPS_PROXY` / `ALL_PROXY`，与 HTTP 客户端代理配置对齐

#### 1.2 修复双重重连 Bug
- **修改**：[okx_ws_client.py](file:///e:/New%20folder%20(2)/quant_okx/backend/services/okx_ws_client.py) `_connect_and_login()` 异常处理器中移除 `asyncio.create_task(self._reconnect())`，重连只由 `_reconnect()` 的 while 循环统一管理，避免协程指数增长

#### 1.3 重连熔断与自恢复
- **修改**：[okx_ws_client.py](file:///e:/New%20folder%20(2)/quant_okx/backend/services/okx_ws_client.py) 增加最大重连次数（默认 20 次）和熔断状态：达到上限后进入 `CIRCUIT_OPEN` 状态，停止重连；启动后台定时器每 60 秒尝试一次探测重连，成功则恢复 `CIRCUIT_CLOSED`
- **修改**：[okx_ws_client.py](file:///e:/New%20folder%20(2)/quant_okx/backend/services/okx_ws_client.py) 暴露 `is_healthy` 属性供策略引擎查询

#### 1.4 前端 axios 超时
- **修改**：[client.ts](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/api/client.ts) `axios.create()` 增加 `timeout: 15000`（15 秒），避免请求无限等待

#### 1.5 OKXClient 同步初始化异步化
- **修改**：[okx_client.py](file:///e:/New%20folder%20(2)/quant_okx/backend/services/okx_client.py) `__init__` 中移除同步 `_sync_time()` 阻塞调用，改为懒加载：首次请求时若时间偏差超阈值才异步同步

#### 1.6 策略引擎容错与自恢复
- **修改**：[strategy_engine.py](file:///e:/New%20folder%20(2)/quant_okx/backend/services/strategy_engine.py) `start_strategy` 包裹 `try/except`，捕获启动异常后标记实例 `error` 状态而非崩溃
- **修改**：[executor.py](file:///e:/New%20folder%20(2)/quant_okx/backend/dsl/executor.py) `ComposableStrategy` 主循环增加网络错误退避（连续错误计数 + 指数退避 sleep）和连续 10 次自动停止
- **修改**：[grid_strategy.py](file:///e:/New%20folder%20(2)/quant_okx/backend/strategies/grid_strategy.py) 网络错误关键词列表补充 `"winerror 64"` / `"winerror 10054"` / `"winerror 10060"` / `"winerror 10061"`

### 问题 2（P1）：QS-Model 保存不再强制交易对
- **修改**：[DslEditor.tsx](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/components/DslEditor.tsx) 保存校验逻辑修改：`hasLogicContent` 仅当 `rules.length > 0` 时为 true（基础策略存在不视为需要交易对，因为实例创建时才选）；移除 `hasLogicContent && !baseSymbol` 的强制拦截
- **修改**：[DslEditor.tsx](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/components/DslEditor.tsx) 模板保存时若 `base_symbol` 为空，基础策略的 `symbol` 参数自动设为 `$meta.base_symbol`（引用占位），实例创建时由用户填入

### 问题 3（P1）：数字输入中间态保留
- **修改**：[DslEditor.tsx](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/components/DslEditor.tsx) `BlockArgsForm` 数字输入改为"草稿字符串"模式：`onChange` 只更新本地 draft string 状态，`onBlur` 时才 `Number(raw)` 归一化并 `onChange` 回传父组件
- **修改**：[DslEditor.tsx](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/components/DslEditor.tsx) `SimpleConditionEditor` 阈值输入同样改为草稿字符串模式
- **修改**：[DslEditor.tsx](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/components/DslEditor.tsx) `ParamsEditor` 默认值输入同样改为草稿字符串模式
- **修改**：[StrategiesPage.tsx](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/pages/StrategiesPage.tsx) 实例参数编辑区数字输入同样改为草稿字符串模式

### 问题 4（P2）：规则阈值支持引用变量
- **修改**：[DslEditor.tsx](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/components/DslEditor.tsx) `referenceOptions` 从顶层下钻传递到 `SimpleConditionEditor` / `IndicatorRefEditor` / `ActionListEditor` / `ConditionTreeEditor`
- **修改**：[DslEditor.tsx](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/components/DslEditor.tsx) `SimpleConditionEditor` 阈值输入旁增加"引用"按钮，点击展开 `RefPicker` 下拉选择 `$params.xxx` 或 `$meta.xxx`
- **修改**：[DslEditor.tsx](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/components/DslEditor.tsx) `IndicatorRefEditor` / `ActionListEditor` 中所有数值/字符串参数均支持 `RefPicker` 引用

### 问题 5（P2）：引用自动同步参数标签
- **修改**：[DslEditor.tsx](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/components/DslEditor.tsx) `RefPicker` 的 `onPick` 增加上下文参数：`onPick(value, context)`，context 含 `{ ruleIndex, ruleName, fieldType, paramKey }`
- **修改**：[DslEditor.tsx](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/components/DslEditor.tsx) 当引用 `$params.xxx` 被选中时，自动生成标签并回写 PARAMS 区对应参数的 `label` 字段：
  - 基础策略参数引用 → 使用被引用参数的原始 label（如网格 `price_upper` → "价格上限"）
  - 规则条件阈值引用 → 生成 `规则{N}{指标label}触发阈值`（如"规则1最新价触发阈值"）
  - 规则动作参数引用 → 生成 `规则{N}{动作label}{参数label}`
- **修改**：[DslEditor.tsx](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/components/DslEditor.tsx) PARAMS 区参数 label 字段增加"自动"标记，用户手动修改后转为"自定义"标记，引用变更时只覆盖"自动"标记的标签

## Impact

### 受影响代码
- **后端（P0 网络韧性）**：
  - [okx_ws_client.py](file:///e:/New%20folder%20(2)/quant_okx/backend/services/okx_ws_client.py)（代理支持 + 双重重连修复 + 熔断器）
  - [okx_client.py](file:///e:/New%20folder%20(2)/quant_okx/backend/services/okx_client.py)（同步初始化异步化）
  - [strategy_engine.py](file:///e:/New%20folder%20(2)/quant_okx/backend/services/strategy_engine.py)（启动容错）
  - [executor.py](file:///e:/New%20folder%20(2)/quant_okx/backend/dsl/executor.py)（主循环退避 + 自动停止）
  - [grid_strategy.py](file:///e:/New%20folder%20(2)/quant_okx/backend/strategies/grid_strategy.py)（错误关键词补充）
- **前端**：
  - [client.ts](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/api/client.ts)（axios 超时）
  - [DslEditor.tsx](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/components/DslEditor.tsx)（问题 2/3/4/5 核心）
  - [StrategiesPage.tsx](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/pages/StrategiesPage.tsx)（问题 3 数字输入草稿）

### 受影响 specs
- `fix-async-blocking`（P0 是其后续：httpx 异步化已解决同步阻塞，但 WebSocket 重连风暴未解决）
- `fix-runtime-bugs-and-template-mgmt`（问题 2 是其问题 3 的延伸：币对锁定逻辑进一步完善）
- `fix-qsm-builder-issues`（问题 2 反转其"未选交易对保存被拦截"需求：模板不绑定交易对）
- `rebrand-strategy-builder-qsm`（问题 4/5 完善 LOGIC 区引用能力）

## ADDED Requirements

### Requirement: WebSocket 代理支持

系统 SHALL 在 WebSocket 连接时传入代理参数，与 HTTP 客户端代理配置对齐，避免 GFW 重置连接。

#### Scenario: 配置代理后 WebSocket 稳定连接
- **WHEN** 环境变量 `HTTPS_PROXY` 或 `ALL_PROXY` 已设置
- **AND** WebSocket 客户端发起连接
- **THEN** `websockets.connect()` 传入 `proxy=` 参数
- **AND** 连接通过代理建立，不被 GFW 频繁重置

#### Scenario: 未配置代理时直连
- **WHEN** 环境变量未设置代理
- **THEN** WebSocket 直连，不传 `proxy` 参数

### Requirement: WebSocket 重连熔断与自恢复

系统 SHALL 限制 WebSocket 最大重连次数，达到上限后进入熔断状态停止重连；启动后台探测定时器，网络恢复后自动重连。

#### Scenario: 双重重连 Bug 修复
- **WHEN** `_connect_and_login()` 抛出异常
- **THEN** 异常处理器不再 `create_task(_reconnect())`
- **AND** 重连只由 `_reconnect()` 的 while 循环统一管理
- **AND** 不出现协程指数增长

#### Scenario: 达到最大重连次数熔断
- **WHEN** 连续重连失败达到 20 次
- **THEN** 进入 `CIRCUIT_OPEN` 熔断状态
- **AND** 停止主动重连
- **AND** `is_healthy` 返回 false

#### Scenario: 熔断后探测自恢复
- **WHEN** 处于 `CIRCUIT_OPEN` 状态
- **THEN** 后台定时器每 60 秒尝试一次探测重连
- **AND** 探测成功后恢复 `CIRCUIT_CLOSED` 并重置重连计数
- **AND** `is_healthy` 返回 true

#### Scenario: 策略引擎查询健康状态
- **WHEN** 策略主循环每 tick 执行
- **THEN** 可查询 `ws_client.is_healthy`
- **AND** 不健康时跳过非关键操作（如 ticker 订阅），等待自恢复

### Requirement: 前端请求超时

系统 SHALL 为所有 axios 请求设置 15 秒超时，避免网络异常时前端无限等待卡死。

#### Scenario: 后端无响应时前端不卡死
- **WHEN** 后端 API 请求 15 秒未返回
- **THEN** axios 触发 timeout 错误
- **AND** 前端展示"请求超时"提示
- **AND** 用户可继续操作其他界面

### Requirement: OKXClient 初始化不阻塞事件循环

系统 SHALL 将 `OKXClient.__init__` 中的同步 `_sync_time()` 改为懒加载，不在构造时阻塞。

#### Scenario: 构造 OKXClient 不阻塞
- **WHEN** `OKXClient(account)` 被构造
- **THEN** 不执行同步 `time.sleep()`
- **AND** 时间同步延迟到首次请求时按需异步执行

### Requirement: 策略引擎启动容错

系统 SHALL 在 `start_strategy` 中捕获启动异常，标记实例 `error` 状态而非让进程崩溃。

#### Scenario: 策略启动失败不崩溃进程
- **WHEN** `await strategy.start()` 抛出异常
- **THEN** 异常被捕获
- **AND** 实例状态标记为 `error`
- **AND** 错误信息记录到日志
- **AND** FastAPI 进程继续运行，其他策略和 API 不受影响

### Requirement: ComposableStrategy 主循环网络退避

系统 SHALL 在 `ComposableStrategy` 主循环中追踪连续网络错误，指数退避并达到阈值自动停止。

#### Scenario: 连续网络错误指数退避
- **WHEN** 主循环 `on_tick` 抛出网络错误
- **THEN** 连续错误计数 +1
- **AND** sleep 时间指数增长（1s → 2s → 4s → 8s → 16s，上限 30s）
- **AND** 不在每个 tick 立即重试

#### Scenario: 连续 10 次错误自动停止
- **WHEN** 连续网络错误计数达到 10
- **THEN** 策略自动停止
- **AND** 实例状态标记为 `error`
- **AND** 记录"连续网络错误超限，自动停止"

#### Scenario: 错误恢复重置计数
- **WHEN** 一次 `on_tick` 成功执行
- **THEN** 连续错误计数归零
- **AND** 退避 sleep 时间重置为默认

### Requirement: 网格策略网络错误关键词完整

系统 SHALL 在网格策略的网络错误关键词列表中包含所有常见 WinError 编号。

#### Scenario: WinError 64 被识别为网络错误
- **WHEN** OKX API 返回 `[WinError 64] The specified network name is no longer available`
- **THEN** 被识别为网络错误
- **AND** 触发退避重试而非直接崩溃

#### Scenario: WinError 10054 被识别为网络错误
- **WHEN** OKX API 返回 `[WinError 10054] An existing connection was forcibly closed by the remote host`
- **THEN** 被识别为网络错误
- **AND** 触发退避重试

### Requirement: QS-Model 模板保存不强制交易对

系统 SHALL 允许 QS-Model 模板在 `base_symbol` 为空时保存，交易对延迟到实例创建时选择。

#### Scenario: 空交易对模板可保存
- **WHEN** 用户未选择基准交易对即点击保存
- **AND** LOGIC 区含基础策略（如 grid）但无规则
- **THEN** 保存成功
- **AND** 模板 `meta.base_symbol` 为空字符串
- **AND** 基础策略 `symbol` 参数自动设为 `$meta.base_symbol`

#### Scenario: 实例创建时填入交易对
- **WHEN** 用户基于 `base_symbol` 为空的模板创建实例
- **THEN** 创建实例弹窗要求用户输入交易对
- **AND** 用户输入后 `$meta.base_symbol` 解析为实际值

### Requirement: 数字输入保留中间态

系统 SHALL 在数字输入框中保留用户输入的中间态字符串（如 "0." / "0.0"），仅在失焦或保存时归一化为数字。

#### Scenario: 输入 0.01 不被吞
- **WHEN** 用户在 order_qty 输入框依次输入 "0" "." "0" "1"
- **THEN** 每次按键后输入框显示 "0" / "0." / "0.0" / "0.01"
- **AND** 小数点不被吞掉

#### Scenario: 失焦时归一化
- **WHEN** 用户输入 "0.01" 后点击其他地方（失焦）
- **THEN** 值归一化为数字 0.01
- **AND** 回传父组件

#### Scenario: 非法输入失焦回退
- **WHEN** 用户输入 "abc" 后失焦
- **THEN** 回退到上一个有效值
- **AND** 不崩溃

### Requirement: 规则条件阈值支持引用变量

系统 SHALL 在规则条件编辑器中为阈值参数提供引用选择器，支持引用 `$params.xxx` 或 `$meta.xxx`。

#### Scenario: 规则条件阈值引用参数
- **WHEN** 用户在规则1的条件"最新价 大于 [阈值]"中点击阈值旁的"引用"按钮
- **AND** 从下拉中选择 `$params.trigger_price`
- **THEN** 阈值字段显示为 `$params.trigger_price`
- **AND** 保存后执行器用参数值替换

#### Scenario: 动作参数支持引用
- **WHEN** 用户在规则动作 `place_order` 的 `qty` 参数中点击"引用"
- **AND** 选择 `$params.order_size`
- **THEN** qty 字段显示为 `$params.order_size`

### Requirement: 引用自动同步参数标签

系统 SHALL 在引用 `$params.xxx` 被选中时，自动为该参数生成上下文化标签并回写 PARAMS 区。

#### Scenario: 基础策略参数引用同步标签
- **WHEN** 用户在网格基础策略的 `price_upper` 参数引用 `$params.upper_limit`
- **THEN** PARAMS 区 `upper_limit` 参数的 label 自动设为"价格上限"
- **AND** label 旁显示"自动"标记

#### Scenario: 规则条件阈值引用同步标签
- **WHEN** 用户在规则1的条件"最新价 大于 [阈值]"中引用 `$params.trigger_price`
- **THEN** PARAMS 区 `trigger_price` 参数的 label 自动设为"规则1最新价触发阈值"
- **AND** label 旁显示"自动"标记

#### Scenario: 用户自定义标签不被覆盖
- **WHEN** 用户手动将某参数 label 改为"我的阈值"（标记转为"自定义"）
- **AND** 后续引用变更
- **THEN** "自定义"标签不被自动覆盖
- **AND** 仅"自动"标记的标签会被引用变更覆盖

## MODIFIED Requirements

### Requirement: QS-Model 基准交易对校验（来自 fix-qsm-builder-issues）

[原] 未选交易对保存被拦截：用户未选择基准交易对即点击保存且 LOGIC 区含基础策略或规则时，校验失败提示"请先选择基准交易对"

[新] 模板保存不强制交易对：`base_symbol` 为空时模板可保存，基础策略 symbol 自动设为 `$meta.base_symbol` 占位；仅当有规则但规则级 symbol 未设引用且无基础策略时才提示

### Requirement: 数字参数输入（来自 fix-runtime-bugs-and-template-mgmt）

[原] float/number 类型 step 为 'any'，int 类型 step 为 1

[新] 在 step 修复基础上，进一步采用草稿字符串模式：onChange 保留中间态字符串，onBlur 归一化，解决 "0." 被吞问题

## 范围说明

本 spec 覆盖：
- P0：WebSocket 代理 + 双重重连修复 + 熔断器 + 前端超时 + OKXClient 异步初始化 + 策略容错退避
- P1：QS-Model 保存不强制交易对 + 数字输入中间态保留
- P2：规则阈值引用变量 + 引用自动同步参数标签

本 spec 不覆盖：
- 将后端从 Python 迁移到 Java（Python asyncio 完全可处理，当前问题是实现缺陷）
- WebSocket 消息层重构（仅修复连接韧性，不改消息协议）
- 新增基础策略或积木（仅完善现有编辑器引用能力）
- PARAMS 区参数依赖关系（二期）
