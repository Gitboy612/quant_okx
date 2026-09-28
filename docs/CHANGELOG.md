# QuantOKX 修改日志

## 2026-09-28

### P0：账户 PnL 聚合、零基线、订单幂等与恢复状态

对应 `docs/ss-project-pnl-order-attribution-development.md` §4 P0：

1. **账户总盈亏**改为各策略最新有效快照之和（`sum(latest_by_strategy)`），不再取全局最近一条。
2. **新建策略零基线**：无成交时 `heartbeat_snapshot` 只返回内存零快照，不再写入全零 `PnlRecord`。
3. **clOrdId 幂等**：下单前生成客户端订单号并透传 OKX；超时后按 `clOrdId` 查询；`OrderManager` 按 `ordId`/`clOrdId` 去重落库。
4. **total_pnl 不变量**：统一经 `compose_total_pnl(realized, unrealized)` 计算。
5. **恢复状态机基础**：新增 `desired_status`；启动时标记 `recovering` 并对账孤儿订单，不再盲目改成 `stopped`；列表接口返回 `runtime_status` / `status_drift`。

## 2026-07-23

### 修复：React 页面刷新返回 404

#### 问题表现

- 在应用内部点击“仪表盘”“策略管理”等菜单可以正常切换。
- 浏览器位于 `/dashboard`、`/strategies` 等页面时刷新，FastAPI 返回：

  ```json
  {"detail":"Not Found"}
  ```

- 后端日志出现 `GET /dashboard HTTP/1.1 404 Not Found`。

#### 根本原因

前端使用 React `BrowserRouter`，页面路径由浏览器 History API 管理。应用内部切换页面时不会重新请求 HTML；刷新时浏览器会直接向 FastAPI 请求当前页面路径。

原实现使用 `StaticFiles(html=True)` 挂载 `frontend/dist`。该组件会查找真实文件或目录中的 `index.html`，但不会把 `/dashboard` 等客户端路由自动回退到根目录 `index.html`，因此刷新返回 404。

#### 修改内容

- 新增 `backend/spa_static.py`：
  - 对 `/dashboard`、`/strategies/123` 等无扩展名的前端页面路径返回根目录 `index.html`。
  - `/api/*`、`/ws/*` 和 `/assets/*` 不参与 SPA fallback。
  - 缺失的 `.js`、`.css`、图片、图标等资源保持 404，避免错误地返回 HTML。
  - 支持 `GET` 和 `HEAD` 请求。
- `backend/main.py` 改用 `SPAStaticFiles` 挂载前端构建目录。
- 新增 `backend/tests/test_spa_static.py`，覆盖页面刷新、嵌套路由、API、静态资源、缺失文件和 HEAD 请求。

#### 行为变化

| 请求 | 修改前 | 修改后 |
| --- | --- | --- |
| `GET /` | 返回 `index.html` | 不变 |
| `GET /dashboard` | 404 JSON | 返回 `index.html`，由 React 渲染 Dashboard |
| `GET /strategies` | 404 JSON | 返回 `index.html`，由 React 渲染 Strategies |
| `GET /api/不存在` | 404 JSON | 保持 404 JSON |
| `GET /assets/不存在.js` | 404 | 保持 404 |

#### 影响范围

只影响前端 History API 页面路径的静态文件响应，不修改账户、策略、订单、PnL、WebSocket 或 OKX 交易逻辑。

#### 验证结果

- `backend/tests/test_spa_static.py`：`7 passed`。
- 前端 `npm run build` 构建成功。
- 运行中服务验证：
  - `GET /dashboard`：`200 text/html`
  - `GET /strategies`：`200 text/html`
  - `HEAD /dashboard`：`200 text/html`
  - `GET /api/not-found`：保持 `404 application/json`
  - `GET /assets/not-found.js`：保持 `404 application/json`
- 浏览器直接打开并刷新 `/dashboard` 后能够加载 Q-Studio；无登录会由 React 跳转到 `/login`，不再显示 FastAPI 的 `{"detail":"Not Found"}`。

