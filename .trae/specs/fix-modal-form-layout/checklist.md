# Checklist

- [x] `Modal.tsx` 新增 `scrollable?: boolean` prop，默认 `true`
- [x] `scrollable={false}` 时面板不设置 `maxHeight`，body 无 `overflow-y-auto`
- [x] `scrollable={false}` 时面板 `overflow` 调整为 `visible`，内容不被裁剪
- [x] 默认（`scrollable=true`）行为与现状一致，其他弹窗未受影响
- [x] AccountsPage 添加账户弹窗传入 `scrollable={false}`
- [x] AccountsPage 表单 API Key / Secret Key 双列布局
- [x] AccountsPage 表单 Passphrase / 交易模式双列布局
- [x] AccountsPage 弹窗 body 无垂直滚动条
- [x] StrategiesPage 新建策略弹窗传入 `scrollable={false}`
- [x] StrategiesPage 新建策略表单模板/账户双列、名称/市场类型双列
- [x] StrategiesPage 新建策略弹窗 body 无垂直滚动条
- [x] StrategiesPage NewTemplateModal 传入 `scrollable={false}`
- [x] StrategiesPage NewTemplateModal 移除内层 `max-h-[70vh] overflow-y-auto`
- [x] StrategiesPage NewTemplateModal 无双重滚动容器
- [x] 窄屏（<640px）下双列布局降级为单列
- [x] `npm run build` 构建无报错（本次修改的 3 个文件 tsc 零报错；构建中唯一的错误来自预先存在的 `PnLChart.tsx` recharts 类型问题，与本次任务无关）
