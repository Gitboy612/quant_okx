# OKX 量化交易本地平台 — 技术实施计划

---

## 1. 摘要

构建一个本地运行的 OKX 量化交易平台，支持现货+合约交易，内置网格/趋势跟随/套利三种策略，通过 React 前端仪表盘实现可视化监控、策略切换、参数动态调整和收益分析。OKX API Key 采用 AES-256 加密存储，所有策略操作全程审计记录。

---

## 2. 当前状态

- 项目目录 `e:\New folder (2)\quant_okx` 为空目录，全新项目从零搭建。
- 无现有代码、配置或依赖。

---

## 3. 设计理念 (frontend-skill)

### Visual Thesis
冷静、精密、专业的量化操作面板 — 深色底、单一强调色、高密度但可扫读的信息层级，传递「可控、可信、高效」的操作氛围。

### Content Plan (App UI — 无 Hero)
1. **登录页** — 管理员认证入口，极简居中表单
2. **仪表盘主页** — 账户总览 KPI（权益/盈亏/仓位）+ 策略运行状态一览
3. **策略管理** — 策略列表、启动/暂停/停止、参数面板
4. **交易记录** — 订单历史、成交明细、操作日志
5. **账户管理** — OKX 账户 API Key 管理（加密存储）

### Interaction Thesis
1. **数字滚动入场** — KPI 数字从 0 递增到实际值的计数动画
2. **面板切换过渡** — 侧边栏导航配合 shared layout 过渡
3. **策略状态脉冲** — 运行中策略的状态指示器带呼吸灯脉冲动画

---

## 4. 技术架构

```
┌──────────────────────────────────────────────────┐
│              React + TypeScript (Vite)            │
│   Recharts / Framer Motion / Tailwind CSS         │
│              ↕ REST + WebSocket                   │
│           Python FastAPI (uvicorn)                │
│   Strategy Engine / OKX Connector / Scheduler     │
│              ↕ SQLite (encrypted)                 │
└──────────────────────────────────────────────────┘
```

| 层 | 技术 | 理由 |
|---|---|---|
| 前端 | React 18 + TypeScript + Vite | 生态完善，Framer Motion + Recharts 支持好 |
| 样式 | Tailwind CSS | 快速构建深色主题，原子化样式 |
| 动画 | Framer Motion | 布局过渡、KPI 计数动画 |
| 图表 | Recharts | React 原生，轻量，渲染准确 |
| 后端 | Python 3.11+ FastAPI | 异步支持，WebSocket 原生，量化生态好 |
| ORM | SQLAlchemy + SQLite | 本地零配置，单文件数据库 |
| 加密 | cryptography (Fernet/AES-256) | API Key 加密存储 |
| OKX SDK | python-okx (官方) | 官方维护，V5 API 完整覆盖 |
| 调度 | APScheduler | 策略定时执行、市场数据轮询 |

---

## 5. 数据库设计

### 表结构 (SQLite)

