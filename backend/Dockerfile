# 后端镜像
FROM python:3.11-slim

# 设置工作目录与环境变量
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# 是否安装 MinerU 增强解析（仅 worker 需要；PyTorch 全家桶，镜像体积大，
# 默认不装以免拖慢 API 服务启动与内存）
ARG INSTALL_MINERU=false

WORKDIR /app

# 安装系统依赖（PyMuPDF、lxml 等需要的基础库）
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libjpeg-dev \
    zlib1g-dev \
    libxml2-dev \
    libxslt1-dev \
    tesseract-ocr \
    mupdf-tools \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# MinerU 可选依赖（仅 INSTALL_MINERU=true 时安装）
COPY backend/requirements-mineru.txt ./requirements-mineru.txt
RUN if [ "$INSTALL_MINERU" = "true" ]; then \
        pip install --no-cache-dir -r requirements-mineru.txt; \
    fi

# MinerU 运行时系统库（opencv-python 依赖，缺失会导致 libGL.so.1 找不到、
# MinerU 导入失败）。放在依赖安装之后，避免 apt 层变更触发 torch 等重型层重建
RUN if [ "$INSTALL_MINERU" = "true" ]; then \
        apt-get update && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        && rm -rf /var/lib/apt/lists/*; \
    fi

# 复制后端代码
COPY backend/ ./backend/
WORKDIR /app/backend

# 暴露端口
EXPOSE 8000

# 启动服务（lifespan 启动时自动执行 Alembic 迁移）
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]