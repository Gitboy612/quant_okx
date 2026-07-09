@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title QuantOKX 环境初始化脚本 (install.bat)

REM ============================================================
REM   QuantOKX - 全新 Windows 环境一键安装 / 前置检查脚本
REM   在首次运行 start.bat 之前执行，完成：
REM     1. 校验 / 安装 Python 3.10+ 和 Node.js 18+
REM     2. 安装 Visual C++ 运行库（bcrypt/cryptography 等依赖需要）
REM     3. 创建 Python 虚拟环境 venv
REM     4. 安装后端 Python 依赖（含 aiosqlite、python-dotenv）
REM     5. 安装前端 npm 依赖
REM     6. 从 .env.example 生成 .env
REM     7. 校验内嵌代理 mihomo.exe 是否就绪
REM     8. 启动前烟雾测试（导入关键模块）
REM ============================================================

cd /d "%~dp0"

set "ROOT_DIR=%CD%"
set "BACKEND_DIR=%ROOT_DIR%\backend"
set "FRONTEND_DIR=%ROOT_DIR%\frontend"
set "VENV_DIR=%BACKEND_DIR%\.venv"
set "ERRORS=0"

echo ============================================================
echo   QuantOKX 环境初始化
echo   项目根目录: %ROOT_DIR%
echo ============================================================
echo.

REM ---------- 0. 操作系统与权限检查 ----------
echo [0/8] 检查操作系统与权限...
ver | findstr /R "10\." >nul
if errorlevel 1 (
    ver | findstr /R "11\." >nul
    if errorlevel 1 (
        echo [警告] 仅在 Windows 10 / 11 上测试通过，当前系统可能不兼容。
    )
)
net session >nul 2>nul
if errorlevel 1 (
    echo [提示] 当前未以管理员身份运行；winget 安装 Python / Node.js 时可能需要管理员权限。
    echo        若后续安装失败，请右键 "以管理员身份运行" 此脚本。
)
echo [完成] 系统检查通过。
echo.

REM ---------- 1. winget 可用性 ----------
echo [1/8] 检查 winget (Windows 应用包管理器)...
where winget >nul 2>nul
if errorlevel 1 (
    echo [警告] 未检测到 winget。后续若需要自动安装 Python / Node.js，将改为提示手动安装。
    set "WINGET_OK=0"
) else (
    set "WINGET_OK=1"
    echo [完成] winget 可用。
)
echo.

REM ---------- 2. Python 3.10+ ----------
echo [2/8] 检查 Python 3.10+ ...
where py >nul 2>nul
if errorlevel 1 (
    where python >nul 2>nul
    if errorlevel 1 (
        echo [缺失] 未检测到 Python。
        if "!WINGET_OK!"=="1" (
            echo [安装] 通过 winget 安装 Python 3.12 ...
            winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
            if errorlevel 1 (
                echo [错误] winget 安装 Python 失败。
                set /a ERRORS+=1
            ) else (
                echo [完成] Python 安装完成。请关闭并重新打开本脚本以使 PATH 生效。
                echo        也可以手动从 https://www.python.org/downloads/ 下载安装。
                goto :eof
            )
        ) else (
            echo [手动] 请访问 https://www.python.org/downloads/ 下载 Python 3.10+，
            echo        安装时务必勾选 "Add Python to PATH"，安装完成后重新运行本脚本。
            set /a ERRORS+=1
        )
    ) else (
        set "PY_CMD=python"
    )
) else (
    set "PY_CMD=py"
)
if defined PY_CMD (
    for /f "delims=" %%v in ('!PY_CMD! -c "import sys;print('%d.%d' % sys.version_info[:2])" 2^>nul') do set "PY_VER=%%v"
    if not defined PY_VER (
        echo [警告] 无法读取 Python 版本，假设可用。
        set "PY_OK=1"
    ) else (
        for /f "tokens=1,2 delims=." %%a in ("!PY_VER!") do (
            set "PY_MAJOR=%%a"
            set "PY_MINOR=%%b"
        )
        set /a PY_NUM=!PY_MAJOR!*100+!PY_MINOR!
        if !PY_NUM! LSS 310 (
            echo [错误] Python 版本 !PY_VER! 低于 3.10，请升级后重试。
            set /a ERRORS+=1
            set "PY_OK=0"
        ) else (
            echo [完成] 检测到 Python !PY_VER!。
            set "PY_OK=1"
        )
    )
)
echo.

