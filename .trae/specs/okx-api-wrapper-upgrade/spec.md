# OKX API工具类封装升级 - Product Requirement Document

## Overview
- **Summary**: 将OKX V5 API按照官方文档分类封装为模块化的工具类，优化性能参数，增加连接池复用、异步原生支持、请求限流与重试、参数验证等功能，并为每个接口提供测试用例确保在模拟账户环境下全部跑通。
- **Purpose**: 现有OKXClient类将所有接口混写在一个文件中，缺乏模块化组织，使用同步httpx.Client通过asyncio.to_thread包装，性能和可维护性较差；缺少很多常用API接口（如资金划转、杠杆设置、成交记录、资金费率、产品信息查询等）；没有统一的参数验证和错误处理规范。需要重构为清晰的模块化工具类架构。
- **Target Users**: 量化策略开发者、系统后端服务（策略引擎、订单管理、账户监控等模块）。

## Goals
- 将OKX V5 API按功能分类封装为独立的工具模块
- 优化核心客户端：使用httpx.AsyncClient原生异步，连接池复用，自动时间同步
- 实现请求限流（rate limiting）、智能重试、断路器机制
- 增加完善的参数类型验证和错误处理
- 覆盖交易常用的核心API接口（公共数据、市场数据、账户、交易、资金五大类）
- 为每个封装的接口编写可运行的测试脚本，使用模拟账户验证全部跑通
- 保持向后兼容，现有业务代码（策略、路由等）无需修改或仅需极小修改即可继续使用

## Non-Goals (Out of Scope)
- 不实现OKX V5的全部API（如大宗交易、价差交易、赚币、NFT等小众接口）
- 不重写WebSocket客户端（现有实现可正常工作，本次仅做兼容性适配）
- 不实现跟单、信号策略等高级策略交易API
- 不修改前端代码
- 不处理提币相关的高危接口（出于安全考虑）

## Background & Context
- 项目是一个OKX量化交易平台，后端使用FastAPI + SQLAlchemy，现有OKXClient位于backend/services/okx_client.py
- 现有代码使用同步httpx.Client通过asyncio.to_thread()包装为异步，效率较低
- 现有实现只包含约10个API方法，缺少很多必要接口（如账户配置、账单查询、成交明细、批量撤单等）
- 用户提供了OKX官方文档地址https://www.okx.com/docs-v5/zh和api.pdf作为参考
- 使用模拟盘（demo/simulated trading）进行测试，不用担心资金安全问题
- 现有策略代码（网格、套利等）依赖OKXClient的现有方法，需要保持兼容

## Functional Requirements
- **FR-1**: 核心客户端重构 - 创建OKXBaseClient基类，管理认证、签名、时间同步、连接池、请求发送、日志记录
- **FR-2**: 公共数据模块(PublicAPI) - 封装无需认证的公共接口：服务器时间、交易产品信息、行情接口、指数/资金费率等
- **FR-3**: 市场数据模块(MarketAPI) - 封装行情相关接口：Ticker、K线、深度、成交记录、标记价格等
- **FR-4**: 账户模块(AccountAPI) - 封装账户相关接口：余额、持仓、账单、持仓模式、杠杆设置、账户配置等
- **FR-5**: 交易模块(TradeAPI) - 封装交易相关接口：下单、批量下单、撤单、批量撤单、改单、订单查询、未成交订单、历史订单、成交明细等
- **FR-6**: 资金模块(FundingAPI) - 封装资金相关接口：资金账户余额、资金划转（不包含提币）、充值地址查询、资金费率等
- **FR-7**: OKXClient门面类 - 保持原有接口作为统一入口，组合各模块实例，保持向后兼容
- **FR-8**: 性能优化 - 使用httpx.AsyncClient原生异步、连接池复用、TCP keepalive、合理的超时设置
- **FR-9**: 可靠性增强 - 请求限流（按OKX官方限额）、指数退避重试（针对5xx和网络错误）、时间偏移自动校准
- **FR-10**: 参数验证 - 对关键参数（如instId格式、数量精度、价格精度、买卖方向等）做基础验证
- **FR-11**: 测试脚本 - 在backend/tests/目录下创建测试文件，每个模块对应测试用例，使用模拟账户验证接口可正常调用

## Non-Functional Requirements
- **NFR-1**: 性能 - 原生异步请求比现有asyncio.to_thread方式降低30%以上延迟；连接池复用避免TCP握手开销
- **NFR-2**: 可靠性 - 网络错误和5xx错误自动重试最多3次，指数退避；请求频率不超过OKX官方限额（公共接口20次/2s，私有接口60次/2s）
- **NFR-3**: 可维护性 - 每个模块单一职责，代码清晰，方法命名遵循OKX官方文档语义
- **NFR-4**: 向后兼容 - OKXClient的原有公共方法（get_balance, get_positions, get_ticker, place_order等）保持相同签名，现有业务代码不需要修改
- **NFR-5**: 可测试性 - 所有API方法均可独立测试，提供测试脚本和测试说明文档

