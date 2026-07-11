# QuantOKX 策略编写指南

本指南面向策略开发者，详细说明如何使用 QS-Model 四段式结构与积木库编写量化策略。

---

## 目录

1. [QS-Model 结构说明](#1-qs-model-结构说明)
2. [基础策略类型](#2-基础策略类型)
3. [积木库参考](#3-积木库参考)
4. [变量引用机制](#4-变量引用机制)
5. [风控配置](#5-风控配置)
6. [示例策略](#6-示例策略)

---

## 1. QS-Model 结构说明

QS-Model v2.0 是 QuantOKX 用于描述策略的四段式复合结构，由四个段组成：

```
QS-Model
├── meta          （元信息段）
├── params        （参数定义段）
├── logic          （策略逻辑段）
│   ├── base_strategy   基础策略引用
│   └── rules           规则列表（条件→动作）
└── risk_filter   （风控段，可选）
```

### 1.1 meta 段（元信息）

定义策略的基本信息，用于展示与分类。

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | string | 是 | 策略名称 |
| `version` | string | 否 | 版本号，默认 `v1.0.0` |
| `author` | string | 否 | 作者 |
| `description` | string | 否 | 策略描述 |
| `asset_class` | string | 否 | 资产类别，默认 `CRYPTO` |
| `frequency` | string | 否 | 运行频率，如 `15min` / `1h` / `1d` |
| `base_symbol` | string | 否 | 基准交易对，如 `BTC-USDT` |

示例：
```json
{
  "name": "BTC 双均线趋势",
  "version": "v1.0.0",
  "author": "量化团队",
  "description": "基于 5/20 均线金叉死叉的趋势跟踪策略",
  "asset_class": "CRYPTO",
  "frequency": "1h",
  "base_symbol": "BTC-USDT"
}
```

### 1.2 params 段（参数定义）

声明策略的可变参数，每个参数包含类型、范围、默认值等。这些参数可在创建实例时被覆盖，实现参数化策略。

参数名为 key，值为 `ParamDefinition` 对象：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `label` | string | 是 | 中文显示名 |
| `value` | any | 是 | 默认值 |
| `type` | string | 是 | 类型：`int` / `float` / `string` / `bool` / `select` |
| `range` | array | 否 | 取值范围 `[min, max]` |
| `description` | string | 否 | 参数说明 |
| `options` | array | 否 | `select` 类型的选项列表 |
| `option_labels` | array | 否 | 选项中文标签 |
| `unit` | string | 否 | 单位，如 `%` / `秒` |

示例：
```json
{
  "fast_period": {
    "label": "快均线周期",
    "value": 5,
    "type": "int",
    "range": [1, 50],
    "description": "快速移动平均线周期"
  },
  "direction": {
    "label": "交易方向",
    "value": "both",
    "type": "select",
    "options": ["long", "short", "both"],
    "option_labels": ["做多", "做空", "双向"]
  }
}
```

### 1.3 logic 段（策略逻辑）

策略的核心逻辑，包含基础策略引用与规则列表。复用 `StrategyDSL` 结构。

```json
{
  "version": "1.0",
  "base_strategy": {
    "kind": "grid",
    "params": {
      "upper_price": "$params.upper_price",
      "lower_price": "$params.lower_price"
    }
  },
  "rules": [
    {
      "name": "止损规则",
      "when": {
        "mode": "condition",
        "condition": {
          "kind": "gt",
          "args": {
            "indicator": {"kind": "position_pnl", "args": {}},
            "threshold": 100
          }
        }
      },
      "then": [
        {"kind": "cancel_all", "args": {}}
      ],
      "cool_down_seconds": 60
    }
  ]
}
```

**base_strategy**：引用一个基础策略 Block（如 grid / trend），提供 `on_start` / `on_tick` / `on_order_filled` 等钩子。

**rules**：规则列表，每条规则定义「何时触发 → 执行什么动作」。规则由 Trigger（触发器）和 Action（动作）组成。

### 1.4 risk_filter 段（风控配置）

可选的风险控制配置，在策略执行时生效。

| 字段 | 类型 | 说明 |
|------|------|------|
| `max_position_ratio` | float | 最大持仓比例 |
| `daily_max_loss` | float | 每日最大亏损（达到后停止策略） |
| `min_trade_size` | float | 最小交易量 |
| `blacklist_hours` | array | 黑名单时段，如 `["00:00", "01:00"]` |
| `stop_loss` | float | 止损阈值（小数，如 -0.05 表示 -5%） |
| `take_profit` | float | 止盈阈值（小数，如 0.1 表示 +10%） |

---

## 2. 基础策略类型

基础策略（Base Strategy）是可拼接的策略 Block，通过 `@base_strategy(kind)` 注册。在 `logic.base_strategy.kind` 中引用。

### 2.1 网格策略（grid）

在价格区间内均匀布置买卖网格，高抛低吸。

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `upper_price` | number | 是 | - | 价格上限 |
| `lower_price` | number | 是 | - | 价格下限 |
| `grid_count` | integer | 是 | - | 网格数量 |
| `order_qty` | number | 否 | 0.001 | 单格交易量 |
| `grid_mode` | select | 否 | arithmetic | 网格模式：`arithmetic`（等差）/ `geometric`（等比） |
| `direction` | select | 否 | neutral | 交易方向：`long`（做多）/ `short`（做空）/ `neutral`（双向） |
| `symbol` | string | 是 | - | 交易对 |

### 2.2 双均线趋势（trend）

短期均线上穿长期均线（金叉）做多，下穿（死叉）做空。

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `fast_period` | integer | 是 | 5 | 快均线周期 |
| `slow_period` | integer | 是 | 20 | 慢均线周期 |
| `direction` | select | 否 | both | 交易方向：`long` / `short` / `both` |
| `bar` | select | 是 | 1H | K 线周期 |
| `symbol` | string | 是 | - | 交易对 |

### 2.3 RSI 超买超卖（rsi_strategy）

RSI 低于超卖阈值时买入，高于超买阈值时卖出。

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `period` | integer | 是 | 14 | RSI 计算周期 |
| `oversold` | integer | 否 | 30 | 超卖阈值（低于买入） |
| `overbought` | integer | 否 | 70 | 超买阈值（高于卖出） |
| `direction` | select | 否 | both | 交易方向 |
| `bar` | select | 是 | 1H | K 线周期 |
| `symbol` | string | 是 | - | 交易对 |

### 2.4 布林带（bollinger_bands）

价格跌破布林带下轨买入，突破上轨卖出。

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `period` | integer | 是 | 20 | 计算周期 |
| `std_multiplier` | number | 否 | 2.0 | 标准差倍数 |
| `direction` | select | 否 | both | 交易方向 |
| `bar` | select | 是 | 1H | K 线周期 |
| `symbol` | string | 是 | - | 交易对 |

### 2.5 唐奇安通道（donchian）

海龟法则：突破入场周期最高价做多，跌破离场周期最低价平多。

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `entry_period` | integer | 是 | 20 | 突破入场回溯周期 |
| `exit_period` | integer | 否 | 10 | 离场回溯周期 |
| `direction` | select | 否 | both | 交易方向 |
| `bar` | select | 是 | 1H | K 线周期 |
| `symbol` | string | 是 | - | 交易对 |

### 2.6 定投策略（dca）

按固定频率和金额定时买入，平摊持仓成本。

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `amount` | number | 是 | 100 | 每期投资金额（计价货币） |
| `frequency` | select | 否 | daily | 定投频率：`daily` / `weekly` / `monthly` |
| `day_of_week` | integer | 否 | 1 | 每周定投的星期（0=周日） |
| `symbol` | string | 是 | - | 交易对 |

### 2.7 马丁格尔（martingale）

亏损后按倍数加仓，一次盈利覆盖全部亏损并平仓重置。

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `initial_size` | number | 是 | 0.001 | 初始交易数量 |
| `multiplier` | number | 否 | 2.0 | 亏损后加仓倍数 |
| `max_levels` | integer | 否 | 5 | 最大加仓层级 |
| `direction` | select | 否 | long | 交易方向：`long` / `short` |
| `symbol` | string | 是 | - | 交易对 |

> ⚠️ 马丁格尔策略风险较高，建议设置较小的 `max_levels` 并配合 `risk_filter.daily_max_loss` 使用。

---

## 3. 积木库参考

积木库分为四类：**指标**（Indicator）、**条件**（Condition）、**动作**（Action）、**事件**（Event）。每个积木通过 `kind` 标识，在 DSL 中以 `{kind, args}` 形式引用。

### 3.1 指标积木（Indicator）

指标用于计算某个数值（如最新价、RSI），供条件判断使用。

#### 行情·价格类

| kind | label | 说明 | 参数 |
|------|-------|------|------|
| `price_last` | 最新价 | 获取交易对的最新成交价 | `symbol`（string，必填） |
| `price_change_pct` | 涨跌幅 | 指定窗口内的价格涨跌幅（小数，0.05=5%） | `window`（select：1m/5m/15m/1h/4h/1d），`symbol`（string） |
| `volume_24h` | 24h成交量 | 24 小时成交量 | `symbol`（string） |

#### 行情·技术指标类

| kind | label | 说明 | 参数 |
|------|-------|------|------|
| `rsi` | RSI | RSI 相对强弱指标，返回 [0, 100] | `period`（int，如 14），`symbol`（string） |
| `macd` | MACD | MACD 柱状值（2*(DIF-DEA)） | `symbol`，`period_fast`（int，默认 12），`period_slow`（int，默认 26），`period_signal`（int，默认 9），`window` |
| `ema` | EMA均线 | 指数移动平均线 | `symbol`，`period`（int，默认 20），`window` |
| `kdj` | KDJ | KDJ 随机指标，返回 J 值 | `symbol`，`period`（int，默认 9），`window` |
| `volatility` | 波动率 | 收益率标准差 | `symbol`，`period`（int，默认 20），`window` |

#### 账户·持仓类

| kind | label | 说明 | 参数 |
|------|-------|------|------|
| `position_qty` | 持仓数量 | 获取交易对持仓量（正多负空） | `symbol`（string） |
| `position_pnl` | 持仓盈亏 | 持仓未实现盈亏（upl） | `symbol`（string） |
| `account_equity` | 账户净值 | 账户总净值（totalEq） | 无 |

#### 策略·内部状态类

| kind | label | 说明 | 参数 |
|------|-------|------|------|
| `realized_pnl` | 已实现盈亏 | 策略已实现盈亏 | 无 |
| `unrealized_pnl` | 未实现盈亏 | 未实现盈亏（优先用持仓 upl） | `symbol`（string，可选） |

指标引用示例：
```json
{
  "kind": "rsi",
  "args": {
    "period": 14,
    "symbol": "BTC-USDT"
  }
}
```

### 3.2 条件积木（Condition）

条件对指标值进行判断，返回布尔值。分为比较类、逻辑组合类、交叉类、区间类。

#### 比较类

| kind | label | 说明 | 参数 |
|------|-------|------|------|
| `gt` | 大于 | 指标值 > 阈值 | `indicator`（object，指标引用），`threshold`（number） |
| `lt` | 小于 | 指标值 < 阈值 | `indicator`，`threshold` |
| `abs_gt` | 绝对值大于 | |指标值| > 阈值 | `indicator`，`threshold` |
| `abs_lt` | 绝对值小于 | |指标值| < 阈值 | `indicator`，`threshold` |

#### 逻辑组合类

| kind | label | 说明 | 参数 |
|------|-------|------|------|
| `and` | 同时满足 | 所有子条件均为真 | `conditions`（array，子条件列表） |
| `or` | 任一满足 | 任一子条件为真 | `conditions`（array） |
| `not` | 取反 | 子条件取反 | `condition`（object，单个子条件） |

#### 交叉类

| kind | label | 说明 | 参数 |
|------|-------|------|------|
| `cross_above` | 上穿 | 指标 A 上穿指标 B（前 A<B，现 A>B） | `indicator_a`（object），`indicator_b`（object） |
| `cross_below` | 下穿 | 指标 A 下穿指标 B（前 A>B，现 A<B） | `indicator_a`，`indicator_b` |

#### 区间类

| kind | label | 说明 | 参数 |
|------|-------|------|------|
| `in_range` | 在区间内 | 指标值 ∈ [lower, upper] | `indicator`，`lower`（number），`upper`（number） |
| `out_range` | 在区间外 | 指标值 ∉ [lower, upper] | `indicator`，`lower`，`upper` |

条件引用示例：
```json
{
  "kind": "and",
  "args": {
    "conditions": [
      {
        "kind": "gt",
        "args": {
          "indicator": {"kind": "rsi", "args": {"period": 14, "symbol": "BTC-USDT"}},
          "threshold": 70
        }
      },
      {
        "kind": "gt",
        "args": {
          "indicator": {"kind": "price_last", "args": {"symbol": "BTC-USDT"}},
          "threshold": 50000
        }
      }
    ]
  }
}
```

### 3.3 动作积木（Action）

动作在规则触发时执行，产生实际效果（下单、撤单、记录等）。

#### 策略控制类

| kind | label | 说明 | 参数 |
|------|-------|------|------|
| `pause_orders` | 暂停挂单 | 撤挂单但保留持仓，调用 `on_pause` 钩子 | `symbol`（string，可选） |
| `resume_orders` | 恢复挂单 | 重新挂网格，调用 `on_resume` 钩子 | `symbol`（可选） |
| `hold_position` | 持有不动 | 保持当前持仓，仅记录事件 | 无 |

#### 持仓类

| kind | label | 说明 | 参数 |
|------|-------|------|------|
| `rebalance_position` | 调仓 | 再平衡持仓至理论持仓 | `symbol`（可选），`mode`（select：`to_theoretical`/`to_target`/`from_zero`），`target`（number，mode=to_target 时使用） |

#### 订单类

| kind | label | 说明 | 参数 |
|------|-------|------|------|
| `place_order` | 下单 | 下一笔订单（市价或限价） | `symbol`（string），`side`（select：buy/sell），`type`（select：market/limit），`qty`（number），`price`（number，限价必填） |
| `cancel_all` | 撤销全部 | 撤销指定交易对所有挂单 | `symbol`（可选） |

#### 通知类

| kind | label | 说明 | 参数 |
|------|-------|------|------|
| `log_event` | 记录事件 | 记录一条 DSL 事件到 StrategyEvent 表 | `level`（select：info/warn/error/critical），`message`（string），`details`（object，可选） |

#### 风控类

| kind | label | 说明 | 参数 |
|------|-------|------|------|
| `stop_loss` | 止损 | 持仓盈亏比例低于阈值时全部平仓 | `threshold`（number，小数如 -0.05 表示 -5%），`symbol`（可选） |
| `take_profit` | 止盈 | 持仓盈亏比例高于阈值时全部平仓 | `threshold`（number，小数如 0.1 表示 +10%），`symbol`（可选） |

#### 状态管理类

| kind | label | 说明 | 参数 |
|------|-------|------|------|
| `set_var` | 设置变量 | 写入策略级状态变量（跨 tick 持久） | `name`（string），`value`（any） |
| `get_var` | 获取变量 | 读取策略级状态变量 | `name`（string），`default`（any，可选） |

动作引用示例：
```json
{
  "kind": "place_order",
  "args": {
    "symbol": "BTC-USDT",
    "side": "buy",
    "type": "market",
    "qty": 0.001
  }
}
```

### 3.4 事件积木（Event）

事件用于驱动规则的触发。与条件不同，事件是「发生时才触发」的，而非每 tick 评估。

#### 行情·事件类

| kind | label | 说明 | 参数 |
|------|-------|------|------|
| `on_tick` | 行情更新 | 每个 tick 触发，返回当前时间戳与最新价 | `symbol`（string，可选） |
| `on_funding_rate` | 资金费率 | 资金费率超过阈值时触发（仅 swap） | `symbol`（可选），`threshold`（float，默认 0.001） |

#### 定时类

| kind | label | 说明 | 参数 |
|------|-------|------|------|
| `on_interval` | 定时触发 | 每隔 N 秒触发一次 | `seconds`（float，必填） |

#### 订单·事件类

| kind | label | 说明 | 参数 |
|------|-------|------|------|
| `on_order_filled` | 订单成交 | 订单成交时触发，可按 side/symbol 过滤 | `side`（select，可选），`symbol`（string，可选） |

#### 持仓·事件类

| kind | label | 说明 | 参数 |
|------|-------|------|------|
| `on_margin_warning` | 保证金预警 | 持仓保证金率低于阈值时触发 | `symbol`（string），`threshold`（float，默认 0.5） |
| `on_position_close` | 持仓平仓 | 持仓数量从非零变为零时触发 | `symbol`（可选） |

#### 账户·事件类

| kind | label | 说明 | 参数 |
|------|-------|------|------|
| `on_balance_change` | 余额变化 | 账户余额变化超过阈值时触发 | `threshold`（float，默认 0.01） |

#### 策略·生命周期类

| kind | label | 说明 | 参数 |
|------|-------|------|------|
| `on_strategy_error` | 策略异常 | 策略抛出异常时触发（一次性消费） | 无 |

事件引用示例：
```json
{
  "kind": "on_order_filled",
  "args": {
    "side": "buy",
    "symbol": "BTC-USDT"
  }
}
```

---

## 4. 变量引用机制

QS-Model 支持在 `logic` 段中使用变量引用，将 `params` 段定义的参数值动态注入到策略逻辑中。

### 4.1 引用语法

| 前缀 | 说明 | 示例 |
|------|------|------|
| `$params.` | 引用 params 段中定义的参数值 | `$params.upper_price` |
| `$meta.` | 引用 meta 段中定义的字段值 | `$meta.base_symbol` |

### 4.2 解析规则

- 变量引用必须是**字符串**且以 `$params.` 或 `$meta.` 开头
- 解析时会递归遍历 `logic` 段中所有值
- `$params.xxx` 优先使用实例创建时的参数覆盖值，否则用 `params` 段的默认值
- `$meta.xxx` 使用 `meta` 段对应的字段值
- 找不到引用时保持原字符串不变

### 4.3 使用示例

params 段定义：
```json
{
  "params": {
    "rsi_period": {"label": "RSI周期", "value": 14, "type": "int"},
    "oversold": {"label": "超卖阈值", "value": 30, "type": "int"}
  }
}
```

logic 段引用：
```json
{
  "logic": {
    "version": "1.0",
    "base_strategy": {
      "kind": "rsi_strategy",
      "params": {
        "period": "$params.rsi_period",
        "oversold": "$params.oversold",
        "symbol": "$meta.base_symbol"
      }
    },
    "rules": []
  }
}
```

解析后（使用默认值）：
```json
{
  "period": 14,
  "oversold": 30,
  "symbol": "BTC-USDT"
}
```

### 4.4 参数覆盖

创建策略实例时，可传入 `param_overrides` 覆盖默认值：

```json
{
  "rsi_period": 21,
  "oversold": 25
}
```

此时 `$params.rsi_period` 解析为 `21`，`$params.oversold` 解析为 `25`。

---

## 5. 风控配置

### 5.1 risk_filter 段字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `max_position_ratio` | float | 最大持仓比例（相对账户净值） |
| `daily_max_loss` | float | 每日最大亏损金额（达到后停止策略） |
| `min_trade_size` | float | 最小交易量（低于此值不下单） |
| `blacklist_hours` | array | 交易黑名单时段，如 `["23:00", "01:00"]` 表示 23:00-01:00 不交易 |
| `stop_loss` | float | 止损阈值（小数，如 -0.05 表示亏损 5% 时平仓） |
| `take_profit` | float | 止盈阈值（小数，如 0.1 表示盈利 10% 时平仓） |

### 5.2 风控触发方式

风控可通过两种方式生效：

1. **risk_filter 段**：在 QS-Model 中声明，由策略执行器在每个 tick 检查
2. **规则中使用风控动作**：在 `rules` 中使用 `stop_loss` / `take_profit` 动作积木

### 5.3 风控配置示例

```json
{
  "risk_filter": {
    "max_position_ratio": 0.5,
    "daily_max_loss": 500,
    "min_trade_size": 0.001,
    "blacklist_hours": ["23:30", "00:30"],
    "stop_loss": -0.05,
    "take_profit": 0.10
  }
}
```

### 5.4 规则中的风控动作示例

在规则中使用 `stop_loss` 动作（更灵活，可配合条件）：

```json
{
  "name": "动态止损",
  "when": {
    "mode": "condition",
    "condition": {
      "kind": "lt",
      "args": {
        "indicator": {"kind": "position_pnl", "args": {"symbol": "BTC-USDT"}},
        "threshold": -200
      }
    }
  },
  "then": [
    {"kind": "stop_loss", "args": {"threshold": -0.05, "symbol": "BTC-USDT"}}
  ],
  "cool_down_seconds": 60
}
```

---

## 6. 示例策略

### 6.1 BTC 现货网格策略

经典的等差网格策略，适合震荡市场。

```json
{
  "qs_model_version": "2.0",
  "meta": {
    "name": "BTC 现货网格",
    "version": "v1.0.0",
    "author": "QuantOKX",
    "description": "BTC-USDT 现货等差网格，区间 40000-50000，10 格",
    "asset_class": "CRYPTO",
    "frequency": "1m",
    "base_symbol": "BTC-USDT"
  },
  "params": {
    "upper_price": {"label": "价格上限", "value": 50000, "type": "float", "range": [30000, 80000], "unit": "USDT"},
    "lower_price": {"label": "价格下限", "value": 40000, "type": "float", "range": [20000, 60000], "unit": "USDT"},
    "grid_count": {"label": "网格数量", "value": 10, "type": "int", "range": [2, 50]},
    "order_qty": {"label": "单格数量", "value": 0.01, "type": "float", "range": [0.001, 1], "unit": "BTC"}
  },
  "logic": {
    "version": "1.0",
    "base_strategy": {
      "kind": "grid",
      "params": {
        "upper_price": "$params.upper_price",
        "lower_price": "$params.lower_price",
        "grid_count": "$params.grid_count",
        "order_qty": "$params.order_qty",
        "grid_mode": "arithmetic",
        "direction": "neutral",
        "symbol": "$meta.base_symbol"
      }
    },
    "rules": []
  },
  "risk_filter": {
    "daily_max_loss": 100,
    "stop_loss": -0.05,
    "take_profit": 0.10
  }
}
```

### 6.2 双均线趋势跟踪策略

5/20 双均线金叉做多、死叉做空。

```json
{
  "qs_model_version": "2.0",
  "meta": {
    "name": "双均线趋势",
    "version": "v1.0.0",
    "description": "5/20 双均线金叉死叉趋势跟踪",
    "frequency": "1h",
    "base_symbol": "BTC-USDT"
  },
  "params": {
    "fast_period": {"label": "快均线周期", "value": 5, "type": "int", "range": [1, 50]},
    "slow_period": {"label": "慢均线周期", "value": 20, "type": "int", "range": [5, 200]}
  },
  "logic": {
    "version": "1.0",
    "base_strategy": {
      "kind": "trend",
      "params": {
        "fast_period": "$params.fast_period",
        "slow_period": "$params.slow_period",
        "direction": "both",
        "bar": "1H",
        "symbol": "$meta.base_symbol"
      }
    },
    "rules": [
      {
        "name": "每日止损检查",
        "when": {
          "mode": "event",
          "event": {"kind": "on_interval", "args": {"seconds": 3600}}
        },
        "then": [
          {"kind": "stop_loss", "args": {"threshold": -0.05}},
          {"kind": "take_profit", "args": {"threshold": 0.15}}
        ],
        "cool_down_seconds": 300
      }
    ]
  },
  "risk_filter": {
    "daily_max_loss": 200,
    "stop_loss": -0.05
  }
}
```

### 6.3 RSI 超买超卖 + 止损止盈策略

RSI 超卖买入、超买卖出，配合止损止盈规则。

```json
{
  "qs_model_version": "2.0",
  "meta": {
    "name": "RSI 超买超卖",
    "version": "v1.0.0",
    "description": "RSI(14) 低于 30 买入，高于 70 卖出",
    "frequency": "15min",
    "base_symbol": "ETH-USDT"
  },
  "params": {
    "period": {"label": "RSI周期", "value": 14, "type": "int", "range": [6, 30]},
    "oversold": {"label": "超卖阈值", "value": 30, "type": "int", "range": [10, 45]},
    "overbought": {"label": "超买阈值", "value": 70, "type": "int", "range": [55, 90]}
  },
  "logic": {
    "version": "1.0",
    "base_strategy": {
      "kind": "rsi_strategy",
      "params": {
        "period": "$params.period",
        "oversold": "$params.oversold",
        "overbought": "$params.overbought",
        "direction": "both",
        "bar": "15m",
        "symbol": "$meta.base_symbol"
      }
    },
    "rules": [
      {
        "name": "止损-5%",
        "when": {
          "mode": "condition",
          "condition": {
            "kind": "lt",
            "args": {
              "indicator": {"kind": "position_pnl", "args": {"symbol": "ETH-USDT"}},
              "threshold": -50
            }
          }
        },
        "then": [
          {"kind": "stop_loss", "args": {"threshold": -0.05}},
          {"kind": "log_event", "args": {"level": "warn", "message": "触发止损"}}
        ],
        "cool_down_seconds": 60
      },
      {
        "name": "止盈+10%",
        "when": {
          "mode": "condition",
          "condition": {
            "kind": "gt",
            "args": {
              "indicator": {"kind": "position_pnl", "args": {"symbol": "ETH-USDT"}},
              "threshold": 100
            }
          }
        },
        "then": [
          {"kind": "take_profit", "args": {"threshold": 0.10}},
          {"kind": "log_event", "args": {"level": "info", "message": "触发止盈"}}
        ],
        "cool_down_seconds": 60
      }
    ]
  },
  "risk_filter": {
    "daily_max_loss": 100,
    "stop_loss": -0.05,
    "take_profit": 0.10
  }
}
```

### 6.4 布林带回归策略

价格跌破下轨买入、突破上轨卖出，回归中轨。

```json
{
  "qs_model_version": "2.0",
  "meta": {
    "name": "布林带回归",
    "version": "v1.0.0",
    "description": "布林带(20,2) 下轨买入、上轨卖出",
    "frequency": "1h",
    "base_symbol": "BTC-USDT"
  },
  "params": {
    "period": {"label": "计算周期", "value": 20, "type": "int", "range": [10, 50]},
    "std_mult": {"label": "标准差倍数", "value": 2.0, "type": "float", "range": [1.0, 3.5]}
  },
  "logic": {
    "version": "1.0",
    "base_strategy": {
      "kind": "bollinger_bands",
      "params": {
        "period": "$params.period",
        "std_multiplier": "$params.std_mult",
        "direction": "both",
        "bar": "1H",
        "symbol": "$meta.base_symbol"
      }
    },
    "rules": []
  },
  "risk_filter": {
    "daily_max_loss": 150,
    "stop_loss": -0.03,
    "take_profit": 0.06
  }
}
```

### 6.5 定投策略

每日定投 100 USDT 买入 BTC。

```json
{
  "qs_model_version": "2.0",
  "meta": {
    "name": "BTC 每日定投",
    "version": "v1.0.0",
    "description": "每日定投 100 USDT 买入 BTC",
    "frequency": "1d",
    "base_symbol": "BTC-USDT"
  },
  "params": {
    "amount": {"label": "每期金额", "value": 100, "type": "float", "range": [1, 10000], "unit": "USDT"},
    "frequency": {"label": "定投频率", "value": "daily", "type": "select", "options": ["daily", "weekly", "monthly"]}
  },
  "logic": {
    "version": "1.0",
    "base_strategy": {
      "kind": "dca",
      "params": {
        "amount": "$params.amount",
        "frequency": "$params.frequency",
        "symbol": "$meta.base_symbol"
      }
    },
    "rules": [
      {
        "name": "余额变化监控",
        "when": {
          "mode": "event",
          "event": {"kind": "on_balance_change", "args": {"threshold": 0.05}}
        },
        "then": [
          {"kind": "log_event", "args": {"level": "info", "message": "账户余额变化超过5%"}}
        ],
        "cool_down_seconds": 0
      }
    ]
  },
  "risk_filter": {
    "max_position_ratio": 0.8
  }
}
```

---

## 附录

### 规则（Rule）完整字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | string | 是 | 规则名称（唯一标识） |
| `when` | Trigger | 是 | 触发器 |
| `then` | array | 是 | 触发时执行的动作列表 |
| `recover_when` | Trigger | 否 | 恢复触发器 |
| `recover_then` | array | 否 | 恢复时执行的动作 |
| `cool_down_seconds` | float | 否 | 冷却时间（秒），0 表示无冷却 |

### Trigger 结构

| 字段 | 类型 | 说明 |
|------|------|------|
| `mode` | string | `condition`（每 tick 评估）或 `event`（仅事件发生时触发） |
| `condition` | ConditionRef | mode=condition 时的条件 |
| `event` | EventRef | mode=event 时的事件 |
| `extra_condition` | ConditionRef | mode=event 时可附加的额外条件 |

### K 线周期（bar）可选值

| 值 | 说明 |
|----|------|
| `1m` | 1 分钟 |
| `5m` | 5 分钟 |
| `15m` | 15 分钟 |
| `1H` | 1 小时 |
| `4H` | 4 小时 |
| `1D` | 1 天 |

> 注意：OKX bar 参数大小写敏感，分钟用小写 `m`，小时用大写 `H`，天用大写 `D`。

### 相关文档

- [用户使用指南](./user-guide.md)：安装、账户、策略运行等操作说明
- [DSL 执行器源码](../backend/dsl/executor.py)：ComposableStrategy 执行逻辑
- [积木库源码](../backend/dsl/blocks/)：各积木的实现细节
