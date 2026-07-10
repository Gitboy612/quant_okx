# Tasks

## 阶段一：P0 网络韧性修复（后端）

- [x] Task 1: WebSocket 代理支持与双重重连修复（`backend/services/okx_ws_client.py`）
  - [x] SubTask 1.1: `websockets.connect()` 增加 `proxy=` 参数，读取环境变量 `HTTPS_PROXY` / `ALL_PROXY` / `HTTP_PROXY`
  - [x] SubTask 1.2: `_connect_and_login()` 异常处理器中移除 `asyncio.create_task(self._reconnect())`，重连只由 `_reconnect()` while 循环管理
  - [x] SubTask 1.3: 验证修复后不再出现协程指数增长

- [x] Task 2: WebSocket 重连熔断与自恢复（`backend/services/okx_ws_client.py`）
  - [x] SubTask 2.1: 增加 `_max_reconnect = 20` 计数与 `_circuit_state`（`CIRCUIT_CLOSED` / `CIRCUIT_OPEN`）
  - [x] SubTask 2.2: `_reconnect()` while 循环中失败计数 +1，达到 20 后进入 `CIRCUIT_OPEN` 并 break
  - [x] SubTask 2.3: `CIRCUIT_OPEN` 状态下启动后台 `asyncio.create_task(_probe_reconnect())`，每 60 秒探测一次，成功则恢复 `CIRCUIT_CLOSED` 并重置计数
  - [x] SubTask 2.4: 暴露 `is_healthy` 属性：`CIRCUIT_CLOSED` 且 ws 连接存活时返回 true
  - [x] SubTask 2.5: 编写测试验证熔断与自恢复逻辑

- [x] Task 3: OKXClient 同步初始化异步化（`backend/services/okx_client.py`）
  - [x] SubTask 3.1: `__init__` 中移除同步 `_sync_time()` 调用及 `time.sleep(1)` 循环
  - [x] SubTask 3.2: 增加 `_time_synced = False` 标志，首次请求时若未同步则异步 `_sync_time()`（用 `asyncio.to_thread` 包装）
  - [x] SubTask 3.3: 验证 `OKXClient(account)` 构造不阻塞事件循环

- [x] Task 4: 策略引擎启动容错（`backend/services/strategy_engine.py`）
  - [x] SubTask 4.1: `start_strategy` 中 `await strategy.start()` 包裹 `try/except Exception`
  - [x] SubTask 4.2: 捕获异常后标记实例 `status = 'error'`，记录错误信息到日志
  - [x] SubTask 4.3: 返回错误响应而非让进程崩溃

- [x] Task 5: ComposableStrategy 主循环网络退避（`backend/dsl/executor.py`）
  - [x] SubTask 5.1: `ComposableStrategy` 增加 `_consecutive_errors = 0` 和 `_backoff_delay = 1.0`
  - [x] SubTask 5.2: 主循环 `on_tick` try/except，捕获网络错误时 `_consecutive_errors += 1`，`_backoff_delay = min(_backoff_delay * 2, 30.0)`，`await asyncio.sleep(_backoff_delay)`
  - [x] SubTask 5.3: `on_tick` 成功时 `_consecutive_errors = 0`，`_backoff_delay = 1.0`
  - [x] SubTask 5.4: `_consecutive_errors >= 10` 时调用 `self.stop()` 并标记 `error` 状态
  - [x] SubTask 5.5: 网络错误识别：`except (httpx.HTTPError, OSError, ConnectionError)` 及错误消息含 "winerror" / "timeout" / "connection"

- [x] Task 6: 网格策略网络错误关键词补充（`backend/strategies/grid_strategy.py`）
  - [x] SubTask 6.1: 网络错误关键词列表补充 `"winerror 64"` / `"winerror 10054"`
  - [x] SubTask 6.2: 验证 WinError 64/10054 触发退避重试而非崩溃

## 阶段二：P0 前端超时

- [x] Task 7: 前端 axios 超时配置（`frontend/src/api/client.ts`）
  - [x] SubTask 7.1: `axios.create()` 增加 `timeout: 15000`
  - [x] SubTask 7.2: 响应拦截器增加 timeout 错误处理，展示"请求超时"提示

## 阶段三：P1 QS-Model 保存不强制交易对

- [x] Task 8: QS-Model 保存校验修复（`frontend/src/components/DslEditor.tsx`）
  - [x] SubTask 8.1: `hasLogicContent` 逻辑修改：仅当 `dslConfig.rules.length > 0` 时为 true（基础策略存在不视为需要交易对）
  - [x] SubTask 8.2: 移除 `hasLogicContent && !baseSymbol` 的强制拦截（或改为仅在纯规则无 symbol 引用时提示）
  - [x] SubTask 8.3: 模板保存时若 `base_symbol` 为空，基础策略的 `symbol` 参数自动设为 `$meta.base_symbol`

## 阶段四：P1 数字输入中间态保留

- [x] Task 9: 抽取 NumberInput 草稿字符串组件（`frontend/src/components/DslEditor.tsx`）
  - [x] SubTask 9.1: 新增 `NumberInput` 内部组件：维护 `draft: string` 状态，`onChange` 只更新 draft，`onBlur` 时 `Number(draft)` 归一化并回传父组件
  - [x] SubTask 9.2: 非法输入（NaN）失焦时回退到上一个有效值
  - [x] SubTask 9.3: 支持 `step` / `min` / `max` props 透传

