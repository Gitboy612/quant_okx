# QuantOKX 打包说明

本目录包含 QuantOKX Windows 安装包的构建脚本与配置。通过 PyInstaller 将 FastAPI 后端打包为 `QuantOKX.exe`（内嵌 React 前端），再用 Inno Setup 生成可分发的安装程序。

## 目录结构

```
installer/
├── quant_okx.iss         # Inno Setup 安装脚本
├── build_installer.bat   # 一键构建脚本
└── Output/               # 构建产物输出目录（构建后自动生成）
    └── QuantOKX-Setup.exe
```

## 一、打包前置依赖

| 依赖 | 版本要求 | 说明 |
| --- | --- | --- |
| Python | 3.10+ | 后端运行时与打包工具 |
| Node.js | 18+ | 前端构建（npm） |
| PyInstaller | 最新版 | 执行 `pip install pyinstaller` 安装 |
| Inno Setup | 6 | 编译 `.iss` 生成安装包，安装后需将其安装目录加入系统 `PATH` |

> 项目根目录需存在 `QuantOKX.spec`（PyInstaller 配置），入口为 `backend/launcher.py`。

## 二、构建步骤

### 方式 A：一键构建（推荐）

双击执行 `build_installer.bat`，或在终端中运行：

```bat
installer\build_installer.bat
```

脚本会依次完成：依赖检查 → 前端构建 → PyInstaller 打包 → Inno Setup 编译。任一步骤失败都会中断并提示原因。

### 方式 B：手动三步

在项目根目录下依次执行：

```bat
:: 1. 构建前端
cd frontend
npm install
npm run build
cd ..

:: 2. PyInstaller 打包后端（产物输出到 dist\QuantOKX\）
pyinstaller QuantOKX.spec --noconfirm

:: 3. Inno Setup 生成安装包
iscc installer\quant_okx.iss
```

## 三、构建产物

- 路径：`installer\Output\QuantOKX-Setup.exe`
- 这是一个标准的 Windows 安装程序，包含：
  - 完整的 `QuantOKX.exe` 及其运行时依赖（PyInstaller onedir 产物）
  - 内嵌的前端静态资源
  - 桌面快捷方式、开始菜单快捷方式（可选开机自启）
- 安装目录默认为 `C:\Program Files\QuantOKX`（64 位系统）。

## 四、安装后使用

1. 双击桌面快捷方式「QuantOKX」（或从开始菜单启动）。
2. 启动后控制台窗口会显示服务日志，浏览器将自动打开 `http://127.0.0.1:8000`。
3. 首次登录账号：**admin / admin123**，登录后请及时在「设置」中修改密码。
4. 关闭控制台窗口或按 `Ctrl+C` 可优雅停止服务。

> 运行时数据（数据库、加密密钥等）保存在 `%APPDATA%\QuantOKX\data`，卸载程序默认**不会**删除该目录，因此卸载重装后数据仍保留。

## 五、云服务器部署说明

默认配置仅监听本机（`127.0.0.1`），如需对外提供服务：

1. 安装完成后，进入安装目录（默认 `C:\Program Files\QuantOKX`）。
2. 编辑目录下的 `.env` 文件（若不存在，从 `.env.example` 复制一份），设置：
   ```env
   HOST=0.0.0.0
   PRODUCTION=true
   JWT_SECRET_KEY=<替换为随机长字符串>
   ```
3. 在服务器防火墙中放行 `8000` 端口（或你在 `PORT` 中指定的端口）。
4. 通过 `http://<服务器公网IP>:8000` 访问。

> ⚠️ 对外暴露前务必修改默认密码与 `JWT_SECRET_KEY`，否则存在安全风险。

## 六、常见问题

**Q1：启动时提示端口被占用？**
编辑安装目录下 `.env`，修改 `PORT` 为其他空闲端口（如 `8001`），然后重启程序。

**Q2：国内访问 OKX API 速度慢或超时？**
- 程序内置嵌入式代理（基于 mihomo），可在「设置」页中开启；
- 或在 `.env` 中配置外部代理：`OKX_PROXY=http://127.0.0.1:7897`（按实际代理地址填写）。
- 也可使用备用接入点：`OKX_ALT_URLS` 默认已包含 `https://www.okx.cab` 等备用地址。

**Q3：数据目录在哪？如何备份？**
- 数据目录：`%APPDATA%\QuantOKX\data`（即 `C:\Users\<用户名>\AppData\Roaming\QuantOKX\data`）。
- 备份时复制整个 `data` 目录即可；其中包含 `quant_okx.db`（数据库）与 `.encryption_key`（密钥），两者需一起备份，否则已加密的 API 密钥无法解密。

**Q4：如何完全卸载并清除数据？**
先通过「控制面板 → 程序与功能」卸载 QuantOKX，再手动删除 `%APPDATA%\QuantOKX` 目录。

**Q5：开机自启如何开启/关闭？**
- 安装时：在安装向导的「附加选项」中勾选「开机自动启动」。
- 安装后：可通过开始菜单的「启动」文件夹管理，或在程序「设置」中调整。
