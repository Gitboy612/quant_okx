# 盈亏数据一致性与订单追踪修复 Spec

## Why

经代码分析发现三类关联问题：盈亏曲线中实现盈亏与未实现盈亏价格基准不一致导致曲线跳变、PnL 快照写入逻辑存在健壮性缺陷、仪表盘「最近交易」因查询排序问题导致已成交订单不显示。

---

### 问题 A：实现盈亏与未实现盈亏价格基准不一致

**理论关系**：`total_pnl = realized_pnl + unrealized_pnl`，网格闭环时浮动盈亏转换为实现盈亏，`total_pnl` 仅下降手续费。

**实际不一致（4 处）**：

1. **买入价基准不一致（核心）**
   - `unrealized_pnl` 用 `avg_buy_price`（全部买单加权均价）— [grid_strategy.py:349](file:///e:/New%20folder%20(2)/quant_okx/backend/strategies/grid_strategy.py#L349)
   - `realized_pnl` 用 `self._grid_levels[grid_idx - 1]`（理论网格档位价）— [grid_strategy.py:76](file:///e:/New%20folder%20(2)/quant_okx/backend/strategies/grid_strategy.py#L76)
   - 多档持仓时均价 ≠ 单笔档位价 → 成交时 total_pnl 跳变

2. **手续费口径不对称**：realized 扣双边手续费，unrealized 不扣（毛浮动）

3. **全局净持仓 vs 单笔闭环**：OrderManager 维护单一全局 `_net_position`/`_avg_buy_price`，realized 按单笔网格闭环计算

4. **TrendStrategy 口径完全不同**：[trend_strategy.py:72](file:///e:/New%20folder%20(2)/quant_okx/backend/strategies/trend_strategy.py#L72) unrealized 恒为 0，全靠 OKX 账户权益差值

---

### 问题 B：PnL 60s 快照写入逻辑缺陷

经审查 [base_strategy.py:263-296](file:///e:/New%20folder%20(2)/quant_okx/backend/strategies/base_strategy.py#L263-L296) 的 `_should_record_pnl` + `record_pnl` 逻辑：

1. **`record_pnl` 无异常保护**：DB 写入失败时异常向上传播，中断整个策略 tick；`_mark_pnl_recorded` 不执行 → 下一个 tick（3s 后）重试，若 DB 持续锁定则反复失败
2. **`_last_pnl_total == 0` 时跳过变化阈值**：[base_strategy.py:269](file:///e:/New%20folder%20(2)/quant_okx/backend/strategies/base_strategy.py#L269) `self._last_pnl_total != 0` 为 False → 首笔 PnL 从 0 变为非 0 时只在 60s 定时触发，错过早期波动
3. **同步 DB 写阻塞事件循环**：`record_pnl` 在 async 循环中同步 `db.commit()`，SQLite 锁定时阻塞整个事件循环
4. **双重 DB 写入**：`record_pnl` 写 pnl_records 表后立即调 `_record_event("pnl_recorded")` 写 strategy_events 表，每条 PnL 记录产生两次 DB 写入

逻辑上可以正常写入（60s 定时 + 1% 变化阈值双触发），但存在健壮性缺陷，在 DB 锁定或异常时可能中断策略。

---

### 问题 C：仪表盘「最近交易」不显示已成交订单

经审查 [DashboardPage.tsx:46-48](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/pages/DashboardPage.tsx#L46-L48) 和 [routers/orders.py:38](file:///e:/New%20folder%20(2)/quant_okx/backend/routers/orders.py#L38)：

1. **查询排序与筛选不匹配**：后端按 `created_at desc` 排序取 50 条（不限状态），前端再 `filter(status === 'filled')`
   - 网格策略初始下 12+ 笔订单（均为 live），每次闭环又新增买卖单
   - 50 条最新订单大多是 `live` 状态 → `filter(filled)` 后结果很少或为空
   - **已成交的旧订单被挤出 limit 50 之外，无法显示**

2. **`updated_at` 字段未更新**：[order_manager.py:227-265](file:///e:/New%20folder%20(2)/quant_okx/backend/services/order_manager.py#L227-L265) `_persist_to_db` 更新订单时未设置 `updated_at`，仅创建时设默认值 → 无法按「最近成交时间」排序

3. **前端未分状态查询**：应分别请求 `status=filled` 和 `status=live` 的订单列表，而非一次取 50 条再客户端过滤

## What Changes

### A. 盈亏一致性
- **统一买入价基准**：`realized_pnl` 改用对应买单的实际成交价（fillPx），缺失时回退网格档位价并告警
- **OrderManager 提供 `get_order_fill_px(ordId)`**：返回买单实际成交价
- **unrealized_pnl 扣预估手续费**：`unrealized = (price - avg_buy) * pos - est_close_fee`
- **TrendStrategy 口径对齐**：持仓记 unrealized，平仓转 realized
- **曲线 tooltip 展示三栏**：total / realized / unrealized

### B. PnL 快照写入健壮性
- **`record_pnl` 增加异常保护**：try/except 包裹 DB 写入，失败时仅记录日志不中断 tick
- **修复 `_last_pnl_total == 0` 逻辑**：改用绝对变化量判断（`abs(delta) > epsilon`）而非仅依赖比率
- **`record_pnl` 改为异步**：使用 `asyncio.to_thread` 避免 DB 写阻塞事件循环
- **移除 PnL 记录的 `_record_event`**：减少冗余 DB 写入，PnL 数据本身已在 pnl_records 表

### C. 订单追踪显示
- **后端新增 `sort_by` 参数**：支持按 `created_at` 或 `updated_at` 排序
- **`_persist_to_db` 更新 `updated_at`**：订单状态变更时写入当前时间
- **前端分状态查询**：Dashboard 分别请求 `status=filled`（最近交易）和 `status=live`（未成交委托），各自 limit
- **后端 `/api/orders` 支持 `sort_by=updated_at`**：最近交易按成交时间排序

- **BREAKING**: 无

## Impact
- Affected specs: `fix-pnl-algorithm-and-monitoring`（盈亏算法）、`revamp-pnl-curve-and-splash`（曲线展示）
- Affected code:
  - 策略核心: `backend/strategies/grid_strategy.py`、`backend/strategies/trend_strategy.py`、`backend/strategies/base_strategy.py`
  - 订单管理: `backend/services/order_manager.py`
  - API: `backend/routers/orders.py`
  - 前端: `frontend/src/components/PnLChart.tsx`、`frontend/src/pages/DashboardPage.tsx`

## ADDED Requirements

### Requirement: 实现盈亏使用实际成交价
系统 SHALL 在计算网格闭环 realized_pnl 时使用对应买单的实际成交价（fillPx），而非理论网格档位价。

#### Scenario: 网格闭环用实际成交价
- **WHEN** 卖单成交完成网格闭环
- **THEN** `cycle_pnl = (sell_fill_px - buy_fill_px) * qty - buy_fee - sell_fee`
- **AND** `buy_fill_px` 取自对应买单的 OrderInfo.fillPx
- **AND** 若买单 fillPx 缺失，回退使用 grid_levels 档位价并记录 `order_warn`

#### Scenario: 成交时 total_pnl 连续
- **WHEN** 单笔网格闭环成交
- **THEN** realized_pnl 增量 = (sell_px - buy_fill_px) * qty - fees
- **AND** unrealized_pnl 减量 ≈ (sell_px - avg_buy_price) * qty
- **AND** total_pnl 变化 ≈ -fees（连续，不跳变）

### Requirement: OrderManager 维护买单成交价映射
系统 SHALL 在 OrderManager 中提供查询订单实际成交价的方法。

#### Scenario: 查询买单成交价
- **WHEN** 卖单成交需计算 realized_pnl
- **THEN** 调用 `order_manager.get_order_fill_px(buy_ord_id)` 获取买单实际成交价
- **AND** 返回 fillPx 浮点值，缺失时返回 0.0

### Requirement: 未实现盈亏扣除预估手续费
系统 SHALL 在计算 unrealized_pnl 时扣除预估平仓手续费。

#### Scenario: 未实现盈亏扣费
- **WHEN** 策略主循环计算 unrealized_pnl
- **THEN** `unrealized_pnl = (current_price - avg_buy_price) * net_position - estimated_close_fee`
- **AND** `estimated_close_fee = abs(net_position) * current_price * fee_rate`
- **AND** fee_rate 从配置读取（默认 0.001）

### Requirement: TrendStrategy 盈亏口径对齐
系统 SHALL 使 TrendStrategy 的 realized/unrealized 口径与 GridStrategy 一致。

#### Scenario: 趋势策略持仓记未实现盈亏
- **WHEN** TrendStrategy 买单成交后持仓
- **THEN** unrealized_pnl = (current_price - buy_fill_px) * position
- **AND** realized_pnl 仅在反向平仓时累加

### Requirement: PnL 快照写入健壮性
系统 SHALL 确保 PnL 记录写入失败时不中断策略运行。

#### Scenario: DB 写入失败不中断
- **WHEN** `record_pnl` 的 DB 写入抛出异常
- **THEN** 异常被捕获并记录日志
- **AND** 策略主循环继续运行（不中断 tick）
- **AND** 下一个 tick 正常重试

#### Scenario: 首笔 PnL 变化不被跳过
- **WHEN** `_last_pnl_total == 0` 且 total_pnl 变为非 0
- **THEN** 使用绝对变化量判断（`abs(total_pnl) > epsilon`）
- **AND** 变化超过阈值时立即写入（不等 60s）

#### Scenario: 异步写入不阻塞事件循环
- **WHEN** `record_pnl` 执行 DB 写入
- **THEN** 使用 `asyncio.to_thread` 在线程池执行
- **AND** 不阻塞事件循环

### Requirement: 订单 updated_at 维护
系统 SHALL 在订单状态变更时更新 `updated_at` 字段。

#### Scenario: 订单状态变更更新时间戳
- **WHEN** OrderManager `_persist_to_db` 更新已存在订单
- **THEN** 设置 `existing.updated_at = datetime.now(timezone.utc)`
- **AND** 供按「最近更新时间」排序查询

### Requirement: 仪表盘最近交易分状态查询
系统 SHALL 在仪表盘分别查询已成交和活跃订单，而非一次查询后客户端过滤。

#### Scenario: 最近交易查询
- **WHEN** Dashboard 加载「最近交易」区域
- **THEN** 调用 `listOrders({ status: 'filled', limit: 10, sort_by: 'updated_at' })`
- **AND** 返回最近成交的 10 笔订单

#### Scenario: 未成交委托查询
- **WHEN** Dashboard 加载「未成交委托」区域
- **THEN** 调用 `listOrders({ status: 'live', limit: 50 })`
- **AND** 返回当前活跃挂单

### Requirement: 盈亏曲线展示 realized/unrealized 分解
系统 SHALL 在盈亏曲线 tooltip 中展示 total/realized/unrealized 三栏数据。

#### Scenario: 曲线 tooltip 三栏
- **WHEN** 用户悬停盈亏曲线数据点
- **THEN** tooltip 显示：总盈亏、实现盈亏、未实现盈亏
- **AND** 实现 + 未实现 = 总盈亏

## MODIFIED Requirements

### Requirement: 盈亏曲线固定时间窗口填充
[原 spec: revamp-pnl-curve-and-splash] 补充：曲线 tooltip 增加实现盈亏与未实现盈亏分栏展示。

## REMOVED Requirements
无。
