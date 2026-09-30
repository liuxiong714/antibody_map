# 后端镜像（基础镜像走 DaoCloud 国内加速源，避免 Docker Hub 拉取慢）
FROM docker.m.daocloud.io/library/python:3.11.9-slim

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
# PyPI 默认源国内访问慢，切到 TUNA 清华源；加大超时与重试，避免弱网下读取超时中断构建
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple \
    && pip config set global.timeout 100 \
    && pip config set global.retries 8
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
# 优先使用本地缓存目录（backend/caj2pdf_cache/）；无缓存时在线拉取（国内源、尽力而为，失败不阻断构建）。
COPY backend/caj2pdf_cache/ /tmp/caj2pdf_cache/
RUN --mount=type=cache,target=/root/.cache/pip \
    if [ -n "$(find /tmp/caj2pdf_cache -name 'caj2pdf.tar.gz' -print -quit 2>/dev/null)" ]; then \
        echo ">>> 使用本地缓存安装 caj2pdf"; \
        mkdir -p /opt/caj2pdf \
        && tar -xzf /tmp/caj2pdf_cache/caj2pdf.tar.gz --strip-components=1 -C /opt/caj2pdf \
        && cp /tmp/caj2pdf_cache/libjbigdec.so /opt/caj2pdf/libjbigdec.so \
        && cp /tmp/caj2pdf_cache/libjbig2codec.so /opt/caj2pdf/libjbig2codec.so \
        && chmod +x /opt/caj2pdf/caj2pdf \
        && python -m pip install PyPDF2==2.2.0 imagesize==1.3.0 \
        && rm -rf /tmp/caj2pdf_cache; \
    else \
        echo ">>> 在线安装 caj2pdf（国内源，尽力而为）"; \
        apt-get update && apt-get install -y --no-install-recommends git jbig2dec libjbig-dev \
        && rm -rf /var/lib/apt/lists/*; \
        mkdir -p /opt/caj2pdf; \
        git clone --depth 1 https://gh-proxy.com/https://github.com/caj2pdf/caj2pdf.git /tmp/caj2pdf-src 2>/dev/null \
        && cp -rf /tmp/caj2pdf-src/. /opt/caj2pdf/ 2>/dev/null || true; \
        cp /usr/lib/x86_64-linux-gnu/libjbig.so.0 /opt/caj2pdf/libjbigdec.so 2>/dev/null || true; \
        cp /usr/lib/x86_64-linux-gnu/libjbig2dec.so.0 /opt/caj2pdf/libjbig2codec.so 2>/dev/null || true; \
        python -m pip install PyPDF2==2.2.0 imagesize==1.3.0 2>/dev/null || true; \
        chmod +x /opt/caj2pdf/caj2pdf 2>/dev/null || true; \
        rm -rf /tmp/caj2pdf-src || true; \
    fi

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
# 复制 docs/（包含 changelog.md，_detect_version() 从这里解析真实版本号）
COPY docs/ ./docs/
# caj2pdf 包装脚本（切换工作目录后执行，确保相对路径共享库可加载）
COPY backend/scripts/caj2pdf-wrapper /usr/local/bin/caj2pdf
RUN chmod +x /usr/local/bin/caj2pdf
WORKDIR /app/backend

# 数据库备份客户端（pg_dump）：独立新增一层，避免触发 caj2pdf/pip 等重型层重建
# apt 源已在前面层切换为阿里云镜像，此处直接 install 即可
RUN apt-get update && apt-get install -y --no-install-recommends postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# C6：以非 root 运行。创建普通用户 app，并将运行期可写目录（数据/日志/备份）
# 归其所有；Home 指向 /home/app（MinerU/modelscope 缓存默认落在 $HOME/.cache）。
# 若宿主机 bind mount 权限导致写入失败，可在 docker-compose.yml 中以
# `user: "0:0"` 覆盖（见 docker-compose.yml backend 服务注释）。
RUN groupadd -r app && useradd -r -g app -d /home/app -m app \
    && mkdir -p /app/backend/data /app/backend/logs /app/backend/backups \
    && chown -R app:app /app/backend/data /app/backend/logs /app/backend/backups /home/app
ENV HOME=/home/app

# 暴露端口
EXPOSE 8000

# 启动服务（lifespan 启动时自动执行 Alembic 迁移）
# C6：--forwarded-allow-ips 不再使用 "*"（避免任意来源伪造 X-Forwarded-For），
# 默认仅信任回环；经 nginx 代理部署时，在 compose 中把 nginx 容器 IP 配入
# FORWARDED_ALLOW_IPS（与 C5 的 TRUSTED_PROXIES 保持一致）。
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips \"${FORWARDED_ALLOW_IPS:-127.0.0.1,::1}\""]

USER app