REM ---------- 3. Node.js 18+ ----------
echo [3/8] 检查 Node.js 18+ ...
where node >nul 2>nul
if errorlevel 1 (
    echo [缺失] 未检测到 Node.js。
    if "!WINGET_OK!"=="1" (
        echo [安装] 通过 winget 安装 OpenJS.NodeJS.LTS ...
        winget install -e --id OpenJS.NodeJS.LTS --accept-source-agreements --accept-package-agreements
        if errorlevel 1 (
            echo [错误] winget 安装 Node.js 失败。
            set /a ERRORS+=1
        ) else (
            echo [完成] Node.js 安装完成。请关闭并重新打开本脚本以使 PATH 生效。
            goto :eof
        )
    ) else (
        echo [手动] 请访问 https://nodejs.org/ 下载 LTS 版本安装，完成后重新运行本脚本。
        set /a ERRORS+=1
    )
) else (
    for /f "delims=" %%v in ('node -v 2^>nul') do set "NODE_VER_RAW=%%v"
    set "NODE_VER=!NODE_VER_RAW:v=!"
    for /f "tokens=1,2 delims=." %%a in ("!NODE_VER!") do (
        set "NODE_MAJOR=%%a"
        set "NODE_MINOR=%%b"
    )
    set /a NODE_NUM=!NODE_MAJOR!
    if !NODE_NUM! LSS 18 (
        echo [错误] Node.js 版本 !NODE_VER_RAW! 低于 18，请升级后重试。
        set /a ERRORS+=1
    ) else (
        echo [完成] 检测到 Node.js !NODE_VER_RAW!。
    )
    where npm >nul 2>nul
    if errorlevel 1 (
        echo [错误] 检测到 node 但未检测到 npm，Node.js 安装可能不完整。
        set /a ERRORS+=1
    )
)
echo.

REM ---------- 4. Visual C++ 运行库 ----------
echo [4/8] 检查 Visual C++ 运行库 (bcrypt / cryptography 需要) ...
set "VCREDIST_FOUND=0"
for /f "delims=" %%k in ('reg query "HKLM\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\X64" /v Version 2^>nul') do (
    echo %%k | findstr /R "Version" >nul && set "VCREDIST_FOUND=1"
)
if "!VCREDIST_FOUND!"=="0" (
    for /f "delims=" %%k in ('reg query "HKLM\SOFTWARE\WOW6432Node\Microsoft\VisualStudio\14.0\VC\Runtimes\X64" /v Version 2^>nul') do (
        echo %%k | findstr /R "Version" >nul && set "VCREDIST_FOUND=1"
    )
)
if "!VCREDIST_FOUND!"=="0" (
    echo [缺失] 未检测到 VC++ 2015-2022 X64 运行库，尝试通过 winget 安装...
    if "!WINGET_OK!"=="1" (
        winget install -e --id Microsoft.VCRedist.2015+.x64 --accept-source-agreements --accept-package-agreements
        if errorlevel 1 (
            echo [警告] winget 安装 VC++ 运行库失败。部分 Python 包可能无法运行，
            echo        可手动从 https://aka.ms/vs/17/release/vc_redist.x64.exe 下载安装。
        ) else (
            echo [完成] VC++ 运行库已安装。
        )
    ) else (
        echo [手动] 请访问 https://aka.ms/vs/17/release/vc_redist.x64.exe 下载安装。
    )
) else (
    echo [完成] VC++ 运行库已存在。
)
echo.

REM ---------- 5. 创建 Python 虚拟环境 ----------
echo [5/8] 创建 / 检查 Python 虚拟环境 ...
if "!PY_OK!"=="0" if not defined PY_CMD goto :fatal
if not defined PY_CMD goto :fatal
if exist "!VENV_DIR!\Scripts\python.exe" (
    echo [完成] 虚拟环境已存在: !VENV_DIR!
) else (
    echo [创建] 在 !VENV_DIR! 创建虚拟环境 ...
    "!PY_CMD!" -m venv "!VENV_DIR!"
    if errorlevel 1 (
        echo [错误] 创建虚拟环境失败。
        set /a ERRORS+=1
        goto :fatal
    )
    echo [完成] 虚拟环境创建完成。
)
set "VENV_PY=!VENV_DIR!\Scripts\python.exe"
set "VENV_PIP=!VENV_DIR!\Scripts\pip.exe"

REM 升级 pip
echo [升级] 升级 pip / setuptools / wheel ...
"!VENV_PY!" -m pip install --upgrade pip setuptools wheel
if errorlevel 1 (
    echo [警告] pip 升级失败，继续后续安装。
)
echo.

