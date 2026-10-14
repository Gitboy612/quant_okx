@echo off
echo ============================================
echo   QuantOKX - OKX量化交易管理平台
echo ============================================
echo.

cd /d "%~dp0"

if not exist "%~dp0backend\.venv\Scripts\python.exe" (
    echo [错误] 未找到后端虚拟环境，请先运行 install.bat。
    pause
    exit /b 1
)
if not exist "%~dp0frontend\node_modules" (
    echo [错误] 未找到前端依赖，请先运行 install.bat。
    pause
    exit /b 1
)
node -e "const [major,minor]=process.versions.node.split('.').map(Number);process.exit(major>22||(major===22&&minor>=12)?0:1)"
if errorlevel 1 (
    echo [错误] 前端需要 Node.js 22.12+，请先运行 install.bat。
    pause
    exit /b 1
)

echo [1/2] Starting backend server...
start "QuantOKX-Backend" /D "%~dp0backend" "%~dp0backend\.venv\Scripts\python.exe" -m uvicorn main:app --reload --host 127.0.0.1 --port 8000

echo [2/2] Starting frontend dev server...
start "QuantOKX-Frontend" /D "%~dp0frontend" cmd /k "npm run dev"

echo.
echo Both servers are starting...
echo Backend API: http://127.0.0.1:8000/docs
echo Frontend UI: http://127.0.0.1:5173
echo.
echo First use: set the admin password in the local login page.
echo.
pause
