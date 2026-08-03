# 抗体地图 (Antibody Map)

血清抗体流行病学数据可视化与分析平台

![平台预览](docs/screenshots/dashboard.png)

## 项目简介

抗体地图是一个面向公共卫生和流行病学领域的**血清抗体水平数据管理、可视化与分析平台**。系统支持上传流行病学相关的 PDF 文献，通过 LLM 自动提取结构化的血清抗体数据点，经过人工审核后在交互式中国地图上可视化展示，并支持多维度数据分析和 AI 报告生成。

### 核心功能

| 模块 | 功能 |
|------|------|
| **文献管理** | 上传 PDF/CAJ/EPUB/DOCX/TXT/HTML 文献、元数据管理、关键词/疾病/省份筛选、在线预览、**表头点击排序**、**文献重复检测与合并** |
| **AI 数据提取** | LLM 自动从文献提取血清阳性率、GMC 等数据点，支持 DeepSeek/OpenAI/Qwen 多厂商 |
| **数据审核与编辑** | 人工审核（通过/驳回）、行内编辑（疾病、地区、年龄段、数值等字段） |
| **地图可视化** | 全国/省级/市级交互式抗体水平热力地图，点击省份钻取市级数据、**时间序列动画自动年份范围** |
| **数据分析** | 逐年趋势、区域对比、年龄分层、免疫屏障评估（含 WHO 阈值）、**数据覆盖度分析** |
| **数据覆盖度分析** | 自动统计数据点分布，识别需要审核的数据、**数据缺失提醒**、疾病名称标准化合并 |
| **报告生成** | LLM 生成抗体分析报告和疫苗接种策略研判报告，支持在线编辑和下载 |
| **文件夹监控** | 定期监测指定文件夹，自动导入新文件并触发信息提取 |
| **PDF 预览** | 基于 pdf.js 的在线 PDF 浏览器，支持分栏布局、面板折叠/展开 |

### 支持的疾病

麻疹、腮腺炎、风疹、百日咳、白喉、破伤风、乙肝、甲肝、脊髓灰质炎、流感、新冠、流行性脑脊髓膜炎、水痘、手足口病、轮状病毒（15 种疫苗可预防 / 重点传染病）

### 支持的文件格式

PDF、CAJ、EPUB、DOCX、TXT、HTML（支持中文文献和外文文献）

### 智能特性

- **疾病名称标准化**：自动合并同一疾病的不同名称（如乙肝/乙型病毒性肝炎、甲肝/甲型病毒性肝炎、乙脑/流行性乙型脑炎）
- **文献重复检测**：基于 DOI、标题、作者、PDF 哈希等多维度自动检测重复文献
- **文件夹自动监控**：配置本地文件夹后，系统自动监测新文件并导入提取

## 技术栈

| 层级 | 技术 |
|------|------|
| **前端** | React 18 + TypeScript, Vite 6, Ant Design 5, ECharts 5, pdfjs-dist, Zustand, React Router 6 |
| **后端** | Python 3.10+, FastAPI + Uvicorn, SQLAlchemy 2.0 (async), Celery + Redis, Pydantic 2.0 |
| **数据库** | PostgreSQL 15 |
| **存储** | MinIO 对象存储 / 本地文件系统双模式 |
| **AI/LLM** | OpenAI SDK 兼容协议，支持 DeepSeek / OpenAI / 通义千问 (Qwen) 多厂商 |
| **PDF 处理** | PyMuPDF (fitz) + Tesseract OCR (中文, 自动探测安装路径) |
| **运维** | Docker Compose (PostgreSQL + Redis + MinIO), start.sh 一键启动 |

## 项目结构

