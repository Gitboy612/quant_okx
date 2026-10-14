# QuantOKX Web 前端

本目录是 React、TypeScript 和 Vite 实现的 Web 界面，通过 `/api` 和 `/ws` 连接 FastAPI 后端。项目的整体说明与手工安装步骤见根目录的 [README](../README.md)。

## 环境与安装

运行 Web 前端请使用 Node.js 22.12+ 和 npm。macOS 可在项目根目录运行 `./install_mac.sh` 完成前后端环境初始化；Windows 可运行 `install.bat`。手工安装时，在本目录执行：

```bash
npm install --include=optional
```

若编辑器将 React、Vite 等导入全部标红，先确认本目录已生成 `node_modules/`，再重载编辑器的 TypeScript 服务。

## 开发、检查与构建

```bash
npm run dev      # Vite 开发服务器，默认访问 http://127.0.0.1:5173
npm run lint     # Oxlint 静态检查
npm run build    # TypeScript 检查并构建到 dist/
```

Vite 会将 `/api` 和 `/ws` 代理到本机的 FastAPI 服务。项目根目录的 `start_mac.sh` 或 `start.bat` 可同时启动前后端开发服务。`dist/` 是生成目录，不提交到 Git；构建后的页面可由后端托管。
