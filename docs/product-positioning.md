# QuantOKX 产品差异化定位文档

> 本文档用于明确 QuantOKX 在量化交易工具市场中的差异化定位，提炼核心卖点并指导前端展示。
> 所有卖点均基于已实现的真实能力，引用具体功能文件位置，不夸大。

---

## 一、平台一句话定位

**QuantOKX 是一款面向 OKX 交易所的本地优先量化交易平台——以可视化策略积木、真实仓位隔离归因与多策略资金风控为核心差异化，让交易者在不泄露 API Key 的前提下，掌控多策略同品种的真实盈亏与风险。**

核心关键词：本地优先 · 仓位隔离归因 · 可视化积木 · 回测即实盘 · 网格突发行情响应

---

## 二、vs FMZ / Coinrule 差异化对比矩阵

> 说明：本矩阵基于公开信息与本平台已实现能力整理，力求真实。竞品能力可能随版本演进，仅作横向参照。

| 能力维度 | QuantOKX（本平台） | FMZ（fmz.com） | Coinrule（web.coinrule.com） |
|----------|--------------------|----------------|------------------------------|
| 部署形态 | **本地优先**：本地 uvicorn 服务 + SQLite，API Key 仅本地 AES 加密存储 | 云端托管 Robot 为主（可自建 Docker），API Key 配置于平台 | 云端 SaaS，API Key 托管于云端 |
| API Key 隐私 | **不上传服务器**，本地 `data/quant_okx.db` 加密保存 | 默认云端托管（自建 Docker 可本地化） | 云端托管 |
| 策略构建方式 | **可视化 DSL 积木库**（指标/条件/动作/事件四类）+ QS-Model 四段式配置 | 纯代码（JavaScript / Python / C++ / 麦语言） | 无代码 if-then 规则 |
| 多策略同品种仓位隔离归因 | **真实隔离**：每策略独立虚拟持仓 + 净持仓均价 + 已实现盈亏独立核算，并通过 `reconcile_positions` 与交易所真实持仓对账 | 无独立虚拟仓位概念，策略间持仓共享 | 无（规则级，无仓位归因） |
| 仓位对账机制 | **有**：虚拟持仓合计 vs 真实持仓，差异超容差触发告警 | 无 | 无 |
| 回测引擎 | **历史 K 线回测**（网格/趋势），含滑点、手续费、最大回撤、夏普、胜率 | 支持回测（代码级） | 基本无回测（规则前向执行） |
| 回测参数 → 实盘对齐 | **一键导出为实例**：回测参数直接生成实盘策略实例 | 需手动迁移参数 | 无回测，无需对齐 |
| 投入资金上限风控 | **有**：`check_capital_limit` 按 `investment_amount × lever` 校验总名义价值 | 依赖策略代码自行实现 | 规则级仓位限制 |
| 杠杆设置 | **有**：合约 `lever` / `td_mode` 自动 `set_leverage` | 需策略代码调用 | 平台级简单设置 |
| 保证金监控 | **有**：`check_margin_risk` 节流检查保证金占用率，>0.80 告警 / >0.95 拒单 | 依赖策略代码 | 无 |
| 仓位冲突检测 | **有**：`check_position_conflict` 平仓前校验"真实持仓 - 其他策略占用"是否充足 | 无（多策略共享持仓易冲突） | 无 |
| 网格突发行情响应 | **事件驱动 + 波动率快速路径**：`_check_volatility_spike` 触发 `_rapid_realign_grid` 批量撤重挂 | 依赖策略代码 | 无 |
| 交易所覆盖 | **单交易所 OKX**（现货 + 永续合约） | 多交易所（OKX/Binance/Huobi 等） | 多交易所 |
| 策略市场 / 社区 | 模板导入导出（JSON 文件），无在线市场 | 有在线策略广场与社区 | 有规则模板库 |
| 通知渠道 | 邮件 / Webhook / Telegram | 邮件 / Webhook / Telegram / 微信 | 邮件 / App 推送 |

---

## 三、核心差异化卖点（基于已实现能力）

### 卖点 1：本地优先隐私——API Key 本地加密，不上传服务器

- **能力**：平台以本地 uvicorn 服务运行，数据库为本地 SQLite（`data/quant_okx.db`），所有 OKX API Key 使用 AES 加密存储，绝不上传任何外部服务器。
- **实现位置**：`docs/user-guide.md` 第 2.1 节"所有 API Key 均使用 AES 加密存储"；启动方式 `uvicorn backend.main:app`（本地）。
- **对比**：FMZ 默认将 Robot 托管于云端、API Key 配置于平台；Coinrule 为云端 SaaS，Key 完全托管。本平台让注重资产安全的交易者完全掌控密钥。