```
antibody_map01/
├── docker-compose.yml              # Docker 基础设施编排 (PostgreSQL, Redis, MinIO)
├── start.sh / stop.sh              # 一键启动 / 停止脚本
├── start.ps1 / stop.ps1            # Windows 一键启动 / 停止脚本
├── .env.example                    # 环境变量配置模板
├── docs/                           # 文档
│   └── tesseract_setup.md          # Tesseract OCR 部署配置指南
├── backend/
│   ├── app/
│   │   ├── main.py                 # FastAPI 应用入口 (CORS, lifespan)
│   │   ├── config.py               # 全局配置 (pydantic-settings)
│   │   ├── api/                    # API 路由层
│   │   │   ├── deps.py             # 依赖注入 (DB Session)
│   │   │   └── v1/
│   │   │       ├── router.py       # 路由注册中心
│   │   │       ├── dictionary.py   # 疾病/省份/检测方法字典
│   │   │       ├── literature.py   # 文献 CRUD + PDF 文件流 + 重复检测
│   │   │       ├── extraction.py   # AI 提取触发 + 数据点编辑/审核
│   │   │       ├── map_data.py     # 省级/市级/汇总地图数据
│   │   │       ├── search.py       # 高级文献 + 数据点检索
│   │   │       ├── analysis.py     # 趋势/区域/年龄/免疫屏障/数据覆盖度分析
│   │   │       ├── report.py       # 报告生成/CRUD/下载
│   │   │       └── folder_monitor.py # 文件夹监控 API
│   │   ├── core/                   # 核心引擎
│   │   │   ├── llm_extractor.py    # LLM 提取器 (多厂商 + 指数退避重试)
│   │   │   ├── pdf_parser.py       # PDF 文本解析 (PyMuPDF)
│   │   │   ├── ocr_service.py      # OCR 服务 (Tesseract 中文)
│   │   │   ├── document_parser.py  # 多格式文档解析 (PDF/CAJ/EPUB/DOCX/TXT/HTML)
│   │   │   ├── text_preprocessor.py # 文本预处理
│   │   │   ├── term_normalizer.py  # 术语 / 地名标准化
│   │   │   └── minio_client.py     # MinIO 客户端
│   │   ├── models/                 # SQLAlchemy ORM 模型
│   │   │   ├── base.py             # Base + Engine + Session
│   │   │   ├── literature.py       # Literature
│   │   │   ├── data_point.py       # DataPoint
│   │   │   ├── disease_dict.py     # 疾病字典
│   │   │   ├── report.py           # Report
│   │   │   └── monitored_folder.py # MonitoredFolder / MonitoredFile
│   │   ├── services/               # 业务逻辑层
│   │   │   ├── analysis_service.py # 数据分析服务（含疾病名称标准化）
│   │   │   ├── map_service.py      # 地图数据服务
│   │   │   ├── literature_service.py # 文献服务（含重复检测与合并）
│   │   │   ├── extraction_service.py # 数据提取服务
│   │   │   ├── report_service.py   # 报告服务
│   │   │   └── folder_monitor_service.py # 文件夹监控服务
│   │   ├── schemas/                # Pydantic 数据模型
│   │   └── tasks/                  # Celery 异步任务
│   ├── tests/                      # 单元测试
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
    │   │   ├── Analysis.tsx         # 多维数据分析 (含数据覆盖度)
    │   │   ├── Report.tsx           # 报告生成与管理
    │   │   └── FolderMonitor.tsx    # 文件夹监控管理
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
- Node.js 18+ (推荐 20+)
- Docker Desktop (Windows / macOS) 或 Docker & Docker Compose (Linux)
- Tesseract OCR (可选，用于扫描版 PDF 的文字识别，安装与配置见 [docs/tesseract_setup.md](docs/tesseract_setup.md))

### Windows 一键部署（推荐）

#### 1. 安装基础软件

按顺序安装以下软件（全部官网下载，下一步即可）：

| 软件 | 下载地址 | 说明 |
|------|----------|------|
| **Git** | https://git-scm.com/download/win | 克隆代码 |
| **Python 3.10+** | https://www.python.org/downloads/ | 安装时勾选 "Add Python to PATH" |
| **Node.js 20+** | https://nodejs.org/ | 选 LTS 版本 |
| **Docker Desktop** | https://www.docker.com/products/docker-desktop/ | 运行 PostgreSQL/Redis/MinIO |

> Docker Desktop 安装完成后需重启电脑，并确保 Docker 处于运行状态（右下角托盘图标）。

#### 2. 克隆项目

打开 PowerShell（或 Git Bash）：

```powershell
git clone https://github.com/liuxiong714/antibody_map.git
cd antibody_map
```

#### 3. 配置环境变量

复制配置模板并编辑：

```powershell
copy .env.example .env
notepad .env
```

**必填项**：`LLM_API_KEY`（你的 LLM API Key，DeepSeek 等）

#### 4. 一键启动

```powershell
.\start.ps1
```

脚本会自动完成：检查依赖 → 安装依赖 → 启动 Docker → 启动后端 → 启动前端 → 打开浏览器。

> 如果提示"无法加载文件，因为在此系统上禁止运行脚本"，请先执行：
> ```powershell
> Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
> ```

#### 5. 停止服务

按 `Ctrl+C` 即可停止全部服务，或单独执行：

```powershell
.\stop.ps1
```

### macOS / Linux 部署

#### 1. 克隆项目

```bash
git clone https://github.com/liuxiong714/antibody_map.git
cd antibody_map
```

#### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，至少填写 LLM_API_KEY
```

#### 3. 一键启动

```bash
bash start.sh
```

### 手动分步启动（高级用户）

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

### 访问地址

