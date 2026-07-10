# Checklist

## A. direction 语义修复
- [x] long 模式：所有 N 个档位挂买单（含高于现价的）
- [x] long 模式：高于现价的买单立即成交建立初始多头持仓
- [x] short 模式：所有 N 个档位挂卖单（含低于现价的）
- [x] short 模式：低于现价的卖单立即成交建立初始空头持仓
- [x] neutral 模式：维持原逻辑（现价下买单、上卖单）
- [x] long 模式买单成交→grid_idx+1 挂卖单（止盈）
- [x] long 模式卖单成交→grid_idx-1 重新挂买单（重新入场）
- [x] short 模式卖单成交→grid_idx-1 挂买单（止盈）
- [x] short 模式买单成交→grid_idx+1 重新挂卖单（重新入场）
- [x] 任意时刻委托单数量守恒（约 N 个买单+卖单）

## B. REST 轮询兜底
- [x] GridBlock.on_tick 非空，包含 REST 轮询逻辑
- [x] 距上次检查 ≥ 15 秒时遍历活跃订单查 OKX 状态
- [x] 状态 live→filled 时触发 update_order + on_order_filled 回调（update_order 内部触发 _trigger_callbacks("filled") → ComposableStrategy._on_order_filled_cb → GridBlock.on_order_filled）
- [x] WebSocket 断连时 REST 轮询仍能检测成交
- [x] 异常不中断 tick

## C. 启动恢复
- [x] on_start 先从 DB 查询 status="live" 订单
- [x] 按价格匹配网格档位填充 active_buy/active_sell
- [x] 只为缺失档位补挂新单（不重复下单）
- [x] 重启后委托单数量正确恢复
