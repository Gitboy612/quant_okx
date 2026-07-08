# Checklist

- [x] YAML 解析使用 CSafeLoader 优先，支持 128KB+ 大文件
- [x] YAML 解析失败时返回详细错误信息（行号、原因）
- [x] mihomo 二进制未找到时自动下载安装
- [x] 下载的 mihomo.exe 保存到 backend/bin/ 目录
- [x] 代理启动后自动测试 OKX API 连通性
- [x] 连通性测试结果返回给前端展示
- [x] 前端导入失败时显示详细错误信息
- [x] 前端代理启动结果包含连通性状态
- [x] 上传 1772848370833.yml 配置文件导入成功
- [x] Python 语法检查通过
- [x] 前端构建无报错