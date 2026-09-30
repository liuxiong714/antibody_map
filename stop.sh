#!/bin/bash
# 停止所有服务：本机开发进程（start.sh 启动的 uvicorn/vite）+ Docker 容器
# 用法: bash stop.sh

BACKEND_PORT=8000
FRONTEND_PORT=3000

kill_port() {
    local port=$1
    if command -v lsof &>/dev/null; then
        local pids=$(lsof -ti :${port} 2>/dev/null || true)
        if [ -n "$pids" ]; then
            echo "关闭端口 ${port} 上的进程: $pids"
            kill -9 $pids 2>/dev/null || true
        fi
    elif command -v netstat &>/dev/null; then
        local pids=$(netstat -ano 2>/dev/null | grep ":${port}" | grep LISTENING | awk '{print $NF}' | sort -u)
        if [ -n "$pids" ]; then
            echo "关闭端口 ${port} 上的进程 PID: $pids"
            for pid in $pids; do
                kill -9 $pid 2>/dev/null || true
            done
        fi
    fi
}

echo "关闭本机开发进程（端口 ${BACKEND_PORT}/${FRONTEND_PORT}）..."
kill_port $BACKEND_PORT
kill_port $FRONTEND_PORT

echo "关闭 Docker 容器..."
docker compose down

echo "已全部停止"