### 卖点 2：真实仓位隔离归因——多策略同品种各自 PnL 独立 + 虚拟仓位对账

- **能力**：每个策略实例维护独立的虚拟持仓（`net_position` / `avg_buy_price` / `realized_pnl`），通过 PnL 核算引擎实现全量核算（`recompute`）、增量核算（`incremental_update`）与心跳快照（`heartbeat_snapshot`）。同账户同品种多策略时，聚合虚拟持仓与交易所真实持仓对账（`reconcile_positions`），差异超容差自动告警。
- **实现位置**：
  - `backend/strategies/base_strategy.py`：`get_virtual_position()`、`_get_current_position_value()`
  - `backend/services/pnl_accounting_engine.py`：`PnlAccountingEngine.recompute` / `incremental_update` / `heartbeat_snapshot` / `reconcile_positions`
- **对比**：FMZ 无独立虚拟仓位概念，多策略同品种持仓共享，难以区分各策略真实贡献；Coinrule 为规则级执行，无仓位归因。本平台是少数能对"多策略跑同一币种"做精确盈亏归因与对账的平台。

### 卖点 3：可视化策略构建——DSL 积木库拖拽式配置

- **能力**：策略以 QS-Model v2.0 四段式结构（meta / params / logic / risk_filter）描述，`logic` 段由积木（Block）拼接：指标（`price_last` / `rsi` / `macd` / `position_pnl` 等）、条件（`gt` / `cross_above` / `in_range` 等）、动作（`place_order` / `cancel_all` / `stop_loss` 等）、事件（`on_tick` / `on_order_filled` / `on_margin_warning` 等）。无需写代码即可组合策略。
- **实现位置**：
  - `backend/dsl/blocks/`：`indicators.py` / `conditions.py` / `actions.py` / `events.py` / `bases.py`
  - `docs/strategy-writing-guide.md` 第 3 章"积木库参考"
- **对比**：FMZ 为纯代码（JavaScript/Python），学习门槛高；Coinrule 虽无代码但仅支持简单 if-then 规则，无法表达均线交叉、网格、马丁等复合策略。本平台在"无代码"与"完整策略能力"之间取得平衡。

### 卖点 4：回测即实盘参数对齐——回测参数一键导出实盘

- **能力**：回测引擎基于真实历史 K 线（OKX `/api/v5/market/history-candles`）按时间重放，支持滑点与手续费，输出总收益率 / 最大回撤 / 夏普比率 / 胜率 / 盈亏比。回测满意后可一键导出为策略实例，参数与实盘完全对齐。
- **实现位置**：
  - `backend/services/backtest_engine.py`：`BacktestEngine.run_backtest` / `MatchingEngine` / `compute_metrics`
  - `docs/user-guide.md` 第 5.4 节"导出为实例"
- **对比**：Coinrule 基本无回测能力，规则直接前向执行，无法在历史区间验证表现；FMZ 回测与实盘参数迁移需手动处理。本平台打通"回测→实盘"参数链路。

### 卖点 5：完善的多层风控——资金上限 + 杠杆 + 保证金监控 + 仓位冲突检测

- **能力**：四道风控闸门保障多策略安全运行：
  1. **投入资金上限**：`check_capital_limit` 按 `investment_amount × lever` 校验总名义价值，超限拒单
  2. **合约杠杆设置**：`_apply_leverage_settings` 启动时自动 `set_leverage`
  3. **保证金监控**：`check_margin_risk` 节流检查保证金占用率，>0.80 告警、>0.95 拒单
  4. **仓位冲突检测**：`check_position_conflict` 平仓前校验"真实持仓 − 其他策略虚拟占用"是否充足，避免多策略互相平掉对方仓位
- **实现位置**：`backend/strategies/base_strategy.py`：`check_capital_limit` / `place_order_with_capital_check` / `_apply_leverage_settings` / `check_margin_risk` / `check_position_conflict` / `close_position_with_conflict_check`
- **对比**：FMZ 的风控完全依赖策略代码自行实现，多策略同品种易互相冲突；Coinrule 仅有规则级仓位限制，无保证金/冲突检测。本平台将多策略风控下沉到基类，开箱即用。

### 卖点 6：网格突发行情响应——事件驱动 + 波动率快速路径