```sql
-- 管理员用户
users (
    id INTEGER PK,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMP
)

-- OKX 交易账户 (API Key 加密存储)
accounts (
    id INTEGER PK,
    name TEXT NOT NULL,
    api_key_encrypted TEXT NOT NULL,      -- AES-256 加密
    secret_key_encrypted TEXT NOT NULL,   -- AES-256 加密
    passphrase_encrypted TEXT,            -- AES-256 加密 (如有)
    trade_mode TEXT DEFAULT 'demo',       -- 'demo' | 'live'
    exchange TEXT DEFAULT 'okx',
    is_active BOOLEAN DEFAULT 1,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
)

-- 策略模板定义
strategy_templates (
    id INTEGER PK,
    name TEXT NOT NULL,                    -- '网格交易' | '趋势跟随' | '期现套利'
    strategy_type TEXT NOT NULL,           -- 'grid' | 'trend' | 'arbitrage'
    description TEXT,
    default_params JSON NOT NULL,          -- 默认参数
    is_builtin BOOLEAN DEFAULT 0,
    created_at TIMESTAMP
)

-- 策略实例 (绑定账户的策略运行实例)
strategy_instances (
    id INTEGER PK,
    template_id INTEGER FK,
    account_id INTEGER FK,
    name TEXT NOT NULL,
    symbol TEXT NOT NULL,                  -- 交易对 e.g. 'BTC-USDT-SWAP'
    market_type TEXT NOT NULL,             -- 'spot' | 'swap' | 'futures'
    params JSON NOT NULL,                  -- 当前参数
    status TEXT DEFAULT 'stopped',         -- 'running' | 'paused' | 'stopped' | 'error'
    started_at TIMESTAMP,
    stopped_at TIMESTAMP,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
)

-- 交易订单记录
orders (
    id INTEGER PK,
    strategy_instance_id INTEGER FK,
    account_id INTEGER FK,
    symbol TEXT NOT NULL,
    order_id TEXT,                         -- OKX 返回的订单ID
    side TEXT NOT NULL,                    -- 'buy' | 'sell'
    order_type TEXT NOT NULL,              -- 'limit' | 'market'
    price REAL,
    quantity REAL,
    filled_quantity REAL DEFAULT 0,
    status TEXT,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
)

-- 盈亏快照 (定时记录)
pnl_records (
    id INTEGER PK,
    account_id INTEGER FK,
    strategy_instance_id INTEGER FK,
    equity REAL,                           -- 账户权益
    unrealized_pnl REAL,                   -- 未实现盈亏
    realized_pnl REAL,                     -- 已实现盈亏
    total_pnl REAL,                        -- 总盈亏
    recorded_at TIMESTAMP
)

-- 操作日志 (审计)
operation_logs (
    id INTEGER PK,
    user_id INTEGER FK,
    action TEXT NOT NULL,                  -- 'login' | 'start_strategy' | 'stop_strategy' | 'update_params' | 'add_account' | etc.
    target_type TEXT,                      -- 'strategy' | 'account' | 'system'
    target_id INTEGER,
    detail JSON,                           -- 操作详情
    ip_address TEXT,
    created_at TIMESTAMP
)
```

---

## 6. API 设计

### REST API

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/auth/login` | 管理员登录，返回 JWT token |
| GET | `/api/auth/me` | 获取当前用户信息 |
| POST | `/api/accounts` | 添加 OKX 账户 (API Key 前端传输时临时加密) |
| GET | `/api/accounts` | 账户列表 (不返回解密后的 secret) |
| DELETE | `/api/accounts/{id}` | 删除账户 |
| PUT | `/api/accounts/{id}` | 更新账户信息 |
| GET | `/api/accounts/{id}/balance` | 查询账户余额 (实时调用 OKX API) |
| GET | `/api/strategies/templates` | 策略模板列表 |
| GET | `/api/strategies/instances` | 策略实例列表 (含运行状态) |
| POST | `/api/strategies/instances` | 创建策略实例 |
| PUT | `/api/strategies/instances/{id}` | 更新策略实例参数 |
| DELETE | `/api/strategies/instances/{id}` | 删除策略实例 |
| POST | `/api/strategies/instances/{id}/start` | 启动策略 |
| POST | `/api/strategies/instances/{id}/pause` | 暂停策略 |
| POST | `/api/strategies/instances/{id}/stop` | 停止策略 |
| GET | `/api/pnl` | 盈亏记录 (支持时间范围、账户、策略筛选) |
| GET | `/api/pnl/summary` | 盈亏汇总 (总盈亏、日盈亏、胜率等) |
| GET | `/api/orders` | 订单历史 |
| GET | `/api/logs` | 操作日志 (分页、筛选) |
| GET | `/api/market/ticker/{symbol}` | 实时行情 |

### WebSocket

| 端点 | 说明 |
|---|---|
| `/ws/strategy/{instance_id}` | 策略实时状态推送 (订单、盈亏、日志) |
| `/ws/dashboard` | 仪表盘聚合数据推送 (所有策略状态、KPI 摘要) |

---

## 7. 策略引擎设计

### 网格交易 (Grid Strategy)
```
参数: upper_price, lower_price, grid_count, order_qty, symbol
逻辑:
  - 在 [lower_price, upper_price] 区间均匀布网格线
  - 价格触及网格线时：上方卖出、下方买入
  - 记录每笔成交，计算网格收益
