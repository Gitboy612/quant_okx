# Checklist

## P0 网络韧性 — WebSocket

- [x] `okx_ws_client.py` `websockets.connect()` 传入 `proxy=` 参数（读取 HTTPS_PROXY/ALL_PROXY）
- [x] `_connect_and_login()` 异常处理器不再 `create_task(_reconnect())`
- [x] 重连只由 `_reconnect()` while 循环统一管理
- [x] 最大重连次数 20 次，达到后进入 `CIRCUIT_OPEN` 熔断状态
- [x] 熔断状态下后台定时器每 60 秒探测重连
- [x] 探测成功后恢复 `CIRCUIT_CLOSED` 并重置计数
- [x] `is_healthy` 属性暴露：CIRCUIT_CLOSED 且 ws 连接存活时返回 true
- [x] 不再出现 8192 个并发重连协程

## P0 网络韧性 — OKXClient

- [x] `OKXClient.__init__` 不执行同步 `_sync_time()` 和 `time.sleep()`
- [x] 时间同步改为懒加载：首次请求时按需异步执行
- [x] `OKXClient(account)` 构造不阻塞事件循环

## P0 网络韧性 — 策略引擎容错

- [x] `start_strategy` 中 `await strategy.start()` 包裹 try/except
- [x] 启动异常后实例标记 `error` 状态
- [x] FastAPI 进程不崩溃，其他策略和 API 不受影响

## P0 网络韧性 — ComposableStrategy 退避

- [x] 主循环增加 `_consecutive_errors` 计数
- [x] 网络错误时指数退避（1s→2s→4s→8s→16s，上限 30s）
- [x] 成功时计数归零、退避重置
- [x] 连续 10 次错误自动停止并标记 `error`

## P0 网络韧性 — 网格策略错误关键词

- [x] 网络错误关键词列表含 `"winerror 64"`
- [x] 网络错误关键词列表含 `"winerror 10054"`
- [x] 网络错误关键词列表含 `"winerror 10060"` / `"winerror 10061"`

## P0 网络韧性 — 前端超时

- [x] `client.ts` `axios.create()` 含 `timeout: 15000`
- [x] 响应拦截器处理 timeout 错误并展示提示
- [x] 后端无响应 15 秒后前端不卡死，用户可操作其他界面

## P1 QS-Model 保存不强制交易对

- [x] `hasLogicContent` 仅当 `rules.length > 0` 时为 true
- [x] 基础策略存在 + 空交易对可保存
- [x] 空交易对时基础策略 `symbol` 自动设为 `$meta.base_symbol`
- [x] 实例创建时用户填入交易对，`$meta.base_symbol` 解析为实际值

## P1 数字输入中间态保留

- [x] `NumberInput` 组件维护 draft string 状态
- [x] onChange 只更新 draft，不归一化
- [x] onBlur 时 Number(draft) 归一化并回传
- [x] 非法输入失焦回退到上一有效值
- [x] `BlockArgsForm` 数字参数使用 NumberInput
- [x] `SimpleConditionEditor` 阈值使用 NumberInput
- [x] `ParamsEditor` 默认值使用 NumberInput
- [x] `StrategiesPage.tsx` 实例参数编辑区使用 NumberInput
- [x] 输入 "0" → "0." → "0.0" → "0.01" 小数点不被吞

## P2 规则阈值支持引用变量

- [x] `referenceOptions` 下钻到 `ConditionTreeEditor`
- [x] `referenceOptions` 下钻到 `SimpleConditionEditor`
- [x] `referenceOptions` 下钻到 `IndicatorRefEditor`
- [x] `referenceOptions` 下钻到 `ActionListEditor`
- [x] `SimpleConditionEditor` 阈值旁有"引用"按钮
- [x] 引用选中后阈值显示为 `$params.xxx`
- [x] 动作参数支持 RefPicker 引用

## P2 引用自动同步参数标签

- [x] `RefPicker.onPick` 签名含 context 参数
- [x] 基础策略参数引用 → 标签同步为被引用参数原始 label（如"价格上限"）
- [x] 规则条件阈值引用 → 标签同步为"规则N指标label触发阈值"
- [x] 规则动作参数引用 → 标签同步为"规则N动作label参数label"
- [x] PARAMS 区参数含 `label_source` 标记（auto/custom）
- [x] 引用变更只覆盖 `label_source = 'auto'` 的标签
- [x] 用户手动修改 label 后转为 `label_source = 'custom'`
- [x] `label_source = 'custom'` 的标签不被自动覆盖

## 验证

- [x] 后端所有模块 import 无报错
- [x] 前端 tsc 编译无报错
- [x] 网络异常时前端不卡死，可切换其他界面
- [x] 网络恢复后策略自动恢复（熔断器探测成功）
- [x] 策略启动失败不崩溃进程
