# SS Project：策略执行、PnL、订单与归因专项开发计划

## 1. 文档目标

本计划把当前提出的策略状态展示、单策略盈亏、新建策略基线、账户总盈亏、策略恢复、交易所订单号、实时行情范围和归因分析问题整理为统一的开发与验收口径。

本次仅补充文档，不修改交易、订单或 PnL 业务代码。

## 2. 已有相似文档与复用关系

项目中已经存在以下相似规格，本计划作为统一入口，不重复替代这些规格中的详细场景：

- `.trae/specs/fix-pnl-realized-unrealized-consistency/spec.md`：已实现/未实现盈亏、手续费和成交价口径。
- `.trae/specs/fix-pnl-attribution-qsm-loop/spec.md`：PnL 全零记录、归因三维度口径和策略切换。
- `.trae/specs/refactor-pnl-accounting-engine/spec.md`：集中式 PnL 核算与增量更新。
- `.trae/specs/strategy-fundamentals-overhaul/spec.md`：策略隔离、生命周期和仓位归属。
- `.trae/specs/add-data-maintenance/spec.md`：盈亏校正、停止状态清理和维护审计。
- `docs/backend-improvement-review.md`：后端整体风险与改进优先级。

## 3. 当前实现判断

### 3.1 策略执行与手动状态展示

当前策略状态同时存在于数据库字段、`StrategyEngine` 内存任务和策略对象状态中。暂停、恢复、停止接口会更新数据库，但手动直接修改数据库中的 `strategy_instances.status` 只改变持久化值，并不会创建或停止运行任务，也不会自动撤单或恢复行情订阅。

主要风险：

- 页面显示 `running`，实际没有对应执行任务。
- 页面显示 `stopped`，旧任务或挂单仍然存在。
- 服务重启后数据库状态、OKX 订单状态和本地虚拟仓位发生漂移。

改进要求：

- 将 `desired_status`（期望状态）与 `runtime_status`（真实状态）分离。
- 查询接口同时返回任务是否存活、最后心跳、活跃订单数和状态来源。
- 禁止把直接数据库改状态当作启动/停止操作；人工干预必须通过服务接口并写操作日志。
- 检测状态漂移并显示 `recovering`、`degraded` 或 `error`，不能静默显示为正常运行。

### 3.2 单个策略的已实现、未实现和总盈亏

统一定义：

```text
strategy_total_pnl = strategy_realized_pnl + strategy_unrealized_pnl
```

- `realized_pnl`：只由该策略已成交且完成配对的成交产生，使用实际 `fill_px`、实际 `fill_sz`、合约面值和真实手续费。
- `unrealized_pnl`：只针对该策略仍持有的虚拟净仓位，使用当前价、剩余持仓成本和统一的预估平仓手续费。
- `total_pnl`：每个快照现场计算，不允许独立累计第三套总盈亏值。

待优化点：

- FIFO 全量重算与增量更新必须使用同一成交排序和费用规则。
- `partially_filled` 必须按增量成交量记账，不能等到最终 `filled` 后一次性重复处理。
- 行情缺失时不能把当前价或 unrealized 静默当作 0，应返回陈旧/不可用状态。
- 所有成交按稳定去重键处理，确保 WebSocket、REST 对账和重启恢复不会重复计入。

### 3.3 新建策略的盈亏基线

新建策略应拥有独立的策略实例 ID 和零基线：

- 无成交时，接口展示 realized、unrealized、total 均为 0。
- 无成交时不写入持久化的全零 `PnlRecord`，避免污染曲线和“最近有效记录”选择。
- 只查询 `strategy_instance_id` 属于当前实例的订单，不继承同账户、同币种或同模板的历史订单。
- 首笔买入成交后只产生持仓成本和未实现盈亏；首笔卖出只有在与已有仓位配对后才产生已实现盈亏。
- 删除后重建、复制策略或复用名称时，也不得复用旧实例的 PnL 基线。

### 3.4 新建策略与账户总盈亏

当前 `backend/routers/pnl.py:get_pnl_summary` 在没有传入 `strategy_instance_id` 时，从全部 PnL 记录中取全局最近一条有效记录作为账户总值。该逻辑在多策略场景不等于所有策略之和。

目标定义：

```text
account_realized_pnl   = sum(latest.realized_pnl   for latest in latest_by_strategy)
account_unrealized_pnl = sum(latest.unrealized_pnl for latest in latest_by_strategy)
account_total_pnl      = account_realized_pnl + account_unrealized_pnl
```

其中 `latest_by_strategy` 必须在同一账户过滤后，每个策略实例各取一条最新有效快照。新建但无成交的策略贡献 0，不得覆盖其他策略的已有累计值。

### 3.5 策略中断后的恢复

建议恢复顺序：