构建仍会提示本机 Node.js `20.18.0` 低于 Vite 建议的 `20.19+`，以及已有 CSS/大包体积警告；本次构建成功，这些警告与 SPA 路由修复无关。

## 2026-07-24

### 修复：策略管理与策略监测状态不同步

#### 问题表现

- 策略在管理页启动、暂停或停止后，已打开的监测页仍可能显示旧状态。
- 策略执行任务已经结束时，数据库仍可能保留 `running` 或 `paused`。
- 没有真实内存任务时，暂停/恢复接口仍可能写入状态，形成“假运行”。
- 暂停或停止已经显示成功，但订单异步撤销和落库可能尚未完成。

#### 修改内容

- `frontend/src/hooks/useStrategiesState.ts`
  - 策略管理页每 5 秒刷新策略实例。
  - 页面重新获得焦点或从后台切回时立即刷新。
- `frontend/src/pages/MonitoringPage.tsx`
  - 策略监测页每 5 秒刷新策略实例、健康指标和仓位数据。
  - 已删除或切换账户后不可见的选中策略会自动清除。
- `backend/services/strategy_engine.py`
  - 增加真实运行任务检查。
  - 执行任务正常结束时自动回写 `stopped`。
  - 执行任务异常退出时自动回写 `error`。
  - 没有真实任务时拒绝暂停和恢复。
  - 暂停和停止等待撤单清理完成后再更新状态。
- `backend/routers/strategies.py`
  - 增加启动、暂停、恢复的状态转换校验。
- `backend/strategies/base_strategy.py`
  - 合约杠杆设置失败时终止启动，避免继续显示 `running`。
  - 暂停/停止等待订单撤销与最终盈亏记录。
- `backend/strategies/grid_strategy.py`
  - 批量下单与暂停/停止撤单使用生命周期锁，避免交叉执行。
- `backend/services/order_manager.py`
  - 增加异步订单持久化等待与最终一致性写入。
- 新增 `backend/tests/test_strategy_state_sync.py`。

#### 验证结果

- 状态同步、策略引擎、参数更新、PnL 算法和保证金相关测试通过。
- 网格与趋势策略端到端生命周期测试通过。
- 相关回归共 `58 passed`。
- 前端 TypeScript 生产构建成功。

### 修复：仓位隔离对账误显示为“运行中”

#### 问题表现

- 只有一个策略运行时，仓位隔离对账仍显示三个交易对。
- 对账成功的记录被显示成绿色“运行中”，容易被误认为对应策略都在运行。
- 监测页面没有按照顶部选中的账户限制数据范围。

#### 根本原因

- 前端对全部策略实例（包括 `stopped`）的 `(account_id, symbol)` 发起对账。
- “对账一致”和“可平仓”错误复用了策略状态 `running` 的徽章。

#### 修改内容

- 仓位对账只包含 `running` 和 `paused` 策略。
- 监测页策略、健康、仓位与下拉列表按照顶部选中账户过滤。
- 新增“对账一致”和“可平仓”语义状态，不再复用“运行中”。

#### 验证结果

- 数据库核对：策略 `#1`、`#2` 为 `stopped`，策略 `#3` 为 `running`。
- 前端 TypeScript 生产构建成功。
- 前端静态检查通过；剩余提示均为项目已有警告。

### 修复：趋势策略不下单、假成功记录与低频参数写死

#### 问题表现

- 趋势策略运行后持续获取行情，但长期没有订单。
- K 线周期固定为 `5m`、主循环固定为 `60s`，前端无法调整交易灵敏度。
- 策略只检查 Python 请求是否返回，没有检查 OKX 外层 `code` 和单笔订单
  `sCode`，下单被交易所拒绝时仍可能继续按成功路径执行。
- 下单成功响应中的交易所 `ordId` 没有传入订单管理器，市场单也会被错误地
  按 `limit` 类型落库。
- 启动可行性检查没有识别 OKX 简单账户模式不支持永续合约，导致检查显示
  “通过”，真正下单时才返回 `51010`。

#### 修改内容

