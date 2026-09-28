# QuantOKX API 接口参考

## 1. 通用约定

| 项目 | 约定 |
|---|---|
| Base URL | 开发默认 `http://127.0.0.1:8000`；业务 REST 前缀通常为 `/api` |
| OpenAPI | `/docs`（Swagger UI）、`/openapi.json`；应用声明版本 `1.0.0` |
| 认证 | 除标记“公开”的接口外，Header `Authorization: Bearer <token>` |
| Content-Type | JSON 为 `application/json`；代理配置上传为 `multipart/form-data` |
| 时间 | 请求通常接受 ISO 8601；响应尽量为 ISO 8601/UTC，部分 SQLite 时间无 `Z` |
| 成功状态 | 路由未显式设置时均为 HTTP 200，包括创建和删除 |
| 错误 | 常见 `{"detail":"message"}`；422 为 FastAPI 校验结构 |
| 业务错误码 | 未建立统一业务码；OKX 代理响应需检查 `code`、`sCode` |
| 幂等 | 未支持 `Idempotency-Key`；GET 幂等，PUT 通常幂等，POST/DELETE 按业务判断 |

所有已认证接口权限相同，没有角色或数据归属检查。公开接口包括 DSL、部分市场行情及 WebSocket。路由未声明 `response_model` 时，OpenAPI 无法完整表达返回字段，本文按实际 return 语句和前端类型记录。

## 2. 认证 `/api/auth`

| 方法与 URL | 认证 | 参数/请求体 | 成功响应 | 主要失败 | 处理函数 |
|---|---:|---|---|---|---|
| `POST /api/auth/login` | 否 | `LoginRequest` | `TokenResponse` | 401 用户名/密码错误；423 锁定 | `routers/auth.py:login` |
| `GET /api/auth/me` | 是 | 无 | `{"id":int,"username":string}` | 401 token/用户错误 | `get_me` |
| `PUT /api/auth/password` | 是 | `ChangePasswordRequest` | `{"message":"密码修改成功"}` | 400 新密码少于 6 位；401 旧密码错误 | `change_password` |

```json
{"username":"admin","password":"<password>"}
```

```json
{"access_token":"<jwt>","token_type":"bearer"}
```

登录连续失败 5 次锁定 15 分钟；JWT 有效期 1440 分钟，无刷新/注销接口。

## 3. 账户 `/api/accounts`

| 方法与 URL | 认证 | 参数/请求体 | 成功响应 | 主要失败 | 处理函数 |
|---|---:|---|---|---|---|
| `GET /api/accounts` | 是 | 无 | 脱敏 `Account[]` | 401 | `list_accounts` |
| `POST /api/accounts` | 是 | `AccountCreate` | `message, account` | 400 OKX Key 验证失败；422 | `create_account` |
| `PUT /api/accounts/{account_id}` | 是 | path `account_id:int`；`AccountUpdate` | 脱敏 `Account` | 404 | `update_account` |
| `DELETE /api/accounts/{account_id}` | 是 | path `account_id:int` | `message` | 404；关联记录约束行为待确认 | `delete_account` |
| `GET /api/accounts/{account_id}/balance` | 是 | path ID | `BalanceData` | 404；500 OKX/解析失败 | `get_balance` |
| `GET /api/accounts/{account_id}/positions` | 是 | path ID | `Position[]`，零持仓过滤 | 404；500 | `get_positions` |
| `GET /api/accounts/{account_id}/balance/cached` | 是 | path ID | 缓存余额/PnL/时间/source | 404 | `get_balance_cached` |
| `GET /api/accounts/network-check` | 是 | 无 | 主/备用域名 DNS 解析结果 | 401 | `check_network_connectivity` |

`AccountCreate` 示例：

```json
{
  "name":"OKX Demo",
  "api_key":"<api-key>",
  "secret_key":"<secret-key>",
  "passphrase":"<passphrase>",
  "trade_mode":"demo"
}
```

