# Checklist

## A. Order 表扩展
- [x] Order 模型新增 `pnl_accounted: Boolean` 字段，default=False, server_default="0"
- [x] Order 模型新增 `ct_val: Float` 字段（nullable=True）
- [x] Order 模型新增 `ct_type: String` 字段（nullable=True）
- [x] Order 模型新增 `settle_ccy: String` 字段（nullable=True）
- [x] Order 模型新增 `actual_qty: Float` 字段（nullable=True）
- [x] 新增复合索引 `(strategy_instance_id, status, pnl_accounted)`
- [x] 存量订单 actual_qty 已回填（合约查 instrument，现货用 quantity）
- [x] 存量订单 pnl_accounted 默认为 False

## B. PnlRecord 表扩展
- [x] PnlRecord 模型新增 `net_position: Float` 字段
- [x] PnlRecord 模型新增 `avg_buy_price: Float` 字段
- [x] PnlRecord 模型新增 `total_fee: Float` 字段
- [x] PnlRecord 模型新增 `order_count: Integer` 字段
- [x] `record_pnl` / `record_final_pnl` 接受并写入新字段（向后兼容）

## C. Instrument 元数据缓存
- [x] `backend/services/instrument_cache.py` 已创建
- [x] `InstrumentCache` 为单例，按 instId 缓存 {ctVal, ctType, settleCcy, tickSz}
- [x] 缓存未命中时调用 `get_instruments` 并写入缓存
- [x] 网络异常或返回空时返回兜底值 {ctVal: 1.0}，不抛异常
- [x] `get_ct_val(instId)` 同步快速访问方法已实现

## D. OrderManager 集成
- [x] `OrderManager.__init__` 接收 InstrumentCache 实例
- [x] `OrderInfo` dataclass 新增 ct_val/ct_type/settle_ccy/actual_qty 字段
- [x] `add_order` 填充合约元数据并计算 actual_qty = sz × ct_val（合约）或 sz（现货）
- [x] `_persist_to_db` 写入新字段到 Order 表
- [x] `_update_position_on_filled` 使用 actual_qty 而非 fillSz 累加净持仓
- [x] `load_from_db` 恢复时读取 actual_qty

## E. PnLAccountingEngine - 全量核算
- [x] `backend/services/pnl_accounting_engine.py` 已创建
- [x] `recompute(strategy_instance_id)` 查询所有 filled 订单（忽略 canceled）
- [x] sell_total = Σ(sell.fillPx × sell.actual_qty)
- [x] buy_total = Σ(buy.fillPx × buy.actual_qty)
- [x] total_fee = Σ(所有 filled 的 fee)
- [x] total_pnl = sell_total - buy_total - total_fee
- [x] matched_qty = min(Σbuy.actual_qty, Σsell.actual_qty)
- [x] realized_pnl = matched_qty × (avg_sell_px - avg_buy_px) - matched_qty × avg_fee_per_unit
- [x] unrealized_pnl = total_pnl - realized_pnl
- [x] net_position = Σbuy.actual_qty - Σsell.actual_qty
- [x] 写入 PnlRecord 并填充全部新字段
- [x] 批量更新 filled 订单 pnl_accounted=True
- [x] 返回 PnlSnapshot dataclass

## F. PnLAccountingEngine - 增量核算
- [x] `incremental_update` 查询 status='filled' AND pnl_accounted=False
- [x] 无新增订单时返回 None（不写空记录）
- [x] 读取最新 PnlRecord 作为基准（realized/net_position/avg_buy_price）
- [x] 新增 buy 订单累加 buy_qty/buy_value，更新 avg_buy_price，net_position +=
- [x] 新增 sell 订单扣减 net_position，闭环时累加 realized_pnl
- [x] 获取当前价格计算 unrealized_pnl = (current_price - avg_buy_price) × net_position - 预估手续费
- [x] 写入新 PnlRecord，标记新增订单 pnl_accounted=True

## G. StrategyEngine 集成
- [x] 启动时创建 `_pnl_sampling_task`，每 60s 对 running 策略调用 incremental_update
- [x] 增量返回 None 时跳过写库
- [x] 策略停止时先 incremental_update 再 record_final_pnl
- [x] 启动时对 status='running' 的实例先执行一次 recompute 重建基准
- [x] `aclose()` 时取消采样任务

## H. 策略层 PnL 移除
- [x] GridStrategy.execute() 移除 unrealized 计算 + record_pnl 块
- [x] TrendStrategy.execute() 移除同上块
- [x] AdvancedGridHedgeStrategy.execute() 移除同上块
- [x] ArbitrageStrategy.execute() 移除 record_pnl 占位调用
- [x] BaseStrategy 保留 _should_record_pnl/record_pnl/record_final_pnl 供引擎复用
- [x] 策略保留 add_realized_pnl（仅内存实时显示）

## I. PnL API 扩展
- [x] `POST /api/pnl/recompute/{strategy_id}` 端点已实现
- [x] `POST /api/pnl/snapshot` 端点已实现
- [x] `GET /api/pnl/summary` by_strategy 增加 net_position/avg_buy_price/order_count
- [x] `GET /api/pnl` 列表响应增加新字段
- [x] 前端 `api/pnl.ts` 新增 recomputePnl/snapshotPnl 函数

## J. 前端合约交易量单位选择器
- [x] StrategiesPage 合约类型显示"交易量单位"下拉
- [x] "目标币"单位提交时调用 instrument 接口获取 ctVal 并转换 sz
- [x] "稳定币"单位提交时获取实时价格转换 sz，失败时提示错误
- [x] 策略参数回显时正确显示原始输入值与单位
- [x] `GET /api/market/instrument` 端点已实现

## K. 单元测试
- [x] 测试全量核算：10 笔 filled（5 buy + 5 sell）计算正确
- [x] 测试增量核算：recompute 后新增 3 笔，incremental_update 累计正确
- [x] 测试合约 actual_qty：sz=10 ct_val=0.1 → actual_qty=1.0
- [x] 测试 InstrumentCache 缓存命中与兜底
- [x] 测试定时采样任务调用 incremental_update
- [x] 测试策略停止时终值写入
- [x] 测试 recompute API 返回 PnlSnapshot
- [x] 验证 ComposableStrategy 运行时盈亏曲线能正常绘制（核心目标）
