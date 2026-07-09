# Tasks

- [x] Task 1: Modal 组件支持关闭滚动
  - [x] 在 `Modal.tsx` 的 `ModalProps` 新增 `scrollable?: boolean`（默认 `true`）
  - [x] 当 `scrollable={false}` 时：面板 `style` 不设置 `maxHeight`，body className 移除 `overflow-y-auto`
  - [x] 面板 `overflow` 在关闭滚动时改为 `visible`，避免内容被裁剪且不出现滚动条
  - [x] 保持默认（`scrollable=true`）行为与现状一致，不影响其他已有弹窗

- [x] Task 2: AccountsPage 添加账户弹窗紧凑双列布局
  - [x] `<Modal>` 传入 `scrollable={false}`
  - [x] 表单外层 `space-y-4` 改为 `space-y-3`
  - [x] API Key 与 Secret Key 改为 `grid grid-cols-2 gap-3`
  - [x] Passphrase 与交易模式改为 `grid grid-cols-2 gap-3`
  - [x] 账户名称（顶部）与提交按钮（底部）保持整行
  - [x] 窄屏（<640px）降级为单列：使用 `grid-cols-1 sm:grid-cols-2`

- [x] Task 3: StrategiesPage 新建策略弹窗紧凑双列布局
  - [x] `<Modal>` 传入 `scrollable={false}`
  - [x] 外层 `space-y-4` 改为 `space-y-3`
  - [x] 策略模板与绑定账户改为 `grid grid-cols-2 gap-3`
  - [x] 策略名称与市场类型改为 `grid grid-cols-2 gap-3`
  - [x] 交易对搜索框保持整行
  - [x] 参数配置区维持 `grid grid-cols-1 sm:grid-cols-2 gap-3`
  - [x] 窄屏降级为单列

- [x] Task 4: StrategiesPage NewTemplateModal 移除双重滚动
  - [x] `<Modal>` 传入 `scrollable={false}`
  - [x] 删除内层 div 的 `max-h-[70vh] overflow-y-auto pr-1`，仅保留 `space-y-3`
  - [x] 表单字段卡片布局不变（已是 `grid-cols-1 sm:grid-cols-2`）

- [x] Task 5: 构建验证
  - [x] 运行 `npm run build` 确认无 TypeScript / 构建错误
  - [x] 检查其他使用 `<Modal>` 的页面（如确认弹窗）未受影响

# Task Dependencies
- Task 1 是基础，Task 2/3/4 依赖 Task 1 提供的 `scrollable` prop
- Task 2、Task 3、Task 4 相互独立，可并行执行
- Task 5 依赖 Task 1-4 全部完成
