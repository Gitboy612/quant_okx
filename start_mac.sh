#!/usr/bin/env bash

# QuantOKX macOS 开发环境启动脚本
# 同时启动 FastAPI 后端和 Vite 前端，Ctrl+C 时清理两个子进程。

set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
VENV_PYTHON="$BACKEND_DIR/.venv/bin/python"
ENV_FILE="$ROOT_DIR/.env"

BACKEND_PID=""
FRONTEND_PID=""

fail() {
    printf '[错误] %s\n' "$1" >&2
    exit 1
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

    if command -v node >/dev/null 2>&1 && node_is_supported "$(command -v node)"; then
        return 0
    fi
    for candidate in "$nvm_root"/versions/node/*/bin/node; do
        if [[ -x "$candidate" ]] && node_is_supported "$candidate"; then
            export PATH="$(dirname "$candidate"):$PATH"
            return 0
        fi
    done
    return 1
}

read_env_value() {
    local key="$1"
    local value=""
    if [[ -f "$ENV_FILE" ]]; then
        value="$(awk -F= -v wanted="$key" '$1 == wanted { sub(/^[^=]*=/, ""); print; exit }' "$ENV_FILE" | tr -d '\r')"
    fi
    printf '%s' "$value"
}

cleanup() {
    trap - EXIT
    if [[ -n "$FRONTEND_PID" ]] && kill -0 "$FRONTEND_PID" >/dev/null 2>&1; then
        kill "$FRONTEND_PID" >/dev/null 2>&1 || true
    fi
    if [[ -n "$BACKEND_PID" ]] && kill -0 "$BACKEND_PID" >/dev/null 2>&1; then
        kill "$BACKEND_PID" >/dev/null 2>&1 || true
    fi
    [[ -z "$FRONTEND_PID" ]] || wait "$FRONTEND_PID" >/dev/null 2>&1 || true
    [[ -z "$BACKEND_PID" ]] || wait "$BACKEND_PID" >/dev/null 2>&1 || true
}

handle_signal() {
    printf '\n[信息] 正在停止 QuantOKX 前后端服务...\n'
    cleanup
    exit 130
}

trap cleanup EXIT
trap handle_signal INT TERM HUP

[[ "$(uname -s)" == "Darwin" ]] || fail "该脚本仅适用于 macOS。"
[[ -x "$VENV_PYTHON" ]] || fail "未找到 backend/.venv。请先运行 ./install_mac.sh。"
[[ -d "$FRONTEND_DIR/node_modules" ]] || fail "未找到前端依赖。请先运行 ./install_mac.sh。"
activate_supported_node || fail "需要 Node.js 22.12+。请先运行 ./install_mac.sh。"
command -v npm >/dev/null 2>&1 || fail "未找到 npm，请安装 Node.js 22.12+。"

BACKEND_HOST="$(read_env_value HOST)"
BACKEND_PORT="$(read_env_value PORT)"
BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="5173"

[[ "$BACKEND_PORT" =~ ^[0-9]+$ ]] || fail ".env 中的 PORT 必须是数字。"

if lsof -nP -iTCP:"$BACKEND_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    fail "后端端口 $BACKEND_PORT 已被占用，请停止占用进程或修改 .env。"
fi
if lsof -nP -iTCP:"$FRONTEND_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    fail "前端端口 $FRONTEND_PORT 已被占用，请停止占用进程后重试。"
fi

printf '%s\n' '============================================================'
printf '%s\n' '  QuantOKX macOS 开发环境'
printf '%s\n' '============================================================'
printf '[1/2] 启动后端：http://127.0.0.1:%s\n' "$BACKEND_PORT"
(
    cd "$BACKEND_DIR"
    exec "$VENV_PYTHON" -m uvicorn main:app \
        --reload \
        --host "$BACKEND_HOST" \
        --port "$BACKEND_PORT"
) &
BACKEND_PID=$!

printf '[2/2] 启动前端：http://127.0.0.1:%s\n' "$FRONTEND_PORT"
(
    cd "$FRONTEND_DIR"
    exec npm run dev -- --host 127.0.0.1 --port "$FRONTEND_PORT" --strictPort
) &
FRONTEND_PID=$!

BACKEND_READY=0
FRONTEND_READY=0
for _ in $(seq 1 40); do
    if ! kill -0 "$BACKEND_PID" >/dev/null 2>&1; then
        fail "后端进程启动失败，请检查上方日志。"
    fi
    if ! kill -0 "$FRONTEND_PID" >/dev/null 2>&1; then
        fail "前端进程启动失败，请检查上方日志。"
    fi

    if curl -fsS "http://127.0.0.1:${BACKEND_PORT}/docs" >/dev/null 2>&1; then
        BACKEND_READY=1
    fi
    if curl -fsS "http://127.0.0.1:${FRONTEND_PORT}" >/dev/null 2>&1; then
        FRONTEND_READY=1
    fi
    if (( BACKEND_READY == 1 && FRONTEND_READY == 1 )); then
        break
    fi
    sleep 0.5
done

if (( BACKEND_READY == 0 )); then
    fail "后端在等待时间内未就绪，请检查上方日志。"
fi
if (( FRONTEND_READY == 0 )); then
    fail "前端在等待时间内未就绪，请检查上方日志。"
fi

printf '\n%s\n' 'QuantOKX 已启动：'
printf '  前端界面：http://127.0.0.1:%s\n' "$FRONTEND_PORT"
printf '  API 文档：http://127.0.0.1:%s/docs\n' "$BACKEND_PORT"
printf '%s\n' '  初始账号：admin / admin123'
printf '%s\n' '按 Ctrl+C 同时停止前端和后端。'

open "http://127.0.0.1:${FRONTEND_PORT}" >/dev/null 2>&1 || true

while true; do
    if ! kill -0 "$BACKEND_PID" >/dev/null 2>&1; then
        fail "后端进程已退出。"
    fi
    if ! kill -0 "$FRONTEND_PID" >/dev/null 2>&1; then
        fail "前端进程已退出。"
    fi
    sleep 1
done
