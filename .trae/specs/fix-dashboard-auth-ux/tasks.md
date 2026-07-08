# Tasks

- [x] Task 1: 修复仪表盘权益核算错误
  - [x] 修改 `DashboardPage.tsx` 中 `loadAssets` 调用，将首次加载和定时刷新均改为调用实时余额接口（`getAccountBalance`），不再使用缓存接口
  - [x] 移除 `loadAssets` 的 `useCached` 参数，统一使用实时接口
  - [x] 验证：进入仪表盘后总权益 KPI 显示实时 OKX 账户余额

- [x] Task 2: 后端新增持仓查询接口
  - [x] 在 `backend/routers/accounts.py` 新增 `GET /api/accounts/{account_id}/positions` 端点
  - [x] 调用 OKX `/api/v5/account/positions` 接口获取持仓数据
  - [x] 返回持仓列表，包含：`instId`（交易对）、`posSide`（多空方向）、`pos`（数量）、`markPx`（标记价格）、`upl`（未实现盈亏）

- [x] Task 3: 前端新增持仓展示
  - [x] 在 `frontend/src/api/accounts.ts` 新增 `getPositions(accountId)` API 函数
  - [x] 在 `frontend/src/types/index.ts` 新增 `Position` 类型
  - [x] 在 `DashboardPage.tsx` 中新增持仓数据加载和状态管理
  - [x] 在账户资产面板中新增持仓表格，展示交易对、多空方向、数量、标记价格、未实现盈亏
  - [x] 未实现盈亏正数绿色、负数红色显示

- [x] Task 4: 盈亏曲线时间粒度选择器
  - [x] 在 `PnLChart.tsx` 组件上方新增时间粒度选择按钮组
  - [x] 支持选项：1分钟、1小时、1天、1周、全部，默认选中"1天"
  - [x] 根据选中的时间粒度在前端过滤 `data` 数组（按 `recorded_at` 时间范围截取）
  - [x] 使用 `React.memo` 包裹 `PnLChart` 组件，避免不必要的重渲染
  - [x] 时间粒度切换时图表平滑过渡

- [x] Task 5: 后端新增密码修改接口
  - [x] 在 `backend/schemas/auth.py` 新增 `ChangePasswordRequest` schema（`old_password`、`new_password`）
  - [x] 在 `backend/routers/auth.py` 新增 `PUT /api/auth/password` 端点
  - [x] 验证旧密码正确性，验证新密码长度 >= 6，更新密码哈希

- [x] Task 6: 前端新增密码修改功能
  - [x] 在 `frontend/src/api/auth.ts` 新增 `changePassword(data)` API 函数
  - [x] 在 `SettingsPage.tsx` 新增"密码修改"面板，包含旧密码、新密码、确认新密码三个输入框
  - [x] 前端验证：新密码 >= 6 位，两次输入一致
  - [x] 提交成功后显示成功提示，失败显示错误信息

- [x] Task 7: Token 存储改为 sessionStorage
  - [x] 将 `useAuth.tsx` 中所有 `localStorage` 替换为 `sessionStorage`
  - [x] 将 `client.ts` 中 token 读取从 `localStorage` 改为 `sessionStorage`
  - [x] 验证：关闭浏览器标签页后重新打开，跳转到登录页

# Task Dependencies
- Task 3 依赖 Task 2（前端持仓展示需要后端接口）
- Task 6 依赖 Task 5（前端密码修改需要后端接口）
- Task 1、Task 4、Task 7 相互独立，可并行执行