| 服务 | 地址 |
|------|------|
| 前端页面 | http://localhost:3000 |
| API 文档 (Swagger) | http://localhost:8080/docs |
| MinIO 控制台 | http://localhost:9001 |

---

## 数据迁移指南

把数据从旧电脑迁移到新电脑的步骤：

### 旧电脑：导出备份

```powershell
# Windows
.\scripts\backup_db.ps1

# macOS/Linux
docker exec -e PGPASSWORD=antibody123 antibody-postgres pg_dump -U antibody -d antibody_map --no-owner --no-privileges > backups/latest_backup.sql
```

备份文件存放在 `backups/` 目录，文件名带时间戳，同时生成 `latest_backup.sql`。

> **重要**：PDF 文件如果存在本地 `backend/data/pdfs/` 目录，需手动复制该文件夹到新电脑。如果使用 MinIO 存储，需额外导出 MinIO bucket。

### 新电脑：恢复备份

1. 先按上面的步骤完成项目部署并启动服务（确保 Docker 容器运行）
2. 把备份文件复制到新电脑的项目目录下
3. 执行恢复：

```powershell
# Windows
.\scripts\restore_db.ps1 -BackupFile backups\latest_backup.sql

# 提示确认时输入 YES
```

> ⚠️ 恢复会**覆盖**当前数据库所有数据，请谨慎操作。

---

## 项目脚本一览

| 脚本 | 平台 | 作用 |
|------|------|------|
| `start.ps1` / `stop.ps1` | Windows | 一键启动/停止所有服务 |
| `start.sh` / `stop.sh` | macOS/Linux | 一键启动/停止所有服务 |
| `scripts/backup_db.ps1` | Windows | 导出数据库备份 |
| `scripts/restore_db.ps1` | Windows | 从备份恢复数据库 |

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
| POST | `/literatures/upload` | 上传文献（支持 PDF/CAJ/EPUB/DOCX/TXT/HTML） |
| GET | `/literatures` | 文献列表 (分页 + 关键词/疾病筛选) |
| GET | `/literatures/{id}` | 文献详情 |
| PUT | `/literatures/{id}` | 更新文献元信息 |
| DELETE | `/literatures/{id}` | 删除文献 |
| GET | `/literatures/{id}/file` | 获取文献文件流 (在线预览) |
| POST | `/literatures/check-duplicate` | 检查单个文献是否重复 |
| POST | `/literatures/scan-duplicates` | 扫描全库重复文献 |
| POST | `/literatures/{id}/merge` | 合并重复文献 |

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
| GET | `/analysis/trend` | 逐年趋势分析 |
| GET | `/analysis/region-compare` | 区域对比分析 |
| GET | `/analysis/age-stratify` | 年龄分层分析 |
| GET | `/analysis/immune-barrier` | 免疫屏障评估 (含 WHO 阈值) |
| GET | `/analysis/summary` | 汇总统计 |
| GET | `/analysis/approved-data-points` | 已审核数据点列表 |
| GET | `/analysis/data-gaps` | 数据覆盖度分析（含数据缺失提醒） |

### 高级检索

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/search/literatures` | 文献高级检索 |
| GET | `/search/data-points` | 数据点高级检索 |

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

### 文件夹监控

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/folders` | 列出所有监控文件夹 |
| POST | `/folders` | 添加监控文件夹 |
| PUT | `/folders/{folder_id}` | 更新监控文件夹配置 |
| DELETE | `/folders/{folder_id}` | 删除监控文件夹 |
| POST | `/folders/{folder_id}/scan` | 手动触发扫描文件夹 |
| GET | `/folders/{folder_id}/files` | 查看文件处理记录 |

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
| `TESSERACT_CMD` | Tesseract 可执行文件路径 | 自动探测 (PATH + Windows 常见安装位置) |
| `TESSERACT_DATA_DIR` | Tesseract 语言包 (tessdata) 目录 | 自动探测 (可执行文件同级 tessdata) |
| `PDF_STORAGE` | PDF 存储模式 | `local` (或 `minio`) |

## 数据流

