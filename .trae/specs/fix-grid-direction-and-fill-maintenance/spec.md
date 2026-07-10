# 网格策略方向与成交维护修复 Spec

## Why

用户报告网格策略（QSModel + GridBlock）三个问题：
1. 设置 `direction=long`（做多）后启动仍是中性网格，无初始持仓
2. 买单成交后不挂对应卖单，订单越来越少（"挂完就不管了"）
3. 80 格的策略任意时刻应维持 80 个委托单

经代码分析，根因是对"做多网格"的理解分歧 + 成交检测不可靠。

---

### 问题 A：direction="long" 实现错误——做多网格未建立初始持仓

**用户理解（正确）**：做多网格 = 所有网格档位都挂买单
- 当前价下方的档位：挂限价买单（等待下跌成交）
- 当前价上方的档位：限价买单立即成交（等效市价买入）→ **建立初始多头持仓**
- 每笔买单成交后 → 在上一格挂卖单（止盈）
- 卖单成交后 → 在下一格重新挂买单（重新入场）
- 任意时刻维持约 N 个委托单（买单+卖单）

**当前实现（错误）**：[bases.py:189-202](file:///e:/New%20folder%20(2)/quant_okx/backend/dsl/blocks/bases.py#L189-L202)
```python
place_buy = self.direction in ("long", "neutral")
place_sell = self.direction in ("short", "neutral")
for i, level in enumerate(self.levels):
    if level < current_price and place_buy:      # 低于现价才挂买单
        buy_orders.append(...)
    elif level > current_price and place_sell:   # 高于现价才挂卖单
        sell_orders.append(...)
```

当 `direction="long"` 时 `place_sell=False`，高于现价的档位**不挂任何单**。结果：
- 只在现价下方挂买单（约 N/2 个），现价上方无单
- 无初始持仓（中性起步）
- 与 neutral 模式仅有的区别是少了上方的卖单 → 更像是"只买不卖"而非"做多网格"

**做空网格同理**：应在所有档位挂卖单，低于现价的卖单立即成交建立空头持仓。

---

### 问题 B：成交后反向挂单失效——订单越来越少

GridBlock 的 `on_order_filled` 逻辑本身正确（买单成交→挂卖单，卖单成交→挂买单），但**成交检测不可靠**：

1. **GridBlock.on_tick 为空**（[bases.py:369-372](file:///e:/New%20folder%20(2)/quant_okx/backend/dsl/blocks/bases.py#L369-L372)）：不包含任何 REST 轮询逻辑，完全依赖 WebSocket `filled` 事件回调
2. **ComposableStrategy 主循环无订单状态同步**（[executor.py:324-413](file:///e:/New%20folder%20(2)/quant_okx/backend/dsl/executor.py#L324-L413)）：只刷新价格+调 on_tick+FSM 转换，不检查订单成交状态
3. **WebSocket 断连时成交丢失**：项目记忆记录了频繁网络问题，WebSocket 断连时 `filled` 回调不触发 → 反向挂单不执行 → 委托单只减不增

**对比旧 GridStrategy**（[grid_strategy.py:314-333](file:///e:/New%20folder%20(2)/quant_okx/backend/strategies/grid_strategy.py#L314-L333)）：有 REST 轮询兜底（每 15 秒检查订单状态），即使 WebSocket 断连也能检测成交。

---

### 问题 C：缺少重启订单恢复

旧 GridStrategy 启动时调 `sync_orders(symbol)` 从 DB 恢复活跃订单（[grid_strategy.py:196-220](file:///e:/New%20folder%20(2)/quant_okx/backend/strategies/grid_strategy.py#L196-L220)），GridBlock 无此逻辑——重启后不恢复已有挂单，导致重复下单或订单丢失。

## What Changes

### A. 修复 direction 语义
- **做多网格（long）**：所有档位挂买单，高于现价的立即成交建立多头持仓
- **做空网格（short）**：所有档位挂卖单，低于现价的立即成交建立空头持仓
- **双向网格（neutral）**：维持当前逻辑（现价下买单、上卖单）
- 成交后反向挂单逻辑：long 模式买单成交→上方挂卖单（止盈），卖单成交→下方重新挂买单；short 模式对称

### B. GridBlock.on_tick 增加 REST 轮询兜底
- 每个 tick 检查 OrderManager 活跃订单的 OKX 实际状态
- 状态从 live→filled 时触发 `update_order` + `on_order_filled` 回调
- 复用旧 GridStrategy 的 REST 轮询逻辑

### C. 启动时恢复活跃订单
- GridBlock.on_start 先从 DB 同步已有活跃订单到 `active_buy`/`active_sell`
- 只为缺失的档位补挂新单

- **BREAKING**: direction 语义变更，long/short 模式行为改变（建立初始持仓）

## Impact
- Affected specs: `fix-pnl-realized-unrealized-consistency`（已实现盈亏计算依赖成交回调）、`add-composable-strategy-dsl`（GridBlock 定义）
- Affected code:
  - `backend/dsl/blocks/bases.py`：GridBlock `_place_grid_orders`、`on_order_filled`、`on_start`、`on_tick`
  - `backend/dsl/executor.py`：ComposableStrategy 主循环可能需要传递 REST 轮询所需依赖

## ADDED Requirements

### Requirement: 做多网格建立初始多头持仓
系统 SHALL 在 direction="long" 时，在所有网格档位挂买单，高于当前价的档位立即成交建立初始多头持仓。

#### Scenario: 做多网格初始下单
- **WHEN** direction="long" 且策略启动
- **THEN** 所有 N 个网格档位都挂买单
- **AND** 低于当前价的档位：限价买单（等待成交）
- **AND** 高于当前价的档位：限价买单立即成交（等效市价买入）
- **AND** 成交后在该档位上方一格挂卖单（止盈）

#### Scenario: 做多网格成交循环
- **WHEN** 做多网格中买单成交
- **THEN** 在 `grid_idx + 1` 档位挂卖单
- **AND** 卖单成交后在 `grid_idx - 1` 档位重新挂买单
- **AND** 任意时刻维持约 N 个委托单（买单+卖单）

### Requirement: 做空网格建立初始空头持仓
系统 SHALL 在 direction="short" 时，在所有网格档位挂卖单，低于当前价的档位立即成交建立初始空头持仓。

#### Scenario: 做空网格初始下单
- **WHEN** direction="short" 且策略启动
- **THEN** 所有 N 个网格档位都挂卖单
- **AND** 高于当前价的档位：限价卖单（等待成交）
- **AND** 低于当前价的档位：限价卖单立即成交（等效市价卖出）
- **AND** 成交后在该档位下方一格挂买单（止盈）

### Requirement: 双向网格维持中性
系统 SHALL 在 direction="neutral" 时，维持当前行为：现价下方挂买单、上方挂卖单。

#### Scenario: 双向网格初始下单
- **WHEN** direction="neutral" 且策略启动
- **THEN** 低于当前价的档位挂限价买单
- **AND** 高于当前价的档位挂限价卖单
- **AND** 不建立初始持仓

### Requirement: GridBlock REST 轮询成交兜底
系统 SHALL 在 GridBlock.on_tick 中定期检查活跃订单的 OKX 实际状态，WebSocket 断连时仍能检测成交。

#### Scenario: REST 轮询检测成交
- **WHEN** on_tick 执行且距上次 REST 检查 ≥ 15 秒
- **THEN** 遍历 OrderManager 活跃订单
- **AND** 调用 `client.get_order(symbol, ordId)` 查询实际状态
- **AND** 状态从 live→filled 时调用 `order_manager.update_order` 触发 `on_order_filled` 回调

#### Scenario: WebSocket 断连时仍维护网格
- **WHEN** WebSocket 断连且订单成交
- **THEN** REST 轮询在 15 秒内检测到成交
- **AND** 触发反向挂单
- **AND** 委托单数量不减少

### Requirement: 启动时恢复已有活跃订单
系统 SHALL 在 GridBlock.on_start 时先从 DB 同步已有活跃订单，只为缺失档位补挂新单。

#### Scenario: 重启后恢复挂单
- **WHEN** 策略重启且 DB 中已有活跃订单
- **THEN** 从 DB 查询 status="live" 的订单
- **AND** 按价格匹配到对应网格档位
- **AND** 填充 `active_buy`/`active_sell` 字典
- **AND** 只为未恢复的档位补挂新单

## MODIFIED Requirements

### Requirement: GridBlock _place_grid_orders
[原实现] 现价下方挂买单、上方挂卖单（neutral 逻辑），direction 仅控制是否允许买/卖。
[修改为] 按 direction 语义：
- long：所有档位挂买单（含高于现价的，立即成交）
- short：所有档位挂卖单（含低于现价的，立即成交）
- neutral：维持原逻辑

### Requirement: GridBlock on_order_filled
[原实现] 买单成交→grid_idx+1 挂卖单；卖单成交→grid_idx-1 挂买单。
[补充] long 模式卖单成交后重新挂买单（而非仅在 grid_idx-1）；short 模式买单成交后重新挂卖单。确保委托单数量守恒。

## REMOVED Requirements
无。
