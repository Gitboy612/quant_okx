@echo off
REM QuantOKX installer build script (ASCII-only, CRLF, goto-based for cmd.exe compat)
REM
REM Usage:
REM   build_installer.bat                    默认 web 版（npm build + PyInstaller + iscc）
REM   build_installer.bat --target web       显式 web 版
REM   build_installer.bat --target desktop   桌面版（PySide6/QML，跳过 npm，用 desktop spec + desktop iss）
REM
REM 两种产物：
REM   web      -> installer\Output\QuantOKX-Setup.exe          (浏览器版，内嵌 React 前端)
REM   desktop  -> installer\Output\QuantOKX-Desktop-Setup.exe  (QML 桌面客户端)
setlocal

echo ============================================================
echo   QuantOKX Installer Build Script
echo ============================================================
echo.

REM ===== Parse --target argument =====
set TARGET=web
if "%~1"=="" goto :args_parsed
if /i "%~1"=="--target" goto :parse_target
if /i "%~1"=="desktop" (
    set TARGET=desktop
    goto :args_parsed
)
if /i "%~1"=="web" (
    set TARGET=web
    goto :args_parsed
)
echo [error] Unknown argument: "%~1"
goto :error
:parse_target
if /i "%~2"=="desktop" (
    set TARGET=desktop
    goto :args_parsed
)
if /i "%~2"=="web" (
    set TARGET=web
    goto :args_parsed
)
echo [error] Unknown --target value: "%~2" (expected: web ^| desktop)
goto :error
:args_parsed
echo [info] Build target: %TARGET%
echo.

REM ===== Dependency check =====
echo [check] Verifying dependencies...
where python >nul 2>nul
if errorlevel 1 goto :no_python
where pyinstaller >nul 2>nul
if errorlevel 1 goto :no_pyinstaller
where iscc >nul 2>nul
if errorlevel 1 goto :no_iscc
REM web 版还需 node/npm（构建 React 前端）；桌面版用 QML，无需 node/npm
if "%TARGET%"=="desktop" goto :deps_ok
where node >nul 2>nul
if errorlevel 1 goto :no_node
where npm >nul 2>nul
if errorlevel 1 goto :no_npm
:deps_ok
echo [ok] All dependencies present.
echo.

REM Switch to project root (parent of this script's directory)
pushd "%~dp0\.."

if "%TARGET%"=="desktop" goto :build_desktop

REM ============ WEB 版流程（保持原样） ============
REM ===== Step 1: Build frontend =====
echo ============================================================
echo   Step 1/3: Build frontend (web)
echo ============================================================
pushd frontend
call npm install
if errorlevel 1 goto :npm_install_failed
call npm run build
if errorlevel 1 goto :npm_build_failed
popd
echo [ok] Frontend build complete.
echo.

REM ===== Step 2: PyInstaller backend =====
echo ============================================================
echo   Step 2/3: PyInstaller build backend (web)
echo ============================================================
pyinstaller QuantOKX.spec --noconfirm
if errorlevel 1 goto :pyinstaller_failed
echo [ok] Backend packaged to dist\QuantOKX\
echo.

REM ===== Step 3: Inno Setup installer =====
echo ============================================================
echo   Step 3/3: Inno Setup generate installer (web)
echo ============================================================
iscc installer\quant_okx.iss
if errorlevel 1 goto :iscc_failed
echo [ok] Installer generated.
echo.

popd

echo ============================================================
echo   Build succeeded! (web)
echo   Installer: installer\Output\QuantOKX-Setup.exe
echo ============================================================
exit /b 0

REM ============ 桌面版流程 ============
:build_desktop
REM 桌面版用 QML，无需 npm build；直接 PyInstaller + Inno Setup（两步）
echo ============================================================
echo   Step 1/2: PyInstaller build desktop (PySide6/QML)
echo ============================================================
pyinstaller desktop\QuantOKX-Desktop.spec --noconfirm
if errorlevel 1 goto :pyinstaller_failed
echo [ok] Desktop packaged to dist\QuantOKX-Desktop\
echo.

REM ===== Step 2: Inno Setup installer =====
echo ============================================================
echo   Step 2/2: Inno Setup generate installer (desktop)
echo ============================================================
iscc installer\quant_okx_desktop.iss
if errorlevel 1 goto :iscc_failed
echo [ok] Installer generated.
echo.

popd

echo ============================================================
echo   Build succeeded! (desktop)
echo   Installer: installer\Output\QuantOKX-Desktop-Setup.exe
echo ============================================================
exit /b 0

REM ===== Error handlers =====
:no_node
echo [error] Node.js not found. Please install Node.js 18+ and retry.
goto :error
:no_npm
echo [error] npm not found. Please check Node.js installation.
goto :error
:no_python
echo [error] Python not found. Please install Python 3.10+ and retry.
goto :error
:no_pyinstaller
echo [error] PyInstaller not found. Run: pip install pyinstaller
goto :error
:no_iscc
echo [error] Inno Setup compiler (iscc) not found.
echo        Install Inno Setup 6 and add its directory to system PATH.
goto :error
:npm_install_failed
echo [error] npm install failed.
popd
goto :error
:npm_build_failed
echo [error] npm run build failed.
popd
goto :error
:pyinstaller_failed
echo [error] PyInstaller build failed.
popd
goto :error
:iscc_failed
echo [error] Inno Setup compile failed.
popd
goto :error

:error
echo.
echo ============================================================
echo   Build failed. Fix the issue above and retry.
echo ============================================================
exit /b 1
