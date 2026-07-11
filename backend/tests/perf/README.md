# 性能基准测试套件

本目录包含 quant_okx 量化交易平台核心模块的性能基准测试，用于持续监控关键路径的执行性能。

## 目录结构

```
backend/tests/perf/
├── __init__.py
├── conftest.py                        # pytest 配置：注册 perf marker、sys.path
├── test_perf_strategy_tick.py         # 策略 tick 吞吐基准
├── test_perf_pnl_accounting.py        # PnL 核算耗时基准
├── test_perf_websocket.py             # WebSocket 延迟基准
└── README.md                          # 本文件
```

## 运行方法

### 运行全部性能测试

```bash
cd backend
python -m pytest tests/perf/ -v --tb=short
```

### 运行单个测试文件

```bash
cd backend
python -m pytest tests/perf/test_perf_strategy_tick.py -v
python -m pytest tests/perf/test_perf_pnl_accounting.py -v
python -m pytest tests/perf/test_perf_websocket.py -v
```

### 在 CI 中跳过性能测试

性能测试使用 `@pytest.mark.perf` 标记，可在 CI 中选择性跳过：

```bash
# 仅运行单元测试（跳过性能测试）
python -m pytest tests/ -v -m "not perf"

# 仅运行性能测试
python -m pytest tests/perf/ -v -m "perf"
```

### 查看详细计时输出

性能测试通过 `print()` 输出计时数据，使用 `-s` 参数查看：

```bash
python -m pytest tests/perf/ -v -s --tb=short
```

## 基准标准

### 1. 策略 Tick 吞吐（test_perf_strategy_tick.py）

| 测试项 | 基准标准 | 说明 |
|--------|----------|------|
| 单次 tick | < 50ms | 10 条规则，含 guard 评估 + 转换扫描 |
| 1000 次连续 tick | < 5s | 10 条规则，含 warm up |
| 5 条规则 tick | < 50ms/tick | 100 ticks 平均 |
| 10 条规则 tick | < 50ms/tick | 100 ticks 平均 |
| 20 条规则 tick | < 50ms/tick | 100 ticks 平均 |
| FSM 编译 (20 rules) | < 100ms | 含状态可达性检查 |

### 2. PnL 核算（test_perf_pnl_accounting.py）

| 测试项 | 基准标准 | 说明 |
|--------|----------|------|
| recompute 100 orders | < 200ms | 全量核算 |
| recompute 500 orders | < 300ms | 全量核算 |
| recompute 1000 orders | < 500ms | **核心基准** |
| recompute 5000 orders | < 3000ms | 压力测试 |
| incremental_update 1 order | < 5ms | 增量核算 |
| incremental_update 10 orders | < 10ms | 增量核算 |
| _compute_pnl_metrics 1000 | < 50ms | 纯计算（隔离 DB） |

### 3. WebSocket 延迟（test_perf_websocket.py）

| 测试项 | 基准标准 | 说明 |
|--------|----------|------|
| 单条 ticker 消息处理 | < 1ms | _handle_data |
| 1000 条 ticker 消息 | < 100ms | 连续处理 |
| 单条 orders 消息处理 | < 1ms | _handle_data |
| 1000 条 orders 消息 | < 100ms | 连续处理 |
| MarketDataService 单条分发 | < 1ms | 回调 fan-out |
| 1000 条 ticker 分发 | < 100ms | 3 回调 fan-out |
| 1000 次 JSON 解析 | < 50ms | json.loads 开销 |

## 测试策略

- **Mock 数据**：所有测试使用 mock 数据，不依赖实际 OKX API 调用或数据库连接
- **计时方式**：使用 `time.perf_counter()` 高精度计时
- **Warm up**：正式计时前执行 warm up 轮次，避免 JIT/缓存冷启动影响
- **超时保护**：基准标准本身即为超时断言，超时即测试失败

## 性能优化建议

### 已有优化

1. **FSM 编译缓存**（`_fsm_cache`）
   - 位置：`backend/dsl/executor.py`
   - 按 `logic_hash` 缓存编译产物，同配置策略实例复用 FSM，避免重复编译

2. **账户权益缓存**（`_cached_equity`）
   - 位置：`backend/dsl/executor.py`
   - 5 秒过期缓存，风控检查/下单风控/持仓估值复用同一缓存值

3. **指标缓存**（`indicator_cache`）
   - 位置：`backend/dsl/context.py`
   - 同 tick 内指标计算结果复用，避免重复调用 API

4. **DB 索引**
   - `orders` 表：`ix_orders_strategy_status_accounted` 复合索引覆盖 `(strategy_instance_id, status, pnl_accounted)`
   - `pnl_records` 表：`ix_pnl_records_strategy_recorded` 复合索引覆盖 `(strategy_instance_id, recorded_at)`

### 潜在优化方向

1. **recompute 全量核算优化**
   - 当前 `_compute_pnl_metrics` 使用列表推导式遍历所有订单
   - 5000+ 订单时可考虑流式处理或 NumPy 向量化计算
   - `incremental_update` 已实现增量路径，优先使用增量而非全量

2. **WebSocket 回调分发**
   - 当前 `_handle_data` 逐条遍历回调列表
   - 高频场景（1000+ msg/s）可考虑回调批量处理或事件循环批处理

3. **tick_interval 调优**
   - 默认 3 秒 tick 间隔，可根据策略类型调整
   - 高频策略可降至 1 秒，低频策略可增至 10 秒以减少 API 调用

4. **连接池调优**
   - `OKXClient` 使用 `httpx.Client(timeout=15)`
   - 高并发策略实例可考虑连接池大小调优
