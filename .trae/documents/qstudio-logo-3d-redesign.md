# Q-Studio Logo 重新绘制 — 真正 3D 素材生成计划

## 背景

当前 `e:\quant_okx\frontend\src\assets\Logo.jpg` 是一个 AI 生成的 3D 金属 Logo，包含圆形外环 + 闪电/柱状图 + 对角斜杠元素。用户认为当前素材不够好，要求重新绘制一个**真正高质量的 3D 素材**。

## 当前状态分析

- 现有 Logo 图片：`Logo.jpg`（圆形 + 闪电 + 柱状图，金属质感，青绿色调）
- 登录页已实现：开场动画 + 3D 鼠标跟踪旋转 Logo（`LoginPage.tsx`）
- 开场动画也引用同一 Logo
- 品牌色：`#00D4AA`（青绿色）
- 设计项目：`e:\quant_okx\qstudio-logo-upgrade\`

## 执行步骤

### Step 1：生成多角度 3D Logo 素材（并行生成 4 张）

使用 `GenerateImage` 工具生成 4 个不同角度/风格的真正 3D Logo 渲染图：

1. **正面视角**（`logo-3d-front.png`）— 经典正面 45 度俯视角，展示 Logo 完整造型，铬面金属材质，青绿色发光边缘，深色环境光，底部反射面
2. **左前侧视角**（`logo-3d-left.png`）— 从左前方 30 度角观看，展示 Logo 侧面厚度和 3D 深度
3. **右后侧视角**（`logo-3d-right.png`）— 从右后方 45 度角观看，展示光影在曲面的反射变化
4. **俯瞰视角**（`logo-3d-top.png`）— 从上方 60 度角俯视，展示 Logo 的立体层次结构

**设计规格**：
- 保持当前 Logo 的核心元素：圆形外环（带缺口）+ 闪电/能量符号 + 柱状图数据元素 + 对角斜杠
- 材质：高端铬面金属 + 青绿色（#00D4AA）发光边缘/能量纹路
- 光照：三点式影棚布光（主光、补光、轮廓光），营造真实的金属反射
- 环境：深色背景 + 反射地面，突出 Logo 主体
- 风格：金融科技/量化交易专业感，参考 Bloomberg / Reuters 品牌质感
- 尺寸：1024x1024（square_hd），确保足够清晰用于 UI

**Prompt 关键词策略**：
- 明确指定 "photorealistic 3D CGI render, ray-traced reflections, PBR materials"
- 指定 "studio three-point lighting, chrome metallic surface, teal-cyan energy glow"
- 指定 Logo 元素细节以确保与现有品牌一致
- 每张图强调不同视角和光影效果

### Step 2：用户选择最佳方案

生成 4 张后，让用户选择最喜欢的一个角度/风格作为最终素材。

### Step 3：替换 Logo 素材到项目中

将用户选定的 3D Logo：
1. 复制到 `e:\quant_okx\frontend\src\assets\Logo.jpg`（替换旧文件，保持 import 路径不变）
2. 同步更新 `e:\quant_okx\qstudio-logo-upgrade\assets\` 下的展示素材
3. 更新设计展示页面的 `.design` 文件中的图片节点

### Step 4：验证

1. TypeScript 编译通过
2. 启动 dev server 在浏览器中预览登录页，确认新 Logo 在 3D 鼠标旋转效果下的表现
3. 确认开场动画中新 Logo 的视觉效果

## 设计约束

- Logo 元素必须与现有品牌保持一致（圆形 + 闪电 + 柱状图 + 对角线）
- 品牌色 `#00D4AA` 必须作为主色调
- 不能使用文字叠加（纯图标）
- 必须是透明感或深色背景，与暗色 UI 融合