响应绝不应返回明文凭证。创建接口会先真实调用 OKX balance 验证，因此不是幂等接口。

## 4. 策略 `/api/strategies`

### 模板

| 方法与 URL | 认证 | 参数/请求体 | 成功响应 | 主要失败/规则 | 处理函数 |
|---|---:|---|---|---|---|
| `GET /templates` | 是 | 无 | `StrategyTemplate[]` | 401 | `list_templates` |
| `POST /templates` | 是 | `StrategyTemplateCreate` | 模板；重复 logic 时 `id:null,duplicate_hint` | 400 同名；422 | `create_template` |
| `PUT /templates/{template_id}` | 是 | path ID；部分 `StrategyTemplateUpdate` | 模板 | 404 | `update_template` |
| `DELETE /templates/{template_id}` | 是 | path ID | `message` | 400 内置模板；404 | `delete_template` |
| `GET /templates/{template_id}/export` | 是 | path ID | 下载 JSON，`Content-Disposition` | 404 | `export_template` |
| `POST /templates/import` | 是 | `TemplateExportPayload` 裸 JSON | 新自定义模板 | 400 JSON/版本/QS-Model/DSL 错误 | `import_template` |

路径均需加 `/api/strategies` 前缀。创建模板不是幂等；`force=false` 时相同 `logic_hash` 不落库。

```json
{
  "name":"示例组合策略",
  "strategy_type":"composable",
  "description":"示例",
  "default_params":{},
  "param_schema":{},
  "dsl_config":null,
  "qs_model_config":{
    "qs_model_version":"2.0",
    "meta":{"name":"示例组合策略","version":"v1.0.0","author":"","description":"","asset_class":"CRYPTO","frequency":"1h","base_symbol":"BTC-USDT"},
    "params":{},
    "logic":{"version":"1.0","base_strategy":{"kind":null,"params":{}},"rules":[]},
    "risk_filter":null
  },
  "force":false
}
```

### 实例与运行时

| 方法与 URL | 认证 | 参数/请求体 | 成功响应 | 主要失败/规则 | 处理函数 |
|---|---:|---|---|---|---|
| `GET /instances` | 是 | 无 | `StrategyInstance[]`，创建时间降序 | 401 | `list_instances` |
| `POST /instances` | 是 | `StrategyInstanceCreate` | `id,message` | 404 模板；symbol 可能被模板覆盖 | `create_instance` |
| `PUT /instances/{instance_id}` | 是 | `StrategyInstanceUpdate` | `message` | 400 运行中改 logic；404 | `update_instance` |
| `DELETE /instances/{instance_id}` | 是 | path ID | `message` | 404；运行中会异步 stop 后物理删除 | `delete_instance` |
| `GET /instances/{instance_id}/feasibility` | 是 | path ID | `FeasibilityResult` | 底层异常可能上抛 | `check_feasibility` |
| `POST /instances/{instance_id}/start` | 是 | path ID | `message,feasibility` | 400 状态/可行性；404 | `start_instance` |
| `POST /instances/{instance_id}/pause` | 是 | path ID | `message` | 400 非 running；404 | `pause_instance` |
| `POST /instances/{instance_id}/resume` | 是 | path ID | `message` | 400 非 paused；404 | `resume_instance` |
| `POST /instances/{instance_id}/stop` | 是 | path ID | `message` | 404；底层停止异常 | `stop_instance` |

`POST start/pause/resume/stop` 是状态命令，不保证重复调用幂等。实例请求示例：

```json
{
  "template_id":1,
  "account_id":1,
  "name":"BTC Demo Grid",
  "symbol":"BTC-USDT",
  "market_type":"spot",
  "params":{"investment_amount":1000}
}
```

### API 调用日志