- **能力**：网格策略采用事件驱动架构：WebSocket 订单成交回调（`_on_order_filled`）实时补单、行情 ticker 订阅实时更新。当波动率超阈值（`volatility_threshold`）时触发快速路径：批量撤单并基于新价位快速重挂网格（`_rapid_realign_grid`），抑制补单回调避免抖动。
- **实现位置**：`backend/strategies/grid_strategy.py`：`_on_ticker_update` / `_on_order_filled` / `_check_volatility_spike`（SubTask 8.2）/ `_rapid_realign_grid`（SubTask 8.3）
- **对比**：FMZ 网格响应完全依赖策略代码轮询逻辑；Coinrule 无网格策略与突发行情处理。本平台为网格策略做了专门的突发行情优化。

---

## 四、适用人群与场景

### 适用人群

| 人群 | 适用度 | 典型诉求 |
|------|--------|----------|
| 个人量化交易者（OKX 用户） | ★★★★★ | 本地掌控 API Key、多策略跑同币种、精确盈亏归因 |
| 注重资产安全的交易者 | ★★★★★ | 不愿将 API Key 托管云端、要求本地加密存储 |
| 震荡/网格策略玩家 | ★★★★☆ | 网格突发行情快速重挂、保证金监控防强平 |
| 希望无代码构建策略的交易者 | ★★★★☆ | DSL 积木拖拽组合，无需写 Python/JS |
| 合约杠杆风控需求者 | ★★★★☆ | 投入资金上限 + 杠杆 + 保证金三层防护 |
| 多交易所套利/跨平台用户 | ★★☆☆☆ | 本平台仅支持 OKX，需另选工具 |

### 适用场景

- **场景一：多策略跑同一币种**——例如对 BTC-USDT 同时跑网格 + 趋势 + 马丁，需各自独立盈亏归因与仓位隔离，避免互相干扰。
- **场景二：合约风控严格**——永续合约多策略运行，需要投入资金上限、保证金占用率监控、仓位冲突检测三重防护。
- **场景三：回测验证再实盘**——先在历史区间回测网格/趋势策略，参数调优后一键导出实盘实例。
- **场景四：API Key 不外传**——机构或个人不信任云端托管，要求所有密钥本地加密。
- **场景五：突发行情应对**——网格策略在剧烈波动时自动快速重挂，避免挂单滞后。

---

## 五、局限性诚实说明

为保持文档真实，以下局限需明确告知：

1. **单交易所**：当前仅支持 OKX（现货 + 永续合约），不支持 Binance / Huobi / Bybit 等其他交易所。跨所套利场景需另选工具。
2. **无在线策略市场**：仅支持模板 JSON 文件本地导入导出，无 FMZ 式在线策略广场与社区共享。
3. **无云端托管**：平台为本地优先架构，需用户自备可运行 Python 3.11+ 的机器并保持开机，无云端 7×24 托管能力。
4. **回测策略类型有限**：回测引擎当前支持 grid / trend（arbitrage 占位复用 trend），RSI / 布林带 / 唐奇安 / 定投 / 马丁等策略的回测尚未独立实现。
5. **单用户/本地账户体系**：默认管理员账号 `admin/admin123`，面向单用户本地部署，非多租户 SaaS。
6. **DSL 积木库仍在完善**：积木库已实现核心指标/条件/动作/事件，但部分高级积木（如多腿组合订单、跨品种价差指标）尚在演进中。
7. **沙箱模式无滑点与流动性模拟**：沙箱使用实时行情但不触发真实下单，实盘表现可能与沙箱有差异。

---

## 六、前端展示指引

核心卖点需在前端（登录页）以"平台亮点"区域展示，详见 `frontend/src/pages/LoginPage.tsx`。展示原则：

- 列 4–6 个核心卖点（图标 + 简短中文文案）
- 复用现有设计风格（glass-card / `#00D4AA` 主色 / motion 动画 / lucide-react 图标）
- 不破坏登录页现有布局与登录表单
- 文案对应本文档第三章卖点

---

## 附录：相关文档与代码索引

| 主题 | 文件位置 |
|------|----------|
| 用户使用指南 | `docs/user-guide.md` |
| 策略编写指南 | `docs/strategy-writing-guide.md` |
| 策略基类（风控/仓位隔离） | `backend/strategies/base_strategy.py` |
| PnL 核算与对账 | `backend/services/pnl_accounting_engine.py` |
| 回测引擎 | `backend/services/backtest_engine.py` |
| 网格策略（突发行情） | `backend/strategies/grid_strategy.py` |
| DSL 积木库 | `backend/dsl/blocks/` |
| 登录页（卖点展示） | `frontend/src/pages/LoginPage.tsx` |