- `backend/strategies/trend_strategy.py`
  - 新增 `bar`、`poll_interval`、`enter_on_start` 和
    `closed_candle_only` 运行参数及校验。
  - 修复新旧均线参数兼容读取时的默认值提前求值问题。
  - 均线计算至少要求 `slow_period + 1` 根 K 线。
  - 默认只处理已完成 K 线，并按 K 线时间戳去重，避免同一根 K 线重复下单。
  - 支持无虚拟持仓时按当前趋势首次入场。
  - 同时检查 OKX 外层 `code`、单笔 `sCode` 与 `ordId`；拒单写入
    `order_rejected`，不再生成假订单。
  - 成功下单后保存交易所返回的真实 `ordId`，并以 `live` 状态交给
    WebSocket 后续更新。
  - 策略重启时恢复最新已实现盈亏、虚拟净持仓和平均持仓价。
- `backend/services/order_manager.py`
  - `OrderInfo` 新增真实订单类型，市场单按 `market` 落库，不再硬编码
    `limit`。
- `backend/strategies/base_strategy.py`
  - 登记活动订单时向订单管理器传递真实订单类型。
- `backend/services/strategy_engine.py`
  - 趋势策略模板增加上述四个可配置字段。
  - 永续合约启动前读取 OKX `acctLv`；简单模式（`acctLv=1`）直接阻止启动并
    给出明确提示。
- 新增 `backend/tests/test_trend_strategy_runtime.py`，并扩展
  `backend/tests/test_strategy_engine_clients.py`。

#### 当前模拟策略参数

策略 `#3 [OKX-DEMO] BTC 合约趋势` 已更新为：

| 参数 | 值 |
| --- | --- |
| 交易对 | `BTC-USDT-SWAP` |
| 快线 / 慢线 | `2 / 5` |
| K 线周期 | `1m` |
| 轮询间隔 | `15s` |
| 单笔数量 | `0.01` 张 |
| 启动时按当前趋势入场 | 开启 |
| 仅使用已完成 K 线 | 开启 |
| 杠杆 / 保证金模式 | `1x / cross` |

#### 实盘式模拟验证

- 项目可行性检查首次返回：当前价约 `64020.1`，估算保证金约 `$640.2`，
  模拟账户可用 `$5000`。
- 策略成功创建真实内存任务并进入 `running`，1 分钟 K 线正常持续拉取。
- 首次趋势信号为 `SELL`，OKX 模拟盘返回：
  `code=1 / sCode=51010 / current account mode`。
- 修复后的代码将其正确记录为 `order_rejected`，`orders` 表没有生成假订单。
- 进一步读取账户配置确认：`acctLv=1`、`posMode=net_mode`，根因是 OKX
  简单模式不支持永续合约，并非均线没有触发。
- 为避免继续产生必然失败的请求，策略已安全停止；当前状态为 `stopped`。
- OKX 模拟盘复核：`BTC-USDT-SWAP` 当前活动持仓 `0`、未成交委托 `0`。
- 现在再次点击启动时，可行性检查会在下单前阻止并提示先调整 OKX 模拟盘
  账户模式。

#### 验证结果

- 趋势参数、信号、OKX 响应校验、订单类型、策略状态同步、客户端生命周期与
  模拟盘趋势生命周期相关测试：`25 passed`。
- 测试只有项目已有的 Starlette/httpx 弃用提示和未注册 timeout 标记提示，
  无测试失败。

## 2026-07-26

### 优化：三条模拟策略产生测试交易

#### 目标

- 保留现有三条策略类型：
  - `#1 [OKX-DEMO] BTC 现货网格`
  - `#2 [OKX-DEMO] ETH 现货网格`
  - `#3 [OKX-DEMO] BTC 合约趋势`
- 在 OKX 模拟账户中产生可核对的委托和成交，用于订单、策略状态和 PnL 测试。
- 防止测试开关在服务重启后反复产生市价单。

#### 账户与安全检查

- OKX 账户：`Test01`，`trade_mode=demo`。
- 账户模式已切换为 `acctLv=3`（跨币种保证金）。
- 持仓模式为 `long_short_mode`。
- 优化前已停止运行中的策略、撤销旧网格委托，并确认无活动合约持仓。

