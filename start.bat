@echo off
chcp 65001 >nul
echo ============================================
echo   QuantOKX - OKX量化交易管理平台
echo ============================================
echo.

cd /d "%~dp0"

set "VENV_DIR=%~dp0.venv"
set "BACKEND_DIR=%~dp0backend"
set "FRONTEND_DIR=%~dp0frontend"

echo [1/4] Checking Python virtual environment...
if not exist "%VENV_DIR%" (
    echo       Creating virtual environment...
    python -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo ERROR: Failed to create virtual environment. Please install Python 3.11+.
        pause
        exit /b 1
    )
)

set "PYTHON=%VENV_DIR%\Scripts\python.exe"
set "PIP=%VENV_DIR%\Scripts\pip.exe"

echo [2/4] Installing backend dependencies...
if not exist "%VENV_DIR%\Lib\site-packages\fastapi" (
    echo       Installing requirements...
    cd /d "%BACKEND_DIR%"
    "%PIP%" install -r requirements.txt
)

echo [3/4] Installing frontend dependencies...
if not exist "%FRONTEND_DIR%\node_modules" (
    echo       Installing npm packages...
    cd /d "%FRONTEND_DIR%"
    npm install
)

echo [4/4] Starting servers...
echo.
echo Starting backend server...
start "QuantOKX-Backend" cmd /k "cd /d "%BACKEND_DIR%" && "%PYTHON%" -m uvicorn main:app --reload --host 127.0.0.1 --port 8000"

echo Starting frontend dev server...
start "QuantOKX-Frontend" cmd /k "cd /d "%FRONTEND_DIR%" && npm run dev"

echo.
echo ============================================
echo   Servers are starting...
echo ============================================
echo   Backend API: http://127.0.0.1:8000/docs
echo   Frontend UI: http://127.0.0.1:5173
echo ============================================
echo   Default login: admin / admin123
echo ============================================
echo.
echo Press any key to close this window...
pause >nul
