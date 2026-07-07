@echo off
echo ============================================
echo   QuantOKX - OKX量化交易管理平台
echo ============================================
echo.

cd /d "%~dp0"

echo [1/2] Starting backend server...
start "QuantOKX-Backend" cmd /k "cd /d "%~dp0backend" && python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000"

echo [2/2] Starting frontend dev server...
cd /d "%~dp0frontend"
start "QuantOKX-Frontend" cmd /k "npm run dev"

echo.
echo Both servers are starting...
echo Backend API: http://127.0.0.1:8000/docs
echo Frontend UI: http://127.0.0.1:5173
echo.
echo Default login: admin / admin123
echo.
pause