| 方法与 URL | 认证 | Query/Path | 成功响应 | 失败 | 处理函数 |
|---|---:|---|---|---|---|
| `GET /api-call-logs` | 是 | `strategy_instance_id?`, `limit=100`，1..500 | `ApiCallLogItem[]` | 422 | `list_api_call_logs` |
| `GET /api-call-logs/files` | 是 | `category=all` | 日志文件元数据数组 | 401 | `list_api_log_files` |
| `GET /api-call-logs/files/{filename}` | 是 | `lines=200`，1..2000；`category=all` | 文件尾部内容 | 404；422 | `read_api_log_file` |

## 5. PnL `/api/pnl`

| 方法与 URL | 认证 | 参数 | 成功响应 | 规则/失败 | 处理函数 |
|---|---:|---|---|---|---|
| `GET /api/pnl` | 是 | `account_id?`, `strategy_instance_id?`, `start_time?`, `end_time?`, `limit=1000`，1..5000 | `PnlRecord[]`，时间倒序 | 非法 ISO 时间当前被忽略；422 范围 | `get_pnl_records` |
| `GET /api/pnl/summary` | 是 | `account_id?`, `strategy_instance_id?` | 总计与 `by_strategy` | 空数据返回 0 | `get_pnl_summary` |
| `POST /api/pnl/recompute/{strategy_id}` | 是 | path ID | `PnlSnapshot`；无成交为 `success:false` | 底层异常 | `recompute_pnl` |
| `POST /api/pnl/snapshot` | 是 | 无 | `snapshots,count` | 仅处理内存 running IDs | `snapshot_pnl` |

PnL 列表使用 `limit` 而非 offset/cursor；`summary` 取最近有效快照，不对未实现盈亏跨时间求和。

## 6. 订单与操作日志

| 方法与 URL | 认证 | 参数 | 成功响应 | 规则 | 处理函数 |
|---|---:|---|---|---|---|
| `GET /api/orders` | 是 | `account_id?`, `strategy_instance_id?`, `symbol?`, `status?`, `limit=100`(1..1000), `sort_by=created_at` | `Order[]` | symbol 为模糊匹配；`partial_fill` 映射为 DB `live`；非法 sort 回退创建时间 | `routers/orders.py:list_orders` |
| `GET /api/logs` | 是 | `action?`, `target_type?`, `limit=100`(1..1000), `offset=0` | `{"total":n,"items":[]}` | 创建时间降序 | `routers/logs.py:list_logs` |

订单接口只读；实际下单由策略运行时触发，不对 Web UI 暴露通用手工下单 REST。

## 7. 市场与 WebSocket

### REST

| 方法与 URL | 认证 | 参数 | 成功响应 | 失败语义 | 处理函数 |
|---|---:|---|---|---|---|
| `GET /api/market/spot-tickers` | 公开 | `symbols` 逗号分隔，默认 12 种币 | `code,data` 映射 | 获取失败仍 HTTP 200、`code=-1` | `market.py:get_spot_tickers` |
| `GET /api/market/instrument` | 是 | `instId` 必填 | instrument 元数据 | 无账户时可返回 `ctVal=1.0` 兜底 | `get_instrument_info` |
| `GET /api/market/ticker` | 是 | `symbol` 必填 | `code,data:{instId,last}` | 失败仍 HTTP 200、`code=-1` | `get_ticker_price` |
| `GET /api/market/ticker/{symbol}` | 公开 | path symbol | 提示使用 WebSocket | 仅占位，不返回行情 | `ws.py:get_ticker` |

### WebSocket

| URL | 认证 | 客户端输入 | 服务端输出 | 处理函数 |
|---|---:|---|---|---|
| `/ws/strategy/{instance_id}` | 无 | 任意 text 作为触发 | `instance_id,status,data` 广播 | `strategy_ws` |
| `/ws/dashboard` | 无 | 任意 text 作为触发 | `type,running_strategies,active_count` | `dashboard_ws` |
| `/ws/market/{symbol}` | 无 | text/ping 保活 | `{"type":"ticker","symbol":"...","data":{...}}` | `market_ws` |

