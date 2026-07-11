# QuantOKX 用户使用指南

本指南面向 QuantOKX 量化交易平台的最终用户，涵盖从安装启动到策略运行、回测、告警、PnL 归因、沙箱模式等全部功能的操作说明。

---

## 目录

1. [快速开始](#1-快速开始)
2. [账户管理](#2-账户管理)
3. [策略创建](#3-策略创建)
4. [策略运行](#4-策略运行)
5. [历史回测](#5-历史回测)
6. [告警通知](#6-告警通知)
7. [PnL 归因分析](#7-pnl-归因分析)
8. [策略模板分享](#8-策略模板分享)
9. [数据维护](#9-数据维护)
10. [沙箱模式](#10-沙箱模式)

---

## 1. 快速开始

### 1.1 环境要求

- Python 3.11+
- Windows / macOS / Linux
- 网络可访问 OKX API（如遇网络问题可配置代理或 DNS 覆盖）

### 1.2 安装

```bash
# 克隆项目
git clone <项目仓库地址>
cd quant_okx

# 安装依赖（建议使用虚拟环境）
python -m venv venv
# Windows
venv\Scripts\activate
# macOS / Linux
source venv/bin/activate

pip install -r requirements.txt
```

### 1.3 启动服务

```bash
# 开发模式（自动热重载）
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000

# 生产模式
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

启动成功后，控制台会输出：

```
INFO:     Uvicorn running on http://127.0.0.1:8000
INFO:     Application startup complete.
```

### 1.4 访问与登录

- 浏览器打开 `http://127.0.0.1:8000`
- 默认管理员账号：`admin` / `admin123`
- **首次登录后请立即修改密码**

> 服务首次启动时会自动创建 `admin` 账户并初始化数据库（SQLite，位于 `data/quant_okx.db`）。

### 1.5 配置文件

关键环境变量（可在 `.env` 文件中配置）：

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `HOST` | `127.0.0.1` | 服务监听地址 |
| `PORT` | `8000` | 服务监听端口 |
| `JWT_SECRET_KEY` | `quant-okx-secret-key-change-in-production` | JWT 签名密钥（**生产环境务必修改**） |
| `OKX_BASE_URL` | `https://openapi.okx.com` | OKX API 接入点 |
| `OKX_PROXY` | （空） | HTTP 代理地址 |
| `CORS_ORIGINS` | （空） | 允许的跨域来源（逗号分隔） |

---

## 2. 账户管理

### 2.1 添加 OKX API Key

1. 登录后进入 **账户管理** 页面
2. 点击 **添加账户**
3. 填写以下信息：
   - **账户名称**：便于识别的名称，如 `OKX 模拟盘`
   - **API Key**：在 OKX 官网创建的 API Key
   - **Secret Key**：对应的 Secret Key
   - **Passphrase**：创建 API 时设置的口令
   - **交易模式**：`demo`（模拟盘）或 `live`（实盘）

> 所有 API Key 均使用 AES 加密存储，不会以明文形式保存到数据库。

### 2.2 模拟盘 vs 实盘

| 项目 | 模拟盘（demo） | 实盘（live） |
|------|----------------|--------------|
| 交易模式 | OKX 模拟交易环境 | 真实资金交易 |
| 请求头 | 携带 `x-simulated-trading: 1` | 不携带模拟头 |
| 资金 | 模拟资金 | 真实资金 |
| 风险 | 无资金风险 | 有真实亏损风险 |
| 适用场景 | 策略测试、功能验证 | 正式策略运行 |

**建议工作流**：
1. 先在模拟盘账户上测试策略
2. 使用沙箱模式验证实时行为（见第 10 章）
3. 通过回测验证历史表现（见第 5 章）
4. 确认无误后切换到实盘账户

### 2.3 账户安全注意事项

- API Key 应只授予必要的权限（交易 + 读取）
- **不要**开启提现权限
- 定期轮换 API Key
- 实盘账户建议设置 IP 白名单

---

## 3. 策略创建

### 3.1 QS-Model 四段式配置

QuantOKX 使用 QS-Model v2.0 四段式结构描述策略，由四个部分组成：

| 段 | 名称 | 作用 |
|----|------|------|
| `meta` | 元信息 | 策略名称、版本、作者、描述、基准交易对等 |
| `params` | 参数定义 | 可变参数的声明（类型、范围、默认值），便于参数调优与界面渲染 |
| `logic` | 策略逻辑 | 基础策略选择 + 规则列表（条件触发动作） |
| `risk_filter` | 风控配置 | 止损、止盈、最大持仓、每日最大亏损等 |

一个完整的 QS-Model 配置示例：

```json
{
  "qs_model_version": "2.0",
  "meta": {
    "name": "BTC 网格策略",
    "version": "v1.0.0",
    "author": "用户",
    "description": "BTC-USDT 现货网格，区间 40000-50000",
    "asset_class": "CRYPTO",
    "frequency": "1m",
    "base_symbol": "BTC-USDT"
  },
  "params": {
    "upper_price": {
      "label": "价格上限",
      "value": 50000,
      "type": "float",
      "range": [30000, 80000],
      "unit": "USDT"
    },
    "lower_price": {
      "label": "价格下限",
      "value": 40000,
      "type": "float",
      "range": [20000, 60000],
      "unit": "USDT"
    },
    "grid_count": {
      "label": "网格数量",
      "value": 10,
      "type": "int",
      "range": [2, 50]
    },
    "order_qty": {
      "label": "单格数量",
      "value": 0.01,
      "type": "float",
      "range": [0.001, 1]
    }
  },
  "logic": {
    "version": "1.0",
    "base_strategy": {
      "kind": "grid",
      "params": {
        "upper_price": "$params.upper_price",
        "lower_price": "$params.lower_price",
        "grid_count": "$params.grid_count",
        "order_qty": "$params.order_qty",
        "symbol": "$meta.base_symbol"
      }
    },
    "rules": []
  },
  "risk_filter": {
    "daily_max_loss": 100,
    "stop_loss": -0.05,
    "take_profit": 0.10
  }
}
```

### 3.2 基础策略类型

QuantOKX 内置以下基础策略：

| 策略类型 | kind | 说明 |
|----------|------|------|
| 网格策略 | `grid` | 在价格区间内均匀布置买卖网格，高抛低吸 |
| 双均线趋势 | `trend` | 短期均线上穿长期均线（金叉）做多，下穿（死叉）做空 |
| RSI 超买超卖 | `rsi_strategy` | RSI 低于超卖线买入，高于超买线卖出 |
| 布林带 | `bollinger_bands` | 价格跌破下轨买入，突破上轨卖出 |
| 唐奇安通道 | `donchian` | 突破入场周期最高价做多，跌破离场周期最低价平多 |
| 定投策略 | `dca` | 按固定频率和金额定时买入 |
| 马丁格尔 | `martingale` | 亏损后按倍数加仓，盈利覆盖全部亏损后平仓重置 |

### 3.3 参数配置

每个基础策略有专属的参数 schema。以网格策略为例：

| 参数 | 类型 | 说明 | 默认值 |
|------|------|------|--------|
| `upper_price` | number | 价格上限 | 必填 |
| `lower_price` | number | 价格下限 | 必填 |
| `grid_count` | integer | 网格数量 | 必填 |
| `order_qty` | number | 单格交易量 | 0.001 |
| `grid_mode` | select | 网格模式（等差/等比） | arithmetic |
| `direction` | select | 交易方向（做多/做空/双向） | neutral |
| `symbol` | string | 交易对 | 必填 |

### 3.4 创建策略模板

1. 进入 **策略管理** → **模板** 页面
2. 点击 **创建模板**
3. 填写模板名称、描述
4. 选择策略类型或粘贴 QS-Model 配置 JSON
5. 配置默认参数
6. 保存

### 3.5 创建策略实例

1. 在模板列表中选择一个模板
2. 点击 **创建实例**
3. 选择关联的 OKX 账户
4. 填写实例名称
5. 选择交易对（如 `BTC-USDT`）和市场类型（spot/swap）
6. 调整参数（覆盖模板默认值）
7. 保存

---

## 4. 策略运行

### 4.1 启动策略

1. 在 **策略实例** 列表中找到目标实例
2. 确认实例状态为 `stopped`
3. 点击 **启动** 按钮
4. 系统会：
   - 构建 OKXClient 连接到 OKX
   - 创建 OrderManager 与 WebSocket 客户端
   - 调用策略的 `start()` 方法
   - 启动 `execute()` 后台任务
5. 实例状态变为 `running`

> 启动时如遇网络错误或 WebSocket 连接失败，实例会被标记为 `error`，请检查账户配置与网络。

### 4.2 暂停与恢复

- **暂停**：撤销当前所有挂单，但保留持仓。状态变为 `paused`
- **恢复**：重新挂单（如网格策略会重新布置网格）。状态恢复为 `running`

暂停与恢复的区别：
- 暂停 ≠ 停止：暂停后策略仍在内存中，可快速恢复
- 停止：完全终止策略任务，需要重新启动

### 4.3 停止策略

点击 **停止** 按钮：
1. 撤销所有挂单
2. 记录最终 PnL 快照
3. 终止后台任务
4. 状态变为 `stopped`

> 停止后持仓不会自动平仓。如需平仓请手动操作。

### 4.4 参数热更新

QuantOKX 支持在不停止策略的情况下更新部分参数：

1. 在策略实例详情页点击 **参数配置**
2. 修改可热更新的参数（如网格的 `upper_price` / `lower_price`）
3. 点击 **保存并应用**
4. 系统会在下一个 tick 生效

**注意**：
- 不是所有参数都支持热更新
- 修改核心参数（如 `grid_count`）可能触发策略重建网格
- 热更新失败会回滚到原参数

### 4.5 监控策略状态

- **仪表盘**：查看所有运行中策略的实时 PnL、持仓、订单数
- **策略详情**：查看单个策略的事件日志、订单明细、PnL 曲线
- **WebSocket 实时推送**：订单状态变化实时更新

---

## 5. 历史回测

### 5.1 配置回测参数

1. 进入 **回测** 页面
2. 填写回测配置：

| 参数 | 说明 | 示例 |
|------|------|------|
| 交易对 | 回测标的 | `BTC-USDT` |
| 策略类型 | 基础策略 | `grid` |
| 策略参数 | JSON 格式参数 | `{"upper_price": 50000, ...}` |
| 开始时间 | 回测起始时间 | `2025-01-01T00:00:00Z` |
| 结束时间 | 回测结束时间 | `2025-06-30T00:00:00Z` |
| K 线周期 | 回测数据粒度 | `1H` |
| 初始资金 | 模拟初始资金 | `10000.0` |
| 滑点 | 滑点比例 | `0.001`（0.1%） |
| 手续费率 | 交易手续费率 | `0.001`（0.1%） |

### 5.2 运行回测

点击 **运行回测**，系统会：
1. 从 OKX 拉取指定时间范围的 K 线数据
2. 按时间顺序逐根 K 线重放
3. 在每根 K 线上执行策略逻辑
4. 记录每笔模拟交易
5. 计算权益曲线

回测为同步执行，可能耗时数秒到数十秒（取决于数据量）。

### 5.3 解读回测结果

回测结果包含以下指标：

| 指标 | 说明 |
|------|------|
| 总收益率 | 期末权益相对初始资金的收益率 |
| 最大回撤 | 权益曲线从峰值回落的最大幅度 |
| 夏普比率 | 风险调整后收益（越高越好） |
| 交易次数 | 回测期间的成交笔数 |
| 胜率 | 盈利交易占总交易的比例 |
| 盈亏比 | 平均盈利 / 平均亏损 |
| 权益曲线 | 每个时间点的账户权益 |

**关键提示**：
- 回测结果基于历史数据，不代表未来表现
- 注意过拟合：参数过度优化可能导致历史表现好但实盘表现差
- 滑点与手续费对高频策略影响显著

### 5.4 导出为实例

回测结果满意后，可将参数导出为策略实例：

1. 在回测结果页点击 **导出为实例**
2. 系统生成策略实例配置 payload
3. 选择关联账户后创建实例
4. 即可在策略管理中看到新实例

---

## 6. 告警通知

### 6.1 通知渠道配置

QuantOKX 支持三种通知渠道：

#### 邮件（Email）

1. 进入 **设置** → **通知**
2. 选择渠道 **邮件**
3. 配置 SMTP 参数：

| 参数 | 说明 | 示例 |
|------|------|------|
| SMTP 服务器 | 邮件服务器地址 | `smtp.gmail.com` |
| SMTP 端口 | 端口 | `465`（SSL）或 `587`（TLS） |
| 用户名 | 登录账号 | `your@gmail.com` |
| 密码 | 登录密码 / 应用专用密码 | `****` |
| 发件人 | 发件地址 | `your@gmail.com` |
| 收件人 | 收件地址（逗号分隔） | `a@x.com, b@y.com` |

#### Webhook

| 参数 | 说明 | 示例 |
|------|------|------|
| Webhook URL | 目标 URL | `https://hooks.example.com/notify` |
| 签名密钥 | 可选，HMAC-SHA256 签名 | `your-secret` |

#### Telegram

| 参数 | 说明 | 示例 |
|------|------|------|
| Bot Token | Telegram Bot 的 Token | `123456:ABC-DEF...` |
| Chat ID | 目标会话 ID | `-100123456789` |

### 6.2 通知规则

通知规则定义「什么事件发送到哪些渠道」：

1. 进入 **通知规则** 页面
2. 点击 **创建规则**
3. 配置：
   - **规则名称**：如 `策略异常告警`
   - **事件类型**：选择要通知的事件（支持多选或 `*` 全选）
   - **渠道**：选择通知渠道
   - **是否启用**：开启/禁用

### 6.3 内置事件类型

| 事件类型 | 触发时机 |
|----------|----------|
| `started` | 策略启动 |
| `stopped` | 策略停止 |
| `paused` | 策略暂停 |
| `resumed` | 策略恢复 |
| `order_placed` | 订单挂出 |
| `order_filled` | 订单成交 |
| `order_canceled` | 订单撤销 |
| `order_failed` | 下单失败 |
| `error` | 策略异常 |
| `test_failure` | 每日回归测试失败 |

### 6.4 测试通知

配置完成后可点击 **测试** 按钮发送测试消息，验证渠道连通性。

---

## 7. PnL 归因分析

### 7.1 按币种分析

进入 **PnL 分析** 页面，可按交易对查看盈亏分布：

- 选择 **按币种** 维度
- 查看各交易对的已实现盈亏、未实现盈亏、总盈亏
- 识别盈利与亏损的主要来源币种

### 7.2 按策略类型分析

- 选择 **按策略类型** 维度
- 对比不同策略类型（grid / trend / rsi 等）的盈亏表现
- 评估哪类策略在当前市场环境下表现更优

### 7.3 按时间段分析

- 选择 **按时间段** 维度
- 查看日 / 周 / 月维度的盈亏趋势
- 识别策略表现的周期性规律

### 7.4 下钻分析

在任意维度下，可点击具体条目下钻查看：
- 该币种/策略/时间段下的所有成交记录
- 每笔成交的盈亏贡献
- 持仓变化轨迹
- 手续费消耗明细

---

## 8. 策略模板分享

### 8.1 导出策略模板

1. 在 **策略模板** 列表中选择模板
2. 点击 **导出**
3. 系统生成 JSON 文件并下载

导出的 JSON 格式：

```json
{
  "export_version": "1.0",
  "template": {
    "name": "BTC 网格策略",
    "strategy_type": "composable",
    "description": "BTC-USDT 现货网格",
    "default_params": { ... },
    "qs_model_config": { ... }
  },
  "exported_at": "2026-01-01T00:00:00Z"
}
```

### 8.2 导入策略模板

1. 进入 **策略模板** 页面
2. 点击 **导入**
3. 上传 JSON 文件或粘贴 JSON 内容
4. 系统校验格式与版本兼容性
5. 确认后导入

**导入约束**：
- 仅支持 `export_version: "1.0"` 的文件
- 逻辑哈希相同的模板不会重复导入
- 导入后可修改名称与参数

### 8.3 分享注意事项

- 导出文件包含策略逻辑，请谨慎分享
- API Key 等敏感信息不会被导出
- 建议在分享前移除实盘参数，保留默认值

---

## 9. 数据维护

### 9.1 盈亏清零

当需要重新开始统计 PnL 时（如切换策略阶段）：

1. 进入 **数据维护** 页面
2. 选择 **盈亏清零**
3. 选择目标策略实例
4. 确认操作

效果：
- 将选中实例的已实现盈亏清零
- 记录清零时间点
- 后续 PnL 从零开始累计

### 9.2 记录清理

定期清理历史数据以释放存储空间：

1. 进入 **数据维护** → **记录清理**
2. 选择要清理的数据类型：
   - **API 调用日志**：按天数清理（如清理 30 天前的日志）
   - **策略事件**：按天数清理
   - **PnL 记录**：按天数清理（谨慎操作）
   - **已完成订单**：清理已结束策略的订单记录
3. 设置保留天数
4. 执行清理

### 9.3 数据校正

当 PnL 数据与 OKX 实际不一致时（如网络中断导致数据丢失）：

1. 进入 **数据维护** → **数据校正**
2. 选择目标策略实例
3. 点击 **重新核算 PnL**
4. 系统会：
   - 从 OKX 拉取最近的成交记录
   - 重新计算已实现盈亏
   - 重建 PnL 基准
   - 修正 `pnl_accounted` 标记

**建议**：
- 服务重启后系统会自动重建 PnL 基准
- 仅在数据明显异常时手动校正
- 校正前建议备份 `data/quant_okx.db`

---

## 10. 沙箱模式

### 10.1 什么是沙箱模式

沙箱模式是一种**策略实时验证**方式：

- 使用**真实实时行情**运行策略
- **不触发任何真实下单**（所有下单被 mock 拦截）
- 记录虚拟订单与虚拟 PnL 变化
- 用于验证策略在当前市场下的实时行为

### 10.2 沙箱 vs 回测

| 维度 | 沙箱模式 | 回测 |
|------|----------|------|
| 数据来源 | 实时真实行情 | 历史 K 线数据 |
| 运行方式 | 实时按 tick 运行 | 离线快速重放 |
| 下单 | 虚拟订单（不真实下单） | 模拟成交 |
| 适用场景 | 验证策略实时行为、观察信号触发 | 验证历史区间表现、参数调优 |
| 运行时长 | 分钟 ~ 小时级 | 秒级 |

### 10.3 启动沙箱

通过 API 启动沙箱运行：

```bash
# 1. 登录获取 token
curl -X POST http://127.0.0.1:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "admin123"}'

# 2. 启动沙箱
curl -X POST http://127.0.0.1:8000/api/sandbox/start \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "qs_model_config": {
      "qs_model_version": "2.0",
      "meta": {
        "name": "沙箱测试",
        "base_symbol": "BTC-USDT"
      },
      "params": {
        "upper_price": {"label": "上限", "value": 70000, "type": "float"},
        "lower_price": {"label": "下限", "value": 60000, "type": "float"},
        "grid_count": {"label": "网格数", "value": 5, "type": "int"},
        "order_qty": {"label": "单格数量", "value": 0.001, "type": "float"}
      },
      "logic": {
        "version": "1.0",
        "base_strategy": {
          "kind": "grid",
          "params": {
            "upper_price": "$params.upper_price",
            "lower_price": "$params.lower_price",
            "grid_count": "$params.grid_count",
            "order_qty": "$params.order_qty",
            "symbol": "$meta.base_symbol"
          }
        },
        "rules": []
      }
    },
    "symbol": "BTC-USDT",
    "duration_seconds": 300,
    "tick_interval": 5
  }'
```

返回示例：

```json
{
  "sandbox_id": "sandbox_1735689600_abc12345",
  "status": {
    "sandbox_id": "sandbox_1735689600_abc12345",
    "symbol": "BTC-USDT",
    "status": "running",
    "started_at": "2026-01-01T00:00:00Z",
    "order_count": 0,
    "pnl_point_count": 0
  },
  "message": "沙箱已启动，使用实时行情运行策略（不触发真实下单）"
}
```

### 10.4 查询沙箱状态

```bash
curl -X GET http://127.0.0.1:8000/api/sandbox/sandbox_1735689600_abc12345/status \
  -H "Authorization: Bearer <token>"
```

### 10.5 获取沙箱结果

```bash
curl -X GET http://127.0.0.1:8000/api/sandbox/sandbox_1735689600_abc12345/result \
  -H "Authorization: Bearer <token>"
```

返回的完整结果包含：
- `virtual_orders`：所有虚拟订单列表
- `pnl_curve`：PnL 变化曲线（每个 tick 一个点）
- `events`：策略事件记录

### 10.6 停止沙箱

```bash
curl -X POST http://127.0.0.1:8000/api/sandbox/sandbox_1735689600_abc12345/stop \
  -H "Authorization: Bearer <token>"
```

### 10.7 沙箱使用建议

1. **先回测后沙箱**：回测验证历史表现后，用沙箱验证实时行为
2. **观察信号触发**：沙箱模式下重点观察策略是否在预期时机触发信号
3. **检查订单逻辑**：查看虚拟订单的 side / price / qty 是否符合策略设计
4. **评估 tick 频率**：根据策略类型选择合适的 `tick_interval`（高频策略用 1-2s，低频用 10-30s）
5. **沙箱不等于实盘**：沙箱无滑点与真实流动性影响，实盘表现可能有差异

---

## 附录

### 常见问题

**Q: 启动后端服务报 `ModuleNotFoundError`？**
A: 确保在项目根目录执行命令，且已安装所有依赖：`pip install -r requirements.txt`

**Q: OKX API 连接超时？**
A: 检查网络是否能访问 OKX，或配置 `OKX_PROXY` 环境变量使用代理，或设置 `OKX_BASE_URL` 切换接入点（如 `https://aws.okx.com`）。

**Q: 策略启动后立即变为 error 状态？**
A: 检查账户 API Key 是否有效、是否开启了交易权限、模拟盘/实盘模式是否匹配。

**Q: PnL 数据不更新？**
A: PnL 采样每 60s 执行一次增量核算，无成交时每 5 分钟写心跳快照。如长时间无更新请检查策略是否正常运行。

**Q: 每日回归测试如何配置定时执行？**
A: 使用系统计划任务（Linux crontab / Windows 任务计划）定时执行：
```bash
# 每天凌晨 2 点执行
python scripts/daily_regression.py --notify
```

### 相关文档

- [策略编写指南](./strategy-writing-guide.md)：QS-Model 结构、积木库参考、示例策略
- [E2E 测试说明](../backend/tests/run_e2e_tests.py)：测试套件使用方法
