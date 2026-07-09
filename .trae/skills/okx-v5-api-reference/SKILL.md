---
name: "okx-v5-api-reference"
description: "Complete OKX V5 API reference with all REST endpoints and error codes. Invoke when working with OKX API integration, debugging API errors, or looking up any OKX endpoint."
---

# OKX V5 API 完整参考

本 skill 包含 OKX V5 API 的所有 REST 接口端点、WebSocket 频道、错误码，基于官方文档 [https://www.okx.com/docs-v5/zh/](https://www.okx.com/docs-v5/zh/) 整理。

---

## 基础信息

### REST API

- **Base URL (实盘)**: `https://openapi.okx.com`
- **Base URL (模拟盘)**: `https://openapi.okx.com` (通过 `x-simulated-trading: 1` 请求头切换)
- **请求头必须包含**:
  - `OK-ACCESS-KEY`: API Key
  - `OK-ACCESS-SIGN`: HMAC SHA256 + Base64 签名
  - `OK-ACCESS-TIMESTAMP`: UTC 时间戳 (ISO 8601, 如 `2020-12-08T09:08:57.715Z`)
  - `OK-ACCESS-PASSPHRASE`: API 密钥的 Passphrase
  - `Content-Type: application/json`
- **签名规则**: `Base64(HmacSHA256(timestamp + method + requestPath + body, SecretKey))`
  - GET 请求 body 为空字符串 `''`
  - 示例: `sign=CryptoJS.enc.Base64.stringify(CryptoJS.HmacSHA256(timestamp + 'GET' + '/api/v5/account/balance?ccy=BTC', SecretKey))`
- **服务器时间误差**: 超过 30 秒会返回错误码 `50102`，建议先调用 `GET /api/v5/public/time` 同步时间
- **限频**: 根据 API Key 权限等级不同，公共接口按 IP 限频，私有接口按 User ID 限频

### WebSocket API

- **实盘地址**:
  - 公共频道: `wss://ws.okx.com:8443/ws/v5/public`
  - 私有频道: `wss://ws.okx.com:8443/ws/v5/private`
  - 业务频道: `wss://ws.okx.com:8443/ws/v5/business`
- **模拟盘地址**:
  - 公共频道: `wss://wspap.okx.com:8443/ws/v5/public`
  - 私有频道: `wss://wspap.okx.com:8443/ws/v5/private`
  - 业务频道: `wss://wspap.okx.com:8443/ws/v5/business`
- **连接限制**: 3 次/秒 (基于 IP)
- **订阅/取消订阅/登录**: 每个连接 480 次/小时
- **心跳**: 30 秒内无数据推送会自动断开，建议发送 `ping` 保持连接
- **子账户维度**: 每个 WebSocket 频道最大连接数 30 个

### 账户模式

- 现货模式、合约模式、跨币种保证金模式、组合保证金模式
- 首次设置需在网页或 App 端操作

---

## 一、Public Data (公共数据) - 无需认证

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v5/public/time` | GET | 获取系统时间 |
| `/api/v5/public/instruments` | GET | 获取交易产品信息 |
| `/api/v5/public/delivery-exercise-history` | GET | 获取交割/行权历史 |
| `/api/v5/public/open-interest` | GET | 获取持仓量 |
| `/api/v5/public/funding-rate` | GET | 获取当前资金费率 |
| `/api/v5/public/funding-rate-history` | GET | 获取资金费率历史 |
| `/api/v5/public/price-limit` | GET | 获取限价 |
| `/api/v5/public/opt-summary` | GET | 获取期权市场数据 |
| `/api/v5/public/estimated-price` | GET | 获取预估交割/行权价 |
| `/api/v5/public/estimated-settlement-info` | GET | 获取预估结算信息 |
| `/api/v5/public/discount-rate-interest-free-quota` | GET | 获取折扣率和免息额度 |
| `/api/v5/public/mark-price` | GET | 获取标记价格 |
| `/api/v5/public/position-tiers` | GET | 获取仓位档位 |
| `/api/v5/public/interest-rate-loan-quota` | GET | 获取借币利率和额度 |
| `/api/v5/public/vip-interest-rate-loan-quota` | GET | 获取VIP借币利率和额度 |
| `/api/v5/public/underlying` | GET | 获取标的指数 |
| `/api/v5/public/insurance-fund` | GET | 获取保险基金 |
| `/api/v5/public/convert-contract-coin` | GET | 币种转换计算 |
| `/api/v5/public/instrument-tick-bands` | GET | 获取期权tick区间 |
| `/api/v5/public/option-trades` | GET | 获取期权成交记录 |
| `/api/v5/public/market-data-history` | GET | 获取历史行情数据 |
| `/api/v5/public/liquidation-orders` | GET | 获取爆仓订单 |
| `/api/v5/public/premium-history` | GET | 获取溢价历史 |
| `/api/v5/public/settlement-history` | GET | 获取结算历史 |
| `/api/v5/public/block-trades` | GET | 获取大宗交易 |
| `/api/v5/public/economic-calendar` | GET | 获取经济日历 |
| `/api/v5/public/mm-instrument-types` | GET | 获取做市商交易产品类型 |
| `/api/v5/public/event-contract/events` | GET | 获取事件合约事件 |
| `/api/v5/public/event-contract/markets` | GET | 获取事件合约市场 |
| `/api/v5/public/event-contract/series` | GET | 获取事件合约系列 |

---

## 二、Market Data (行情数据) - 无需认证

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v5/market/tickers` | GET | 获取所有产品行情 |
| `/api/v5/market/ticker` | GET | 获取单个产品行情 |
| `/api/v5/market/index-tickers` | GET | 获取指数行情 |
| `/api/v5/market/books` | GET | 获取深度数据 |
| `/api/v5/market/books-full` | GET | 获取全量深度 |
| `/api/v5/market/books-lite` | GET | 获取精简深度数据 |
| `/api/v5/market/books-sbe` | GET | 获取SBE深度数据 |
| `/api/v5/market/candles` | GET | 获取K线数据 |
| `/api/v5/market/history-candles` | GET | 获取历史K线（仅主流币） |
| `/api/v5/market/index-candles` | GET | 获取指数K线 |
| `/api/v5/market/history-index-candles` | GET | 获取历史指数K线 |
| `/api/v5/market/mark-price-candles` | GET | 获取标记价格K线 |
| `/api/v5/market/history-mark-price-candles` | GET | 获取历史标记价格K线 |
| `/api/v5/market/trades` | GET | 获取成交数据 |
| `/api/v5/market/history-trades` | GET | 获取历史成交数据 |
| `/api/v5/market/platform-24-volume` | GET | 获取平台24小时成交量 |
| `/api/v5/market/index-components` | GET | 获取指数成分 |
| `/api/v5/market/exchange-rate` | GET | 获取汇率 |
| `/api/v5/market/block-tickers` | GET | 获取大宗交易行情列表 |
| `/api/v5/market/block-ticker` | GET | 获取大宗交易单产品行情 |
| `/api/v5/market/block-trades` | GET | 获取大宗交易成交明细 |
| `/api/v5/market/option/instrument-family-trades` | GET | 获取期权品种成交 |
| `/api/v5/market/call-auction-details` | GET | 获取集合竞价详情 |
| `/api/v5/market/sprd-ticker` | GET | 获取价差行情 |
| `/api/v5/market/sprd-candles` | GET | 获取价差K线 |
| `/api/v5/market/sprd-history-candles` | GET | 获取价差历史K线 |

---

## 三、Account (账户) - 需认证

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v5/account/instruments` | GET | 获取账户可交易产品 |
| `/api/v5/account/balance` | GET | 获取账户余额 |
| `/api/v5/account/positions` | GET | 获取持仓信息 |
| `/api/v5/account/positions-history` | GET | 获取持仓历史 |
| `/api/v5/account/account-position-risk` | GET | 获取账户持仓风险 |
| `/api/v5/account/bills` | GET | 获取账单流水（近7天） |
| `/api/v5/account/bills-archive` | GET | 获取账单流水（近3个月） |
| `/api/v5/account/bills-history-archive` | POST | 申请账单历史归档 |
| `/api/v5/account/config` | GET | 获取账户配置 |
| `/api/v5/account/set-position-mode` | POST | 设置持仓模式 |
| `/api/v5/account/set-leverage` | POST | 设置杠杆倍数 |
| `/api/v5/account/max-size` | GET | 获取最大可买卖数量 |
| `/api/v5/account/max-avail-size` | GET | 获取最大可用数量 |
| `/api/v5/account/position/margin-balance` | POST | 调整保证金 |
| `/api/v5/account/leverage-info` | GET | 获取杠杆信息 |
| `/api/v5/account/max-loan` | GET | 获取最大借币量 |
| `/api/v5/account/trade-fee` | GET | 获取交易费率 |
| `/api/v5/account/interest-accrued` | GET | 获取借币计息记录 |
| `/api/v5/account/interest-rate` | GET | 获取借币利率 |
| `/api/v5/account/set-greeks` | POST | 设置Greeks显示 |
| `/api/v5/account/set-isolated-mode` | POST | 设置逐仓/全仓 |
| `/api/v5/account/max-withdrawal` | GET | 获取最大可提币数量 |
| `/api/v5/account/risk-state` | GET | 获取账户风险状态 |
| `/api/v5/account/borrow-repay` | POST | 手动借还币 |
| `/api/v5/account/borrow-repay-history` | GET | 获取借还币历史 |
| `/api/v5/account/interest-limits` | GET | 获取借币限额 |
| `/api/v5/account/simulated_margin` | POST | 模拟保证金计算 |
| `/api/v5/account/greeks` | GET | 获取Greeks |
| `/api/v5/account/position-tiers` | GET | 获取仓位档位限制 |
| `/api/v5/account/set-riskOffset-type` | POST | 设置风险对冲类型 |
| `/api/v5/account/set-riskOffset-amt` | POST | 设置风险对冲金额 |
| `/api/v5/account/set-auto-loan` | POST | 设置自动借币 |
| `/api/v5/account/set-auto-repay` | POST | 设置自动还币 |
| `/api/v5/account/set-auto-earn` | POST | 设置自动赚币 |
| `/api/v5/account/set-account-level` | POST | 设置账户模式 |
| `/api/v5/account/account-level-switch-preset` | POST | 账户等级切换预检查 |
| `/api/v5/account/activate-option` | POST | 激活期权账户 |
| `/api/v5/account/position-builder` | POST | 持仓构建器 |
| `/api/v5/account/position-builder-graph` | POST | 持仓构建器图表 |
| `/api/v5/account/spot-manual-borrow-repay` | POST | 现货手动借还币 |
| `/api/v5/account/set-collateral-assets` | POST | 设置质押资产 |
| `/api/v5/account/set-fee-type` | POST | 设置手续费类型 |
| `/api/v5/account/set-settle-currency` | POST | 设置结算币种 |
| `/api/v5/account/set-trading-config` | POST | 设置交易配置 |
| `/api/v5/account/move-positions` | POST | 移仓 |
| `/api/v5/account/mmp-config` | POST | 做市商保护配置 |
| `/api/v5/account/mmp-reset` | POST | 重置做市商保护 |
| `/api/v5/account/demo-adjust-balance` | POST | 模拟盘调整余额 |
| `/api/v5/account/precheck-set-delta-neutral` | GET | 预检查Delta中性设置 |
| `/api/v5/account/subtypes` | GET | 获取账单子类型 |
| `/api/v5/account/spot-borrow-repay-history` | GET | 获取现货借还币历史 |
| `/api/v5/account/vip-interest-accrued` | GET | 获取VIP借币计息记录 |
| `/api/v5/account/vip-interest-deducted` | GET | 获取VIP利息扣减记录 |
| `/api/v5/account/vip-loan-order-list` | GET | 获取VIP借币订单列表 |
| `/api/v5/account/vip-loan-order-detail` | GET | 获取VIP借币订单详情 |
| `/api/v5/account/fixed-loan/borrowing-limit` | GET | 获取定借限额 |
| `/api/v5/account/fixed-loan/borrowing-quote` | GET | 获取定借报价 |
| `/api/v5/account/fixed-loan/borrowing-order` | POST | 下定借订单 |
| `/api/v5/account/fixed-loan/amend-borrowing-order` | POST | 修改定借订单 |
| `/api/v5/account/fixed-loan/manual-reborrow` | POST | 手动续借 |
| `/api/v5/account/fixed-loan/repay-borrowing-order` | POST | 偿还定借订单 |
| `/api/v5/account/fixed-loan/borrowing-orders-list` | GET | 获取定借订单列表 |

---

## 四、Trade (交易) - 需认证

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v5/trade/order` | POST | 下单 |
| `/api/v5/trade/order` | GET | 获取订单信息 |
| `/api/v5/trade/batch-orders` | POST | 批量下单 |
| `/api/v5/trade/cancel-order` | POST | 撤销订单 |
| `/api/v5/trade/cancel-batch-orders` | POST | 批量撤销订单 |
| `/api/v5/trade/cancel-all-after` | POST | 定时撤单 |
| `/api/v5/trade/mass-cancel` | POST | 批量撤单（按标签） |
| `/api/v5/trade/amend-order` | POST | 修改订单 |
| `/api/v5/trade/amend-batch-orders` | POST | 批量修改订单 |
| `/api/v5/trade/close-position` | POST | 市价平仓 |
| `/api/v5/trade/order-precheck` | POST | 订单预检查 |
| `/api/v5/trade/orders-pending` | GET | 获取未成交订单 |
| `/api/v5/trade/orders-history` | GET | 获取历史订单（近7天） |
| `/api/v5/trade/orders-history-archive` | GET | 获取历史订单（近3个月） |
| `/api/v5/trade/fills` | GET | 获取成交明细（近3天） |
| `/api/v5/trade/fills-history` | GET | 获取成交明细（近3个月） |
| `/api/v5/trade/order-algo` | POST | 设置策略委托 |
| `/api/v5/trade/order-algo` | GET | 获取策略委托详情 |
| `/api/v5/trade/cancel-algos` | POST | 撤销策略委托 |
| `/api/v5/trade/amend-algos` | POST | 修改策略委托 |
| `/api/v5/trade/orders-algo-pending` | GET | 获取未完成策略委托 |
| `/api/v5/trade/orders-algo-history` | GET | 获取策略委托历史 |
| `/api/v5/trade/account-rate-limit` | GET | 获取账户限速 |
| `/api/v5/trade/easy-convert-currency-list` | GET | 获取闪兑币种列表 |
| `/api/v5/trade/easy-convert` | POST | 闪兑 |
| `/api/v5/trade/easy-convert-history` | GET | 获取闪兑历史 |
| `/api/v5/trade/one-click-repay-currency-list` | GET | 获取一键还币币种列表 |
| `/api/v5/trade/one-click-repay` | POST | 一键还币 |
| `/api/v5/trade/one-click-repay-history` | GET | 获取一键还币历史 |
| `/api/v5/trade/one-click-repay-currency-list-v2` | GET | 获取一键还币币种列表V2 |
| `/api/v5/trade/one-click-repay-v2` | POST | 一键还币V2 |
| `/api/v5/trade/one-click-repay-history-v2` | GET | 获取一键还币历史V2 |

---

## 五、Funding / Asset (资金/资产) - 需认证

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v5/asset/currencies` | GET | 获取币种信息 |
| `/api/v5/asset/balances` | GET | 获取资金账户余额 |
| `/api/v5/asset/non-tradable-assets` | GET | 获取不可交易资产 |
| `/api/v5/asset/asset-valuation` | GET | 获取资产估值 |
| `/api/v5/asset/transfer` | POST | 资金划转 |
| `/api/v5/asset/transfer-state` | GET | 获取划转状态 |
| `/api/v5/asset/deposit-address` | GET | 获取充值地址 |
| `/api/v5/asset/deposit-history` | GET | 获取充值记录 |
| `/api/v5/asset/deposit-lightning` | GET | 获取闪电网络充值记录 |
| `/api/v5/asset/deposit-withdraw-status` | GET | 获取充提状态 |
| `/api/v5/asset/withdrawal` | POST | 提币 |
| `/api/v5/asset/withdrawal-lightning` | POST | 闪电网络提币 |
| `/api/v5/asset/withdrawal-history` | GET | 获取提币记录 |
| `/api/v5/asset/cancel-withdrawal` | POST | 取消提币 |
| `/api/v5/asset/convert-dust-assets` | POST | 小额资产兑换 |
| `/api/v5/asset/bills` | GET | 获取资金账单 |
| `/api/v5/asset/purchase_redempt` | POST | 申购/赎回 |
| `/api/v5/asset/monthly-statement` | POST | 月度账单 |

---

## 六、SubAccount (子账户) - 需认证

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v5/users/subaccount/list` | GET | 获取子账户列表 |
| `/api/v5/users/subaccount/apikey` | GET | 获取子账户APIKey |
| `/api/v5/users/subaccount/create-subaccount` | POST | 创建子账户 |
| `/api/v5/users/subaccount/apikey` | POST | 创建子账户APIKey |
| `/api/v5/users/subaccount/modify-apikey` | POST | 修改子账户APIKey |
| `/api/v5/users/subaccount/delete-apikey` | POST | 删除子账户APIKey |
| `/api/v5/users/subaccount/set-transfer-out` | POST | 设置子账户转出权限 |
| `/api/v5/users/entrust-subaccount-list` | GET | 获取托管子账户列表 |
| `/api/v5/account/subaccount/balances` | GET | 获取子账户余额 |
| `/api/v5/asset/subaccount/balances` | GET | 获取子账户资金余额 |
| `/api/v5/asset/subaccount/bills` | GET | 获取子账户账单 |
| `/api/v5/asset/subaccount/transfer` | POST | 子账户资金划转 |
| `/api/v5/account/subaccount/set-loan-allocation` | POST | 设置子账户VIP借币分配 |
| `/api/v5/account/subaccount/interest-limits` | GET | 获取子账户借币限额 |

---

## 七、Convert (兑换) - 需认证

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v5/asset/convert/currencies` | GET | 获取兑换币种列表 |
| `/api/v5/asset/convert/currency-pair` | GET | 获取兑换币对 |
| `/api/v5/asset/convert/estimate-quote` | POST | 预估兑换报价 |
| `/api/v5/asset/convert/trade` | POST | 兑换交易 |
| `/api/v5/asset/convert/history` | GET | 获取兑换历史 |

---

## 八、Block Trading / RFQ (大宗交易) - 需认证

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v5/rfq/counterparties` | GET | 获取对手方列表 |
| `/api/v5/rfq/create-rfq` | POST | 创建询价单 |
| `/api/v5/rfq/cancel-rfq` | POST | 撤销询价单 |
| `/api/v5/rfq/cancel-batch-rfqs` | POST | 批量撤销询价单 |
| `/api/v5/rfq/cancel-all-rfqs` | POST | 撤销所有询价单 |
| `/api/v5/rfq/cancel-all-after` | POST | 定时撤销 |
| `/api/v5/rfq/execute-quote` | POST | 执行报价 |
| `/api/v5/rfq/create-quote` | POST | 创建报价 |
| `/api/v5/rfq/cancel-quote` | POST | 撤销报价 |
| `/api/v5/rfq/cancel-batch-quotes` | POST | 批量撤销报价 |
| `/api/v5/rfq/cancel-all-quotes` | POST | 撤销所有报价 |
| `/api/v5/rfq/rfqs` | GET | 获取询价单 |
| `/api/v5/rfq/quotes` | GET | 获取报价单 |
| `/api/v5/rfq/trades` | GET | 获取RFQ成交 |
| `/api/v5/rfq/public-trades` | GET | 获取RFQ公开成交 |
| `/api/v5/rfq/mmp-config` | POST | MMP配置 |
| `/api/v5/rfq/mmp-reset` | POST | 重置MMP状态 |
| `/api/v5/rfq/maker-instrument-settings` | POST | 设置做市商产品设置 |
| `/api/v5/rfq/maker-instrument-settings` | GET | 获取做市商产品设置 |
| `/api/v5/rfq/mmp-config` | GET | 获取MMP配置 |

---

## 九、Trading Bot (交易机器人) - 需认证

### Grid (网格交易)

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v5/tradingBot/grid/order-algo` | POST | 创建网格策略 |
| `/api/v5/tradingBot/grid/amend-order-algo` | POST | 修改网格策略 |
| `/api/v5/tradingBot/grid/stop-order-algo` | POST | 停止网格策略 |
| `/api/v5/tradingBot/grid/orders-algo-pending` | GET | 获取运行中网格策略 |
| `/api/v5/tradingBot/grid/orders-algo-history` | GET | 获取网格策略历史 |
| `/api/v5/tradingBot/grid/orders-algo-details` | GET | 获取网格策略详情 |
| `/api/v5/tradingBot/grid/sub-orders` | GET | 获取网格子订单 |
| `/api/v5/tradingBot/grid/positions` | GET | 获取网格持仓 |
| `/api/v5/tradingBot/grid/withdraw-income` | POST | 提取网格收益 |
| `/api/v5/tradingBot/grid/compute-margin-balance` | POST | 计算网格保证金 |
| `/api/v5/tradingBot/grid/margin-balance` | POST | 调整网格保证金 |
| `/api/v5/tradingBot/grid/ai-param` | GET | 获取网格AI参数 |
| `/api/v5/tradingBot/grid/close-position` | POST | 平仓网格仓位 |
| `/api/v5/tradingBot/grid/cancel-close-order` | POST | 取消平仓单 |
| `/api/v5/tradingBot/grid/min-investment` | GET | 获取最小投资额 |
| `/api/v5/tradingBot/grid/adjust-investment` | POST | 调整投资金额 |
| `/api/v5/tradingBot/grid/grid-quantity` | GET | 获取网格数量 |
| `/api/v5/tradingBot/grid/copy-order-algo` | POST | 复制网格策略 |
| `/api/v5/tradingBot/grid/order-instant-trigger` | POST | 即时触发网格 |
| `/api/v5/tradingBot/grid/amend-algo-basic-param` | POST | 修改网格基础参数 |

### Recurring Buy (定投)

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v5/tradingBot/recurring/order-algo` | POST | 创建定投策略 |
| `/api/v5/tradingBot/recurring/amend-order-algo` | POST | 修改定投策略 |
| `/api/v5/tradingBot/recurring/stop-order-algo` | POST | 停止定投策略 |
| `/api/v5/tradingBot/recurring/orders-algo-pending` | GET | 获取运行中定投策略 |
| `/api/v5/tradingBot/recurring/orders-algo-history` | GET | 获取定投策略历史 |
| `/api/v5/tradingBot/recurring/orders-algo-details` | GET | 获取定投策略详情 |
| `/api/v5/tradingBot/recurring/sub-orders` | GET | 获取定投子订单 |
| `/api/v5/tradingBot/recurring/add-investment` | POST | 追加投资 |
| `/api/v5/tradingBot/recurring/amend-price-range` | POST | 修改价格区间 |
| `/api/v5/tradingBot/recurring/amend-recurring-amount` | POST | 修改定投金额 |
| `/api/v5/tradingBot/recurring/amend-recurring-time` | POST | 修改定投时间 |
| `/api/v5/tradingBot/recurring/pause` | POST | 暂停定投 |
| `/api/v5/tradingBot/recurring/restart` | POST | 重启定投 |

### Signal (信号交易)

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v5/tradingBot/signal/order-algo` | POST | 创建信号策略 |
| `/api/v5/tradingBot/signal/set-instruments` | POST | 设置信号产品 |
| `/api/v5/tradingBot/signal/stop-order-algo` | POST | 停止信号策略 |
| `/api/v5/tradingBot/signal/margin-balance` | POST | 调整保证金 |
| `/api/v5/tradingBot/signal/orders-algo-pending` | GET | 获取运行中信号策略 |
| `/api/v5/tradingBot/signal/orders-algo-details` | GET | 获取信号策略详情 |
| `/api/v5/tradingBot/signal/orders-algo-history` | GET | 获取信号策略历史 |
| `/api/v5/tradingBot/signal/positions` | GET | 获取信号持仓 |
| `/api/v5/tradingBot/signal/positions-history` | GET | 获取信号持仓历史 |
| `/api/v5/tradingBot/signal/close-position` | POST | 平仓信号仓位 |
| `/api/v5/tradingBot/signal/sub-order` | POST | 创建信号子订单 |
| `/api/v5/tradingBot/signal/cancel-sub-order` | POST | 取消信号子订单 |
| `/api/v5/tradingBot/signal/sub-orders` | GET | 获取信号子订单 |
| `/api/v5/tradingBot/signal/event-history` | GET | 获取信号事件历史 |
| `/api/v5/tradingBot/signal/create-signal` | POST | 创建信号 |
| `/api/v5/tradingBot/signal/amendTPSL` | POST | 修改止盈止损 |
| `/api/v5/tradingBot/signal/signals` | GET | 获取信号列表 |

### DCA (平均成本策略)

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v5/tradingBot/dca/create` | POST | 创建DCA策略 |
| `/api/v5/tradingBot/dca/stop` | POST | 停止DCA策略 |
| `/api/v5/tradingBot/dca/ongoing-list` | GET | 获取运行中DCA |
| `/api/v5/tradingBot/dca/history-list` | GET | 获取DCA历史 |
| `/api/v5/tradingBot/dca/cycle-list` | GET | 获取DCA周期列表 |
| `/api/v5/tradingBot/dca/orders` | GET | 获取DCA子订单 |
| `/api/v5/tradingBot/dca/position-details` | GET | 获取DCA持仓详情 |
| `/api/v5/tradingBot/dca/amend-order-algo` | POST | 修改DCA策略 |
| `/api/v5/tradingBot/dca/margin/add` | POST | 追加保证金 |
| `/api/v5/tradingBot/dca/margin/reduce` | POST | 减少保证金 |
| `/api/v5/tradingBot/dca/settings/reinvestment` | POST | 设置复投 |
| `/api/v5/tradingBot/dca/settings/take-profit` | POST | 设置止盈 |
| `/api/v5/tradingBot/dca/orders/manual-buy` | POST | 手动买入 |

### TradingBot 公共

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v5/tradingBot/public/rsi-back-testing` | GET | RSI回测 |

---

## 十、Finance / Staking (金融/赚币) - 需认证

### Staking Defi

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v5/finance/staking-defi/offers` | GET | 获取赚币产品 |
| `/api/v5/finance/staking-defi/purchase` | POST | 申购赚币 |
| `/api/v5/finance/staking-defi/redeem` | POST | 赎回赚币 |
| `/api/v5/finance/staking-defi/cancel` | POST | 取消赚币 |
| `/api/v5/finance/staking-defi/orders-active` | GET | 获取活跃赚币订单 |
| `/api/v5/finance/staking-defi/orders-history` | GET | 获取赚币历史 |

### ETH Staking

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v5/finance/staking-defi/eth/product-info` | GET | 获取ETH质押产品信息 |
| `/api/v5/finance/staking-defi/eth/purchase` | POST | ETH质押申购 |
| `/api/v5/finance/staking-defi/eth/redeem` | POST | ETH质押赎回 |
| `/api/v5/finance/staking-defi/eth/cancel-redeem` | POST | 取消ETH赎回 |
| `/api/v5/finance/staking-defi/eth/balance` | GET | 获取ETH质押余额 |
| `/api/v5/finance/staking-defi/eth/purchase-redeem-history` | GET | 获取ETH质押历史 |
| `/api/v5/finance/staking-defi/eth/apy-history` | GET | 获取ETH质押APY历史 |

### SOL Staking

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v5/finance/staking-defi/sol/product-info` | GET | 获取SOL质押产品信息 |
| `/api/v5/finance/staking-defi/sol/purchase` | POST | SOL质押申购 |
| `/api/v5/finance/staking-defi/sol/redeem` | POST | SOL质押赎回 |
| `/api/v5/finance/staking-defi/sol/balance` | GET | 获取SOL质押余额 |
| `/api/v5/finance/staking-defi/sol/purchase-redeem-history` | GET | 获取SOL质押历史 |
| `/api/v5/finance/staking-defi/sol/apy-history` | GET | 获取SOL质押APY历史 |

### Savings (余币宝)

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v5/finance/savings/balance` | GET | 获取余币宝余额 |
| `/api/v5/finance/savings/purchase-redempt` | POST | 余币宝申购/赎回 |
| `/api/v5/finance/savings/set-lending-rate` | POST | 设置出借利率 |
| `/api/v5/finance/savings/lending-history` | GET | 获取出借历史 |
| `/api/v5/finance/savings/lending-rate-summary` | GET | 获取出借利率汇总 |
| `/api/v5/finance/savings/lending-rate-history` | GET | 获取出借利率历史 |

### Stable Rewards (稳定收益)

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v5/finance/stable-rewards/balance` | GET | 获取稳定收益余额 |
| `/api/v5/finance/stable-rewards/product-info` | GET | 获取稳定收益产品信息 |
| `/api/v5/finance/stable-rewards/apy-history` | GET | 获取APY历史 |
| `/api/v5/finance/stable-rewards/subscribe-redeem-history` | GET | 获取申购赎回历史 |
| `/api/v5/finance/stable-rewards/quote` | POST | 报价 |
| `/api/v5/finance/stable-rewards/trade` | POST | 交易 |

### Flexible Loan (活期借贷)

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v5/finance/flexible-loan/borrow-currencies` | GET | 获取可借币种 |
| `/api/v5/finance/flexible-loan/collateral-assets` | GET | 获取抵押资产 |
| `/api/v5/finance/flexible-loan/max-loan` | GET | 获取最大可借 |
| `/api/v5/finance/flexible-loan/max-collateral-redeem-amount` | GET | 获取最大可赎回抵押 |
| `/api/v5/finance/flexible-loan/adjust-collateral` | POST | 调整抵押物 |
| `/api/v5/finance/flexible-loan/loan-info` | GET | 获取借贷信息 |
| `/api/v5/finance/flexible-loan/loan-history` | GET | 获取借贷历史 |
| `/api/v5/finance/flexible-loan/interest-accrued` | GET | 获取借贷计息记录 |

### Dual Investment (双币赢/鲨鱼鳍 DCD)

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v5/finance/sfp/dcd/currency-pair` | GET | 获取双币赢币对 |
| `/api/v5/finance/sfp/dcd/products` | GET | 获取双币赢产品 |
| `/api/v5/finance/sfp/dcd/quote` | POST | 请求双币赢报价 |
| `/api/v5/finance/sfp/dcd/trade` | POST | 双币赢交易 |
| `/api/v5/finance/sfp/dcd/redeem-quote` | POST | 请求双币赢赎回报价 |
| `/api/v5/finance/sfp/dcd/redeem` | POST | 双币赢赎回 |
| `/api/v5/finance/sfp/dcd/order-status` | GET | 获取双币赢订单状态 |
| `/api/v5/finance/sfp/dcd/order-history` | GET | 获取双币赢订单历史 |

### OKUSD

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v5/finance/okusd/subscribe` | POST | OKUSD申购 |
| `/api/v5/finance/okusd/redeem` | POST | OKUSD赎回 |
| `/api/v5/finance/okusd/limits` | GET | 获取OKUSD限额 |

---

## 十一、Copy Trading (跟单交易) - 需认证

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v5/copytrading/current-subpositions` | GET | 获取当前跟单持仓 |
| `/api/v5/copytrading/subpositions-history` | GET | 获取跟单持仓历史 |
| `/api/v5/copytrading/algo-order` | POST | 设置跟单止盈止损 |
| `/api/v5/copytrading/close-subposition` | POST | 平仓跟单持仓 |
| `/api/v5/copytrading/instruments` | GET | 获取跟单交易产品 |
| `/api/v5/copytrading/set-instruments` | POST | 修改跟单交易产品 |
| `/api/v5/copytrading/first-copy-settings` | POST | 首次跟单设置 |
| `/api/v5/copytrading/amend-copy-settings` | POST | 修改跟单设置 |
| `/api/v5/copytrading/stop-copy-trading` | POST | 停止跟单 |
| `/api/v5/copytrading/amend-profit-sharing-ratio` | POST | 修改分润比例 |
| `/api/v5/copytrading/profit-sharing-details` | GET | 获取分润详情 |
| `/api/v5/copytrading/total-profit-sharing` | GET | 获取总分润 |
| `/api/v5/copytrading/total-unrealized-profit-sharing` | GET | 获取总未实现分润 |
| `/api/v5/copytrading/unrealized-profit-sharing-details` | GET | 获取未实现分润详情 |

---

## 十二、Spread Trading (价差交易) - 需认证

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v5/sprd/order` | POST | 价差下单 |
| `/api/v5/sprd/amend-order` | POST | 修改价差订单 |
| `/api/v5/sprd/cancel-order` | POST | 撤销价差订单 |
| `/api/v5/sprd/mass-cancel` | POST | 批量撤销价差订单 |
| `/api/v5/sprd/cancel-all-after` | POST | 定时撤销价差 |
| `/api/v5/sprd/order` | GET | 获取价差订单详情 |
| `/api/v5/sprd/orders-pending` | GET | 获取未成交价差订单 |
| `/api/v5/sprd/orders-history` | GET | 获取价差订单历史 |
| `/api/v5/sprd/orders-history-archive` | GET | 获取价差订单历史归档 |
| `/api/v5/sprd/trades` | GET | 获取价差成交 |
| `/api/v5/sprd/spreads` | GET | 获取价差产品 |
| `/api/v5/sprd/books` | GET | 获取价差深度 |
| `/api/v5/sprd/public-trades` | GET | 获取价差公开成交 |

---

## 十三、Trading Data (交易数据/Rubik) - 无需认证

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v5/rubik/stat/trading-data/support-coin` | GET | 获取支持的币种 |
| `/api/v5/rubik/stat/taker-volume` | GET | 获取主动成交量 |
| `/api/v5/rubik/stat/taker-volume-contract` | GET | 获取合约主动成交量 |
| `/api/v5/rubik/stat/margin/loan-ratio` | GET | 获取杠杆借币比例 |
| `/api/v5/rubik/stat/contracts/long-short-account-ratio` | GET | 获取合约多空比 |
| `/api/v5/rubik/stat/contracts/long-short-account-ratio-contract` | GET | 获取合约多空账户比 |
| `/api/v5/rubik/stat/contracts/long-short-account-ratio-contract-top-trader` | GET | 获取顶级交易员多空账户比 |
| `/api/v5/rubik/stat/contracts/long-short-position-ratio-contract-top-trader` | GET | 获取顶级交易员持仓比 |
| `/api/v5/rubik/stat/contracts/open-interest-volume` | GET | 获取合约持仓量 |
| `/api/v5/rubik/stat/contracts/open-interest-history` | GET | 获取合约持仓量历史 |
| `/api/v5/rubik/stat/option/open-interest-volume` | GET | 获取期权持仓量 |
| `/api/v5/rubik/stat/option/open-interest-volume-ratio` | GET | 获取期权看跌/看涨比 |
| `/api/v5/rubik/stat/option/open-interest-volume-expiry` | GET | 获取期权到期持仓量 |
| `/api/v5/rubik/stat/option/open-interest-volume-strike` | GET | 获取期权行权价持仓量 |
| `/api/v5/rubik/stat/option/taker-block-volume` | GET | 获取期权主动成交 |

---

## 十四、Fiat (法币) - 需认证

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v5/fiat/buy-sell/currencies` | GET | 获取法币币种 |
| `/api/v5/fiat/buy-sell/currency-pair` | GET | 获取法币币对 |
| `/api/v5/fiat/buy-sell/history` | GET | 获取法币历史 |
| `/api/v5/fiat/buy-sell/quote` | POST | 法币询价 |
| `/api/v5/fiat/buy-sell/trade` | POST | 法币交易 |

---

## 十五、其他

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v5/system/status` | GET | 获取系统状态 |
| `/api/v5/support/announcements` | GET | 获取公告 |
| `/api/v5/support/announcement-types` | GET | 获取公告类型 |
| `/api/v5/broker/fd/rebate-per-orders` | GET | 获取返佣订单 |
| `/api/v5/broker/fd/rebate-per-orders` | POST | 设置返佣订单 |

---

## REST API 错误码速查

### 通用

| 错误码 | 说明 |
|--------|------|
| `0` | 成功 |
| `1` | 操作全部失败 |
| `2` | 批量操作部分成功 |
| `50000` | 内部系统错误 |
| `50001` | 未知错误 |
| `50002` | 服务不可用 |
| `50004` | 请求超时 |
| `50011` | 用户请求频率过快，超过该接口允许的限额 |
| `50013` | 系统繁忙，请稍后重试 |
| `50026` | 系统繁忙，请稍后重试 |
| `50044` | 系统繁忙，请稍后重试 |
| `50061` | 子账户订单请求频率过快 |

### API 认证类 (501xx)

| 错误码 | 说明 |
|--------|------|
| `50100` | API Key 与请求环境不匹配 |
| `50101` | API Key 不存在 |
| `50102` | 请求时间戳过期（服务器时间差超过30秒） |
| `50103` | 请求头中缺少 OK-ACCESS-KEY |
| `50104` | 请求头中缺少 OK-ACCESS-SIGN |
| `50105` | 请求头中缺少 OK-ACCESS-TIMESTAMP |
| `50106` | 请求头中缺少 OK-ACCESS-PASSPHRASE |
| `50107` | 无效的 OK-ACCESS-KEY |
| `50108` | 无效的 OK-ACCESS-SIGN |
| `50109` | 无效的 OK-ACCESS-PASSPHRASE |
| `50110` | IP 不在白名单中 |
| `50111` | API Key 权限不足 |
| `50112` | API Key 已过期 |
| `50113` | 无效的签名 |
| `50114` | API Key 被冻结 |
| `50115` | 不支持的认证方式 |
| `50122` | 模拟盘请求头缺少 x-simulated-trading |

### 交易类 (510xx-516xx)

| 错误码 | 说明 |
|--------|------|
| `51000` | 参数错误 |
| `51001` | 交易产品ID不存在 |
| `51002` | 订单ID不存在 |
| `51006` | 订单价格不在限价范围内 |
| `51008` | 订单类型不支持 |
| `51009` | 订单数量超过最大限制 |
| `51010` | 订单数量低于最小限制 |
| `51011` | 可用余额不足 |
| `51020` | 订单不在待处理状态 |
| `51021` | 订单已成交 |
| `51022` | 订单已撤销 |
| `51023` | 订单无法撤销 |
| `51024` | 账户被冻结 |
| `51044` | 订单不在待处理状态 |
| `51046` | 订单类型不支持修改 |
| `51100` | 交易量超过限制 |
| `51108` | 杠杆不在有效范围内 |
| `51111` | 持仓模式无效 |
| `51112` | 订单数量小于最小值 |
| `51119` | 订单修改网络繁忙 |
| `51120` | 订单数量超过持仓限制 |
| `51131` | 账户无交易权限 |
| `51201` | 客户自定义订单ID已存在 |
| `51205` | 订单未找到 |
| `51300` | 产品不支持 |
| `51321` | 请求过于频繁 |
| `51400` | 撤单失败 |
| `51401` | 修改订单失败 |
| `51405` | 撤单失败，订单未找到 |
| `51406` | 修改订单失败，订单未找到 |
| `51410` | 撤单失败，订单已完成 |
| `51500` | 下单失败 |
| `51600` | 账户无交易权限 |
| `51601` | 账户未授权 |
| `51602` | 账户被冻结 |
| `51603` | 账户不在白名单中 |
| `51625` | 预检查失败 |

### 金融类 (517xx)

| 错误码 | 说明 |
|--------|------|
| `51700` | 金融产品不存在 |
| `51702` | API Key 无效 |
| `51703` | API Key 未授权 |
| `51704` | API Key 已过期 |
| `51732` | API Key 无效 |

### 账户/权限类 (519xx, 520xx, 529xx)

| 错误码 | 说明 |
|--------|------|
| `51900` | 账户无操作权限 |
| `52000` | 划转失败 |
| `52900` | 价差交易产品不存在 |
| `52901` | 价差订单不存在 |
| `52925` | 闪兑失败 |

### 资金/提币类 (530xx, 540xx, 580xx)

| 错误码 | 说明 |
|--------|------|
| `53000` | 提币超过限额 |
| `53001` | 提币低于最小值 |
| `53002` | 提币地址无效 |
| `53008` | 提币金额超过可用余额 |
| `53017` | 风控限制提币 |
| `54000` | 保证金不足 |
| `54048` | 借贷限额不足 |
| `55000` | 保证金不足（永续合约） |
| `55500` | 系统繁忙 |
| `58000` | 网络繁忙 |
| `58001` | 服务不可用 |
| `58100-58140` | 服务不可用 |
| `58200-58212` | 提币不可用 |
| `58300-58352` | 账户不可用 |

### 订单/持仓类 (590xx-591xx)

| 错误码 | 说明 |
|--------|------|
| `59000-59011` | 订单不可用 |
| `59100-59112` | 持仓不可用 |

### 策略委托/跟单类 (592xx-593xx)

| 错误码 | 说明 |
|--------|------|
| `59200-59206` | 策略委托不可用 |
| `59206` | 该带单交易员已无更多跟单空位 |
| `59216` | 仓位不存在 |
| `59218` | 市价全平中 |
| `59245` | 单次下单张数超限 |
| `59247` | 杠杆倍数过高 |
| `59256` | 无法切换为买卖模式 |
| `59260` | 不是现货带单交易员 |
| `59262` | 不是合约带单交易员 |
| `59263` | 仅白名单用户支持跟单 |
| `59264` | 不支持现货跟单 |
| `59267` | 跟单关系不存在 |
| `59270` | 最大跟单金额需大于等于单笔跟单金额 |
| `59273` | 不是合约跟单用户 |
| `59274` | 无法跟自己带的单 |
| `59277` | 到达跟单人数上限 |
| `59279` | 已设置跟单，勿重复设置 |
| `59280` | 跟单关系不存在 |
| `59284` | 超过本月调整上限 |
| `59287` | 分润比例不在有效范围 |
| `59292` | 该带单交易员未开启自定义跟单模式 |
| `59300-59307` | 大宗交易/跟单不可用 |

### 价差交易类 (594xx)

| 错误码 | 说明 |
|--------|------|
| `59400-59417` | 价差交易不可用 |

### 交易机器人类 (595xx)

| 错误码 | 说明 |
|--------|------|
| `59500-59529` | 交易机器人不可用 |

### 子账户/账户配置类 (596xx)

| 错误码 | 说明 |
|--------|------|
| `59601` | 子账户名称已存在 |
| `59603` | 创建的子账户数量已达上限 |
| `59604` | 仅母账户APIKey有操作此接口的权限 |
| `59606` | 删除失败，请将子账户余额划转至母账户 |
| `59608` | 仅Broker账户有操作此接口的权限 |
| `59613` | 当前未与子账户建立托管关系 |
| `59614` | 托管子账户不支持此操作 |
| `59615` | 起始日期和结束日期的时间间隔不能超过180天 |
| `59616` | 起始日期不能大于结束日期 |
| `59641` | 有定期借币，无法切换账户模式 |
| `59642` | 跟单和带单员只能使用现货或合约模式 |
| `59643` | 存在现货跟单，暂不可切换 |
| `59648-59652` | 现货对冲相关 |
| `59658-59667` | 质押资产相关 |
| `59668-59670` | 杠杆调整相关 |
| `59671-59676` | 自动赚币相关 |
| `59678-59679` | 切换手续费币种相关 |
| `59683-59686` | 结算币种相关 |
| `59689-59693` | 兑换/余额相关 |

### 大宗交易 RFQ (700xx)

| 错误码 | 说明 |
|--------|------|
| `70000` | 询价单不存在 |
| `70001` | 报价单不存在 |
| `70002` | 大宗交易不存在 |
| `70003` | 公共的大宗交易不存在 |
| `70004` | 无效的产品ID |
| `70005` | 组合交易的数量超过最大值 |
| `70006` | 不满足最小资产要求 |
| `70007` | 产品类型标的指数不存在 |
| `70008` | MMP状态下操作失败 |
| `70009` | Data数组必须至少含有一个有效元素 |
| `70010` | 时间戳参数必须是Unix毫秒格式 |
| `70011` | 产品类型存在重复设置 |
| `70012` | instFamily/instId 存在重复设置 |
| `70013` | endTs必须大于等于beginTs |
| `70014` | 不允许对所有产品类别设置includeAll=True |
| `70015` | 需完成高级身份认证才能交易 |
| `70016` | 需选择至少一个交易品种 |
| `70060-70067` | 仓位转移相关 |
| `70100` | 组合交易中产品ID重复 |
| `70101` | clRfqId重复 |
| `70102` | 未指定对手方 |
| `70103` | 无效的对手方 |
| `70105` | 非全现货RFQ总价值应大于最小名义值 |
| `70106` | 下单数量小于最小交易数量 |
| `70107` | 对手方数量不能超过最大值 |
| `70108` | 全现货RFQ总价值应大于最小名义值 |
| `70109` | 所选产品无有效对手方 |
| `70200` | 不能取消该状态的询价单 |
| `70203` | 取消失败，询价单数量超过限制 |
| `70207` | 取消失败，没有询价挂单 |
| `70208` | 取消失败，服务暂时不可用 |
| `70301` | clQuoteId重复 |
| `70303` | 不能对该状态询价单报价 |
| `70304` | 价格应为下单价格精度整数倍 |
| `70305` | 买入价格不能高于报价 |
| `70306` | 报价组合交易不匹配 |
| `70307` | 数量应为下单数量精度整数倍 |
| `70308` | 不允许对自己的询价单报价 |
| `70309` | 不允许同一方向重复报价 |
| `70310` | 报价超过预设价格限制 |
| `70400` | 不能取消该状态报价单 |
| `70408` | 取消失败，报价单数量超限 |
| `70409` | 取消失败，没有报价挂单 |
| `70501-70518` | 执行报价相关错误 |

### 价差交易 (750xx)

| 错误码 | 说明 |
|--------|------|
| `75001` | 交易ID不存在 |
| `75002` | 目前无法下新订单或修改现有订单 |
| `75003` | 价格无效 |

### 大宗交易 Block (560xx)

| 错误码 | 说明 |
|--------|------|
| `56000` | 大宗交易不存在 |
| `56001` | 多腿数量不能超过限制 |
| `56002` | 执行和验证的多腿数量不匹配 |
| `56003` | 重复的clBlockTdId |
| `56004` | 不允许自成交 |
| `56005` | 执行和验证的clBlockTdId不匹配 |
| `56006` | 执行和验证的角色不能相同 |
| `56007` | 执行和验证的腿不匹配 |
| `56008` | 重复的产品名称 |

### 策略交易 (551xx)

| 错误码 | 说明 |
|--------|------|
| `55100` | 止盈百分比应在范围内 |
| `55101` | 止损百分比应在范围内 |
| `55102` | 止盈百分比需大于当前策略收益率 |
| `55103` | 止损百分比需小于当前策略收益率 |
| `55104` | 仅合约网格支持按收益率止盈止损 |
| `55105` | 当前状态不支持加仓操作 |
| `55106` | 加仓金额应在范围内 |
| `55111` | 信号名称正在使用中 |
| `55112` | 信号不存在 |
| `55113` | 创建信号策略杠杆倍数大于最大杠杆 |
| `55116` | 每个交易对只能进行一笔追逐限价委托 |

---

## WebSocket 错误码

### 公共错误 (600xx-640xx)

| 错误码 | 错误消息 |
|--------|---------|
| `60004` | 无效的 timestamp |
| `60005` | 无效的 apiKey |
| `60006` | 请求时间戳过期 |
| `60007` | 无效的签名 |
| `60008` | 当前服务不支持订阅该频道，请检查WebSocket地址 |
| `60009` | 登录失败 |
| `60011` | 用户需要登录 |
| `60012` | 不合法的请求 |
| `60013` | 无效的参数 args |
| `60014` | 用户请求频率过快 |
| `60018` | 错误的 URL 或频道不存在 |
| `60019` | 无效的op |
| `60023` | 批量登录请求过于频繁 |
| `60024` | passphrase不正确 |
| `60026` | 不支持APIKey和token同时登录 |
| `60027` | 参数不可为空 |
| `60028` | 当前服务不支持此功能 |
| `60031` | WebSocket地址不支持多账户和重复登录 |
| `60032` | API key 不存在 |
| `60033` | 参数错误 |
| `63999` | 由于内部错误，登录失败 |
| `64000` | 订阅参数 uly 已失效，请替换为 instFamily |
| `64001` | 该频道已迁移到 '/business' URL |
| `64002` | "/business" URL 不支持该频道 |
| `64003` | 用户交易费等级不支持访问该频道 |
| `64004` | 不允许同时订阅该频道和 books-l2-tbt |
| `64007` | WebSocket 内部错误导致操作失败 |
| `64008` | 因服务升级，该连接即将关闭 |

### 关闭帧 (Close Frame)

| 状态码 | 文案 |
|--------|------|
| `1009` | 用户订阅请求过大 |
| `4001` | 登录失败 |
| `4002` | 参数不合法 |
| `4003` | 登录账户多于100个 |
| `4004` | 空闲超时30秒 |
| `4005` | 写缓冲区满 |
| `4006` | 异常场景关闭 |
| `4007` | API key已更新或删除，请重新连接 |
| `4008` | 总订阅频道数量超过最大限制 |
| `4009` | 该连接订阅频道数超限制 |

---

## 使用建议

1. **REST Base URL**: 实盘 `https://openapi.okx.com`，不是 `https://www.okx.com`
2. 查询接口优先使用 `GET`，操作类接口使用 `POST`
3. 时间戳必须为 UTC 时间，格式 `2020-12-08T09:08:57.715Z`
4. 模拟盘交易在请求头加 `x-simulated-trading: 1`
5. 遇到 `50011` 错误时减少请求频率
6. 遇到 `50102` 时检查系统时间同步，先调用 `/api/v5/public/time`
7. 错误码 `0` 表示成功，非 `0` 表示失败
8. WebSocket 保持心跳：30秒内无数据需发送 `ping` 字符串