# 前端镜像：构建阶段 + 运行阶段
# ---- 构建阶段 ----
FROM node:20-alpine AS build

WORKDIR /app

# 先复制依赖清单，利用层缓存加速
COPY frontend/package*.json ./
RUN npm install

# 复制源码并构建
COPY frontend/ ./
RUN npm run build

# ---- 运行阶段 ----
FROM nginx:alpine

# 复制 nginx 配置（SPA 路由回退 + /api 反向代理）
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf

# 复制构建产物
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]