前两个连接由 `ConnectionManager` 按 key 广播；第三个连接通过 `MarketDataService` 订阅公共 OKX ticker。代码未实现 WebSocket token、来源和实例访问校验。

## 8. 设置与代理 `/api/settings`

| 方法与 URL | 认证 | 请求/参数 | 成功响应 | 主要失败/副作用 | 处理函数 |
|---|---:|---|---|---|---|
| `GET /api/settings` | 是 | 无 | `{"refresh_interval":"30"}` | 401 | `get_settings` |
| `PUT /api/settings` | 是 | 任意 object；只保存白名单 key | `message` | 未知 key 静默忽略 | `save_settings` |
| `GET /api/settings/proxy` | 是 | 无 | 代理设置与解析节点 | 配置解析异常由服务处理 | `get_proxy_settings_route` |
| `PUT /api/settings/proxy` | 是 | `proxy_enabled,proxy_url,proxy_config_path,proxy_embedded_port` | `message` | 值转为字符串 | `save_proxy_settings_route` |
| `POST /api/settings/proxy/test` | 是 | 可选 `proxy_url` | google/github/okx 连通性 | 网络超时按结果返回 | `test_proxy_route` |
| `GET /api/settings/proxy/status` | 是 | 无 | status/port/pid/uptime/connectivity | 401 | `get_proxy_core_status` |
| `POST /api/settings/proxy/start` | 是 | 可选 `config_path,port,bootstrap_proxy` | 进程启动结果 | 文件/端口/下载问题以服务结果返回 | `start_proxy_core` |
| `POST /api/settings/proxy/stop` | 是 | 无 | 停止结果 | 401 | `stop_proxy_core` |
| `GET /api/settings/proxy/log` | 是 | 无 | Mihomo 日志尾部 | 401 | `get_proxy_log_route` |
| `GET /api/settings/proxy/mmdb-status` | 是 | 无 | MMDB 文件状态 | 401 | `get_mmdb_status_route` |
| `POST /api/settings/proxy/config/import` | 是 | multipart `file` 必填 | 节点/保存结果 | 400 编码或 YAML；422 无文件 | `import_proxy_config` |
| `GET /api/settings/proxy/sample-configs` | 是 | 无 | `samples[]` | 扫描 backend 根目录 | `get_sample_configs_route` |
| `POST /api/settings/proxy/sample-configs/import` | 是 | `{"path":"..."}` | 导入结果 | 400 不存在/解析失败 | `import_sample_config_route` |
| `GET /api/settings/rate-limit` | 是 | 无 | `remaining,limit,percentage` | 无运行策略均为 null | `get_rate_limit_status_route` |

代理 start/import 是有外部状态和文件副作用的非幂等操作。上传目前没有显式大小限制。

## 9. 监控 `/api/monitoring`

| 方法与 URL | 认证 | 参数 | 成功响应 | 规则/失败 | 处理函数 |
|---|---:|---|---|---|---|
| `GET /reconcile` | 是 | `account_id:int`, `symbol:string`, `tolerance?` | 虚拟/真实总持仓、差值、matched | 超差记录事件/通知 | `reconcile_positions` |
| `GET /position_conflicts` | 是 | `account_id:int` | `account_id,conflicts,total` | 只扫描 running/paused；OKX 获取失败真实仓位按 0 | `get_position_conflicts` |
| `GET /health` | 是 | `account_id:int` | `strategies,alerts` | 指标失败局部返回 null | `get_health_metrics` |
| `GET /strategy/{strategy_id}/events` | 是 | `limit=100`(1..1000), `event_type?` | `total,items` | 422 | `list_strategy_events` |
| `DELETE /strategy/{strategy_id}/events` | 是 | path ID | `message,deleted` | 物理删除；不存在也返回 deleted=0 | `delete_strategy_events` |
| `GET /strategy/{strategy_id}/events/export` | 是 | path ID | `text/csv` 下载 | 空列表仍返回表头 | `export_strategy_events` |

