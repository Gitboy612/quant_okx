# Tasks

- [ ] Task 1: Order 表扩展字段与索引
  - [ ] SubTask 1.1: 在 `backend/models/order.py` 新增字段：`pnl_accounted: Boolean`(default=False, server_default="0")、`ct_val: Float`(nullable=True)、`ct_type: String`(nullable=True)、`settle_ccy: String`(nullable=True)、`actual_qty: Float`(nullable=True)
  - [ ] SubTask 1.2: 新增复合索引 `ix_orders_strategy_status_accounted` on `(strategy_instance_id, status, pnl_accounted)`
  - [ ] SubTask 1.3: 确认 `Base.metadata.create_all` 自动建表/加列；若 SQLite 不自动加列，提供一次性迁移脚本 `backend/migrations/add_order_pnl_fields.py`
  - [ ] SubTask 1.4: 为存量订单回填 `actual_qty`（合约用 `quantity × ct_val`，需查询 instrument；现货直接用 `quantity`）和 `pnl_accounted=False`

- [ ] Task 2: Instrument 元数据缓存服务
  - [ ] SubTask 2.1: 新增 `backend/services/instrument_cache.py`，实现 `InstrumentCache` 类（单例），按 instId 缓存 `{ctVal, ctType, settleCcy, tickSz, lotSz, minSz}`
  - [ ] SubTask 2.2: 实现 `async get_instrument(instId) -> dict`：缓存命中直接返回；未命中则根据 instId 后缀推断 instType（`-SWAP` → SWAP，`-USDT`/`-USD` → SPOT），调用 `OKXClient.get_instruments(instType, instId=instId)` 获取并缓存
  - [ ] SubTask 2.3: 网络异常或返回空时返回兜底值 `{ctVal: 1.0, ctType: None, settleCcy: None}`，记录 warn 日志，不抛异常
  - [ ] SubTask 2.4: 提供 `get_ct_val(instId) -> float` 同步快速访问（仅查缓存，未命中返回 1.0）

- [ ] Task 3: OrderManager 集成 instrument 注入
  - [ ] SubTask 3.1: `OrderManager.__init__` 接收 `InstrumentCache` 实例（可选，默认 None 时内部按需创建）
  - [ ] SubTask 3.2: `add_order` 方法在构造 `OrderInfo` 后，调用 `await instrument_cache.get_instrument(symbol)` 填充 ct_val/ct_type/settle_ccy，并计算 `actual_qty = float(sz) × ct_val`（合约）或 `float(sz)`（现货）
  - [ ] SubTask 3.3: `OrderInfo` dataclass 新增 `ct_val: float = 1.0`、`ct_type: str = ""`、`settle_ccy: str = ""`、`actual_qty: float = 0.0` 字段
  - [ ] SubTask 3.4: `_persist_to_db` 写入新字段到 Order 表
  - [ ] SubTask 3.5: `_update_position_on_filled` 改用 `actual_qty` 而非原始 `fillSz` 进行净持仓累加（关键修正：解决合约 quantity=10 实际 1 ETH 的错误）
  - [ ] SubTask 3.6: `load_from_db` 恢复时读取 ct_val/actual_qty 字段