```

### 趋势跟随 (Trend Following Strategy)
```
参数: fast_ma_period, slow_ma_period, order_qty, symbol
逻辑:
  - 快线上穿慢线 → 开多 / 平空
  - 快线下穿慢线 → 开空 / 平多
  - 基于 MA 交叉信号执行
```

### 期现套利 (Arbitrage Strategy)
```
参数: spot_symbol, futures_symbol, spread_threshold, order_qty
逻辑:
  - 监控现货与合约价差
  - 价差 > 阈值 → 卖合约买现货
  - 价差回归 → 平仓获利
```

### 引擎架构
```
StrategyEngine (单例)
  ├── GridStrategy (继承 BaseStrategy)
  ├── TrendStrategy (继承 BaseStrategy)
  ├── ArbitrageStrategy (继承 BaseStrategy)
  └── StrategyScheduler (APScheduler 管理定时/轮询)
      └── 每个策略实例独立线程/协程
```

---

## 8. 安全设计

### API Key 加密方案
```
加密算法: AES-256-CBC (via cryptography.Fernet)
密钥管理:
  - 首次启动时生成随机 256-bit 主密钥
  - 主密钥存储在本地文件 (keyfile)，权限 600
  - 所有 API Key/Secret/Passphrase 用主密钥加密后存入 SQLite

前端传输:
  - 前端到后端全程 HTTPS (本地 localhost 可用 HTTP)
  - API Key 提交时用 session 临时密钥加密
  - 后端收到后立即用主密钥加密落库
  - 绝不将解密后的 secret 返回给前端
```

### 认证方案
```
- JWT token 认证，有效期 24 小时
- 密码 bcrypt 哈希存储
- 登录失败 5 次锁定 15 分钟
- 所有 API 请求需 Bearer token (除 login)
```

---

## 9. 前端页面设计

### 设计系统

| 属性 | 值 |
|---|---|
| 主背景 | `#0A0A0F` (接近纯黑) |
| 面板背景 | `#14141A` |
| 边框/分割 | `#1E1E28` |
| 主文字 | `#E8E8ED` |
| 次文字 | `#6B6B7B` |
| 强调色 | `#00D4AA` (青绿色，仅一处) |
| 多头/盈利 | `#00D4AA` |
| 空头/亏损 | `#FF4757` |
| 字体 | Inter (UI) + JetBrains Mono (数字/代码) |

### 页面结构

#### 1. 登录页 (`/login`)
- 深色全屏背景，居中 400px 宽表单
- 品牌名 "QuantOKX" 顶部大字
- 用户名 + 密码输入框 + 登录按钮
- 登录失败动画抖动提示
- 登录成功 → 路由跳转 `/dashboard`

#### 2. 仪表盘 (`/dashboard`)
```
┌────────────────────────────────────────────┐
│  Sidebar (固定左侧 240px)                   │
│  ├── Logo / QuantOKX                       │
│  ├── 仪表盘 (active)                       │
│  ├── 策略管理                              │
│  ├── 交易记录                              │
│  ├── 账户管理                              │
│  └── 操作日志                              │
├────────────────────────────────────────────┤
│  Top Bar (账户选择器 + 时间范围)            │
├────────────────────────────────────────────┤
│  KPI Row (4 个数字指标)                     │
│  [总权益] [未实现盈亏] [已实现盈亏] [策略数] │
├──────────────────┬────────────────────────-┤
│  PnL 曲线图      │  策略状态列表             │
│  (Recharts 面    │  (运行中/暂停/停止        │
│   积图)          │   状态指示器脉冲)         │
├──────────────────┴────────────────────────-┤
│  最近交易记录 (精简表格)                    │
└────────────────────────────────────────────┘
```

#### 3. 策略管理 (`/strategies`)
```
┌────────────────────────────────────────────┐
│  策略实例列表                               │
│  ┌──────────────────────────────────────┐  │
│  │ BTC网格 #1  ● 运行中   [暂停][停止]  │  │
│  │ ETH趋势 #1  ● 运行中   [暂停][停止]  │  │
│  │ 套利 #1     ◐ 已暂停   [启动][停止]  │  │
│  └──────────────────────────────────────┘  │
│                                            │
│  [+ 新建策略] 按钮 → 弹出策略配置面板       │
│                                            │
│  点击策略行 → 展开参数面板 (可动态调整)     │
│  ┌──────────────────────────────────────┐  │
│  │ 网格参数: upper_price, lower_price,  │  │
│  │ grid_count, order_qty               │  │
│  │ [保存参数]  (运行中也可调)            │  │
│  └──────────────────────────────────────┘  │
└────────────────────────────────────────────┘
```

