# Checklist

- [x] Modal 面板有 mx-4 边距，窄屏不贴边
- [x] Modal 面板有 max-h-[85vh] overflow-y-auto，高内容可滚动
- [x] Modal 面板有 max-w-[calc(100vw-2rem)] 防溢出
- [x] Dropdown 移除了 min-w-[120px]，改为 w-full
- [x] Dropdown 选项面板有 max-h-60 overflow-y-auto
- [x] 新建策略弹窗使用 wide（max-w-2xl）
- [x] 自定义模板弹窗使用 wide（max-w-2xl）
- [x] 参数定义 grid 在窄屏降级为单列（grid-cols-1 sm:grid-cols-2）
- [x] grid 子元素有 min-w-0
- [x] 新建策略参数配置区使用双列布局
- [x] AccountsPage 添加账户弹窗使用 wide
- [x] index.css 有全局 min-width:0 规则
- [x] 前端构建无报错