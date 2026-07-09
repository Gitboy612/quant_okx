# Tasks

- [x] Task 1: 修复 Modal 组件溢出
  - [x] 在 `Modal.tsx` 面板 className 中添加 `mx-4 max-h-[85vh] overflow-y-auto`
  - [x] 添加 `max-w-[calc(100vw-2rem)]` 防止窄屏溢出
  - [x] 默认 max-w 从 `max-w-md` 改为 `max-w-lg`（448px→512px，略宽一点适应更多内容）

- [x] Task 2: 修复 Dropdown 硬宽度限制
  - [x] 在 `Dropdown.tsx` 中移除 `min-w-[120px]`，改为 `w-full`
  - [x] 在选项面板添加 `max-h-60 overflow-y-auto`

- [x] Task 3: 修复策略管理弹窗布局
  - [x] 在 `StrategiesPage.tsx` 新建策略 `<Modal>` 传入 `wide` 属性
  - [x] 在 `NewTemplateModal` 的 `<Modal>` 传入 `wide` 属性
  - [x] 在参数定义的 `grid grid-cols-2` 改为 `grid grid-cols-1 sm:grid-cols-2 gap-2`
  - [x] 在每个 grid 子 div 添加 `min-w-0`
  - [x] 在新建策略弹窗的参数配置区，从单列改为 `grid grid-cols-1 sm:grid-cols-2 gap-3`

- [x] Task 4: 修复 AccountsPage 弹窗
  - [x] 在 `AccountsPage.tsx` 的添加账户 `<Modal>` 传入 `wide` 属性

- [x] Task 5: 全局 CSS 防溢出
  - [x] 在 `index.css` 添加全局规则：所有 `div > *` 默认 `min-width: 0; min-height: 0`

# Task Dependencies
- Task 1、Task 2、Task 5 相互独立，可并行执行
- Task 3 和 Task 4 依赖 Task 1 和 Task 2（需要 Modal 和 Dropdown 先修好）
- Task 3 和 Task 4 可并行执行