# 快速开始

## 环境要求

- Python 3.10+
- Node.js 18+ (推荐 20+)
- Docker Desktop (Windows / macOS) 或 Docker & Docker Compose (Linux)
- Tesseract OCR (可选，用于扫描版 PDF 的文字识别)
- **CAJ 转换工具** (可选，用于解析 CAJ 格式文献)
- **NVIDIA GPU + NVIDIA Container Toolkit**（可选但推荐）：worker 容器 GPU 加速 MinerU 文档解析

## Windows 一键部署

### 1. 安装基础软件

| 软件 | 下载地址 | 说明 |
|------|----------|------|
| **Git** | https://git-scm.com/download/win | 克隆代码 |
| **Python 3.10+** | https://www.python.org/downloads/ | 安装时勾选 "Add Python to PATH" |
| **Node.js 20+** | https://nodejs.org/ | 选 LTS 版本 |
| **Docker Desktop** | https://www.docker.com/products/docker-desktop/ | 运行 PostgreSQL/Redis/MinIO |

### 2. 克隆项目

```powershell
git clone https://github.com/liuxiong714/antibody_map.git
cd antibody_map
```

### 3. 配置环境变量

```powershell
copy .env.example .env
notepad .env
```

**必填项**：`LLM_API_KEY`（你的 LLM API Key，DeepSeek 等）

### 4. 一键启动

```powershell
.\start.ps1
```

脚本会自动完成：检查依赖 → 安装依赖 → 启动 Docker → 启动后端 → 启动前端 → 打开浏览器。

> 如果提示"无法加载文件，因为在此系统上禁止运行脚本"，请先执行：
> ```powershell
> Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
> ```

### 5. 停止服务

按 `Ctrl+C` 即可停止全部服务，或单独执行 `.\stop.ps1`。

## macOS / Linux 部署

```bash
git clone https://github.com/liuxiong714/antibody_map.git
cd antibody_map
cp .env.example .env
# 编辑 .env，至少填写 LLM_API_KEY
bash start.sh
```

## 手动分步启动（高级用户）

```bash
# 1. 启动基础设施
docker compose up -d

# 2. 后端 (端口 8080)
cd backend
pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8080 --reload

# 3. 前端 (端口 3000)
cd frontend
npm install
npm run dev

# 4. Celery Worker (可选，用于异步 AI 提取)
cd backend
celery -A app.tasks.celery_app worker --loglevel=info --concurrency=2
```

## 访问地址

| 服务 | 地址 |
|------|------|
| 前端页面 | http://localhost:3000 |
| API 文档 (Swagger) | http://localhost:8080/docs |
| MinIO 控制台 | http://localhost:9001 |