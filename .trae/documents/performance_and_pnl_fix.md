# 性能优化与 PnL 数据修复计划

## 1. 根因分析

### PnL 为 0 的原因
策略循环（[grid_strategy.py](file:///e:/quant_okx/backend/strategies/grid_strategy.py#L196-L209)）依赖 `getBalance()` 获取 OKX 的 `upl`（未实现盈亏）和 `totalEq`（总权益）：
```
balances = client.get_balance()   ← OKX API 被墙 → 返回空
if balances:                      ← False
    ... record_pnl(...)           ← 从未执行！数据库无盈亏记录
```
**但实际不需要这个API！** 策略本地已有所有计算所需数据：
- 已实现盈亏：`self._realized_pnl`（内存中累计，行176-177的 `cycle_pnl`）
- 未实现盈亏：`∑(当前市价 - 买单价格) × 数量` —— 从 `active_buy_orders` + `grid_levels` 直接算
- 总权益：`初始权益 + 已实现盈亏 + 未实现盈亏`

### 慢的原因
- 仪表盘 `loadAssets()` → `getBalance()` 网络请求，15秒超时
- 策略循环中 `getBalance()` 同样被阻塞
- 账户管理/交易记录/策略监测是纯 SQLite 查询（毫秒级），但仪表盘加载时浏览器连接池可能被阻塞

---

## 2. 修改方案

### 2.1 本地计算未实现盈亏（核心修复）

**文件**: `backend/strategies/grid_strategy.py`

不调用 `getBalance()`，改为从活跃买单直接计算：

```python
# 替代原有的 getBalance() 调用块（行196-206）
# 计算未实现盈亏：活跃买单的 (current_price - buy_price) × qty
unrealized_pnl = 0.0
for idx, order_id in active_buy_orders.items():
    buy_price = grid_levels[idx]
    unrealized_pnl += (current_price - buy_price) * order_qty

realized_pnl = self.get_realized_pnl()
total_equity = self._initial_equity + realized_pnl + unrealized_pnl
self.record_pnl(total_equity, unrealized_pnl, realized_pnl)
```

**文件**: `backend/strategies/base_strategy.py`

新增 `_initial_equity` 字段，策略启动时记录初始权益：

```python
def __init__(self, ...):
    ...
    self._initial_equity = 0.0  # 策略启动时从 getBalance() 获取一次
```

### 2.2 修复 PnL 汇总计算 Bug

**文件**: `backend/routers/pnl.py`

`realized_pnl` 是累计值，取最新一条即可，不做 sum：

```python
# 修复前（错误）
total_realized = sum(r.realized_pnl or 0 for r in records)

# 修复后
total_realized = latest.realized_pnl or 0
```

### 2.3 仪表盘性能优化

**文件**: `frontend/src/pages/DashboardPage.tsx`

- 合并重复的 `listOrders`（当前调了两次 limit=10 和 limit=50，改为一次 limit=50）
- 资产卡片（`loadAssets`）改为非阻塞：首次加载时 KPI 卡片和曲线先显示（来自本地 SQLite 的 PnL 记录），资产余额延迟加载

**文件**: `backend/routers/accounts.py`

新增 `/api/accounts/{id}/balance/cached` 端点，从最近的 PnlRecord 返回缓存的权益数据，避免每次都请求 OKX。

### 2.4 前端加载骨架屏

**文件**: `frontend/src/pages/AccountsPage.tsx`、`OrdersPage.tsx`、`MonitoringPage.tsx`

添加脉冲动画占位块，加载期间显示骨架屏而非"暂无数据"。

---

## 3. 修改清单

| 文件 | 修改 | 类型 |
|------|------|------|
| `backend/strategies/grid_strategy.py` | 本地计算未实现盈亏，移除 getBalance 依赖 | Bug Fix |
| `backend/strategies/base_strategy.py` | 新增 `_initial_equity` 字段 | Enhancement |
| `backend/routers/pnl.py` | `sum(realized_pnl)` → `latest.realized_pnl` | Bug Fix |
| `backend/routers/accounts.py` | 新增 `/balance/cached` 端点 | Feature |
| `frontend/src/pages/DashboardPage.tsx` | 合并 orders 调用，资产卡片非阻塞 | Perf |
| `frontend/src/pages/AccountsPage.tsx` | 添加 loading 骨架屏 | UX |
| `frontend/src/pages/OrdersPage.tsx` | 添加 loading 骨架屏 | UX |
| `frontend/src/pages/MonitoringPage.tsx` | 添加 loading 骨架屏 | UX |

---

## 4. 验证

1. 策略启动后，即使 OKX 网络不通，日志中也能看到 `record_pnl` 调用（每3秒一次）
2. 仪表盘首次加载时 KPI 卡片快速出现（不再等 15 秒）
3. 盈亏曲线在策略启动约 3 秒后出现第一个数据点
4. 已实现盈亏 = 平仓收回 - 开仓投入（网格单次 = `(sell_px - buy_px) × qty`）
5. 未实现盈亏 = 剩余活跃买单的 `(current_price - buy_price) × qty` 之和
6. 账户管理/交易记录/策略监测页面有 loading 骨架屏