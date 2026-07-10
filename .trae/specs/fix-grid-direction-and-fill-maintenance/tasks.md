# Tasks

- [x] Task 1: 修复 _place_grid_orders 的 direction 语义
  - [x] SubTask 1.1: long 模式——所有档位挂买单（含高于现价的，立即成交）
  - [x] SubTask 1.2: short 模式——所有档位挂卖单（含低于现价的，立即成交）
  - [x] SubTask 1.3: neutral 模式维持原逻辑（现价下买单、上卖单）
  - [x] SubTask 1.4: 验证批量下单逻辑正确处理 long/short/neutral 三种模式

- [x] Task 2: on_order_filled 适配 direction 模式
  - [x] SubTask 2.1: long 模式买单成交→grid_idx+1 挂卖单（止盈），卖单成交→grid_idx-1 重新挂买单
  - [x] SubTask 2.2: short 模式卖单成交→grid_idx-1 挂买单（止盈），买单成交→grid_idx+1 重新挂卖单（含 PnL 反转计算）
  - [x] SubTask 2.3: neutral 模式维持当前逻辑

- [x] Task 3: GridBlock.on_tick 增加 REST 轮询兜底
  - [x] SubTask 3.1: GridBlock 新增 `_last_rest_check` 时间戳属性
  - [x] SubTask 3.2: on_tick 中距上次检查 ≥ 15 秒时遍历活跃订单调 `client.get_order`
  - [x] SubTask 3.3: 状态从 live→filled 时调 `order_manager.update_order` 触发回调（update_order 内部触发 _trigger_callbacks）
  - [x] SubTask 3.4: 异常容错不中断 tick

- [x] Task 4: on_start 启动时恢复已有活跃订单
  - [x] SubTask 4.1: on_start 先从 DB 查询 status="live" 的订单
  - [x] SubTask 4.2: 按价格匹配网格档位填充 active_buy/active_sell
  - [x] SubTask 4.3: 只为缺失档位补挂新单（复用 _place_grid_orders 跳过逻辑）

# Task Dependencies
- [Task 2] 依赖 [Task 1]（direction 语义变更后反向挂单逻辑需适配）
- [Task 3] 独立
- [Task 4] 独立（但需与 Task 1 的 _place_grid_orders 跳过逻辑配合）
