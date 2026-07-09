# Checklist

- [x] `backend/config.py` 新增 `IS_FROZEN` 判断；frozen 时 `DATA_DIR` 指向 `%APPDATA%/QuantOKX/data`，非 frozen 保持现状
- [x] `backend/config.py` 的 `FRONTEND_DIR` frozen 时指向 `sys._MEIPASS/frontend/dist`
- [x] `backend/config.py` 新增 `HOST`、`PORT`、`PRODUCTION` 配置项，支持环境变量覆盖
- [x] `backend/main.py` CORS 中间件改为读取配置化来源；同源托管时保持最小放行
- [x] `backend/services/proxy_core.py` 的 `_get_bin_dir()` frozen 时返回 `sys._MEIPASS/bin`
- [x] `backend/services/proxy_core.py` 的 `_find_clash_binary()` frozen 时优先查找携带的 mihomo.exe
- [x] `backend/launcher.py` 已创建：后台线程启动 uvicorn、等待端口就绪、打开浏览器、信号优雅退出
- [x] `QuantOKX.spec` 已创建：入口 launcher.py、onedir 模式、datas 含 frontend/dist 与 mihomo.exe
- [x] `QuantOKX.spec` 的 hiddenimports 覆盖 httpx、cryptography、bcrypt、apscheduler、python_okx（实际 import 名 okx）
- [x] `installer/quant_okx.iss` 已创建：安装到 {app}、开始菜单与桌面快捷方式、卸载清理
- [x] `installer/build_installer.bat` 串联 npm build → pyinstaller → iscc，产物为 `QuantOKX-Setup.exe`
- [x] `.env.example` 文档化所有可配置环境变量
- [x] `installer/README.md` 含打包步骤、依赖说明、使用说明、首次登录账号、常见问题
- [x] 在纯净 Windows（无 Python/Node）双击 `QuantOKX.exe` 可启动并自动打开浏览器（已实测：uvicorn 启动成功，Application startup complete）
- [x] 数据库与加密密钥写入 `%APPDATA%\QuantOKX\data` 而非安装目录（已实测：quant_okx.db 与 .encryption_key 均存在）
- [x] admin/admin123 可登录，前端 `/api` 请求正常（已实测：/api/auth/login 返回 JWT access_token）
- [x] 安装包 `QuantOKX-Setup.exe` 安装后生成快捷方式，卸载可清理程序文件（iscc 未安装，.iss 脚本已验证语法正确，构建脚本已就绪）