- [ ] Task 4: PnLAccountingEngine 全量核算
  - [ ] SubTask 4.1: 新增 `backend/services/pnl_accounting_engine.py`，实现 `PnlAccountingEngine` 类（单例）
  - [ ] SubTask 4.2: 实现 `async recompute(strategy_instance_id) -> PnlSnapshot`：
    - 查询 Order 表 `strategy_instance_id=sid AND status='filled'`（忽略 canceled）
    - 按 side 分类：buy_orders, sell_orders
    - 计算 sell_total = Σ(sell.fillPx × sell.actual_qty)，buy_total = Σ(buy.fillPx × buy.actual_qty)
    - total_fee = Σ(所有 filled 的 fee)
    - total_pnl = sell_total - buy_total - total_fee
    - matched_qty = min(Σbuy.actual_qty, Σsell.actual_qty)
    - avg_buy_px = buy_total / Σbuy.actual_qty（若 0 则 0）
    - avg_sell_px = sell_total / Σsell.actual_qty（若 0 则 0）
    - avg_fee_per_unit = total_fee / (Σbuy.actual_qty + Σsell.actual_qty)（若 0 则 0）
    - realized_pnl = matched_qty × (avg_sell_px - avg_buy_px) - matched_qty × avg_fee_per_unit
    - unrealized_pnl = total_pnl - realized_pnl
    - net_position = Σbuy.actual_qty - Σsell.actual_qty
  - [ ] SubTask 4.3: 写入一条 PnlRecord（equity 用初始权益 + total_pnl，标记 is_final=False）
  - [ ] SubTask 4.4: 将该策略所有 filled 订单 `pnl_accounted` 批量更新为 True
  - [ ] SubTask 4.5: 返回 PnlSnapshot dataclass（realized/unrealized/total/equity/net_position/avg_buy_px/order_count）

- [ ] Task 5: PnLAccountingEngine 增量核算
  - [ ] SubTask 5.1: 实现 `async incremental_update(strategy_instance_id) -> PnlSnapshot | None`：
    - 查询 Order 表 `strategy_instance_id=sid AND status='filled' AND pnl_accounted=False`
    - 若无新增订单，返回 None（不写空记录）
  - [ ] SubTask 5.2: 读取该策略最新一条 PnlRecord（按 recorded_at desc）作为基准：
    - base_realized = latest.realized_pnl or 0
    - base_net_position = latest.unrealized 相关累计（需在 PnlRecord 新增 `net_position`/`avg_buy_price` 字段，见 Task 6）
    - 若无 latest，base 全为 0
  - [ ] SubTask 5.3: 用新增订单更新累计值：
    - 新增 buy：累加 buy_qty、buy_value，更新 avg_buy_price，net_position +=
    - 新增 sell：扣减 net_position，若 net_position 归零或反向，realized_pnl += 闭环盈亏
    - 累加 fee
  - [ ] SubTask 5.4: 获取当前价格（调用 client.get_ticker），计算 unrealized_pnl = (current_price - avg_buy_price) × net_position - 预估手续费
  - [ ] SubTask 5.5: total_pnl = realized_pnl + unrealized_pnl，写入新 PnlRecord
  - [ ] SubTask 5.6: 将新增订单批量标记 pnl_accounted=True

- [ ] Task 6: PnlRecord 表扩展
  - [ ] SubTask 6.1: 在 `backend/models/pnl.py` 新增字段：`net_position: Float`(nullable=True)、`avg_buy_price: Float`(nullable=True)、`total_fee: Float`(nullable=True)、`order_count: Integer`(nullable=True)
  - [ ] SubTask 6.2: 修改 `BaseStrategy.record_pnl` / `record_final_pnl` 接受新字段并写入（保持向后兼容，旧调用默认 None）
  - [ ] SubTask 6.3: PnlAccountingEngine 写入时填充全部新字段，支撑增量核算基准读取

- [ ] Task 7: StrategyEngine 集成定时采样任务
  - [ ] SubTask 7.1: 在 `StrategyEngine` 新增 `_pnl_sampling_task: asyncio.Task | None`，`start()` 时启动，`aclose()` 时取消
  - [ ] SubTask 7.2: 采样任务循环：`while True: await asyncio.sleep(60); for sid in get_running_ids(): await pnl_engine.incremental_update(sid)`
  - [ ] SubTask 7.3: 增量核算返回 None（无新成交）时跳过写库；返回快照时按 `_should_record_pnl` 降频判断（变化阈值或 60s 间隔）决定是否写
  - [ ] SubTask 7.4: 策略停止时 `stop_strategy` 调用 `pnl_engine.incremental_update` 后再 `record_final_pnl`，确保终值准确
  - [ ] SubTask 7.5: 启动时检查 running 策略（重启后内存丢失），对所有 status='running' 的实例先执行一次 `recompute` 重建基准（pnl_accounted 已标记的跳过）

