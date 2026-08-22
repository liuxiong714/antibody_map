# 部署指南

## Docker 部署

### 生产环境部署

```bash
# 克隆项目
git clone https://github.com/liuxiong714/antibody_map.git
cd antibody_map

# 配置环境变量
cp .env.example .env
# 编辑 .env，设置生产环境所需参数

# 构建并启动服务
docker compose up -d --build

# 查看日志
docker compose logs -f
```

### 重建特定服务

```bash
# 仅重建后端
docker compose up -d --build backend

# 仅重建 worker
docker compose up -d --build worker

# 仅重建前端
docker compose up -d --build frontend
```

### 停止服务

```bash
docker compose down
```

## GPU 加速（MinerU/Worker）

worker 容器通过 `deploy.resources.reservations.devices` 配置 NVIDIA GPU 透传：

```yaml
deploy:
  resources:
    reservations:
      devices:
        - driver: nvidia
          count: 1
          capabilities: [gpu]
```

Windows 下需在 WSL2 中安装 NVIDIA Container Toolkit 后重启 Docker。

## 数据迁移

### 旧电脑：导出备份

```powershell
# Windows
.\scripts\backup_db.ps1

# macOS/Linux
docker exec -e PGPASSWORD=antibody123 antibody-postgres pg_dump -U antibody -d antibody_map --no-owner --no-privileges > backups/latest_backup.sql
```

PDF 文件如果存在本地 `backend/data/pdfs/` 目录，需手动复制该文件夹到新电脑。

### 新电脑：恢复备份

1. 完成项目部署并启动服务（确保 Docker 容器运行）
2. 把备份文件复制到新电脑的项目目录下
3. 执行恢复：

```powershell
# Windows
.\scripts\restore_db.ps1 -BackupFile backups\latest_backup.sql
```

> ⚠️ 恢复会**覆盖**当前数据库所有数据，请谨慎操作。