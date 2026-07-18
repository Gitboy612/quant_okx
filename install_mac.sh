#!/usr/bin/env bash

# QuantOKX macOS 环境初始化脚本
#
# 功能：
#   1. 检查 macOS、Xcode Command Line Tools、Python 3.10+、Node.js 22.12+ 与 npm
#   2. 在缺少运行环境时通过已安装的 Homebrew 补齐依赖
#   3. 创建 backend/.venv 并安装后端依赖
#   4. 安装前端 npm 依赖
#   5. 从 .env.example 创建 .env，并生成随机 JWT 密钥
#   6. 执行后端关键依赖导入烟雾测试

set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
VENV_DIR="$BACKEND_DIR/.venv"

info() {
    printf '[信息] %s\n' "$1"
}

success() {
    printf '[完成] %s\n' "$1"
}

warn() {
    printf '[警告] %s\n' "$1" >&2
}

fail() {
    printf '[错误] %s\n' "$1" >&2
    exit 1
}

command_exists() {
    command -v "$1" >/dev/null 2>&1
}

python_is_supported() {
    "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1
}

find_supported_python() {
    local candidate
    for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
        if command_exists "$candidate" && python_is_supported "$candidate"; then
            command -v "$candidate"
            return 0
        fi
    done
    return 1
}

node_is_supported() {
    "$1" -e '
        const [major, minor] = process.versions.node.split(".").map(Number);
        process.exit(major > 22 || (major === 22 && minor >= 12) ? 0 : 1);
    ' >/dev/null 2>&1
}

