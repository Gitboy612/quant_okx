# OKX API工具类封装升级 - Verification Checklist

## 架构与模块
- [x] backend/services/okx/目录创建完成，包含__init__.py, base.py, public.py, market.py, account.py, trade.py, funding.py, exceptions.py
- [x] OKXBaseClient基类使用httpx.AsyncClient原生异步，非同步Client+to_thread
- [x] 连接池配置合理：max_connections=100, max_keepalive_connections=20
- [x] 模块按功能分类组织：Public/Market/Account/Trade/Funding，单一职责清晰
- [x] 统一异常类OKXAPIException定义并使用

## 核心功能
- [x] HMAC-SHA256签名算法与原有实现100%兼容（复用完全相同签名逻辑）
- [x] 时间同步功能正常，启动时自动同步，错误码50112/50115触发自动重同步
- [x] 请求限流实现：令牌桶算法，公共接口20次/2s，私有接口60次/2s
- [x] 指数退避重试：网络错误/5xx/50011频率超限最多重试3次
- [x] 模拟盘支持：x-simulated-trading头正确添加
- [x] 代理和DNS override功能保持原有可用
- [ ] API调用日志记录功能正常工作（需实际运行验证）

## PublicAPI 公共接口
- [x] get_server_time() 返回code="0"，包含正确时间戳 ✓
- [x] get_instruments(instType="SWAP") 返回code="0"，包含合约列表 ✓
- [x] get_funding_rate(instId="BTC-USDT-SWAP") 返回code="0"，包含资金费率 ✓
- [x] get_funding_rate_history(instId="BTC-USDT-SWAP", limit="5") 返回code="0" ✓
- [x] get_mark_price(instType="SWAP") 返回code="0"，包含标记价格 ✓
- [x] get_open_interest(instType="SWAP") 返回code="0"，包含持仓量 ✓
- [x] get_system_status() 返回code="0"，路径已修正为/api/v5/system/status ✓

## MarketAPI 市场接口
- [x] get_ticker(instId="ETH-USDT-SWAP") 返回code="0"，包含last价格 ✓
- [x] get_tickers(instType="SWAP") 返回code="0"，包含所有合约行情 ✓
- [x] get_candles(instId="BTC-USDT-SWAP", bar="1m", limit="10") 返回code="0"，10根K线 ✓
- [x] get_orderbook(instId="BTC-USDT-SWAP", sz="5") 返回code="0"，5档深度 ✓
- [x] get_trades(instId="BTC-USDT-SWAP", limit="5") 返回code="0"，最近成交 ✓
- [x] get_index_ticker(instId="BTC-USDT") 返回code="0"，指数价格 ✓

## AccountAPI 账户接口 (需API Key - 用户配置模拟盘后运行test_account.py)
- [ ] get_balance() 返回code="0"，包含totalEq和details余额列表
- [ ] get_positions() 返回code="0"，返回持仓列表（空列表也正常）
- [ ] get_config() 返回code="0"，包含账户配置信息
- [ ] get_bills(limit="10") 返回code="0"，最近10条账单
- [ ] get_fee_rates(instType="SWAP", instId="BTC-USDT-SWAP") 返回code="0"，手续费率
- [ ] get_positions_history(limit="10") 返回code="0"，持仓历史
- [ ] get_leverage(instId="BTC-USDT-SWAP", mgnMode="cross") 返回code="0"，杠杆倍数

## TradeAPI 交易接口 (需API Key - 用户配置模拟盘后运行test_trade.py)
- [ ] place_order 限价买单测试成功返回ordId，code="0"
- [ ] get_order 根据ordId查询订单返回正确状态，code="0"
- [ ] cancel_order 撤单成功，code="0"
- [ ] batch_place_orders 批量下单3笔全部成功（sCode="0"），code="0"
- [ ] batch_cancel_orders 批量撤单全部成功，code="0"
- [ ] get_pending_orders 返回未成交订单列表，code="0"
- [ ] get_orders_history(limit="10") 返回历史订单列表，code="0"
- [ ] get_fills(limit="10") 返回成交明细，code="0"
- [ ] 交易测试后无遗留挂单（所有测试订单已撤销）

## FundingAPI 资金接口 (公共接口已验证，私有接口需API Key)
- [x] get_currencies() 返回code="0"，币种列表 ✓
- [ ] get_balances() 返回code="0"，资金账户余额
- [ ] get_bills(limit="5") 返回code="0"，资金账单
- [ ] transfer 小额划转测试（交易账户→资金账户→交易账户）双向成功，code="0"
- [ ] get_transfer_state 查询划转状态返回成功，code="0"
- [ ] get_deposit_address(ccy="USDT") 返回code="0"，充值地址信息
- [x] 未实现提币接口（安全约束）✓

## 向后兼容性
- [x] OKXClient原有方法get_balance()签名和返回格式不变 ✓
- [x] OKXClient原有方法get_positions()签名和返回格式不变 ✓
- [x] OKXClient原有方法get_ticker(inst_id)参数名inst_id（下划线）不变 ✓
- [x] OKXClient原有方法get_candles(inst_id, bar, limit)参数名不变 ✓
- [x] OKXClient原有方法place_order(inst_id, side, ord_type, sz, px)参数顺序和名称不变，tdMode默认"cross" ✓
- [x] OKXClient原有方法batch_place_orders(orders)参数格式兼容 ✓
- [x] OKXClient原有方法cancel_order(inst_id, order_id)参数名不变 ✓
- [x] OKXClient原有方法get_order(inst_id, order_id)参数名不变 ✓
- [x] OKXClient原有方法get_pending_orders(inst_id)参数名不变 ✓
- [x] OKXClient原有方法get_orders_history(inst_id, limit)参数名不变 ✓
- [x] client._request("GET", "/api/v5/account/balance")直接调用仍然可用 ✓
- [x] client.api_key, client.secret_key, client.passphrase, client.trade_mode等实例变量可访问 ✓
- [x] 全局代理设置OKXClient.set_global_proxy()功能正常 ✓
- [x] 新模块可通过client.public, client.market, client.account, client.trade, client.funding访问 ✓

## WebSocket兼容
- [x] OKXWsClient独立模块，不依赖新基类，保持原有实现 ✓
- [ ] WS连接模拟盘可以正常登录成功（event=login, code=0）（需实际运行验证）
- [ ] WS订单订阅可正常接收订单更新（需实际运行验证）

## 测试脚本
- [x] backend/tests/目录创建完成，包含所有测试文件 ✓
- [x] test_public.py可独立运行，所有公共接口PASS (7/7) ✓
- [x] test_market.py可独立运行，所有行情接口PASS (6/6) ✓
- [ ] test_account.py可独立运行，所有账户接口PASS
- [ ] test_trade.py可独立运行，完整下单→查询→撤单流程PASS，无遗留挂单
- [ ] test_funding.py可独立运行，划转测试双向PASS
- [x] test_backward_compat.py可独立运行，方法存在性检查通过 ✓
- [x] 测试脚本从数据库读取模拟盘账户配置，不硬编码API Key ✓

## 集成验证
- [x] 后端服务uvicorn启动无导入错误，无启动异常 ✓
- [ ] /api/accounts 账户列表接口正常返回
- [ ] /api/accounts/{id}/balance 余额查询接口正常返回数据
- [ ] /api/accounts/{id}/positions 持仓查询接口正常返回
- [x] /api/accounts/network-check 网络检查接口路由正常（401说明认证正常，服务运行中）✓
- [ ] 网格策略可以正常初始化，批量下单成功（模拟盘小额测试）
- [x] Python语法无错误，代码风格符合项目现有规范 ✓