以上 URL 均以 `/api/monitoring` 开头。对账 GET 可能产生事件与通知副作用，因此严格说不是纯只读幂等操作。

## 10. 维护 `/api/maintenance`

| 方法与 URL | 认证 | JSON 请求体 | 成功响应 | 主要失败/注意 | 处理函数 |
|---|---:|---|---|---|---|
| `POST /reset-pnl` | 是 | `account_id?`, `strategy_instance_id?` | 重置数量/结果 | 无过滤可能影响大范围数据 | `reset_pnl_route` |
| `POST /cleanup/pnl-records` | 是 | `strategy_instance_id?`, `before_date?` | 删除结果 | 非法日期 400；物理删除 | `cleanup_pnl_records_route` |
| `POST /cleanup/order-records` | 是 | `strategy_instance_id?`, `status_list?` | 删除结果 | 物理删除 | `cleanup_order_records_route` |
| `POST /cleanup/strategy-events` | 是 | `strategy_instance_id` 必填 | 删除结果 | 缺失 400 | `cleanup_strategy_events_route` |
| `POST /correct/equity` | 是 | `account_id` 必填 | 校正结果 | 缺失 400；访问 OKX | `correct_equity_route` |
| `POST /correct/unrealized-pnl` | 是 | `strategy_instance_id` 必填 | 当前服务返回未实现说明/结果 | 功能未完整实现 | `correct_unrealized_pnl_route` |
| `POST /correct/realized-pnl` | 是 | `strategy_instance_id` 必填 | 校正结果 | 缺失 400 | `correct_realized_pnl_route` |

维护接口均为非幂等或高影响操作，没有二次确认/角色隔离；调用前备份数据库。

## 11. DSL `/api/dsl`（公开）

| 方法与 URL | 认证 | 请求 | 成功响应 | 失败 | 处理函数 |
|---|---:|---|---|---|---|
| `GET /api/dsl/blocks` | 否 | 无 | indicators/conditions/actions/events/base_strategies 元数据 | 代码导入错误才失败 | `list_blocks` |
| `POST /api/dsl/validate` | 否 | `StrategyDSL` 裸 JSON | `{"valid":bool,"errors":[]}` | 普通校验错误仍 200 | `validate_dsl` |
| `POST /api/dsl/dry-run` | 否 | `config,symbol,bar?,limit?` | steps 与统计 | 400 `ValueError`；422 非 object | `dry_run` |

```json
{
  "config":{"version":"1.0","base_strategy":{"kind":null,"params":{}},"rules":[]},
  "symbol":"BTC-USDT",
  "bar":"1H",
  "limit":100
}
```

无 OKX 客户端时 dry-run 使用模拟 K 线；因此 API 结果不等同于真实历史回放。

## 12. 回测 `/api/backtest`

| 方法与 URL | 认证 | 请求/参数 | 成功响应 | 失败/限制 | 处理函数 |
|---|---:|---|---|---|---|
| `POST /api/backtest/run` | 是 | `BacktestRequest` | config/trades/equity_curve/metrics/kline_count/error/created_at | 500；同步执行 | `run_backtest` |
| `GET /api/backtest/history` | 是 | `limit=20`，代码夹到 1..50 | `data,total` | 内存存储，重启丢失 | `get_history` |
| `POST /api/backtest/export` | 是 | `ExportRequest` | `instance_payload,message` | 返回体不含 account/template ID，不能直接创建 | `export_to_instance` |

```json
{
  "symbol":"BTC-USDT",
  "strategy_type":"grid",
  "params":{"grid_count":10},
  "start_time":"2026-07-01T00:00:00Z",
  "end_time":"2026-07-31T23:59:59Z",
  "interval":"1H",
  "initial_capital":10000,
  "slippage":0.001,
  "fee_rate":0.001
}
```

## 13. 通知 `/api/notifications`