## Constraints
- **Technical**: Python 3.10+, httpx作为HTTP客户端（项目已使用），必须支持模拟盘(x-simulated-trading头)
- **Business**: 使用模拟账户测试，不提币，不使用真实资金；保持与现有代码兼容
- **Dependencies**: httpx, 现有加密服务(encryption_service), 现有日志服务(log_service)

## Assumptions
- 用户已有配置好的模拟盘API Key可以用于测试
- 现有.encryption_key和数据库配置可正常工作
- 网络环境可以访问OKX API（或通过代理）
- OKX V5 API接口保持文档描述的兼容性，无重大breaking change

## Acceptance Criteria

### AC-1: 模块化架构清晰
- **Given**: 开发者使用新的OKX API工具类
- **When**: 导入和使用各模块API
- **Then**: 代码按public/market/account/trade/funding分类组织在独立文件中，OKXClient作为门面组合各模块
- **Verification**: `human-judgment`
- **Notes**: 文件结构清晰，职责分明，便于后续扩展和维护

### AC-2: 核心客户端使用原生异步
- **Given**: OKXBaseClient初始化
- **When**: 创建HTTP客户端
- **Then**: 使用httpx.AsyncClient而非同步Client+to_thread包装，配置连接池、keepalive、合理超时
- **Verification**: `programmatic`
- **Notes**: 检查代码中使用AsyncClient，async/await原生调用

### AC-3: 公共数据接口可调用
- **Given**: PublicAPI实例
- **When**: 调用获取服务器时间、产品信息、标记价格等接口
- **Then**: 返回正确的OKX响应数据，code="0"
- **Verification**: `programmatic`
- **Notes**: 测试脚本验证至少3个公共接口正常返回

### AC-4: 市场数据接口可调用
- **Given**: MarketAPI实例
- **When**: 调用get_ticker, get_candles, get_orderbook等接口
- **Then**: 返回正确的行情数据，code="0"
- **Verification**: `programmatic`
- **Notes**: 测试脚本验证Ticker和K线接口正常

### AC-5: 账户接口可调用
- **Given**: AccountAPI实例（使用模拟盘API Key）
- **When**: 调用get_balance, get_positions, get_bills等接口
- **Then**: 返回正确的账户数据，code="0"
- **Verification**: `programmatic`
- **Notes**: 测试脚本验证余额查询、持仓查询正常

### AC-6: 交易接口可调用（模拟盘）
- **Given**: TradeAPI实例（使用模拟盘API Key）
- **When**: 调用下单、撤单、查询订单等接口
- **Then**: 限价单可以成功下单、撤单，订单状态查询正确
- **Verification**: `programmatic`
- **Notes**: 在模拟盘上测试：下单→查询→撤单完整流程

### AC-7: 资金划转接口可调用（模拟盘）
- **Given**: FundingAPI实例（使用模拟盘API Key）
- **When**: 调用资金账户余额查询、交易账户与资金账户间划转
- **Then**: 划转接口正常返回，余额相应变动
- **Verification**: `programmatic`
- **Notes**: 只测试账户内划转，不提币

### AC-8: 原有接口向后兼容
- **Given**: 现有业务代码（grid_strategy.py, accounts.py等）
- **When**: 使用新的OKXClient调用原有方法
- **Then**: get_balance, get_positions, get_ticker, place_order, batch_place_orders, cancel_order, get_order, get_pending_orders, get_orders_history, get_candles等原有方法签名不变，返回格式不变，代码无需修改即可运行
- **Verification**: `programmatic`
- **Notes**: 启动服务和运行策略验证无报错

### AC-9: 请求限流和重试机制生效
- **Given**: 短时间内发起大量请求或遇到网络错误
- **When**: 触发限流或遇到5xx/网络错误
- **Then**: 请求按照配置限流，不超过OKX频率限制；可重试错误自动指数退避重试
- **Verification**: `human-judgment`
- **Notes**: 代码审查确认限流和重试逻辑正确

### AC-10: 所有封装的接口测试通过
- **Given**: backend/tests/目录下的测试脚本
- **When**: 运行测试脚本（使用有效的模拟盘API Key）
- **Then**: 所有封装的API接口均返回code="0"，测试全部通过
- **Verification**: `programmatic`
- **Notes**: 提供测试说明和预期结果

## Open Questions
- [ ] 确认是否需要实现网格策略/策略委托相关API（OKX提供的系统网格API，区别于我们自己实现的网格逻辑）？
- [ ] 是否需要支持子账户API？
- [ ] 除了ETH-USDT-SWAP和BTC-USDT，测试时还需要覆盖哪些交易对？
