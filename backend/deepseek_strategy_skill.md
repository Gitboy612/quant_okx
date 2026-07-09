# 量化策略分类与参数体系 Skill

> **文档版本**：v1.0.0  
> **适用场景**：AI辅助策略开发、系统参数解析、策略模板生成  
> **策略覆盖**：信号驱动型（8类）+ 执行规则型（4类）+ 混合型（2类）

---

## 📑 目录

1. [策略分类总览](#一策略分类总览)
2. [信号驱动型策略](#二信号驱动型策略)
   - 2.1 双均线策略
   - 2.2 通道突破策略
   - 2.3 布林带策略
   - 2.4 RSI策略
   - 2.5 唐奇安通道策略
   - 2.6 成交量加权突破策略
   - 2.7 K线形态策略
   - 2.8 波动率策略
3. [执行规则型策略](#三执行规则型策略)
   - 3.1 网格策略
   - 3.2 马丁格尔策略
   - 3.3 反马丁格尔策略
   - 3.4 定投策略
4. [混合策略](#四混合策略)
   - 4.1 信号驱动网格
   - 4.2 趋势过滤马丁格尔
5. [参数维度总览](#五参数维度总览)
6. [AI集成示例](#六ai集成示例)
7. [策略类型速查表](#七策略类型速查表)

---

## 一、策略分类总览

```
┌─────────────────────────────────────────────────────────────────┐
│                      量化策略分类树                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────── 信号驱动型 (Signal-Driven) ──────────────┐  │
│  │  依赖价格/指标/统计特征，生成离散买卖信号                 │  │
│  │  包括：趋势跟踪、均值回归、突破动量、统计形态              │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                 │
│  ┌─────────────── 执行规则型 (Rule-Based) ──────────────────┐  │
│  │  依赖价格网格或区间，按预设机械规则执行                    │  │
│  │  包括：网格策略、马丁格尔策略、定投策略                   │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                 │
│  ┌─────────────── 混合策略 (Hybrid) ────────────────────────┐  │
│  │  信号决定方向，规则决定仓位管理                            │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 二、信号驱动型策略

### 2.1 双均线策略 (MA Crossover)

**核心逻辑**：短期均线上穿长期均线（金叉）做多，下穿（死叉）做空。

| 参数名 | 类型 | 默认值 | 范围 | 说明 |
|--------|------|--------|------|------|
| `fast_period` | int | 5 | [1, 50] | 快均线周期 |
| `slow_period` | int | 20 | [5, 200] | 慢均线周期 |
| `ma_type` | enum | "SMA" | ["SMA", "EMA", "WMA"] | 均线类型 |
| `direction` | enum | "both" | ["long", "short", "both"] | 交易方向 |

**信号逻辑**：
- 金叉（fast > slow 且上一根 ≤）→ 买入信号
- 死叉（fast < slow 且上一根 ≥）→ 卖出信号

---

### 2.2 通道突破策略 (Channel Breakout)

**核心逻辑**：价格突破近期最高价或最低价时，认为趋势启动。

| 参数名 | 类型 | 默认值 | 范围 | 说明 |
|--------|------|--------|------|------|
| `lookback_period` | int | 20 | [5, 100] | 回溯周期 |
| `entry_multiplier` | float | 0.0 | [0.0, 0.05] | 突破阈值加成（ATR倍数） |
| `exit_period` | int | 10 | [3, 50] | 离场回溯周期 |
| `direction` | enum | "both" | ["long", "short", "both"] | 交易方向 |
| `volume_filter` | float | 1.0 | [0.5, 3.0] | 成交量放大倍数（可选） |

**信号逻辑**：
- 价格 > 回溯期最高价 × (1 + entry_multiplier) → 做多
- 价格 < 回溯期最低价 × (1 - entry_multiplier) → 做空

---

### 2.3 布林带策略 (Bollinger Bands)

**核心逻辑**：价格触及下轨买入，触及上轨卖出，回归中轨平仓。

| 参数名 | 类型 | 默认值 | 范围 | 说明 |
|--------|------|--------|------|------|
| `period` | int | 20 | [10, 50] | 计算周期 |
| `std_multiplier` | float | 2.0 | [1.0, 3.5] | 标准差倍数 |
| `entry_lower` | float | 1.0 | [0.5, 2.0] | 下轨入场倍数 |
| `entry_upper` | float | 1.0 | [0.5, 2.0] | 上轨入场倍数 |
| `exit_mid` | bool | true | [true, false] | 是否回中轨平仓 |
| `direction` | enum | "both" | ["long", "short", "both"] | 交易方向 |

**信号逻辑**：
- 价格 < 下轨 × entry_lower → 买入信号
- 价格 > 上轨 × entry_upper → 卖出信号

---

### 2.4 RSI 策略

**核心逻辑**：RSI低于超卖线买入，高于超买线卖出。

| 参数名 | 类型 | 默认值 | 范围 | 说明 |
|--------|------|--------|------|------|
| `period` | int | 14 | [6, 30] | RSI 计算周期 |
| `oversold_threshold` | int | 30 | [10, 45] | 超卖阈值 |
| `overbought_threshold` | int | 70 | [55, 90] | 超买阈值 |
| `divergence_filter` | bool | false | [true, false] | 是否启用背离过滤 |
| `direction` | enum | "both" | ["long", "short", "both"] | 交易方向 |

**信号逻辑**：
- RSI < oversold_threshold → 买入信号
- RSI > overbought_threshold → 卖出信号

---

### 2.5 唐奇安通道策略 (Donchian Channel) — 海龟交易

**核心逻辑**：经典海龟交易法则，突破入场，反向突破离场。

| 参数名 | 类型 | 默认值 | 范围 | 说明 |
|--------|------|--------|------|------|
| `entry_period` | int | 20 | [10, 60] | 突破入场周期 |
| `exit_period` | int | 10 | [5, 30] | 离场周期 |
| `position_sizing` | enum | "fixed" | ["fixed", "atr_based"] | 仓位计算方式 |
| `risk_per_trade` | float | 0.02 | [0.005, 0.05] | 单笔风险资金占比 |
| `atr_period` | int | 14 | [7, 30] | ATR 计算周期 |
| `direction` | enum | "both" | ["long", "short", "both"] | 交易方向 |

**信号逻辑**：
- 价格突破 entry_period 最高价 → 开多
- 价格跌破 exit_period 最低价 → 平多

---

### 2.6 成交量加权突破策略

**核心逻辑**：价格突破配合成交量放大，确认突破有效性。

| 参数名 | 类型 | 默认值 | 范围 | 说明 |
|--------|------|--------|------|------|
| `lookback` | int | 20 | [5, 50] | 突破回溯周期 |
| `volume_threshold` | float | 1.5 | [1.0, 3.0] | 成交量放量倍数 |
| `volume_ma_period` | int | 5 | [3, 15] | 均量计算周期 |
| `direction` | enum | "both" | ["long", "short", "both"] | 交易方向 |

**信号逻辑**：
- 价格 > 前高 AND 当前量 > 均量 × volume_threshold → 做多

---

### 2.7 K线形态策略

**核心逻辑**：识别特定K线组合形态，结合位置发出交易信号。

| 参数名 | 类型 | 默认值 | 范围 | 说明 |
|--------|------|--------|------|------|
| `pattern_type` | enum | "engulfing" | ["engulfing", "hammer", "shooting_star", "doji", "morning_star"] | 形态类型 |
| `confirmation_bars` | int | 1 | [0, 3] | 确认所需后续K线数 |
| `trend_filter` | enum | "none" | ["none", "uptrend", "downtrend"] | 趋势过滤 |
| `trend_period` | int | 10 | [5, 30] | 趋势判断周期 |

---

### 2.8 波动率策略

**核心逻辑**：波动率处于极端低位时入场，预期波动率回归扩张。

| 参数名 | 类型 | 默认值 | 范围 | 说明 |
|--------|------|--------|------|------|
| `atr_period` | int | 14 | [7, 30] | ATR 计算周期 |
| `volatility_percentile` | float | 0.20 | [0.05, 0.50] | 低位波动率分位数 |
| `entry_trigger` | enum | "low_vol" | ["low_vol", "high_vol", "vol_expansion"] | 触发条件 |
| `direction` | enum | "both" | ["long", "short", "both"] | 交易方向 |

---

## 三、执行规则型策略

### 3.1 网格策略 (Grid Trading)

**核心逻辑**：在预设价格区间内等距或等比挂单，价格每穿越网格执行一次交易。

| 参数名 | 类型 | 默认值 | 范围 | 说明 |
|--------|------|--------|------|------|
| `upper_price` | float | 100.0 | [>lower] | 网格上限 |
| `lower_price` | float | 80.0 | [<upper] | 网格下限 |
| `grid_count` | int | 20 | [5, 200] | 网格数量 |
| `grid_mode` | enum | "arithmetic" | ["arithmetic", "geometric"] | 等差/等比 |
| `quantity_per_grid` | float | 0.001 | [>0] | 每格基础数量 |
| `quantity_mode` | enum | "fixed" | ["fixed", "progressive", "pyramid"] | 固定/递增/金字塔 |
| `direction` | enum | "neutral" | ["long", "short", "neutral"] | 交易方向 |
| `order_type` | enum | "limit" | ["limit", "market"] | 订单类型 |
| `grid_expand` | bool | false | [true, false] | 是否动态扩缩边界 |
| `max_position_ratio` | float | 0.5 | [0.1, 1.0] | 最大持仓比例 |

**价格计算公式**：
- 等差：`P_i = lower + i × (upper - lower) / grid_count`
- 等比：`P_i = lower × (upper / lower) ^ (i / grid_count)`

**执行规则**：
```
每格同时挂买入单和卖出单
价格从下往上穿 P_{i+1} → 执行卖出
价格从上往下穿 P_i → 执行买入
```

---

### 3.2 马丁格尔策略 (Martingale)

**核心逻辑**：亏损后加倍加仓，一次盈利覆盖全部亏损。

| 参数名 | 类型 | 默认值 | 范围 | 说明 |
|--------|------|--------|------|------|
| `initial_size` | float | 0.001 | [>0] | 初始交易数量 |
| `multiplier` | float | 2.0 | [1.1, 3.0] | 加仓倍数 |
| `price_step` | float | 0.5 | [>0] | 加仓价格间隔 |
| `max_levels` | int | 5 | [2, 20] | 最大加仓层级 |
| `take_profit` | float | 0.01 | [0.001, 0.05] | 整体止盈比例 |
| `stop_loss` | float | 0.05 | [0.01, 0.20] | 整体止损比例 |
| `direction` | enum | "long" | ["long", "short"] | 交易方向 |

**执行规则**：
```
级别0：P0 买入 size0
级别1：P0 - step 买入 size1 = size0 × multiplier
级别2：P0 - 2×step 买入 size2 = size1 × multiplier
...
整体止盈价 = (总成本 / 总数量) × (1 + take_profit)
```

---

### 3.3 反马丁格尔策略 (Anti-Martingale)

**核心逻辑**：盈利后加仓，亏损时减仓或止损。

| 参数名 | 类型 | 默认值 | 范围 | 说明 |
|--------|------|--------|------|------|
| `initial_size` | float | 0.001 | [>0] | 初始交易数量 |
| `multiplier` | float | 2.0 | [1.1, 3.0] | 盈利加仓倍数 |
| `win_steps` | int | 3 | [2, 10] | 连续盈利加仓步数 |
| `take_profit` | float | 0.02 | [0.005, 0.10] | 止盈比例 |
| `stop_loss` | float | 0.02 | [0.005, 0.10] | 止损比例 |

---

### 3.4 定投策略 (DCA)

**核心逻辑**：固定时间、固定金额买入，平摊成本。

| 参数名 | 类型 | 默认值 | 范围 | 说明 |
|--------|------|--------|------|------|
| `investment_amount` | float | 100.0 | [>0] | 每期投资金额 |
| `frequency` | enum | "daily" | ["daily", "weekly", "biweekly", "monthly"] | 定投频率 |
| `day_of_week` | int | 1 | [0, 6] | 每周第几天 |
| `day_of_month` | int | 1 | [1, 28] | 每月第几天 |
| `price_discount` | float | 0.0 | [0.0, 0.05] | 智能定投折扣 |
| `max_investment_ratio` | float | 0.3 | [0.1, 1.0] | 累计投资上限 |

---

## 四、混合策略

### 4.1 信号驱动网格策略

| 参数名 | 类型 | 默认值 | 范围 | 说明 |
|--------|------|--------|------|------|
| `signal_source` | enum | "rsi" | ["rsi", "ma", "macd", "boll"] | 方向信号源 |
| `signal_threshold` | float | 0.3 | [0.0, 1.0] | 信号强度阈值 |
| `grid_upper` | float | 100.0 | [>lower] | 网格上限 |
| `grid_lower` | float | 80.0 | [<upper] | 网格下限 |
| `grid_count` | int | 15 | [5, 100] | 网格数量 |
| `direction_mode` | enum | "signal_based" | ["signal_based", "long_only", "short_only"] | 方向模式 |

**逻辑**：信号多头时仅执行网格多头方向，信号空头时仅执行空头方向。

---

### 4.2 趋势过滤马丁格尔

| 参数名 | 类型 | 默认值 | 范围 | 说明 |
|--------|------|--------|------|------|
| `trend_ma_period` | int | 60 | [20, 200] | 趋势判断均线 |
| `martingale_multiplier` | float | 1.5 | [1.1, 2.5] | 加仓倍数 |
| `martingale_levels` | int | 4 | [2, 10] | 最大层级 |
| `stop_loss` | float | 0.05 | [0.01, 0.15] | 整体止损 |

**逻辑**：价格 > 均线时允许做多马丁格尔，价格 < 均线时允许做空马丁格尔。

---

## 五、参数维度总览

```
┌─────────────────────────────────────────────────────────────────┐
│                    策略可变参数维度                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  1. 时间维度 (Time)                                            │
│     ├── 周期参数: period, lookback, fast/slow                  │
│     └── 频率参数: frequency, 定时触发                          │
│                                                                 │
│  2. 价格维度 (Price)                                           │
│     ├── 阈值参数: upper, lower, 突破价                         │
│     ├── 幅度参数: multiplier, step, std_multiplier             │
│     └── 通道参数: 布林带/唐奇安通道边界                        │
│                                                                 │
│  3. 数量维度 (Quantity)                                        │
│     ├── 基础数量: initial_size, quantity_per_grid              │
│     ├── 比例参数: risk_per_trade, max_position_ratio           │
│     └── 递进参数: multiplier, 加仓系数                         │
│                                                                 │
│  4. 模式维度 (Mode)                                            │
│     ├── 计算方式: arithmetic/geometric, fixed/progressive      │
│     ├── 方向: long/short/both/neutral/signal_based             │
│     └── 订单类型: limit/market                                 │
│                                                                 │
│  5. 风控维度 (Risk Control)                                    │
│     ├── 止损: stop_loss                                        │
│     ├── 止盈: take_profit                                      │
│     ├── 层级: max_levels, grid_count                           │
│     └── 资金限制: max_position_ratio                           │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 六、AI集成示例

### 6.1 策略配置文件示例（网格策略）

```yaml
# ================================================================
#  策略配置文件示例：BTC_USDT 网格策略
# ================================================================

strategy_name: "BTC_USDT_Grid_Strategy"
strategy_type: "grid"
version: "1.0.0"
symbol: "BTCUSDT"

# █████████████████████████████████████████████████████████████████
#  可变参数
# █████████████████████████████████████████████████████████████████

params:
  upper_price:
    value: 65000
    type: float
    range: [30000, 100000]
    step: 500
    unit: "USD"
    description: "网格上限价格"

  lower_price:
    value: 55000
    type: float
    range: [30000, 100000]
    step: 500
    unit: "USD"
    description: "网格下限价格"

  grid_count:
    value: 25
    type: int
    range: [5, 200]
    description: "网格分割数量"

  grid_mode:
    value: "arithmetic"
    type: enum
    options: ["arithmetic", "geometric"]
    description: "等差：固定价差 | 等比：固定百分比"

  quantity_per_grid:
    value: 0.002
    type: float
    range: [0.0001, 1.0]
    step: 0.0001
    unit: "BTC"
    description: "每格基础挂单数量"

  quantity_mode:
    value: "fixed"
    type: enum
    options: ["fixed", "progressive", "pyramid"]
    description: "fixed:固定 | progressive:递增 | pyramid:金字塔递减"

  direction:
    value: "neutral"
    type: enum
    options: ["long", "short", "neutral"]
    description: "long:只做多 | short:只做空 | neutral:双向"

  max_position_ratio:
    value: 0.5
    type: float
    range: [0.1, 1.0]
    description: "最大持仓占资金比例"

# █████████████████████████████████████████████████████████████████
#  风控设置
# █████████████████████████████████████████████████████████████████

risk_control:
  max_drawdown: 0.15
  daily_loss_limit: 0.05
  min_trade_size: 0.001

# █████████████████████████████████████████████████████████████████
#  逻辑描述
# █████████████████████████████████████████████████████████████████

logic:
  description: |
    1. 根据上下限和网格数量计算每个网格价格
    2. 在每个网格价格挂买入单和卖出单
    3. 价格下跌穿越网格时买入，上涨穿越时卖出
    4. 达到最大持仓比例后停止开新仓
```

---

### 6.2 AI Prompt 模板

```
你是一个量化策略生成器，请根据以下要求生成策略配置文件：

【策略类型】: {strategy_type}
【交易标的】: {symbol}
【风险偏好】: {risk_profile}  # 保守/稳健/激进
【资金规模】: {capital}

请输出完整的 YAML 配置，包含：
1. 策略元信息
2. 所有可变参数（含类型、范围、默认值）
3. 逻辑伪代码
4. 风控参数
```

---

## 七、策略类型速查表

| 策略类型 | 英文标识 | 适合市场 | 风险等级 | 信号方式 | 核心参数数 |
|----------|----------|----------|----------|----------|-----------|
| 双均线 | ma_crossover | 趋势市 | 中 | 金叉死叉 | 3 |
| 通道突破 | channel_breakout | 强趋势 | 中高 | 突破信号 | 4 |
| 布林带 | bollinger_bands | 震荡市 | 中 | 触轨信号 | 5 |
| RSI | rsi_strategy | 震荡市 | 中 | 超买超卖 | 4 |
| 唐奇安 | donchian | 趋势市 | 高 | 突破信号 | 6 |
| 成交量突破 | volume_breakout | 趋势市 | 中高 | 量价确认 | 4 |
| K线形态 | pattern_recog | 任意 | 中 | 形态识别 | 4 |
| 波动率策略 | volatility_strat | 波动率回归 | 中 | 波动率极值 | 4 |
| **网格策略** | **grid_trading** | **震荡市** | **低中** | **机械挂单** | **8** |
| **马丁格尔** | **martingale** | **任意** | **极高** | **亏损加仓** | **7** |
| **反马丁格尔** | **anti_martingale** | **趋势市** | **中高** | **盈利加仓** | **5** |
| **定投** | **dca** | **长期慢牛** | **低** | **定时买入** | **5** |
| 信号网格 | hybrid_grid | 震荡市 | 中 | 信号+网格 | 6 |
| 趋势马丁 | hybrid_martingale | 趋势市 | 高 | 趋势过滤 | 4 |

---

## 📌 使用说明

1. **策略选择**：根据市场环境（趋势/震荡）和风险偏好选择策略类型
2. **参数配置**：参考各策略参数表，根据标的特征调整
3. **AI集成**：使用 6.2 中的 Prompt 模板让 AI 生成完整配置
4. **系统解析**：YAML 格式可直接被系统读取，渲染参数面板

---

*文档结束*