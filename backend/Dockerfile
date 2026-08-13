# 后端镜像
FROM python:3.11-slim

# 设置工作目录与环境变量
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

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

# 复制后端代码
COPY backend/ ./backend/
WORKDIR /app/backend

# 暴露端口
EXPOSE 8000

# 启动服务（lifespan 启动时自动执行 Alembic 迁移）
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]