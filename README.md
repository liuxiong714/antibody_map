# 抗体地图 (Antibody Map)

血清抗体流行病学数据可视化与分析平台

## 项目简介

抗体地图是一个面向公共卫生和流行病学领域的**血清抗体水平数据管理、可视化与分析平台**。系统支持上传流行病学相关的 PDF 文献，通过 LLM 自动提取结构化的血清抗体数据点，经过人工审核后在交互式中国地图上可视化展示，并支持多维度数据分析和 AI 报告生成。

### 核心功能

| 模块 | 功能 |
|------|------|
| **文献管理** | 上传 PDF 文献、元数据管理、关键词/疾病/省份筛选、在线预览 |
| **AI 数据提取** | LLM 自动从文献提取血清阳性率、GMC 等数据点，支持 DeepSeek/OpenAI/Qwen 多厂商 |
| **数据审核与编辑** | 人工审核（通过/驳回）、行内编辑（疾病、地区、年龄段、数值等字段） |
| **地图可视化** | 全国/省级/市级交互式抗体水平热力地图，点击省份钻取市级数据 |
| **数据分析** | 逐年趋势、区域对比、年龄分层、免疫屏障评估（含 WHO 阈值） |
| **报告生成** | LLM 生成抗体分析报告和疫苗接种策略研判报告，支持在线编辑和下载 |
| **PDF 预览** | 基于 pdf.js 的在线 PDF 浏览器，支持分栏布局、面板折叠/展开 |

### 支持的疾病

麻疹、腮腺炎、风疹、百日咳、白喉、破伤风、乙肝、甲肝、脊髓灰质炎、流感、新冠、流行性脑脊髓膜炎、水痘、手足口病、轮状病毒（15 种疫苗可预防 / 重点传染病）

## 技术栈

| 层级 | 技术 |
|------|------|
| **前端** | React 18 + TypeScript, Vite 6, Ant Design 5, ECharts 5, pdfjs-dist, Zustand, React Router 6 |
| **后端** | Python 3.10+, FastAPI + Uvicorn, SQLAlchemy 2.0 (async), Celery + Redis, Pydantic 2.0 |
| **数据库** | PostgreSQL 15 |
| **存储** | MinIO 对象存储 / 本地文件系统双模式 |
| **AI/LLM** | OpenAI SDK 兼容协议，支持 DeepSeek / OpenAI / 通义千问 (Qwen) 多厂商 |
| **PDF 处理** | PyMuPDF (fitz) + Tesseract OCR (中文支持) |
| **运维** | Docker Compose (PostgreSQL + Redis + MinIO), start.sh 一键启动 |

## 项目结构

```
antibody_map01/
├── docker-compose.yml              # Docker 基础设施编排 (PostgreSQL, Redis, MinIO)
├── start.sh / stop.sh              # 一键启动 / 停止脚本
├── .env.example                    # 环境变量配置模板
├── backend/
│   ├── app/
│   │   ├── main.py                 # FastAPI 应用入口 (CORS, lifespan)
│   │   ├── config.py               # 全局配置 (pydantic-settings)
│   │   ├── api/                    # API 路由层
│   │   │   ├── deps.py             # 依赖注入 (DB Session)
│   │   │   └── v1/
│   │   │       ├── router.py       # 路由注册中心
│   │   │       ├── dictionary.py   # 疾病/省份/检测方法字典
│   │   │       ├── literature.py   # 文献 CRUD + PDF 文件流
│   │   │       ├── extraction.py   # AI 提取触发 + 数据点编辑/审核
│   │   │       ├── map_data.py     # 省级/市级/汇总地图数据
│   │   │       ├── search.py       # 高级文献 + 数据点检索
│   │   │       ├── analysis.py     # 趋势/区域/年龄/免疫屏障分析
│   │   │       └── report.py       # 报告生成/CRUD/下载
│   │   ├── core/                   # 核心引擎
│   │   │   ├── llm_extractor.py    # LLM 提取器 (多厂商 + 指数退避重试)
│   │   │   ├── pdf_parser.py       # PDF 文本解析 (PyMuPDF)
│   │   │   ├── ocr_service.py      # OCR 服务 (Tesseract 中文)
│   │   │   ├── text_preprocessor.py # 文本预处理
│   │   │   ├── term_normalizer.py  # 术语 / 地名标准化
│   │   │   └── minio_client.py     # MinIO 客户端
│   │   ├── models/                 # SQLAlchemy ORM 模型
│   │   │   ├── base.py             # Base + Engine + Session
│   │   │   ├── literature.py       # Literature
│   │   │   ├── data_point.py       # DataPoint
│   │   │   ├── disease_dict.py     # 疾病字典
│   │   │   └── report.py           # Report
│   │   ├── services/               # 业务逻辑层
│   │   ├── schemas/                # Pydantic 数据模型
│   │   └── tasks/                  # Celery 异步任务
│   ├── tests/                      # 单元测试 (44 个用例)
│   └── requirements.txt
└── frontend/
    ├── src/
    │   ├── App.tsx                  # 前端路由配置
    │   ├── layouts/
    │   │   └── MainLayout.tsx       # 全局布局 (侧边导航 + 全局筛选)
    │   ├── pages/
    │   │   ├── MapOverview.tsx      # 地图总览 (全国热力图 + 省份详情)
    │   │   ├── Literature.tsx       # 文献管理列表
    │   │   ├── LiteratureDetail.tsx # 文献详情 (PDF 预览 + 数据提取 + 审核编辑)
    │   │   ├── Assessment.tsx       # 免疫屏障评估
    │   │   ├── Analysis.tsx         # 多维数据分析
    │   │   └── Report.tsx           # 报告生成与管理
    │   ├── components/              # 公共组件 (PdfViewer, PdfPreviewModal, 选择器等)
    │   ├── services/                # API 服务层 (Axios)
    │   ├── store/                   # Zustand 全局状态管理
    │   ├── types/                   # TypeScript 类型定义
    │   └── utils/                   # 工具函数 / 常量
    ├── package.json
    └── vite.config.ts
```

