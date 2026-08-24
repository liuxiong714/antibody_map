# 后端镜像
FROM python:3.11-slim

# 设置工作目录与环境变量
# 不再强制 PIP_NO_CACHE_DIR=1：配合 BuildKit 缓存挂载（--mount=type=cache,target=/root/.cache/pip）
# 将下载的 wheel 固化到构建缓存，避免下次重建（含 torch 等重型依赖）反复下载。
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# 是否安装 MinerU 增强解析（仅 worker 需要；PyTorch 全家桶，镜像体积大，
# 默认不装以免拖慢 API 服务启动与内存）
ARG INSTALL_MINERU=false

WORKDIR /app

# 安装系统依赖（PyMuPDF、lxml 等需要的基础库）
# 默认源（deb.debian.org）国内访问慢，切换为阿里云镜像加速（TUNA 偶发 403）
RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g' \
        /etc/apt/sources.list \
        /etc/apt/sources.list.d/debian.sources 2>/dev/null || true; \
    apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libjpeg-dev \
    zlib1g-dev \
    libxml2-dev \
    libxslt1-dev \
    tesseract-ocr \
    tesseract-ocr-chi-sim \
    mupdf-tools \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
# PyPI 默认源国内访问慢，统一切到阿里云镜像（TUNA 偶发不通，改用阿里源）
RUN pip config set global.index-url https://mirrors.aliyun.com/pypi/simple
# 本地 wheel 仓库（离线安装用，由 scripts/download_wheels.ps1 生成）
# 有 .whl 文件时优先离线安装，否则回退到 PyPI 在线下载
COPY backend/wheels/ /wheels/
COPY backend/requirements.txt ./requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    if [ -n "$(find /wheels -maxdepth 1 -name '*.whl' -print -quit 2>/dev/null)" ]; then \
        echo ">>> 使用本地 wheel 仓库离线安装"; \
        python -m pip install --no-index --find-links=/wheels -r requirements.txt; \
    else \
        echo ">>> 本地 wheel 仓库为空，在线下载安装"; \
        python -m pip install -r requirements.txt; \
    fi

# CAJ 转换工具（知网 .caj → PDF）：caj2pdf 不在 PyPI，从 GitHub 拉取源码与预编译共享库。
# 依赖 mutool（mupdf-tools，已在上面安装）；共享库 libjbig*.so 通过相对路径 ./libjbig*.so 加载，
# 因此运行时通过包装脚本 scripts/caj2pdf-wrapper 切换到 /opt/caj2pdf 再执行。
# 使用本地缓存目录（backend/caj2pdf_cache/）避免构建时 GitHub 下载不稳定。
COPY backend/caj2pdf_cache/ /tmp/caj2pdf_cache/
RUN --mount=type=cache,target=/root/.cache/pip \
    mkdir -p /opt/caj2pdf \
    && tar -xzf /tmp/caj2pdf_cache/caj2pdf.tar.gz --strip-components=1 -C /opt/caj2pdf \
    && cp /tmp/caj2pdf_cache/libjbigdec.so /opt/caj2pdf/libjbigdec.so \
    && cp /tmp/caj2pdf_cache/libjbig2codec.so /opt/caj2pdf/libjbig2codec.so \
    && chmod +x /opt/caj2pdf/caj2pdf \
    && python -m pip install --no-index --find-links=/wheels PyPDF2==2.2.0 imagesize==1.3.0 \
    && rm -rf /tmp/caj2pdf_cache

# MinerU 可选依赖（仅 INSTALL_MINERU=true 时安装）
COPY backend/requirements-mineru.txt ./requirements-mineru.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    if [ "$INSTALL_MINERU" = "true" ]; then \
        if [ -n "$(find /wheels -maxdepth 1 -name '*.whl' -print -quit 2>/dev/null)" ]; then \
            echo ">>> [MinerU] 使用本地 wheel 仓库离线安装"; \
            python -m pip install --no-index --find-links=/wheels -r requirements-mineru.txt; \
        else \
            echo ">>> [MinerU] 本地 wheel 仓库为空，在线下载安装"; \
            python -m pip install -r requirements-mineru.txt; \
        fi; \
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
# caj2pdf 包装脚本（切换工作目录后执行，确保相对路径共享库可加载）
COPY backend/scripts/caj2pdf-wrapper /usr/local/bin/caj2pdf
RUN chmod +x /usr/local/bin/caj2pdf
WORKDIR /app/backend

# 数据库备份客户端（pg_dump）：独立新增一层，避免触发 caj2pdf/pip 等重型层重建
# apt 源已在前面层切换为阿里云镜像，此处直接 install 即可
RUN apt-get update && apt-get install -y --no-install-recommends postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# 暴露端口
EXPOSE 8000

# 启动服务（lifespan 启动时自动执行 Alembic 迁移）
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]