# 抗体地图 (Antibody Map)

血清抗体流行病学数据可视化平台

## 项目简介

本项目是一个面向公共卫生和流行病学领域的**血清抗体水平数据管理、可视化与分析平台**。核心功能包括：

- **文献采集与管理**：上传流行病学相关的 PDF 文献，支持元数据管理
- **AI 自动数据提取**：利用 LLM 自动从文献中提取结构化的血清抗体数据点（血清阳性率、GMC 等）
- **数据审核**：对 AI 提取的数据点进行人工审核
- **地图可视化**：在中国地图上展示加权血清阳性率热力分布
- **数据分析**：支持逐年趋势、区域对比、年龄分层、免疫屏障评估
- **报告生成**：自动生成免疫学参考意见报告

## 技术栈

### 后端

| 组件 | 技术 |
|------|------|
| Web 框架 | FastAPI + Uvicorn |
| ORM / 数据库 | SQLAlchemy 2.0 (异步) + PostgreSQL 15 |
| 异步任务 | Celery + Redis |
| 对象存储 | MinIO |
| PDF 解析 | PyMuPDF + 百度 OCR |
| LLM 集成 | OpenAI SDK（兼容 DeepSeek / Qwen / OpenAI） |
| 数据校验 | Pydantic 2.0 |

### 前端

| 组件 | 技术 |
|------|------|
| 框架 | React 18 + TypeScript |
| 构建工具 | Vite |
| UI 组件库 | Ant Design 5 |
| 图表/地图 | ECharts + echarts-for-react |
| 状态管理 | Zustand |
| HTTP 客户端 | Axios |

### 基础设施

- Docker Compose 管理 PostgreSQL、Redis、MinIO
- 支持 deepseek、openai、qwen 等多厂商 LLM

## 快速开始

### 环境要求

- Python 3.10+
- Node.js 18+
- Docker & Docker Compose

### 1. 启动基础设施

```bash
docker compose up -d
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，填写 LLM_API_KEY 等配置
```

### 3. 启动后端

```bash
cd backend
pip install -r requirements.txt
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 4. 启动前端

```bash
cd frontend
npm install
npm run dev -- --host 0.0.0.0 --port 3000
```

### 5. （可选）启动 Celery Worker

```bash
cd backend
celery -A app.tasks.celery_app worker --loglevel=info --concurrency=2
```

### 一键启动

```bash
bash start.sh
```

### 访问地址

| 服务 | 地址 |
|------|------|
| 前端页面 | http://localhost:3000 |
| API 文档 (Swagger) | http://localhost:8000/docs |
| MinIO 控制台 | http://localhost:9001 |

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `LLM_API_KEY` | LLM API 密钥 | - |
| `LLM_BASE_URL` | LLM API 地址 | `https://api.deepseek.com` |
| `LLM_MODEL` | 默认模型名称 | `deepseek-chat` |
| `DATABASE_URL` | PostgreSQL 连接串 | `postgresql+asyncpg://antibody:antibody123@localhost:5432/antibody_map` |
| `REDIS_URL` | Redis 连接串 | `redis://localhost:6379/0` |
| `CELERY_BROKER_URL` | Celery 消息队列 | `redis://localhost:6379/1` |
| `CORS_ORIGINS` | 跨域白名单 | `localhost:3000,localhost:5173` |

支持按厂商配置独立模型参数：`DEEPSEEK_API_KEY`、`OPENAI_API_KEY`、`QWEN_API_KEY` 等，未配置时自动回退到通用配置。

## 项目结构

```
antibody_map01/
├── docker-compose.yml          # Docker 基础设施编排
├── start.sh / stop.sh          # 一键启动/停止脚本
├── .env.example                # 环境配置示例
├── backend/
│   ├── app/
│   │   ├── main.py             # FastAPI 应用入口
│   │   ├── config.py           # 配置管理
│   │   ├── api/v1/             # API 路由（literature/map/search/analysis/report 等）
│   │   ├── core/               # 核心引擎（LLM 提取、PDF 解析、OCR、MinIO）
│   │   ├── models/             # SQLAlchemy ORM 模型
│   │   ├── schemas/            # Pydantic 数据模型
│   │   ├── services/           # 业务逻辑层
│   │   └── tasks/              # Celery 异步任务
│   ├── tests/                  # 单元测试
│   └── requirements.txt
└── frontend/
    ├── src/
    │   ├── App.tsx             # 路由配置
    │   ├── layouts/            # 布局组件
    │   ├── pages/              # 业务页面（地图/文献/分析/评估/报告）
    │   ├── components/         # 公共组件
    │   ├── services/           # API 服务层
    │   ├── store/              # Zustand 全局状态
    │   └── utils/              # 工具函数
    ├── package.json
    └── vite.config.ts
```

## 数据流

```
上传 PDF → 文献入库 → 触发 AI 提取 → Celery 异步任务
    → PDF 解析(PyMuPDF + OCR兜底)
    → LLM 提取结构化数据（疾病/省份/阳性率/GMC等）
    → 创建 DataPoint → 人工审核 → 地图可视化 + 数据分析 + 报告生成
```

## 作者

- **Liu Xiong** - [liuxiong714@163.com](mailto:liuxiong714@163.com)

## License

MIT