1. 读取策略配置、期望状态和最后一次运行版本。
2. 查询 OKX 活跃订单、订单历史和成交明细。
3. 以 OKX `ordId` 为主键对账本地订单，补录孤儿订单并去重成交。
4. 从成交记录恢复虚拟仓位、持仓成本、累计 realized 和手续费。
5. 使用新鲜行情重算 unrealized 与 total。
6. 恢复 WebSocket 订阅、策略内部状态机和执行任务。
7. 写入一次恢复结果事件，记录差异、修复动作和失败原因。

恢复流程必须幂等：重复执行不会重复下单、重复记账或重复扩大仓位。网络不可用时保持 `recovering/degraded`，不能直接标记为 `running`。

### 3.6 `orders` 表中的订单 ID

字段语义固定如下：

| 字段 | 含义 | 约束与用途 |
| --- | --- | --- |
| `id` | SQLite 内部自增主键 | 仅用于数据库关联，不发送给 OKX |
| `order_id` | OKX 返回的 `ordId` | 唯一；成交、撤单、查询、恢复和 PnL 去重的主标识 |
| `cl_ord_id` | 客户端生成的 `clOrdId` | 建议下单前生成并唯一，用于超时重试和订单意图幂等 |

下单成功后必须原样保存 OKX 返回的 `ordId`。如果网络超时但交易所可能已经受理，应先用 `clOrdId` 查询确认，不能直接再次下单。

### 3.7 是否实时查询所有币种价格

答案：不是逐个币种持续实时查询，也不是把所有币种都用于策略计算。

- 展示层 `BlockchainBackground` 每 20 秒请求一次配置的币种集合。
- 后端 `/api/market/spot-tickers` 通过 OKX `market/tickers?instType=SPOT` 获取一次全部现货快照，缓存 15 秒，再只返回前端请求的币种。
- 策略执行层由 `MarketDataService` 按实际策略品种引用计数订阅 WebSocket ticker；PnL 必要时按策略品种获取当前价。

建议增加：

- 响应携带交易所时间戳、服务接收时间和数据来源（WebSocket/REST/cache）。
- 定义行情陈旧阈值，超过阈值停止新开仓并显示告警。
- PnL 计算使用与策略交易品种一致的 `instId`，不能用现货 BTC-USDT 价格替代合约价格。

### 3.8 归因分析

当前归因服务已经尝试统一使用 `PnlRecord`，但仍需用共享查询组件强制统一：

- 数据范围：同一账户、同一起止时间、同一策略实例集合。
- 已实现盈亏：明确使用期末累计值还是区间增量，三个维度只能选一种口径。
- 未实现盈亏：只取期末快照，不能跨时间相加。
- 总盈亏：始终为 realized + unrealized。
- 平均成本：先在策略内计算，再按净仓位绝对值聚合，不能跨策略直接混合买卖订单。
- 交易次数、胜率和手续费必须使用实际成交而非委托订单。

交叉验收：同一筛选条件下，按币种、按策略类型和按时间段的汇总总额必须一致，允许的误差只来自统一规定的小数舍入。

## 4. 开发优先级

### P0：在实盘验证前完成

1. 修正账户总盈亏为 `sum(latest_by_strategy)`。
2. 固化新策略零基线和实例隔离。
3. 固化 `orders.order_id = OKX ordId`，增加成交去重与 `clOrdId` 幂等流程。
4. 统一单策略 realized/unrealized/total 计算入口和不变量断言。
5. 增加恢复状态机与 OKX 对账，禁止数据库状态直接代表真实运行状态。

### P1：完成 P0 后推进

1. 归因三个维度共享快照选择器和区间口径。
2. 行情响应增加来源、时间戳和陈旧状态。
3. 对部分成交、合约面值、手续费币种和多空反转补齐测试。
4. 页面增加状态漂移与恢复进度展示。

## 5. 自动化验收场景

- 单策略只有买入持仓：realized 为 0，unrealized 随价格变化，total 恒等于两者之和。
- 单策略完成一次闭环：unrealized 转为 realized，total 只因价格与手续费按统一口径变化。
- 新建策略无成交：不新增 PnL 数据库记录，API 展示 0，账户旧总盈亏保持不变。
- 两个策略并行：账户总盈亏等于两个策略各自最新快照之和。
- 同币种多策略：订单、持仓、PnL 按策略实例隔离，归因汇总可加回账户总值。
- WebSocket 与 REST 重复返回同一成交：只记账一次。
- 服务在下单确认前中断：通过 `clOrdId` 和 `ordId` 对账，不重复下单。
- 服务在成交后、落库前中断：恢复后补录一次成交并重算 PnL。
- 行情超过陈旧阈值：停止新开仓，保留上次值并明确标记 stale，不静默写 0。
- 归因交叉核对：按币种、策略类型、时间段的 realized/unrealized/total 汇总一致。

## 6. 当前验证状态

最近一次本地完整测试结果为 843 项通过、4 项跳过、12 项失败、4 项收集错误。失败集中在 PnL 增量/性能、研究功能检查和运行迭代逻辑；收集错误来自依赖 `runner` fixture 的 OKX 接口脚本。专项验收完成前，不应把“服务可启动”解释为“PnL 与恢复业务逻辑已完全通过”。