- [x] Task 10: 替换所有数字输入为 NumberInput（`DslEditor.tsx` + `StrategiesPage.tsx`）
  - [x] SubTask 10.1: `BlockArgsForm` 数字参数输入替换为 `NumberInput`
  - [x] SubTask 10.2: `SimpleConditionEditor` 阈值输入替换为 `NumberInput`
  - [x] SubTask 10.3: `ParamsEditor` 默认值输入替换为 `NumberInput`
  - [x] SubTask 10.4: `StrategiesPage.tsx` 实例参数编辑区数字输入替换为 `NumberInput`

## 阶段五：P2 规则阈值支持引用变量

- [x] Task 11: referenceOptions 下钻传递（`frontend/src/components/DslEditor.tsx`）
  - [x] SubTask 11.1: `referenceOptions` 从顶层传递到 `ConditionTreeEditor` / `SimpleConditionEditor` / `IndicatorRefEditor` / `ActionListEditor`
  - [x] SubTask 11.2: `SimpleConditionEditor` 阈值输入旁增加"引用"按钮，点击展开 `RefPicker`
  - [x] SubTask 11.3: `IndicatorRefEditor` 参数表单支持 `RefPicker` 引用
  - [x] SubTask 11.4: `ActionListEditor` 动作参数支持 `RefPicker` 引用
  - [x] SubTask 11.5: 引用选中后阈值字段显示为 `$params.xxx` 字符串

## 阶段六：P2 引用自动同步参数标签

- [x] Task 12: RefPicker 上下文化与标签自动同步（`frontend/src/components/DslEditor.tsx`）
  - [x] SubTask 12.1: `RefPicker` 的 `onPick` 签名改为 `onPick(value, context)`，context 含 `{ ruleIndex, ruleName, fieldType, paramKey, sourceLabel }`
  - [x] SubTask 12.2: 基础策略参数引用时，context.sourceLabel 传递被引用参数的原始 label（如"价格上限"）
  - [x] SubTask 12.3: 规则条件阈值引用时，生成标签 `规则{N}{指标label}触发阈值`（如"规则1最新价触发阈值"）
  - [x] SubTask 12.4: 规则动作参数引用时，生成标签 `规则{N}{动作label}{参数label}`
  - [x] SubTask 12.5: 引用选中后调用 `setParams` 回写对应参数的 `label` 字段

- [x] Task 13: PARAMS 区标签"自动/自定义"标记（`frontend/src/components/DslEditor.tsx`）
  - [x] SubTask 13.1: `ParamDefinition` 增加 `label_source?: 'auto' | 'custom'` 字段（前端态，不入库可选）
  - [x] SubTask 13.2: 新建参数默认 `label_source = 'custom'`
  - [x] SubTask 13.3: 引用自动同步时设 `label_source = 'auto'`
  - [x] SubTask 13.4: 用户手动修改 label 时设 `label_source = 'custom'`
  - [x] SubTask 13.5: 引用变更时只覆盖 `label_source = 'auto'` 的标签

## 阶段七：验证

- [ ] Task 14: 后端验证
  - [ ] SubTask 14.1: WebSocket 代理参数传递验证
  - [ ] SubTask 14.2: 双重重连修复验证（不再出现协程指数增长）
  - [ ] SubTask 14.3: 熔断器状态机验证（20 次失败 → CIRCUIT_OPEN → 60s 探测 → CIRCUIT_CLOSED）
  - [ ] SubTask 14.4: OKXClient 构造不阻塞验证
  - [ ] SubTask 14.5: 策略启动失败不崩溃验证
  - [ ] SubTask 14.6: ComposableStrategy 退避与自动停止验证
  - [ ] SubTask 14.7: 网格策略 WinError 64/10054 识别验证
  - [ ] SubTask 14.8: 后端所有模块 import 无报错

- [ ] Task 15: 前端验证
  - [ ] SubTask 15.1: QS-Model 空交易对模板可保存验证
  - [ ] SubTask 15.2: 数字输入 0.01 不被吞验证
  - [ ] SubTask 15.3: 规则条件阈值可引用 $params.xxx 验证
  - [ ] SubTask 15.4: 引用后参数标签自动同步验证
  - [ ] SubTask 15.5: 用户自定义标签不被覆盖验证
  - [ ] SubTask 15.6: axios 超时配置验证
  - [ ] SubTask 15.7: 前端 tsc 编译无报错

# Task Dependencies

- Task 1 / Task 2（WebSocket 修复）可并行，独立于其他后端任务
- Task 3（OKXClient 异步化）独立
- Task 4 / Task 5 / Task 6（策略容错）可并行，依赖现有策略代码
- Task 7（前端超时）独立
- Task 8（QS-Model 保存）独立
- Task 9（NumberInput 组件）→ Task 10（替换所有数字输入）
- Task 11（referenceOptions 下钻）独立于 Task 12
- Task 12（标签自动同步）依赖 Task 11（引用能力就绪）
- Task 13（标签标记）依赖 Task 12
- Task 14 / Task 15（验证）依赖全部上游

可并行：
- Task 1 / Task 2 / Task 3 / Task 4 / Task 5 / Task 6 后端网络韧性修复（互不依赖）
- Task 7 / Task 8 / Task 9 前端独立任务
- Task 11 / Task 12 / Task 13 前端引用相关（有依赖链但可与其他并行）
