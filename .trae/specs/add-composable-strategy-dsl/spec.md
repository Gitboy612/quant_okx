# 可拼接策略 DSL（积木式策略语言）Spec

## Why

当前系统的策略（grid / trend / arbitrage / advanced_grid_hedge）都是硬编码 Python 类，新增策略变体必须由量化开发人员手写代码并注册到 [strategy_engine.py](file:///e:/New%20folder%20(2)/quant_okx/backend/services/strategy_engine.py) 的 `_strategy_map`。投资人员无法在不写代码的前提下完成"策略二次创作"——例如"在网格基础上叠加单边行情暂停 + 持仓再平衡"这类常见需求。

需要一套**声明式可拼接策略语法**，让投资人员通过"基础策略 + 监测条件 + 触发动作"的积木组合方式生成完整策略实例，由后端统一编译、校验、执行。

## What Changes

- **新增**：可拼接策略 DSL 语法框架（JSON 声明式 + 状态机模型），定义六类积木：`BaseStrategy` / `Indicator` / `Condition` / `Event` / `Action` / `Rule`
- **新增**：后端 DSL 解析、校验、编译、执行流水线（基于 Pydantic Schema + 注册表模式）
- **新增**：内置积木库（指标库 / 事件库 / 条件库 / 动作库），按 P0/P1/P2 三期实现，覆盖用户示例场景
- **新增**：策略正确性校验机制（静态校验 + Dry-Run 模拟执行）
- **修改**：[strategy_engine.py](file:///e:/New%20folder%20(2)/quant_okx/backend/services/strategy_engine.py) 增加 `composable` 策略类型分发，兼容现有硬编码策略
- **修改**：[StrategyTemplate](file:///e:/New%20folder%20(2)/quant_okx/backend/models/strategy.py) 模型增加 `dsl_config` JSON 字段保存积木配置
- **不破坏**：现有四种硬编码策略继续工作，无需迁移

## Impact

- 受影响代码：
  - [backend/strategies/base_strategy.py](file:///e:/New%20folder%20(2)/quant_okx/backend/strategies/base_strategy.py)（新增生命周期钩子）
  - [backend/services/strategy_engine.py](file:///e:/New%20folder%20(2)/quant_okx/backend/services/strategy_engine.py)（新增 composable 分发）
  - [backend/models/strategy.py](file:///e:/New%20folder%20(2)/quant_okx/backend/models/strategy.py)（新增字段）
  - [backend/schemas/strategy.py](file:///e:/New%20folder%20(2)/quant_okx/backend/schemas/strategy.py)（新增 DSL Pydantic 模型）
- 新增目录：`backend/dsl/`（DSL 核心）、`backend/dsl/blocks/`（积木库）、`backend/dsl/validators/`（校验器）

## 语言选型结论

**采用 Python（与现有后端一致）实现 DSL 引擎，使用 Pydantic 做声明式配置校验。**

| 候选 | 优点 | 缺点 | 结论 |
|---|---|---|---|
| **Python + Pydantic + JSON** | 与现有 FastAPI/SQLAlchemy/asyncio 无缝衔接；动态分发天然适合注册表模式；JSON 配置易于前端可视化拖拽生成；Pydantic 自动产出 Schema | 文本语法非用户友好（但前端可视化可解决） | ✅ **推荐** |
| Python + Lark 自定义文本 DSL | 可读性强，支持表达式 | 需维护文法、AST、解析器；前端拼装仍需 JSON 中间态；额外复杂度 | ⏸ 二期可选 |
| JavaScript/TS（独立子服务） | 前后端同构 | 与现有 Python 后端割裂，需新服务、新部署、跨进程调用 OKX 客户端 | ❌ 否决 |
| Lua / 嵌入式脚本 | 灵活 | 引入新运行时，安全沙箱成本高 | ❌ 否决 |

**核心理由**：DSL 的"积木拼装"本质是数据（JSON 配置）+ 解释器（Python 注册表），而非"用户写代码"。Python 已具备所有必要能力，无需引入新语言。前端用可视化编辑器产出 JSON，后端用 Pydantic + 注册表解释执行。

## ADDED Requirements

### Requirement: 策略 DSL 六类积木原语

系统 SHALL 提供六类可组合积木原语，所有积木通过唯一 `kind` 标识符在注册表中查找：

1. **BaseStrategy（基础策略）**：底层执行引擎，如 `grid`、`trend`；暴露生命周期钩子 `on_start` / `on_tick` / `on_order_filled` / `on_pause` / `on_resume` / `on_stop`
2. **Indicator（指标）**：从行情/持仓/账户派生的数值信号，如 `price_change_pct(window="1h")`、`rsi(period=14)`、`position_qty()`
3. **Condition（条件）**：对指标的逻辑谓词，如 `gt(indicator, threshold)`、`and(c1, c2)`、`cross_above(i1, i2)`
4. **Event（事件）**：触发源信号，`on_` 前缀，如 `on_tick`、`on_order_filled`、`on_margin_warning`、`on_interval`、`on_strategy_error`
5. **Action（动作）**：执行操作，如 `pause_orders()`、`resume_orders()`、`rebalance_position()`、`place_order(side, qty)`
6. **Rule（规则）**：`WHEN <condition|event> THEN action`，可选 `RECOVER_WHEN <condition|event> THEN action` 表达"触发-恢复"对

#### Scenario: 用户示例可被 DSL 表达
- **WHEN** 投资人员配置「基础=网格做多 + 规则=单边行情暂停恢复」
- **THEN** DSL 引擎能解析为：BaseStrategy(grid) + Rule(when=price_change_pct_1h > 5%, then=pause_orders+hold_position+log_event, recover_when=|price_change_pct_1h| < 5%, then=rebalance_position+resume_orders)
- **AND** 生成的策略行为等价于量化人员手写代码

### Requirement: 状态机执行模型

系统 SHALL 将可拼接策略编译为有限状态机（FSM）执行：

- 每条 Rule 编译为一个或多个 FSM 转换 `transition: (from_state, event, guard, action, to_state)`
- 基础策略始终运行在 `RUNNING` 主状态；触发条件时迁移到 `PAUSED` / `REBALANCING` 等派生状态
- 派生状态下基础策略的 `on_tick` 被抑制，仅执行该状态绑定的 Action
- 恢复条件满足时迁移回 `RUNNING`，调用基础策略 `on_resume`

#### Scenario: 单边行情暂停-恢复流程
- **WHEN** 网格策略运行中，1h 涨幅 > 5%
- **THEN** FSM 从 RUNNING 迁移到 PAUSED，调用 grid.on_pause() 撤销挂单
- **AND** 保留持仓不动作
- **WHEN** 1h 涨跌幅回落到 ±5% 以内
- **THEN** FSM 迁移到 REBALANCING，计算理论持仓 vs 实际持仓的差值
- **AND** 下单一笔市价单抹平差值
- **THEN** FSM 迁移回 RUNNING，调用 grid.on_resume() 重新挂网格

### Requirement: 积木注册表与发现机制

系统 SHALL 维护三个全局注册表（`IndicatorRegistry` / `ConditionRegistry` / `ActionRegistry`），基础策略通过 `BaseStrategyRegistry` 注册：

- 每个积木声明 `kind`、`param_schema`（Pydantic 模型）、`output_type`（指标返回类型）、`description`、`category`（用于前端分组）
- 注册表提供 `list()` 接口供前端获取可用积木目录
- 注册表提供 `get(kind)` 接口供编译器查找实现

#### Scenario: 前端获取可用积木
- **WHEN** 前端调用 `GET /api/dsl/blocks`
- **THEN** 返回 `{"indicators": [...], "conditions": [...], "actions": [...], "base_strategies": [...]}`
- **AND** 每个积木包含 `kind` / `category` / `description` / `param_schema`，足以驱动可视化拖拽面板

### Requirement: DSL 静态校验

系统 SHALL 在策略实例创建/更新时执行静态校验：

1. **结构校验**：DSL 配置符合 Pydantic Schema（字段类型、必填项）
2. **引用校验**：所有 `kind` 在注册表中存在；指标引用的 `symbol` 与基础策略一致；Action 引用的状态合法
3. **类型校验**：Condition 的输入指标类型与谓词期望类型匹配（如 `gt` 期望数值型指标）
4. **语义校验**：每条 Rule 至少有一个 Action；RECOVER_WHEN 必须配合 WHEN 使用；不能形成无法回到 RUNNING 的死锁状态；事件触发器（`mode=event`）必须提供 `event` 字段；条件触发器必须提供 `condition` 字段
5. **资源校验**：指标计算所需数据源（K线周期）OKX 支持；Action 的下单量满足交易对最小单位；事件订阅所需 WebSocket 频道 OKX 支持

#### Scenario: 非法配置被拒绝
- **WHEN** 用户配置 `condition=gt(rsi(period=14), 70)` 但 `rsi` 未在 IndicatorRegistry 注册
- **THEN** 返回 422 错误，明确指出未知 kind `rsi`
- **AND** 不创建策略实例

### Requirement: Dry-Run 模拟执行

系统 SHALL 提供 Dry-Run 接口，用历史 K 线数据回放验证 DSL 配置：

- 输入：DSL 配置 + 回放起止时间 + 交易对
- 输出：模拟的事件序列、状态转换日志、模拟 PnL 曲线
- 不实际下单，仅记录"如果在某时刻会触发某规则、执行某动作"

#### Scenario: 上线前验证
- **WHEN** 投资人员配置完 DSL 后点击"模拟运行"
- **THEN** 后端用过去 7 天 1h K 线回放
- **AND** 返回时间轴：每个 tick 的指标值、是否触发规则、FSM 状态、执行的 Action
- **AND** 投资人员据此判断配置是否符合预期

## DSL 语法规范（JSON 声明式）

### 顶层结构

```json
{
  "version": "1.0",
  "base_strategy": {
    "kind": "grid",
    "params": { "upper_price": 50000, "lower_price": 40000, "grid_count": 10, "order_qty": 0.01, "symbol": "BTC-USDT" }
  },
  "rules": [
    {
      "name": "单边行情暂停",
      "when": {
        "mode": "condition",
        "condition": { "kind": "gt", "args": { "indicator": { "kind": "price_change_pct", "args": { "window": "1h", "symbol": "BTC-USDT" } }, "threshold": 0.05 } }
      },
      "then": [ { "kind": "pause_orders" }, { "kind": "hold_position" }, { "kind": "log_event", "args": { "level": "warn", "message": "单边上涨暂停" } } ],
      "recover_when": {
        "mode": "condition",
        "condition": { "kind": "abs_lt", "args": { "indicator": { "kind": "price_change_pct", "args": { "window": "1h", "symbol": "BTC-USDT" } }, "threshold": 0.05 } }
      },
      "recover_then": [ { "kind": "rebalance_position", "args": { "mode": "to_theoretical" } }, { "kind": "resume_orders" } ],
      "cool_down_seconds": 60
    }
  ]
}
```

### 五类积木的统一形态

所有积木采用 `{"kind": "...", "args": {...}}` 形态，便于前端递归渲染与后端递归解析：

| 积木类 | kind 示例 | args 示例 | 输出 |
|---|---|---|---|
| BaseStrategy | `grid` / `trend` | 策略专属参数 | 策略执行体 |
| Indicator | `price_change_pct` / `rsi` / `position_qty` | `{"window":"1h","symbol":"BTC-USDT"}` | float / dict |
| Condition | `gt` / `lt` / `cross_above` / `and` / `or` | `{"indicator":<Indicator>, "threshold":0.05}` | bool |
| Event | `on_tick` / `on_order_filled` / `on_margin_warning` | `{"symbol":"BTC-USDT-SWAP","threshold":0.5}` | 事件对象 |
| Action | `pause_orders` / `resume_orders` / `rebalance_position` / `place_order` | 各自参数 | None（副作用） |
| Rule | 顶层 `rules[]` 数组项 | `when/then/recover_when/recover_then` | FSM 转换 |

### 文本语法（二期可选，非本 spec 范围）

二期可基于 Lark 提供：

```
STRATEGY grid(symbol=BTC-USDT, upper=50000, lower=40000, grid=10, qty=0.01)
RULE 单边行情暂停
  WHEN price_change_pct(window=1h) > 5%
  THEN pause_orders, hold_position
  RECOVER_WHEN |price_change_pct(window=1h)| < 5%
  RECOVER_THEN rebalance_position(mode=to_theoretical), resume_orders
```

## 积木清单（金融技术视角）

> 本节为内置积木的统一目录。每个积木标注 `kind` / `category`（前端分组用） / `output_type` / `args` / `数据源` / `说明`。第一期实现标注 P0（最小可用集，覆盖用户示例），后续标注 P1/P2。
>
> 数据源缩写：`REST`=OKX REST API、`WS`=OKX WebSocket、`DB`=本地数据库、`STATE`=策略内存状态、`CALC`=纯计算派生。

### A. 指标库（Indicator）—— 信号源

#### A1. 行情价格类（category: 行情·价格）

| kind | P级 | args | output | 数据源 | 说明 |
|---|---|---|---|---|---|
| `price_last` | P0 | `{symbol}` | float | REST/WS | 最新成交价 |
| `price_change_pct` | P0 | `{window, symbol}` | float | REST | window 起点价 → 现价 的涨跌幅（小数，0.05=5%） |
| `price_change_abs` | P1 | `{window, symbol}` | float | REST | 绝对涨跌额 |
| `price_high` | P1 | `{window, symbol}` | float | REST | window 内最高价 |
| `price_low` | P1 | `{window, symbol}` | float | REST | window 内最低价 |
| `price_range_pct` | P1 | `{window, symbol}` | float | REST | 振幅 (high-low)/open |
| `price_volatility` | P1 | `{window, symbol}` | float | REST+CALC | window 内收益率标准差（年化） |
| `vwap` | P1 | `{window, symbol}` | float | REST+CALC | 成交量加权均价 |
| `twap` | P2 | `{window, symbol}` | float | REST+CALC | 时间加权均价 |
| `bid_ask_spread` | P1 | `{symbol}` | float | REST/WS | 买一卖一价差（绝对值或 bp） |
| `order_book_imbalance` | P2 | `{symbol, depth}` | float | REST | 盘口失衡度 (bid_vol-ask_vol)/(bid_vol+ask_vol) |

#### A2. 技术指标类（category: 行情·技术指标）

| kind | P级 | args | output | 数据源 | 说明 |
|---|---|---|---|---|---|
| `ma` | P1 | `{period, symbol, field=close}` | float | REST+CALC | 简单移动平均 |
| `ema` | P1 | `{period, symbol, field=close}` | float | REST+CALC | 指数移动平均 |
| `rsi` | P0 | `{period, symbol}` | float | REST+CALC | 相对强弱指标 [0,100] |
| `macd` | P1 | `{fast, slow, signal, symbol}` | dict | REST+CALC | `{macd, signal, hist}` |
| `boll` | P1 | `{period, std, symbol}` | dict | REST+CALC | `{upper, mid, lower}` |
| `kdj` | P2 | `{period, symbol}` | dict | REST+CALC | `{k, d, j}` |
| `atr` | P1 | `{period, symbol}` | float | REST+CALC | 真实波动幅度 |
| `cci` | P2 | `{period, symbol}` | float | REST+CALC | 顺势指标 |
| `obv` | P2 | `{symbol}` | float | REST+CALC | 能量潮 |
| `wr` | P2 | `{period, symbol}` | float | REST+CALC | 威廉指标 |

#### A3. 成交量类（category: 行情·成交量）

| kind | P级 | args | output | 数据源 | 说明 |
|---|---|---|---|---|---|
| `volume` | P1 | `{window, symbol}` | float | REST | window 内成交量 |
| `volume_change_pct` | P1 | `{window, symbol}` | float | REST+CALC | 量比（当前量 / 上一周期量） |
| `volume_ma` | P1 | `{period, symbol}` | float | REST+CALC | 成交量均值 |
| `turnover` | P1 | `{window, symbol}` | float | REST | window 内成交额 |

#### A4. 持仓账户类（category: 账户·持仓）

| kind | P级 | args | output | 数据源 | 说明 |
|---|---|---|---|---|---|
| `position_qty` | P0 | `{symbol}` | float | REST | 当前持仓数量（正多负空） |
| `position_pnl` | P0 | `{symbol}` | float | REST | 持仓未实现盈亏（U） |
| `position_pnl_pct` | P1 | `{symbol}` | float | REST+CALC | 持仓盈亏率 |
| `position_margin_ratio` | P1 | `{symbol}` | float | REST | 保证金率（强平预警用） |
| `position_leverage` | P1 | `{symbol}` | float | REST | 当前杠杆倍数 |
| `liquidation_price` | P1 | `{symbol}` | float | REST | 强平价 |
| `account_equity` | P0 | `{}` | float | REST | 账户净值 |
| `account_balance` | P1 | `{}` | float | REST | 账户余额 |
| `account_available` | P1 | `{ccy=USDT}` | float | REST | 可用资金 |
| `account_leverage` | P1 | `{}` | float | REST | 账户总杠杆 |

#### A5. 资金费率与跨市场类（category: 衍生品·跨市场）

| kind | P级 | args | output | 数据源 | 说明 |
|---|---|---|---|---|---|
| `funding_rate` | P1 | `{symbol}` | float | REST | 当前资金费率 |
| `funding_rate_history` | P2 | `{symbol, window}` | list | REST | 历史资金费率序列 |
| `basis` | P1 | `{spot_symbol, futures_symbol}` | float | REST | 基差 = 合约价 - 现货价 |
| `basis_pct` | P1 | `{spot_symbol, futures_symbol}` | float | REST+CALC | 基差率 = 基差/现货价 |
| `correlation` | P2 | `{sym1, sym2, window}` | float | REST+CALC | 滚动相关系数 |

#### A6. 策略状态类（category: 策略·内部状态）

| kind | P级 | args | output | 数据源 | 说明 |
|---|---|---|---|---|---|
| `realized_pnl` | P0 | `{}` | float | STATE | 累计已实现盈亏 |
| `unrealized_pnl` | P0 | `{}` | float | STATE+REST | 当前未实现盈亏 |
| `grid_fill_count` | P1 | `{}` | int | STATE | 网格累计成交次数 |
| `grid_active_orders` | P1 | `{}` | int | STATE | 当前活跃挂单数 |
| `rule_active` | P1 | `{rule_name}` | bool | STATE | 某规则是否处于触发态（用于规则互斥） |
| `strategy_uptime` | P2 | `{}` | float | STATE | 策略运行秒数 |

### B. 事件库（Event）—— 触发源

> Rule 的 `when` 既可以是条件（每个 tick 评估），也可以绑定事件（仅事件发生时触发）。事件类积木的 `kind` 以 `on_` 前缀标识，注册在独立的 `event_registry` 中。Rule 的 `when` 字段接受 `ConditionRef | EventRef`。

#### B1. 行情事件（category: 行情·事件）

| kind | P级 | args | 触发时机 | 数据源 | 说明 |
|---|---|---|---|---|---|
| `on_tick` | P0 | `{symbol}` | 每个 tick | WS/REST | 价格更新（默认 3s 轮询或 WS 推送） |
| `on_kline_close` | P1 | `{symbol, interval}` | K线收盘 | WS | 1m/5m/1h/1d K 线收盘时 |
| `on_price_above` | P1 | `{symbol, level}` | 价格上穿阈值 | WS+STATE | 等价于 cross_above(price, level) |
| `on_price_below` | P1 | `{symbol, level}` | 价格下穿阈值 | WS+STATE | 等价于 cross_below(price, level) |
| `on_volume_spike` | P2 | `{symbol, multiplier}` | 量比超倍数 | REST+CALC | 当前量 / 均量 > multiplier |

#### B2. 订单事件（category: 订单·事件）

| kind | P级 | args | 触发时机 | 数据源 | 说明 |
|---|---|---|---|---|---|
| `on_order_placed` | P1 | `{}` | 订单创建成功 | WS | 任意订单挂出 |
| `on_order_filled` | P0 | `{side?, symbol?}` | 订单成交 | WS | 可按方向/品种过滤 |
| `on_order_partially_filled` | P2 | `{}` | 订单部分成交 | WS | |
| `on_order_canceled` | P1 | `{}` | 订单撤销 | WS | |
| `on_order_rejected` | P1 | `{}` | 订单被拒 | WS | 风控/参数错误 |

#### B3. 持仓事件（category: 持仓·事件）

| kind | P级 | args | 触发时机 | 数据源 | 说明 |
|---|---|---|---|---|---|
| `on_position_opened` | P1 | `{symbol}` | 持仓从 0 变非 0 | REST+STATE | 新开仓 |
| `on_position_closed` | P1 | `{symbol}` | 持仓从非 0 变 0 | REST+STATE | 全平 |
| `on_position_changed` | P2 | `{symbol, delta}` | 持仓量变化超阈值 | REST+STATE | |
| `on_margin_warning` | P0 | `{symbol, threshold=0.5}` | 保证金率低于阈值 | REST | 强平预警 |
| `on_liquidation_approaching` | P1 | `{symbol, pct=5%}` | 价距强平价 < pct | REST+CALC | 接近强平 |

#### B4. 账户事件（category: 账户·事件）

| kind | P级 | args | 触发时机 | 数据源 | 说明 |
|---|---|---|---|---|---|
| `on_equity_drawdown` | P1 | `{pct}` | 净值回撤超 pct | REST+STATE | 从历史高点回撤 |
| `on_balance_update` | P2 | `{}` | 余额变动 | WS | 充提/划转 |
| `on_daily_settlement` | P2 | `{}` | 每日结算时点 | 定时 | UTC 0:00 |

#### B5. 定时事件（category: 定时）

| kind | P级 | args | 触发时机 | 数据源 | 说明 |
|---|---|---|---|---|---|
| `on_interval` | P0 | `{seconds}` | 每 N 秒 | 定时 | 固定周期 |
| `on_schedule` | P1 | `{cron}` | cron 表达式 | 定时 | 灵活调度（如每日 8:00） |
| `on_session_open` | P2 | `{market}` | 市场开盘 | 定时 | 美股/港股等 |

#### B6. 策略生命周期事件（category: 策略·生命周期）

| kind | P级 | args | 触发时机 | 数据源 | 说明 |
|---|---|---|---|---|---|
| `on_strategy_start` | P1 | `{}` | 策略启动 | STATE | |
| `on_strategy_stop` | P1 | `{}` | 策略停止 | STATE | |
| `on_strategy_error` | P0 | `{}` | 策略异常 | STATE | 用于异常兜底动作 |
| `on_rule_triggered` | P2 | `{rule_name}` | 其他规则触发 | STATE | 规则联动 |

### C. 条件库（Condition）—— 逻辑谓词

#### C1. 比较类（category: 比较）

| kind | P级 | args | 输入 | 输出 | 说明 |
|---|---|---|---|---|---|
| `gt` | P0 | `{indicator, threshold}` | 数值 | bool | indicator > threshold |
| `lt` | P0 | `{indicator, threshold}` | 数值 | bool | indicator < threshold |
| `gte` | P1 | `{indicator, threshold}` | 数值 | bool | ≥ |
| `lte` | P1 | `{indicator, threshold}` | 数值 | bool | ≤ |
| `eq` | P1 | `{indicator, threshold, tolerance}` | 数值 | bool | 在容差范围内相等 |
| `abs_gt` | P0 | `{indicator, threshold}` | 数值 | bool | \|indicator\| > threshold |
| `abs_lt` | P0 | `{indicator, threshold}` | 数值 | bool | \|indicator\| < threshold |

#### C2. 交叉类（category: 交叉，需保留上 tick 状态）

| kind | P级 | args | 输入 | 输出 | 说明 |
|---|---|---|---|---|---|
| `cross_above` | P1 | `{indicator_a, indicator_b}` | 两数值 | bool | a 上穿 b |
| `cross_below` | P1 | `{indicator_a, indicator_b}` | 两数值 | bool | a 下穿 b |
| `cross_value` | P1 | `{indicator, value}` | 数值 | bool | indicator 上穿常数 |

#### C3. 区间类（category: 区间）

| kind | P级 | args | 输入 | 输出 | 说明 |
|---|---|---|---|---|---|
| `in_range` | P1 | `{indicator, lower, upper}` | 数值 | bool | indicator ∈ [lower, upper] |
| `out_range` | P1 | `{indicator, lower, upper}` | 数值 | bool | indicator ∉ [lower, upper] |

#### C4. 趋势类（category: 趋势，需窗口状态）

| kind | P级 | args | 输入 | 输出 | 说明 |
|---|---|---|---|---|---|
| `rising` | P2 | `{indicator, window}` | 数值 | bool | 连续 window 上升 |
| `falling` | P2 | `{indicator, window}` | 数值 | bool | 连续 window 下降 |
| `plateau` | P2 | `{indicator, window, tolerance}` | 数值 | bool | window 内波动 < tolerance |

#### C5. 逻辑组合（category: 逻辑）

| kind | P级 | args | 输入 | 输出 | 说明 |
|---|---|---|---|---|---|
| `and` | P0 | `{conditions: [ConditionRef,...]}` | 多 bool | bool | 全部为真 |
| `or` | P0 | `{conditions: [ConditionRef,...]}` | 多 bool | bool | 任一为真 |
| `not` | P0 | `{condition: ConditionRef}` | bool | bool | 取反 |
| `xor` | P2 | `{a, b}` | 两 bool | bool | 异或 |

#### C6. 统计类（category: 统计，需窗口状态）

| kind | P级 | args | 输入 | 输出 | 说明 |
|---|---|---|---|---|---|
| `zscore_deviation` | P2 | `{indicator, window, threshold}` | 数值 | bool | Z-score 超阈值 |
| `deviation_from_mean` | P2 | `{indicator, window, pct}` | 数值 | bool | 偏离均值超 pct |

### D. 动作库（Action）—— 执行体

#### D1. 订单动作（category: 订单）

| kind | P级 | args | 副作用 | 说明 |
|---|---|---|---|---|
| `place_order` | P0 | `{symbol, side, type, qty, price?}` | 下单 | type: limit/market/post_only |
| `cancel_order` | P1 | `{symbol, order_id}` | 撤单 | 指定订单 |
| `cancel_all` | P0 | `{symbol?}` | 撤单 | 撤所有/指定品种 |
| `batch_place_orders` | P1 | `{orders: [...]}` | 批量下单 | 单批 ≤20（OKX 限制） |
| `modify_order` | P2 | `{order_id, new_price, new_qty}` | 改单 | OKX 改单接口 |

#### D2. 持仓动作（category: 持仓）

| kind | P级 | args | 副作用 | 说明 |
|---|---|---|---|---|
| `open_position` | P1 | `{symbol, side, qty, type=market}` | 开仓 | 显式开仓 |
| `close_position` | P1 | `{symbol, qty?}` | 平仓 | qty 省略=全平 |
| `close_all` | P1 | `{symbol?}` | 平仓 | 全平 |
| `reduce_position` | P1 | `{symbol, pct}` | 减仓 | 按比例减 |
| `increase_position` | P1 | `{symbol, side, pct}` | 加仓 | 按比例加 |
| `rebalance_position` | P0 | `{symbol, mode, target?}` | 调仓 | mode: to_theoretical/to_target/from_zero |
| `hedge_position` | P1 | `{symbol, pct}` | 套保 | 反向开仓 pct% |
| `unhedge_position` | P1 | `{symbol}` | 平套保 | 平掉套保仓 |
| `hold_position` | P0 | `{}` | 无 | 仅记录事件，保持现状 |

#### D3. 策略控制动作（category: 策略控制）

| kind | P级 | args | 副作用 | 说明 |
|---|---|---|---|---|
| `pause_orders` | P0 | `{symbol?}` | 暂停 | 撤挂单但保留持仓，停止 on_tick |
| `resume_orders` | P0 | `{symbol?}` | 恢复 | 重新挂网格/启动 on_tick |
| `stop_strategy` | P1 | `{}` | 停止 | 调用基础策略 on_stop |
| `restart_strategy` | P2 | `{}` | 重启 | 停止后重新 start |
| `switch_params` | P2 | `{params}` | 切换 | 动态修改基础策略参数 |

#### D4. 风控动作（category: 风控）

| kind | P级 | args | 副作用 | 说明 |
|---|---|---|---|---|
| `set_stop_loss` | P1 | `{symbol, price?, pct?}` | 设止损 | 价或比例二选一 |
| `set_take_profit` | P1 | `{symbol, price?, pct?}` | 设止盈 | |
| `set_trailing_stop` | P2 | `{symbol, pct}` | 移动止损 | 跟踪价回撤 pct 触发 |
| `adjust_leverage` | P1 | `{symbol, level}` | 调杠杆 | OKX 设置杠杆 |
| `transfer_margin` | P2 | `{symbol, amount}` | 划转保证金 | 增减仓位保证金 |

#### D5. 通知动作（category: 通知）

| kind | P级 | args | 副作用 | 说明 |
|---|---|---|---|---|
| `send_alert` | P1 | `{channel, message}` | 通知 | channel: webhook/email/telegram |
| `log_event` | P0 | `{level, message, details?}` | 记录 | 写 StrategyEvent 表 |
| `send_webhook` | P2 | `{url, payload}` | HTTP | 自定义 webhook |

#### D6. 状态动作（category: 状态）

| kind | P级 | args | 副作用 | 说明 |
|---|---|---|---|---|
| `set_state` | P1 | `{key, value}` | 写内存 | 策略级 KV，用于跨规则通信 |
| `clear_state` | P1 | `{key}` | 写内存 | 清除 KV |
| `mark_rule_active` | P1 | `{rule_name}` | 写内存 | 配合 `rule_active` 指标实现规则互斥 |

### E. 基础策略库（BaseStrategy）—— 执行引擎

| kind | P级 | 说明 | 暴露钩子 |
|---|---|---|---|
| `grid` | P0 | 网格（高低抛吸） | on_start/on_tick/on_order_filled/on_pause/on_resume/on_stop |
| `trend` | P1 | 双均线趋势跟随 | 同上 |
| `arbitrage` | P1 | 期现套利 | 同上 |
| `advanced_grid_hedge` | P1 | 网格+套保 | 同上 |
| `dca` | P2 | 定投（后续） | 同上 |
| `martingale` | P2 | 马丁格尔（后续） | 同上 |

### F. 优先级汇总

- **P0（第一期必做，覆盖用户示例 + 基础闭环）**：
  - 指标：`price_last` / `price_change_pct` / `rsi` / `position_qty` / `position_pnl` / `account_equity` / `realized_pnl` / `unrealized_pnl`
  - 事件：`on_tick` / `on_order_filled` / `on_margin_warning` / `on_strategy_error` / `on_interval`
  - 条件：`gt` / `lt` / `abs_gt` / `abs_lt` / `and` / `or` / `not`
  - 动作：`place_order` / `cancel_all` / `rebalance_position` / `hold_position` / `pause_orders` / `resume_orders` / `log_event`
  - 基础：`grid`
- **P1（第二期，丰富常用积木）**：上表所有 P1 项
- **P2（后续按需）**：上表所有 P2 项

### G. 积木组合示例（金融场景验证）

**场景 1：单边行情暂停网格（用户原始示例）**
```
WHEN  on_tick AND price_change_pct(window=1h) > 5%
THEN  pause_orders, hold_position, log_event(level=warn, message="单边上涨暂停")
RECOVER_WHEN  abs_lt(price_change_pct(window=1h), 0.05)
RECOVER_THEN  rebalance_position(mode=to_theoretical), resume_orders
```

**场景 2：保证金率预警自动减仓**
```
WHEN  on_margin_warning(symbol=BTC-USDT-SWAP, threshold=0.5)
THEN  log_event(level=critical, message="保证金率告警"),
      reduce_position(symbol=BTC-USDT-SWAP, pct=0.3),
      send_alert(channel=telegram, message="强平风险，已减仓30%")
```

**场景 3：RSI 超买 + 趋势确认的网格暂停**
```
WHEN  and([
        gt(rsi(period=14, symbol=BTC-USDT), 70),
        cross_below(ma(period=5), ma(period=20))
      ])
THEN  pause_orders
RECOVER_WHEN  lt(rsi(period=14, symbol=BTC-USDT), 50)
RECOVER_THEN  resume_orders
```

**场景 4：资金费率套利触发**
```
WHEN  abs_gt(funding_rate(symbol=BTC-USDT-SWAP), 0.001)
THEN  hedge_position(symbol=BTC-USDT-SWAP, pct=1.0),
      log_event(level=info, message="资金费率套保触发")
RECOVER_WHEN  abs_lt(funding_rate(symbol=BTC-USDT-SWAP), 0.0003)
RECOVER_THEN  unhedge_position(symbol=BTC-USDT-SWAP)
```

**场景 5：净值回撤保护**
```
WHEN  on_equity_drawdown(pct=0.1)
THEN  close_all,
      stop_strategy,
      send_alert(channel=webhook, message="回撤超10%，全平止损")
```

## 后端类与接口设计

### 目录结构（新增）

```
backend/dsl/
├── __init__.py
├── schema.py              # Pydantic 模型：StrategyDSL / Rule / Indicator / Condition / Action / Event
├── registry.py            # 四个注册表 + 装饰器（indicator/condition/action/event/base_strategy）
├── compiler.py            # DSL -> FSM 编译器
├── executor.py            # ComposableStrategy（FSM 执行器，继承 BaseStrategy）
├── validator.py           # 静态校验器
├── dry_run.py             # 历史回放模拟器
└── blocks/
    ├── __init__.py
    ├── indicators.py      # 行情/技术/持仓/账户/资金费率/策略状态 共 30+ 指标（按 P0/P1/P2 分期实现）
    ├── events.py          # 行情/订单/持仓/账户/定时/生命周期 共 20+ 事件（on_ 前缀）
    ├── conditions.py      # 比较/交叉/区间/趋势/逻辑/统计 共 20+ 条件
    ├── actions.py         # 订单/持仓/策略控制/风控/通知/状态 共 25+ 动作
    └── bases.py           # 将现有 GridStrategy/TrendStrategy 包装为可钩子调用的 BaseStrategyBlock
```

### 核心类签名

```python
# backend/dsl/schema.py
from pydantic import BaseModel
from typing import Any, Literal

class BlockRef(BaseModel):
    """统一积木引用形态"""
    kind: str
    args: dict[str, Any] = {}

class IndicatorRef(BlockRef): pass
class ConditionRef(BlockRef): pass
class ActionRef(BlockRef): pass
class EventRef(BlockRef): pass   # 事件类积木，kind 以 on_ 前缀

class Trigger(BaseModel):
    """Rule 的触发器：可以是条件（每 tick 评估）或事件（仅事件发生时触发）"""
    mode: Literal["condition", "event"] = "condition"
    condition: ConditionRef | None = None
    event: EventRef | None = None
    # 也可组合：event AND condition，事件发生时再评估条件
    extra_condition: ConditionRef | None = None

class Rule(BaseModel):
    name: str
    when: Trigger
    then: list[ActionRef] = []
    recover_when: Trigger | None = None
    recover_then: list[ActionRef] = []
    cool_down_seconds: float = 0.0   # 触发后冷却，避免抖动

class BaseStrategyRef(BaseModel):
    kind: Literal["grid", "trend", "arbitrage", "advanced_grid_hedge"]
    params: dict[str, Any]

class StrategyDSL(BaseModel):
    version: Literal["1.0"]
    base_strategy: BaseStrategyRef
    rules: list[Rule] = []
```

```python
# backend/dsl/registry.py
class Registry:
    def register(self, kind: str, cls): ...
    def get(self, kind: str): ...
    def list(self) -> list[dict]: ...   # 返回 [{kind, category, description, param_schema}]

indicator_registry = Registry()
condition_registry = Registry()
action_registry = Registry()
event_registry = Registry()           # 事件类积木（on_ 前缀）
base_strategy_registry = Registry()

def indicator(kind: str):
    def deco(cls):
        indicator_registry.register(kind, cls)
        return cls
    return deco

# condition / action / event / base_strategy 装饰器同理
```

```python
# backend/dsl/blocks/indicators.py
@indicator("price_change_pct")
class PriceChangePct:
    param_schema = { "window": {"type":"str","required":True}, "symbol": {"type":"str","required":True} }
    output_type = float
    category = "行情"

    def __init__(self, window: str, symbol: str):
        self.window = window   # "1h" / "5m" / "1d"
        self.symbol = symbol
        self._ref_price = None
        self._ref_ts = 0

    async def compute(self, ctx: "ExecutionContext") -> float:
        # 取 window 起点价格 vs 当前价
        ...
```

```python
# backend/dsl/compiler.py
class FSMCompiler:
    def compile(self, dsl: StrategyDSL) -> "FSM":
        # 1. 实例化 base_strategy
        # 2. 对每条 Rule 生成两个 transition：
        #    - (RUNNING, <event|tick>, when_guard, then, PAUSED_<rule_name>)
        #    - (PAUSED_<rule_name>, <event|tick>, recover_when_guard, recover_then, REBALANCING/RUNNING)
        #    其中 event 来自 Rule.when.mode=="event" 时的事件订阅，tick 来自 mode=="condition" 时的轮询评估
        # 3. 校验状态可达性（所有 PAUSED/REBALANCING 都能回到 RUNNING）
        ...
```

```python
# backend/dsl/executor.py
class ComposableStrategy(BaseStrategy):
    """可拼接策略执行器，作为 _strategy_map['composable'] 的实现"""
    async def execute(self):
        # 1. 从 self.params["dsl_config"] 加载 StrategyDSL
        # 2. FSMCompiler 编译为 FSM
        # 3. 启动基础策略（调用其 on_start）
        # 4. 主循环：每个 tick 计算所有指标、评估当前状态的 transition guard、迁移状态、执行 action
        ...

    async def validate_params(self) -> bool:
        return DSLValidator().validate(self.params.get("dsl_config", {}))
```

### StrategyEngine 集成

[strategy_engine.py](file:///e:/New%20folder%20(2)/quant_okx/backend/services/strategy_engine.py) 的 `_strategy_map` 增加：

```python
"composable": ComposableStrategy,
```

`start_strategy` 内部逻辑不变（已经按 `template.strategy_type` 分发），新增的 `composable` 类型自动走 `ComposableStrategy.execute()`，后者从 `instance.params["dsl_config"]` 读取 DSL 配置。

### 数据模型变更

[StrategyTemplate](file:///e:/New%20folder%20(2)/quant_okx/backend/models/strategy.py) 新增字段（向后兼容，已有行不受影响）：

```python
dsl_config = Column(JSON, nullable=True)  # 可拼接策略的 DSL 配置；NULL 表示传统硬编码策略
```

### REST API（新增）

| Method | Path | 用途 |
|---|---|---|
| GET | `/api/dsl/blocks` | 列出所有可用积木（indicators/conditions/actions/events/base_strategies），按 category 分组 |
| POST | `/api/dsl/validate` | 静态校验 DSL 配置，返回错误列表 |
| POST | `/api/dsl/dry-run` | 历史回放模拟，返回事件时间轴 |

## 用户示例的 DSL 表达（验证设计自洽）

投资人员通过前端拖拽生成以下 `dsl_config`：

```json
{
  "version": "1.0",
  "base_strategy": {
    "kind": "grid",
    "params": { "upper_price": 50000, "lower_price": 40000, "grid_count": 10, "order_qty": 0.01, "symbol": "BTC-USDT" }
  },
  "rules": [
    {
      "name": "单边上涨暂停",
      "when": {
        "mode": "condition",
        "condition": { "kind": "gt", "args": { "indicator": { "kind": "price_change_pct", "args": { "window": "1h", "symbol": "BTC-USDT" } }, "threshold": 0.05 } }
      },
      "then": [ { "kind": "pause_orders" }, { "kind": "hold_position" }, { "kind": "log_event", "args": { "level": "warn", "message": "单边上涨暂停" } } ],
      "recover_when": {
        "mode": "condition",
        "condition": { "kind": "abs_lt", "args": { "indicator": { "kind": "price_change_pct", "args": { "window": "1h", "symbol": "BTC-USDT" } }, "threshold": 0.05 } }
      },
      "recover_then": [ { "kind": "rebalance_position", "args": { "mode": "to_theoretical" } }, { "kind": "resume_orders" } ],
      "cool_down_seconds": 60
    }
  ]
}
```

FSM 编译产物（伪表示）：

```
States: { RUNNING, PAUSED_单边上涨暂停, REBALANCING_单边上涨暂停 }
Transitions:
  RUNNING --[price_change_pct_1h > 5%]--> PAUSED_单边上涨暂停
    action: pause_orders, hold_position
  PAUSED_单边上涨暂停 --[|price_change_pct_1h| < 5%]--> REBALANCING_单边上涨暂停
    action: rebalance_position(to_theoretical)
  REBALANCING_单边上涨暂停 --[always]--> RUNNING
    action: resume_orders
```

## 范围说明

本 spec 仅覆盖**语法框架 + 后端接口设计 + 语言选型**。前端可视化编辑器、文本 DSL 解析器（Lark）、更丰富的指标库（MACD/BOLL 等）将在后续 spec 中分别设计。