```
文献上传 (PDF/CAJ/EPUB/DOCX/TXT/HTML)
    │
    ▼
多格式文档解析 (PyMuPDF + caj2pdf + ebooklib + python-docx + bs4)
    │
    ▼
文本预处理 (清洗 OCR 乱码、提取表格数据)
    │
    ▼
LLM 结构化提取 (疾病 / 省份 / 阳性率 / GMC / 年龄段 / 样本量 / 采集年份)
    │
    ▼
疾病名称标准化 (别名 → 标准名称: 乙型病毒性肝炎→乙肝 等)
    │
    ▼
术语标准化 (疾病名 / 省份名 → 字典映射)
    │
    ▼
文献重复检测 (DOI / 标题 / 作者 / PDF 哈希 多维度比对)
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
数据覆盖度分析 (数据缺失提醒 + 待审核数据统计)
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
| disease | TEXT | 疾病名称（支持多种别名，后端会自动标准化） |
| province / city | TEXT | 省 / 市 |
| data_type | TEXT | seroprevalence / gmc |
| value / unit | FLOAT / TEXT | 数值 / 单位 (%) |
| sample_size | INT | 样本量 |
| age_min / age_max | FLOAT | 年龄段 (岁) |
| collection_year | INT | 数据采集年份 |
| confidence | ENUM | high / medium / low |
| review_status | ENUM | pending / approved / rejected |

### MonitoredFolder (监控文件夹)

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 主键 |
| name | TEXT | 文件夹名称 |
| folder_path | TEXT | 文件夹路径 |
| scan_interval | INT | 扫描间隔（分钟） |
| status | ENUM | idle / scanning / error |
| last_scan_at | DATETIME | 上次扫描时间 |
| error_message | TEXT | 错误信息 |

### MonitoredFile (监控文件记录)

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 主键 |
| folder_id | UUID | 外键 → MonitoredFolder |
| file_path | TEXT | 文件路径 |
| file_hash | TEXT | 文件哈希（用于变更检测） |
| status | ENUM | pending / imported / error |
| literature_id | UUID | 导入的文献 ID |
| error_message | TEXT | 错误信息 |

## License

MIT

## 作者

**Liu Xiong** - [liuxiong714@163.com](mailto:liuxiong714@163.com)

## 更新日志

### v1.4.0 (2026-08-04)

#### 新功能

- **扫描版文献 OCR 识别**：文字层缺失或损坏的扫描 PDF 自动触发 Tesseract OCR（中文 chi_sim + 英文 eng 双语言）识别；支持自动探测 Tesseract 安装位置与语言包目录，并新增 `TESSERACT_CMD` / `TESSERACT_DATA_DIR` 配置项，安装与配置详见 [docs/tesseract_setup.md](docs/tesseract_setup.md)。

- **文献列表状态保持**：点击文献标题进入详情页再返回列表时，自动恢复上次的排序方式、筛选条件和页码，避免每次返回都重置到第一页。

- **疾病名称标准化扩展**：`DISEASE_MAP` 补全梅毒、艾滋病及其英文别名（HIV、AIDS、Treponema pallidum、Syphilis 等），查询与入库统一复用标准化逻辑。

#### 优化

- 修复扫描版 PDF 中"文字层损坏但非空"导致的 OCR 兜底不触发问题（单页文本 < 100 字符即走 OCR）
- 提取结果为空时状态标记为 `failed`（而非 `done`），避免无数据文献误判为提取成功
- 修正文献上传测试断言（TXT 已受支持），后端测试增至 44 项全部通过
- 文献详情页与列表页关键节点新增调试日志，便于排查状态恢复问题
- Git 换行符统一为 LF（.gitattributes），前端构建产物与临时文件移出版本库（.gitignore）

### v1.3.0 (2026-08-03)

#### 新功能

- **文献重复检测与合并**：系统可基于 DOI、标题、作者、PDF 哈希等多维度自动检测重复文献，支持字段级冲突合并。

- **数据覆盖度分析**：新增数据覆盖度分析模块，自动统计各省份各年份的数据点分布，识别需要审核的数据点，提供数据缺失提醒。

- **疾病名称标准化**：实现疾病名称自动合并功能，将同一疾病的不同名称统一（如乙肝/乙型病毒性肝炎、甲肝/甲型病毒性肝炎、乙脑/流行性乙型脑炎等），提升数据展示准确性。

- **文件夹监控**：支持配置本地文件夹进行定期监测，自动导入新文件并触发信息提取，实现文献数据的持续积累。

- **多格式文献支持**：文献上传和提取支持 PDF、CAJ、EPUB、DOCX、TXT、HTML 等多种格式。

#### 优化

- 优化文献详情页面，从数据点同步年份和省份信息
- 支持点击省份查看详细市级数据
- 免疫屏障评估默认血清阳性率数据类型
- 优化时间序列动画的年份范围选择

### v1.2.0 (2026-07-31)

#### 新功能

- **文献管理表格排序**：支持点击表头按标题、作者、期刊、年份、省份、提取状态、创建时间等任意列进行排序，支持升序/降序切换，排序状态与下拉筛选器同步。

- **时间序列动画自动年份范围**：切换到时间序列动画模式时，系统自动根据可用数据设置合适的年份范围（从最小可用年份到当前年份），无需手动调整，提升用户体验。

#### 优化

- 优化地图总览页面时间序列控件的交互体验
- 修复Ant Design表格sortOrder类型兼容性问题