| 方法与 URL | 认证 | 请求 | 成功响应 | 主要失败 | 处理函数 |
|---|---:|---|---|---|---|
| `GET /rules` | 是 | 无 | `items:NotificationRule[]` | 401 | `list_rules` |
| `POST /rules` | 是 | `NotificationRuleInput` | 新规则 | 400 name/event/channel/config | `create_rule` |
| `PUT /rules/{rule_id}` | 是 | 部分输入 | 更新规则 | 400；404 | `update_rule` |
| `DELETE /rules/{rule_id}` | 是 | path ID | `message` | 404 | `delete_rule` |
| `POST /test` | 是 | `channel_type,channel_config?` | `ok,channel_type` | 400 不支持类型 | `test_notification` |

完整前缀为 `/api/notifications`。`channel_type` 仅为 `email`、`webhook`、`telegram`；`channel_config` 可能包含敏感值，不应写入日志或示例。

## 14. 归因 `/api/analytics`

| 方法与 URL | 认证 | Query | 成功响应 | 失败/过滤 | 处理函数 |
|---|---:|---|---|---|---|
| `GET /attribution/by-symbol` | 是 | `account_id,start_date,end_date` | 按 symbol 的 realized/fee/trades/win rate/share | 422 必填；日期解析由 service | `attribution_by_symbol` |
| `GET /attribution/by-strategy-type` | 是 | 同上 | 按策略类型的 realized/unrealized/trades/return/drawdown | 422 | `attribution_by_strategy_type` |
| `GET /attribution/by-period` | 是 | 同上，`period=daily` | 周期桶 PnL 与成交数 | `daily/weekly/monthly`；非法值行为见 service | `attribution_by_period` |
| `GET /drill-down` | 是 | `start_date,end_date,symbol?,strategy_type?,account_id?` | 订单明细数组 | 422 必填 | `drill_down` |

## 15. 沙箱 `/api/sandbox`

| 方法与 URL | 认证 | 请求/参数 | 成功响应 | 主要失败/限制 | 处理函数 |
|---|---:|---|---|---|---|
| `POST /start` | 是 | `SandboxStartRequest` | `sandbox_id,status,message` | 422 duration 10..86400、tick 1..3600；500 | `start_sandbox` |
| `GET /{sandbox_id}/status` | 是 | path ID | 当前状态 | 404 | `get_sandbox_status` |
| `POST /{sandbox_id}/stop` | 是 | path ID | ID/status/message | 404 | `stop_sandbox` |
| `GET /{sandbox_id}/result` | 是 | path ID | 虚拟订单、PnL、事件等 | 404 | `get_sandbox_result` |
| `GET /list` | 是 | 无 | `data` 状态数组 | 401 | `list_sandboxes` |

```json
{
  "qs_model_config":{
    "qs_model_version":"2.0",
    "meta":{"name":"Sandbox","base_symbol":"BTC-USDT"},
    "params":{},
    "logic":{"version":"1.0","base_strategy":{"kind":null,"params":{}},"rules":[]},
    "risk_filter":null
  },
  "symbol":"BTC-USDT",
  "duration_seconds":300,
  "tick_interval":5,
  "account_id":1
}
```

沙箱使用真实行情但拦截写操作；状态和结果只在当前进程内保存。

## 16. 请求参数和响应一致性注意事项

- 大多数创建接口仍返回 HTTP 200 而不是 201；删除返回 200 而不是 204。
- 只有 15 个 OpenAPI component schemas；大量 `dict` 响应和嵌套字段没有机器可读契约。
- `GET /api/accounts/{account_id}/balance/cached` 与实时 balance 的字段集合不同。
- `GET /api/market/ticker/{symbol}` 是占位接口，真实 REST ticker 是 Query 版 `/api/market/ticker?symbol=...`。
- 日期格式校验不统一：PnL 列表忽略非法日期，归因由 service 解析，回测由引擎处理。
- API 没有统一请求 ID、响应 envelope、错误码、排序枚举或 cursor pagination。
