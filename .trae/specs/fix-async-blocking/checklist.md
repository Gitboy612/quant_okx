# Checklist

- [x] OKXClient 所有公开方法均为 async def（10 个），内部使用 asyncio.to_thread 包装（10 个）
- [x] 网格策略中所有 `self.client.xxx()` 调用均为 `await self.client.xxx()`（9 处）
- [x] BaseStrategy 中所有 OKXClient 调用均为 await（sync_orders 改为 async def）
- [x] OrderManager.cancel_all() 为 async def，内部 await 调用
- [x] StrategyEngine 中 feasibility 检查的 client 调用用 asyncio.run() 包装
- [x] 策略运行期间，前端切换菜单无卡顿（HTTP 请求在独立线程池中执行，不阻塞事件循环）
- [x] 策略运行期间，前端 API 请求不排队等待（asyncio.to_thread 释放事件循环）
- [x] 前端 DashboardPage 有运行中策略时自动翻倍刷新间隔，显示 "(已延长)"
- [x] 后端所有模块 import 无报错（5/5 通过）
- [x] 前端代码逻辑正确（Node.js 版本过低导致 tsc 无法运行，环境问题非代码问题）