#!/bin/bash
# ============================================================
# Docker 一键启动脚本（自动探测 GPU）
# - 有 NVIDIA Container Toolkit → 默认 GPU 模式
# - 无 GPU / 无 toolkit        → 自动退回 CPU 模式
# 用法: bash docker-start.sh [up|down|restart|logs]
# ============================================================
set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

ACTION="${1:-up}"

# ---- 探测 NVIDIA GPU ----
GPU_ENABLED=0

if docker info 2>/dev/null | grep -q "Runtimes:" && docker info 2>/dev/null | grep -q "nvidia"; then
    # nvidia runtime 已注册
    GPU_ENABLED=1
elif command -v nvidia-smi &>/dev/null && nvidia-smi -L &>/dev/null; then
    # 宿主机有 nvidia-smi 且能列出 GPU
    GPU_ENABLED=1
fi

# ---- 构建 compose 命令 ----
COMPOSE_FILES="-f docker-compose.yml"

if [ "$GPU_ENABLED" = "1" ]; then
    echo "✅ 检测到 NVIDIA GPU，使用 GPU 模式启动 worker"
else
    echo "⚠️  未检测到 NVIDIA GPU，自动退回 CPU 模式"
    COMPOSE_FILES="$COMPOSE_FILES -f docker-compose.cpu.yml"
fi

# ---- 执行 ----
case "$ACTION" in
    up)
        echo "启动服务..."
        docker compose $COMPOSE_FILES up -d
        echo "等待健康检查..."
        sleep 15
        docker compose $COMPOSE_FILES ps --format "table {{.Name}}\t{{.Status}}"
        ;;
    down)
        docker compose $COMPOSE_FILES down
        ;;
    restart)
        docker compose $COMPOSE_FILES restart
        sleep 10
        docker compose $COMPOSE_FILES ps --format "table {{.Name}}\t{{.Status}}"
        ;;
    logs)
        docker compose $COMPOSE_FILES logs --tail=50
        ;;
    *)
        echo "用法: bash docker-start.sh [up|down|restart|logs]"
        exit 1
        ;;
esac