## 快速开始

### 环境要求

- Python 3.10+
- Node.js 18+
- Docker & Docker Compose
- Tesseract OCR (可选，用于扫描版 PDF 的文字识别)

### 1. 克隆项目

```bash
git clone https://github.com/liuxiong714/antibody_map.git
cd antibody_map
```

### 2. 启动基础设施

```bash
docker compose up -d
```

### 3. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，至少填写 LLM_API_KEY (DeepSeek API Key)
```

### 4. 启动服务

**一键启动：**
```bash
bash start.sh
```

**或手动分步启动：**

```bash
# 后端 (端口 8080)
cd backend
pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8080 --reload

# 前端 (端口 3000)
cd frontend
npm install
npm run dev

# Celery Worker (可选，用于异步 AI 提取)
cd backend
celery -A app.tasks.celery_app worker --loglevel=info --concurrency=2
```

### 访问地址

| 服务 | 地址 |
|------|------|
| 前端页面 | http://localhost:3000 |
| API 文档 (Swagger) | http://localhost:8080/docs |
| MinIO 控制台 | http://localhost:9001 |

## API 接口一览

所有接口挂载在 `/api/v1` 前缀下。

### 字典接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/dictionary/diseases` | 获取 15 种疾病列表 |
| GET | `/dictionary/provinces` | 获取 34 个省级行政区 |
| GET | `/dictionary/methods` | 获取 9 种血清学检测方法 |

### 文献管理

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/literatures/upload` | 上传 PDF 文献 |
| GET | `/literatures` | 文献列表 (分页 + 关键词/疾病筛选) |
| GET | `/literatures/{id}` | 文献详情 |
| PUT | `/literatures/{id}` | 更新文献元信息 |
| DELETE | `/literatures/{id}` | 删除文献 |
| GET | `/literatures/{id}/file` | 获取 PDF 文件流 (在线预览) |

### 数据提取与审核

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/literatures/{id}/extraction` | 触发 AI 数据提取 (可指定模型/API Key/Base URL) |
| GET | `/literatures/{id}/extraction/status` | 查询提取任务状态 |
| GET | `/literatures/{id}/extraction` | 获取提取的数据点列表 |
| PUT | `/literatures/{id}/extraction` | 编辑数据点字段 + 审核状态更新 |
| POST | `/literatures/{id}/extraction/confirm` | 批量审核通过 |
| POST | `/literatures/{id}/extraction/dispute` | 批量驳回 |

