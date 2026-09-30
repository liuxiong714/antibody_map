# 前端镜像：构建阶段 + 运行阶段
# ---- 构建阶段 ----
# 国内构建优先走 DaoCloud 镜像站，避免 docker.1ms.run / docker.xuanyuan.me 挂掉时阻塞
ARG REGISTRY=docker.m.daocloud.io
FROM ${REGISTRY}/library/node:20-alpine AS build

WORKDIR /app

# npm 国内源，加快依赖安装
RUN npm config set registry https://registry.npmmirror.com

# 先复制依赖清单，利用层缓存加速
# 用 npm ci（而非 npm install）严格按 package-lock.json 安装，保证每次构建依赖可复现
COPY frontend/package*.json ./
RUN npm ci

# 复制源码并构建
COPY frontend/ ./
RUN npm run build

# ---- 运行阶段 ----
ARG REGISTRY=docker.m.daocloud.io
FROM ${REGISTRY}/library/nginx:alpine

# 复制 nginx 配置（SPA 路由回退 + /api 反向代理）
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf

# 复制构建产物
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]