REM ---------- 6. 安装后端 Python 依赖 ----------
echo [6/8] 安装后端 Python 依赖 (requirements.txt) ...
if not exist "!BACKEND_DIR!\requirements.txt" (
    echo [错误] 未找到 backend\requirements.txt。
    set /a ERRORS+=1
    goto :fatal
)
"!VENV_PIP!" install -r "!BACKEND_DIR!\requirements.txt"
if errorlevel 1 (
    echo [错误] 安装 requirements.txt 失败。
    set /a ERRORS+=1
    goto :fatal
)

REM requirements.txt 缺失但代码引用的依赖（补丁）
echo [补丁] 安装缺失依赖 aiosqlite / python-dotenv ...
"!VENV_PIP!" install aiosqlite python-dotenv
if errorlevel 1 (
    echo [警告] aiosqlite / python-dotenv 安装失败，启动后端时可能报错。
    set /a ERRORS+=1
) else (
    echo [完成] 后端 Python 依赖安装完成。
)
echo.

REM ---------- 7. 安装前端 npm 依赖 ----------
echo [7/8] 安装前端 npm 依赖 ...
if not exist "!FRONTEND_DIR!\package.json" (
    echo [错误] 未找到 frontend\package.json。
    set /a ERRORS+=1
    goto :fatal
)
pushd "!FRONTEND_DIR!"
if exist "node_modules" (
    echo [完成] node_modules 已存在，跳过安装。如需重装请删除该目录。
) else (
    call npm install
    if errorlevel 1 (
        echo [错误] npm install 失败。
        popd
        set /a ERRORS+=1
        goto :fatal
    )
    echo [完成] 前端依赖安装完成。
)
popd
echo.

REM ---------- 8. .env 文件 + mihomo 代理校验 ----------
echo [8/8] 检查 .env 配置与内嵌代理 mihomo.exe ...
if not exist "!ROOT_DIR!\.env" (
    if exist "!ROOT_DIR!\.env.example" (
        copy /Y "!ROOT_DIR!\.env.example" "!ROOT_DIR!\.env" >nul
        echo [完成] 已从 .env.example 生成 .env。
        echo [提示] 生产部署请编辑 .env 修改 JWT_SECRET_KEY / HOST / PRODUCTION。
    ) else (
        echo [警告] 未找到 .env.example，请手动创建 .env 文件。
    )
) else (
    echo [完成] .env 已存在。
)

if exist "!BACKEND_DIR!\bin\mihomo.exe" (
    echo [完成] 内嵌代理 mihomo.exe 已就绪。
) else if exist "!BACKEND_DIR!\bin\mihomo-windows-amd64-v3-go120.exe" (
    echo [提示] 检测到 mihomo-windows-amd64-v3-go120.exe，建议重命名为 mihomo.exe。
) else (
    echo [警告] 未找到 backend\bin\mihomo.exe，嵌入式代理功能将不可用。
    echo        可手动下载 mihomo (Clash.Meta) 并放置到 backend\bin\mihomo.exe。
)
echo.

REM ---------- 烟雾测试：导入关键后端模块 ----------
echo ============================================================
echo   启动前烟雾测试：导入后端关键模块
echo ============================================================
pushd "!BACKEND_DIR!"
"!VENV_PY!" -c "import fastapi, uvicorn, sqlalchemy, httpx, bcrypt, cryptography, jose, apscheduler, websockets, multipart, pydantic, aiosqlite, dotenv; print('OK: all key modules imported successfully')"
if errorlevel 1 (
    echo [错误] 关键模块导入失败，请检查上方错误信息。
    popd
    set /a ERRORS+=1
    goto :fatal
) else (
    echo [完成] 关键模块导入成功。
)
popd
echo.

REM ---------- 最终结论 ----------
if !ERRORS! GTR 0 (
    goto :fatal
)

echo ============================================================
echo   环境初始化完成！
echo ============================================================
echo.
echo 下一步：双击 start.bat 启动 QuantOKX
echo   - 后端 API 文档: http://127.0.0.1:8000/docs
echo   - 前端 UI:       http://127.0.0.1:5173
echo   - 默认账号:       admin / admin123
echo.
echo 注意事项：
echo   1) 生产部署请编辑 .env 修改 JWT_SECRET_KEY，并设置 PRODUCTION=true
echo   2) 若对外暴露服务，请将 HOST 改为 0.0.0.0 并放行端口
echo   3) 国内访问 OKX 慢可在前端设置页开启嵌入式代理
echo.
pause
exit /b 0

:fatal
echo.
echo ============================================================
echo   初始化失败，共 !ERRORS! 项错误，请根据上方提示修复后重试。
echo ============================================================
pause
exit /b 1