#### 代码修改

- `backend/services/okx_client.py`
  - 单笔下单支持可选 `posSide`、`reduceOnly` 和 `tgtCcy`。
  - 未使用可选参数时保持原有请求结构。
- `backend/strategies/trend_strategy.py`
  - 启动时读取 OKX `posMode`。
  - `long_short_mode` 下按信号与虚拟仓位传递正确的 `long`/`short`
    `posSide`，修复 OKX `51000 Parameter posSide error`。
  - 增加活动订单 REST 兜底同步，避免市价单成交早于 WebSocket 回调而长期
    停留在 `live`。
  - 现货市价单使用 `tgtCcy=base_ccy`，使数量统一按基础币解释。
  - 增加 `long_only` 参数；空仓时跳过做空信号，避免当前只支持多头 FIFO
    的策略级 PnL 把空头平均开仓价当成 0。
- `backend/strategies/grid_strategy.py`
  - 增加 `demo_test_order_on_start`：仅 OKX 模拟盘允许，启动时提交一次小额
    现货市价买单。
  - 测试单被 OKX 接受后自动将开关持久化为 `false`，防止重启重复下单。
  - 初始网格登记完成后再发送测试单，避免快速成交回调和初始网格并发生成
    重复相邻订单。
  - 完整校验测试单的 OKX `code`、`sCode` 与 `ordId`。
- `backend/services/order_manager.py`
  - 从数据库恢复活动订单时同时按 `account_id` 和
    `strategy_instance_id` 过滤，修复同账户三条策略互相读取订单的问题。
- `backend/services/strategy_engine.py`
  - 网格模板暴露一次性模拟测试单开关。
  - 趋势模板暴露“仅做多”开关。
  - 趋势慢线最小周期由 5 调整为 3，允许灵敏的 `2/3` 测试配置。

#### 当前策略参数

| 策略 | 关键测试参数 |
| --- | --- |
| BTC 现货网格 | 区间 `64456.87–64650.53`、7 格、每格 `0.0001 BTC`、REST 兜底 1 秒 |
| ETH 现货网格 | 区间 `1879.64–1885.28`、7 格、每格 `0.001 ETH`、REST 兜底 1 秒 |
| BTC 合约趋势 | `2/3` 均线、`1m` K 线、10 秒轮询、每次 `0.01` 张、仅做多 |

两个网格的区间按照配置时实时价格约 `±0.15%` 设置；价格明显离开区间时需要
重新居中，不能把该固定区间长期当成生产参数。

#### 模拟盘成交验证

- BTC 现货网格：
  - 一次性市价买单成交；
  - 中心网格买单成交；
  - 累计验证 `2` 笔 filled，当前保留 `6` 笔活动窄网格委托。
- ETH 现货网格：
  - 一次性市价买单成交；
  - 买卖网格发生完全成交和部分成交；
  - 累计验证 `4` 笔 filled，当前保留 `6` 笔活动窄网格委托。
- BTC 合约趋势：
  - 修复后 SELL 市价单以 `posSide=short` 成交；
  - 随后的 BUY 市价单正确平空；
  - 额外完成空仓清理单，累计数据库中 `4` 笔 filled；
  - 当前外部合约持仓为 0，实例使用 `long_only=true` 等待下一次买入信号。

三条策略最终状态均为 `running`。最新策略级 PnL：

| 策略 | 净仓位 | 已实现 PnL | 未实现 PnL |
| --- | ---: | ---: | ---: |
| BTC 现货网格 | 0 | 0 | 0 |
| ETH 现货网格 | 0 | -0.0025 | 0 |
| BTC 合约趋势 | 0 | -0.007241 | 0 |

上述小额亏损主要来自模拟成交价差和手续费，符合测试单预期。

#### 验证结果

- 参数、OKX 响应、双向持仓 `posSide`、现货数量单位、趋势 REST 订单同步、
  订单实例隔离、状态同步及网格/趋势生命周期：`38 passed`。
- 仅存在项目已有的 Starlette/httpx 弃用提示和未注册 timeout 标记提示。