### 地图数据

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/map/province-data` | 省级抗体水平地图数据 |
| GET | `/map/city-data` | 市级抗体水平数据 |
| GET | `/map/summary` | 全国汇总统计 |

### 数据分析

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/analysis/trend` | 逐年趋势分析 |
| POST | `/analysis/region-compare` | 区域对比分析 |
| POST | `/analysis/age-stratify` | 年龄分层分析 |
| POST | `/analysis/immune-barrier` | 免疫屏障评估 (含 WHO 阈值) |
| GET | `/analysis/summary` | 汇总统计 |
| GET | `/analysis/approved-data-points` | 已审核数据点列表 |

### 高级检索

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/search/literatures` | 文献高级检索 |
| POST | `/search/data-points` | 数据点高级检索 |

### 报告

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/reports/generate` | 生成抗体分析报告 |
| POST | `/reports/generate-vaccination-strategy` | 生成疫苗接种策略报告 |
| GET | `/reports` | 报告列表 |
| GET | `/reports/{id}` | 报告详情 |
| PUT | `/reports/{id}` | 编辑报告 |
| DELETE | `/reports/{id}` | 删除报告 |
| GET | `/reports/{id}/download` | 下载报告 (.md) |

## 环境变量

### LLM 配置

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `LLM_API_KEY` | 通用 LLM API 密钥 | - |
| `LLM_BASE_URL` | 通用 LLM API 地址 | `https://api.deepseek.com` |
| `LLM_MODEL` | 默认模型名称 | `deepseek-chat` |
| `DEEPSEEK_API_KEY` | DeepSeek 独立 API 密钥 | 回退到 `LLM_API_KEY` |
| `OPENAI_API_KEY` | OpenAI 独立 API 密钥 | 回退到 `LLM_API_KEY` |
| `QWEN_API_KEY` | 通义千问独立 API 密钥 | 回退到 `LLM_API_KEY` |

### 数据库与存储

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `DATABASE_URL` | PostgreSQL 连接串 | `postgresql+asyncpg://antibody:antibody123@localhost:5432/antibody_map` |
| `REDIS_URL` | Redis 连接串 | `redis://localhost:6379/0` |
| `CELERY_BROKER_URL` | Celery 消息队列 | `redis://localhost:6379/1` |
| `MINIO_ENDPOINT` | MinIO 地址 | `localhost:9000` |

### 其他

| 变量 | 说明 | 默认值 |
|------|------|------|
| `CORS_ORIGINS` | 跨域白名单 (逗号分隔) | `localhost:3000,localhost:5173` |
| `TESSERACT_CMD` | Tesseract 可执行文件路径 | `tesseract` |
| `PDF_STORAGE` | PDF 存储模式 | `local` (或 `minio`) |

## 数据流

```
上传 PDF 文献
    │
    ▼
PDF 文本解析 (PyMuPDF, 乱码时 OCR 兜底)
    │
    ▼
LLM 结构化提取 (疾病 / 省份 / 阳性率 / GMC / 年龄段 / 样本量 / 采集年份)
    │
    ▼
术语标准化 (疾病名 / 省份名 → 字典映射)
    │
    ▼
生成 DataPoint 记录 (review_status = pending)
    │
    ▼
人工审核 + 行内编辑 → approved / rejected
    │
    ▼
地图可视化 (全国 / 省份 / 城市) + 多维度分析
    │
    ▼
LLM 生成免疫学报告 + 疫苗接种策略报告
```

## 数据库模型

### Literature (文献)

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 主键 |
| title / title_en | TEXT | 中/英文标题 |
| authors | TEXT | 作者列表 |
| journal | TEXT | 期刊名称 |
| pub_year | INT | 出版年份 |
| doi / pmid | TEXT | DOI / PubMed ID |
| province | TEXT | 研究所在省份 |
| extraction_status | ENUM | pending / processing / done / failed |
| extracted_count | INT | 已提取数据点数量 |
| approved_count | INT | 已审核通过数量 |

### DataPoint (数据点)

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 主键 |
| literature_id | UUID | 外键 → Literature |
| disease | TEXT | 疾病名称 |
| province / city | TEXT | 省 / 市 |
| data_type | TEXT | seroprevalence / gmc |
| value / unit | FLOAT / TEXT | 数值 / 单位 (%) |
| sample_size | INT | 样本量 |
| age_min / age_max | FLOAT | 年龄段 (岁) |
| collection_year | INT | 数据采集年份 |
| confidence | ENUM | high / medium / low |
| review_status | ENUM | pending / approved / rejected |

## License

MIT

## 作者

**Liu Xiong** - [liuxiong714@163.com](mailto:liuxiong714@163.com)
