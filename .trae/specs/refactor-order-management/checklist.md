# Checklist

- [x] Order DB 模型包含所有新字段（cl_ord_id, state, fill_px, fill_sz, fee, update_time）
- [x] order_id 字段有唯一索引，不会产生重复记录
- [x] OrderManager 内存队列正确维护订单生命周期（live → filled → 移出活跃队列）
- [x] 下单成功后订单立即出现在内存队列和 DB 中
- [x] WebSocket 推送成交后，内存状态和 DB 同步更新
- [x] 策略暂停时所有活跃订单被正确撤销
- [x] 服务器重启后能从 DB 恢复订单状态并重新订阅 WebSocket
- [x] WebSocket 断开后自动重连，重连期间降级到 REST 轮询
- [x] 网格策略不再逐单 REST 轮询订单状态
- [x] 前端订单列表展示成交均价、已成交数量、手续费
- [x] 前端可按状态筛选订单（全部/活跃/已成交/已撤销）
- [x] 100 个网格订单的初始化能在 3 秒内完成
- [x] 订单成交到策略补单的延迟不超过 1 秒（WebSocket 实时推送）