activate_supported_node() {
    local candidate
    local nvm_root="${NVM_DIR:-${HOME:-}/.nvm}"

    if command_exists node && node_is_supported "$(command -v node)"; then
        return 0
    fi

    # Codex/终端未加载 nvm 时，直接寻找已经安装的 Node 版本。
    for candidate in "$nvm_root"/versions/node/*/bin/node; do
        if [[ -x "$candidate" ]] && node_is_supported "$candidate"; then
            export PATH="$(dirname "$candidate"):$PATH"
            return 0
        fi
    done
    return 1
}

ensure_homebrew() {
    if ! command_exists brew; then
        fail "缺少 Homebrew。请先访问 https://brew.sh 安装 Homebrew，然后重新运行本脚本。"
    fi
}

printf '%s\n' '============================================================'
printf '%s\n' '  QuantOKX macOS 环境初始化'
printf '  项目目录：%s\n' "$ROOT_DIR"
printf '%s\n' '============================================================'

if [[ "$(uname -s)" != "Darwin" ]]; then
    fail "该脚本仅适用于 macOS。"
fi

if ! xcode-select -p >/dev/null 2>&1; then
    warn "未安装 Xcode Command Line Tools，正在打开系统安装程序。"
    xcode-select --install >/dev/null 2>&1 || true
    fail "请完成 Xcode Command Line Tools 安装后重新运行本脚本。"
fi
success "Xcode Command Line Tools 已就绪。"

PYTHON_CMD="$(find_supported_python || true)"
if [[ -z "$PYTHON_CMD" ]]; then
    ensure_homebrew
    info "未找到 Python 3.10+，将通过 Homebrew 安装 Python 3.12。"
    brew install python@3.12
    hash -r
    PYTHON_CMD="$(find_supported_python || true)"
fi
[[ -n "$PYTHON_CMD" ]] || fail "Python 3.10+ 安装后仍不可用，请检查 PATH。"
PYTHON_VERSION="$($PYTHON_CMD -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')"
success "使用 Python ${PYTHON_VERSION}：$PYTHON_CMD"

if ! activate_supported_node; then
    ensure_homebrew
    info "未找到 Node.js 22.12+，将通过 Homebrew 安装或升级 Node.js。"
    if brew list --versions node >/dev/null 2>&1; then
        brew upgrade node || true
    else
        brew install node
    fi
    hash -r
fi

command_exists node || fail "Node.js 安装后仍不可用，请检查 PATH。"
command_exists npm || fail "未找到 npm，请重新安装 Node.js。"
node_is_supported "$(command -v node)" || fail "需要 Node.js 22.12+，当前版本为 $(node --version)。"
success "使用 Node.js $(node --version) 与 npm $(npm --version)。"

[[ -f "$BACKEND_DIR/requirements.txt" ]] || fail "未找到 backend/requirements.txt。"
[[ -f "$FRONTEND_DIR/package.json" ]] || fail "未找到 frontend/package.json。"

if [[ -x "$VENV_DIR/bin/python" ]]; then
    if ! python_is_supported "$VENV_DIR/bin/python"; then
        fail "现有 backend/.venv 使用的 Python 版本低于 3.10。请先将它改名或删除，再重新运行脚本。"
    fi
    success "后端虚拟环境已经存在。"
else
    info "正在创建后端虚拟环境：backend/.venv"
    "$PYTHON_CMD" -m venv "$VENV_DIR"
    success "后端虚拟环境创建完成。"
fi

VENV_PYTHON="$VENV_DIR/bin/python"

info "正在升级 pip、setuptools 和 wheel。"
"$VENV_PYTHON" -m pip install --upgrade pip setuptools wheel

info "正在安装后端依赖。"
"$VENV_PYTHON" -m pip install \
    -r "$BACKEND_DIR/requirements.txt" \
    aiosqlite \
    python-dotenv \
    PyYAML \
    pytest \
    pytest-asyncio
success "后端依赖安装完成。"

info "正在安装或同步前端依赖。"
(
    cd "$FRONTEND_DIR"
    npm install --include=optional
)
success "前端依赖安装完成。"

if [[ ! -f "$ROOT_DIR/.env" ]]; then
    if [[ -f "$ROOT_DIR/.env.example" ]]; then
        cp "$ROOT_DIR/.env.example" "$ROOT_DIR/.env"
        GENERATED_SECRET="$($VENV_PYTHON -c 'import secrets; print(secrets.token_urlsafe(48))')"
        sed -i.bak \
            "s|JWT_SECRET_KEY=change-this-to-a-random-secret-key|JWT_SECRET_KEY=${GENERATED_SECRET}|" \
            "$ROOT_DIR/.env"
        rm -f "$ROOT_DIR/.env.bak"
        success "已从 .env.example 创建 .env，并生成随机 JWT 密钥。"
    else
        warn "未找到 .env.example，请手动创建 .env。"
    fi
else
    success ".env 已存在，未覆盖现有配置。"
fi

if command_exists mihomo || command_exists clash || command_exists clash-meta; then
    success "检测到系统级 Mihomo/Clash，可供代理功能使用。"
else
    warn "未检测到 macOS 版 Mihomo/Clash；代理功能不可用，但不影响项目基本启动。"
    warn "仓库中的 backend/bin/*.exe 是 Windows 程序，不能在 macOS 上运行。"
fi

info "正在执行后端依赖导入烟雾测试。"
(
    cd "$BACKEND_DIR"
    "$VENV_PYTHON" -c "import fastapi, uvicorn, sqlalchemy, httpx, bcrypt, cryptography, jose, apscheduler, websockets, multipart, pydantic, aiosqlite, dotenv, yaml; print('OK: 后端关键依赖导入成功')"
)
success "烟雾测试通过。"

printf '\n%s\n' '============================================================'
printf '%s\n' '  QuantOKX macOS 环境初始化完成'
printf '%s\n' '============================================================'
printf '%s\n' '下一步：'
printf '%s\n' '  ./start_mac.sh'
printf '\n%s\n' '启动后访问：'
printf '%s\n' '  前端界面：http://127.0.0.1:5173'
printf '%s\n' '  API 文档：http://127.0.0.1:8000/docs'
printf '%s\n' '  初始账号：admin / admin123'
printf '\n%s\n' '首次登录后请立即修改默认密码；实盘使用前请先在 OKX 模拟盘验证。'