#### 4. 交易记录 (`/orders`)
- 筛选器: 账户 / 策略 / 交易对 / 时间范围
- 订单表格: 时间、交易对、方向、价格、数量、状态
- CSV 导出按钮

#### 5. 账户管理 (`/accounts`)
- OKX 账户列表
- 添加账户: API Key / Secret / Passphrase 表单
- 每个账户显示: 名称、模式(demo/live)、状态、余额摘要
- 删除确认对话框

#### 6. 操作日志 (`/logs`)
- 时间线表格
- 筛选: 操作类型、时间范围
- 每条: 时间、用户、操作、目标、详情

### 动画计划

| 动画 | 技术 | 描述 |
|---|---|---|
| KPI 数字滚动 | Framer Motion `useSpring` | 页面加载时数字从 0 递增到实际值，弹簧缓出 |
| 策略状态脉冲 | CSS `@keyframes` + Framer | 运行中绿点 2s 呼吸脉冲循环 |
| 侧边栏路由切换 | Framer Motion `AnimatePresence` | 页面内容 fade + slide 过渡 |
| 参数面板展开 | Framer Motion `layout` | 策略行点击展开参数面板，共享布局动画 |
| 数据行入场 | Framer Motion `staggerChildren` | 列表数据逐行 staggered 淡入 |

---

## 10. 项目目录结构

```
quant_okx/
├── backend/
│   ├── main.py                    # FastAPI 入口
│   ├── config.py                  # 配置管理 (加密密钥路径、DB路径等)
│   ├── database.py                # SQLAlchemy 初始化
│   ├── models/
│   │   ├── __init__.py
│   │   ├── user.py
│   │   ├── account.py
│   │   ├── strategy.py
│   │   ├── order.py
│   │   ├── pnl.py
│   │   └── log.py
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── auth.py
│   │   ├── account.py
│   │   ├── strategy.py
│   │   └── common.py
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── auth.py
│   │   ├── accounts.py
│   │   ├── strategies.py
│   │   ├── pnl.py
│   │   ├── orders.py
│   │   ├── logs.py
│   │   └── ws.py                  # WebSocket 端点
│   ├── services/
│   │   ├── __init__.py
│   │   ├── auth_service.py
│   │   ├── account_service.py
│   │   ├── encryption_service.py  # AES-256 加密/解密
│   │   ├── okx_client.py         # OKX API 封装
│   │   └── strategy_engine.py    # 策略引擎调度
│   ├── strategies/
│   │   ├── __init__.py
│   │   ├── base_strategy.py       # 策略基类
│   │   ├── grid_strategy.py       # 网格策略
│   │   ├── trend_strategy.py      # 趋势跟随策略
│   │   └── arbitrage_strategy.py  # 套利策略
│   ├── middleware/
│   │   ├── __init__.py
│   │   └── auth.py                # JWT 认证中间件
│   └── requirements.txt
├── frontend/
│   ├── index.html
│   ├── package.json
│   ├── vite.config.ts
│   ├── tailwind.config.js
│   ├── tsconfig.json
│   ├── src/
│   │   ├── main.tsx               # React 入口
│   │   ├── App.tsx                # 路由配置
│   │   ├── index.css              # Tailwind + 全局样式
│   │   ├── api/
│   │   │   ├── client.ts          # axios 实例 + 拦截器
│   │   │   ├── auth.ts
│   │   │   ├── accounts.ts
│   │   │   ├── strategies.ts
│   │   │   ├── pnl.ts
│   │   │   └── useWebSocket.ts    # WebSocket hook
│   │   ├── components/
│   │   │   ├── Layout.tsx         # 侧边栏布局
│   │   │   ├── Sidebar.tsx        # 导航侧边栏
│   │   │   ├── TopBar.tsx         # 顶栏 (账户选择器)
│   │   │   ├── KpiCard.tsx        # KPI 指标卡片
│   │   │   ├── StatusBadge.tsx    # 策略状态指示器
│   │   │   ├── PnLChart.tsx       # 盈亏曲线图
│   │   │   ├── DataTable.tsx      # 通用数据表格
│   │   │   └── Modal.tsx          # 通用对话框
│   │   ├── pages/
│   │   │   ├── LoginPage.tsx
│   │   │   ├── DashboardPage.tsx
│   │   │   ├── StrategiesPage.tsx
│   │   │   ├── OrdersPage.tsx
│   │   │   ├── AccountsPage.tsx
│   │   │   └── LogsPage.tsx
│   │   ├── hooks/
│   │   │   ├── useAuth.ts
│   │   │   ├── useCountUp.ts      # KPI 数字滚动 hook
│   │   │   └── useWebSocket.ts
│   │   └── types/
│   │       └── index.ts           # TypeScript 类型定义
│   └── public/
│       └── favicon.svg
└── start.bat                       # Windows 一键启动脚本
```