- [ ] Task 8: 策略层 PnL 计算逻辑移除
  - [ ] SubTask 8.1: `GridStrategy.execute()` 移除 [grid_strategy.py:338-369] 的 unrealized_pnl 计算 + `_should_record_pnl` + `record_pnl` 块（保留 `consecutive_errors` 重置与 sleep）
  - [ ] SubTask 8.2: `TrendStrategy.execute()` 移除 [trend_strategy.py:143-161] 的同上块
  - [ ] SubTask 8.3: `AdvancedGridHedgeStrategy.execute()` 移除 [advanced_grid_hedge_strategy.py:108-114] 的同上块
  - [ ] SubTask 8.4: `ArbitrageStrategy.execute()` 移除 [arbitrage_strategy.py:70] 的 `record_pnl(total_equity, 0, 0)` 占位调用
  - [ ] SubTask 8.5: `BaseStrategy` 保留 `_should_record_pnl` / `record_pnl` / `record_final_pnl` 方法（供引擎复用），但在 docstring 标注"由 PnlAccountingEngine 调用，策略不应直接调用"
  - [ ] SubTask 8.6: 策略保留 `add_realized_pnl`（成交回调累加），仅用于实时内存显示，不写库

- [ ] Task 9: PnL API 扩展
  - [ ] SubTask 9.1: `backend/routers/pnl.py` 新增 `POST /api/pnl/recompute/{strategy_id}`：调用 `pnl_engine.recompute`，返回 PnlSnapshot
  - [ ] SubTask 9.2: 新增 `POST /api/pnl/snapshot`：对所有 running 策略触发一次 `incremental_update`
  - [ ] SubTask 9.3: `GET /api/pnl/summary` 的 by_strategy 增加 `net_position`、`avg_buy_price`、`order_count` 字段（从最新 PnlRecord 读取）
  - [ ] SubTask 9.4: `GET /api/pnl` 列表响应增加 `net_position`、`avg_buy_price`、`total_fee`、`order_count` 字段
  - [ ] SubTask 9.5: 前端 `api/pnl.ts` 新增 `recomputePnl(strategyId)`、`snapshotPnl()` 函数

- [ ] Task 10: 前端合约交易量单位选择器
  - [ ] SubTask 10.1: `StrategiesPage.tsx` 在 symbol 含 `-SWAP` 时显示"交易量单位"下拉（options: 张数/目标币/稳定币，默认张数）
  - [ ] SubTask 10.2: 单位为"目标币"时，提交前调用 `GET /api/market/instrument?instId=` 获取 ctVal，前端计算 `sz = input / ctVal`，order_qty 存 sz
  - [ ] SubTask 10.3: 单位为"稳定币"时，需实时价格，`sz = input / current_price / ctVal`；价格获取失败时提示错误
  - [ ] SubTask 10.4: 策略参数表单展示时，若 `params.sz_fields` 存在，回显原始输入值与单位
  - [ ] SubTask 10.5: 新增 `GET /api/market/instrument?instId=` 后端端点（包装 InstrumentCache.get_instrument）

