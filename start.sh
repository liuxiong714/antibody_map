#!/bin/bash
# ============================================================
# Antibody Map 一键启动脚本
# 用法: bash start.sh
# 支持 WSL / Git Bash / Linux
# ============================================================

set -e

# ---- 配置 ----
BACKEND_PORT=8000
FRONTEND_PORT=3000
FRONTEND_URL="http://localhost:${FRONTEND_PORT}"

# 自动检测项目根目录（脚本所在目录）
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="${PROJECT_DIR}/backend"
FRONTEND_DIR="${PROJECT_DIR}/frontend"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "============================================"
echo "  Antibody Map 一键启动"
echo "============================================"

# ---- 1. 关闭已有服务 ----
echo -e "${YELLOW}[1/4] 检查已有服务...${NC}"

kill_port() {
    local port=$1
    if command -v lsof &>/dev/null; then
        local pids=$(lsof -ti :${port} 2>/dev/null || true)
        if [ -n "$pids" ]; then
            echo "  关闭端口 ${port} 上的进程: $pids"
            kill -9 $pids 2>/dev/null || true
        fi
    elif command -v netstat &>/dev/null; then
        local pids=$(netstat -ano 2>/dev/null | grep ":${port}" | grep LISTENING | awk '{print $NF}' | sort -u)
        if [ -n "$pids" ]; then
            for pid in $pids; do
                echo "  关闭端口 ${port} 上的进程 PID: $pid"
                kill -9 $pid 2>/dev/null || true
            done
        fi
    fi
}

kill_port $BACKEND_PORT
kill_port $FRONTEND_PORT
sleep 1

# ---- 2. 检查依赖 ----
echo -e "${YELLOW}[2/4] 检查依赖...${NC}"

if ! command -v python &>/dev/null && ! command -v python3 &>/dev/null; then
    echo -e "${RED}错误: 未找到 Python，请先安装 Python 3.10+${NC}"
    exit 1
fi
PYTHON=$(command -v python3 || command -v python)
echo "  Python: $($PYTHON --version)"

if ! command -v npm &>/dev/null; then
    echo -e "${RED}错误: 未找到 npm，请先安装 Node.js${NC}"
    exit 1
fi
echo "  Node: $(node --version)"
echo "  npm:  $(npm --version)"

# 检查前端 node_modules
if [ ! -d "${FRONTEND_DIR}/node_modules" ]; then
    echo "  安装前端依赖..."
    cd "${FRONTEND_DIR}" && npm install
fi

# ---- 3. 启动服务 ----
echo -e "${YELLOW}[3/4] 启动服务...${NC}"

# 启动后端
echo "  启动后端 (port ${BACKEND_PORT})..."
cd "${BACKEND_DIR}"
$PYTHON -m uvicorn app.main:app --host 0.0.0.0 --port ${BACKEND_PORT} --reload &
BACKEND_PID=$!
echo "  后端 PID: ${BACKEND_PID}"

# 启动前端
echo "  启动前端 (port ${FRONTEND_PORT})..."
cd "${FRONTEND_DIR}"
npm run dev -- --host 0.0.0.0 --port ${FRONTEND_PORT} &
FRONTEND_PID=$!
echo "  前端 PID: ${FRONTEND_PID}"

# ---- 4. 等待就绪并打开浏览器 ----
echo -e "${YELLOW}[4/4] 等待服务就绪...${NC}"

# 等待后端
echo "  等待后端..."
BACKEND_READY=0
for i in $(seq 1 30); do
    if curl -s "http://localhost:${BACKEND_PORT}/docs" > /dev/null 2>&1; then
        echo -e "  ${GREEN}后端就绪${NC}"
        BACKEND_READY=1
        break
    fi
    sleep 1
done
if [ "$BACKEND_READY" != "1" ]; then
    echo -e "  ${RED}后端 ${BACKEND_PORT} 端口 30 秒内未就绪，请检查后端日志${NC}"
fi

# 等待前端
echo "  等待前端..."
FRONTEND_READY=0
for i in $(seq 1 30); do
    if curl -s "http://localhost:${FRONTEND_PORT}" > /dev/null 2>&1; then
        echo -e "  ${GREEN}前端就绪${NC}"
        FRONTEND_READY=1
        break
    fi
    sleep 1
done
if [ "$FRONTEND_READY" != "1" ]; then
    echo -e "  ${RED}前端 ${FRONTEND_PORT} 端口 30 秒内未就绪，请检查前端日志${NC}"
fi

# 打开浏览器
echo ""
echo -e "${GREEN}============================================${NC}"
if [ "$BACKEND_READY" = "1" ] && [ "$FRONTEND_READY" = "1" ]; then
    echo -e "${GREEN}  服务启动完成！${NC}"
else
    echo -e "${YELLOW}  服务启动部分完成（后端就绪:$BACKEND_READY 前端就绪:$FRONTEND_READY），请检查上方警告${NC}"
fi
echo -e "${GREEN}  前端页面: ${FRONTEND_URL}${NC}"
echo -e "${GREEN}  后端文档: http://localhost:${BACKEND_PORT}/docs${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""

# 尝试打开浏览器（兼容 WSL / Linux / macOS）
if command -v powershell.exe &>/dev/null; then
    # WSL 环境
    powershell.exe -Command "Start-Process '${FRONTEND_URL}'"
elif command -v cmd.exe &>/dev/null; then
    # Git Bash / Cygwin
    cmd.exe /c start "${FRONTEND_URL}"
elif command -v xdg-open &>/dev/null; then
    xdg-open "${FRONTEND_URL}"
elif command -v open &>/dev/null; then
    open "${FRONTEND_URL}"
fi

# 清理：脚本退出时关闭服务（递归杀子进程，避免 --reload/vite 子进程残留）
kill_tree() {
    local pid=$1
    [ -z "$pid" ] && return
    # 先杀子进程（uvicorn --reload 的 reloader 子进程、npm 派生的 vite/node）
    pkill -TERM -P "$pid" 2>/dev/null || true
    kill -TERM "$pid" 2>/dev/null || true
    sleep 1
    # 残留进程强杀
    pkill -9 -P "$pid" 2>/dev/null || true
    kill -9 "$pid" 2>/dev/null || true
}

cleanup() {
    echo ""
    echo "关闭服务..."
    kill_tree $BACKEND_PID
    kill_tree $FRONTEND_PID
    echo "已关闭"
}
trap cleanup EXIT

# 保持脚本运行，等待 Ctrl+C
echo "按 Ctrl+C 停止所有服务"
wait