---

## 11. 实施步骤

### Phase 1: 后端基础设施
1. 初始化 Python 项目，安装 FastAPI / SQLAlchemy / python-okx / cryptography / APScheduler
2. 实现 `config.py`、`database.py`、加密服务 `encryption_service.py`
3. 创建所有数据模型 (models/)
4. 实现认证系统 (JWT + bcrypt) + 用户模型种子数据

### Phase 2: OKX 集成 + 策略引擎
5. 封装 `okx_client.py` (现货/合约行情、下单、余额查询)
6. 实现 `base_strategy.py` 策略基类
7. 依次实现网格、趋势跟随、套利三种策略
8. 实现 `strategy_engine.py` 调度器 (APScheduler)
9. 完善 REST API 路由 (accounts / strategies / pnl / orders / logs)
10. 实现 WebSocket 端点

### Phase 3: 前端框架
11. 初始化 Vite + React + TypeScript + Tailwind 项目
12. 实现 Layout / Sidebar / TopBar 布局组件
13. 实现登录页 + 认证逻辑
14. 实现 API client + useWebSocket hook

### Phase 4: 前端页面
15. 实现仪表盘 (KPI 卡片 + PnL 图表 + 策略状态列表)
16. 实现策略管理页 (列表 + 创建/暂停/停止 + 参数面板)
17. 实现交易记录页 (筛选 + 表格)
18. 实现账户管理页 (CRUD + 加密传输)
19. 实现操作日志页

### Phase 5: 动画 + 打磨
20. KPI 数字滚动计数动画
21. 策略状态脉冲动画
22. 页面过渡动画
23. 数据行 staggered 动画

### Phase 6: 测试 + 启动
24. 编写 `start.bat` 一键启动脚本
25. 端到端测试 (使用 OKX Demo 账户)

---

## 12. 验证方式

- 后端: `uvicorn backend.main:app --reload` 启动后，访问 `/docs` 查看 Swagger API 文档
- 前端: `npm run dev` 启动后，浏览器访问 `http://localhost:5173`
- 功能验证: 使用 OKX Demo Trading API 创建模拟账户，部署网格策略，观察订单生成和 PnL 曲线
- 安全验证: 检查 SQLite 中 `api_key_encrypted` 字段为密文，前端不展示 secret
- 日志验证: 每次策略启动/停止/参数修改均在 `operation_logs` 表中生成记录

---

## 13. 假设与决策

| 决策 | 理由 |
|---|---|
| 本地单用户模式 | 符合「本地平台」定位，无需多用户注册系统 |
| SQLite 数据库 | 本地零配置，单文件易备份，数据量可控 |
| 无 Docker | 本地 Windows 平台，用 bat 脚本直接启动更简单 |
| Demo/Live 双模式 | 支持 OKX Demo Trading 模拟交易测试后再切真实交易 |
| 策略独立线程 | 每个策略实例独立协程运行，互不干扰 |
| 前端构建后由 FastAPI 托管静态文件 | 生产模式无需 nginx，单进程部署 |