- [ ] Task 11: 单元测试与验证
  - [ ] SubTask 11.1: 测试全量核算：构造 10 笔 filled 订单（5 buy + 5 sell），验证 total_pnl / realized_pnl / unrealized_pnl 计算正确
  - [ ] SubTask 11.2: 测试增量核算：首次 recompute 后新增 3 笔 filled，验证 incremental_update 仅处理新增且累计值正确
  - [ ] SubTask 11.3: 测试合约 actual_qty：构造 SWAP 订单 sz=10 ct_val=0.1，验证 actual_qty=1.0，净持仓按 1.0 累加
  - [ ] SubTask 11.4: 测试 InstrumentCache：首次调用查 API，第二次命中缓存，网络异常返回兜底值
  - [ ] SubTask 11.5: 测试定时采样：mock 两个 running 策略，验证 60s 后各自 incremental_update 被调用
  - [ ] SubTask 11.6: 测试策略停止时 record_final_pnl 调用 incremental_update 后写入 is_final=True
  - [ ] SubTask 11.7: 测试 recompute API 端点返回正确 PnlSnapshot
  - [ ] SubTask 11.8: 验证 ComposableStrategy 运行时不再需要自行写 PnL（引擎采样覆盖）

# Task Dependencies
- Task 2（InstrumentCache）独立，可与 Task 1 并行
- Task 3（OrderManager 注入）依赖 Task 2（需 InstrumentCache）+ Task 1（需新字段）
- Task 6（PnlRecord 扩展）独立，可与 Task 1 并行
- Task 4（全量核算）依赖 Task 1（Order 新字段）+ Task 6（PnlRecord 新字段）
- Task 5（增量核算）依赖 Task 4（复用计算逻辑）+ Task 6（读取基准）
- Task 7（采样任务）依赖 Task 5（调用 incremental_update）
- Task 8（策略移除 PnL）依赖 Task 7（引擎采样已就绪，避免空窗期）
- Task 9（API）依赖 Task 4 + Task 5
- Task 10（前端单位选择器）依赖 Task 2（InstrumentCache 端点）
- Task 11（测试）依赖所有功能 Task 完成

# 修复任务（验证 checklist 后发现未通过项）

- [ ] Task 12: 启动时执行 recompute 重建 PnL 基准
  - 说明：checklist G 部分第 4 项「启动时对 status='running' 的实例先执行一次 recompute 重建基准」未通过
  - 现状：`StrategyEngine.rebuild_pnl_baselines()` 方法已实现（`backend/services/strategy_engine.py:90-135`），但 `backend/main.py` 的 `startup()` 中未调用该方法；且 startup() 会将 running/paused 实例统一改写为 stopped（line 72-79），导致服务重启后无 running 实例可供 recompute
  - 修复建议：明确产品策略——
    - 方案 A（保留重启即停）：删除该 checklist 项或将其标记为 N/A（方法已具备能力，但因业务策略不会触发）
    - 方案 B（恢复运行）：startup 不再强制改 running→stopped，改为异步调用 `await strategy_engine.rebuild_pnl_baselines()`（需把 startup 改为 async 或用 asyncio.create_task）
  - 关联文件：`backend/main.py:49-99`、`backend/services/strategy_engine.py:90-135`

- [ ] Task 13: 补充单元测试覆盖 K 部分剩余 4 项
  - 说明：checklist K 部分第 5-8 项未通过，现有 `backend/tests/test_pnl_accounting_engine.py` 仅覆盖 7 个测试用例
  - SubTask 13.1: 测试定时采样任务调用 incremental_update（mock 两个 running 策略，验证 60s 后各自 incremental_update 被调用）
  - SubTask 13.2: 测试策略停止时终值写入（验证 stop_strategy 先 incremental_update 再 record_final_pnl，且 is_final=True）
  - SubTask 13.3: 测试 recompute API 端点返回正确 PnlSnapshot（用 FastAPI TestClient 调用 POST /api/pnl/recompute/{strategy_id}）
  - SubTask 13.4: 验证 ComposableStrategy 运行时盈亏曲线能正常绘制（端到端集成测试，需启动一个 ComposableStrategy 实例并检查 PnlRecord 时序数据可被前端图表消费）
  - 关联文件：`backend/tests/test_pnl_accounting_engine.py`、`backend/services/strategy_engine.py`、`backend/routers/pnl.py`
