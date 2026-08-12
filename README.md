# 抗体地图 (Antibody Map)

血清抗体流行病学数据可视化与分析平台

![平台预览](docs/screenshots/dashboard.png)

## 项目简介

抗体地图是一个面向公共卫生和流行病学领域的**血清抗体水平数据管理、可视化与分析平台**。系统支持上传流行病学相关的 PDF 文献，通过 LLM 自动提取结构化的血清抗体数据点，经过人工审核后在交互式中国地图上可视化展示，并支持多维度数据分析和 AI 报告生成。

### 核心功能

| 模块 | 功能 |
|------|------|
| **文献管理** | 上传 PDF/CAJ/EPUB/DOCX/PPTX/XLSX/TXT/HTML 文献、**URL 网页导入**、元数据管理、关键词/疾病/省份筛选、在线预览、**表头点击排序**、**文献重复检测与合并**、**多格式导入导出**（CSV/Excel/JSON，JSON 含数据点可跨电脑迁移导入、支持仅导出选中文献）、**元数据批量同步**（从数据点自动聚合年份/省份）、**文档格式标识列**（彩色 Tag 显示 PDF/CAJ/DOCX/HTML 等格式，点击即可预览） |
| **AI 数据提取** | LLM 自动从文献提取血清阳性率、GMC 等数据点，支持 DeepSeek/OpenAI/Qwen 多厂商，支持**上传后手动选择是否自动提取**、**上传/提取时可重新选定默认模型**、**批量AI提取**（多选文献后统一设置模型重新提取，自动跳过 processing 中的文献）、**手动停止提取**（单篇卡住的 processing 强制重置为 failed）、**一键重置所有卡住的提取状态**（适用于服务器重启后任务丢失的场景）；提取完成后可选显示**Token 用量、费用估算及使用的大模型** |
| **精确字符溯源** | 每个数据点锚定到原文的精确字符区间（`source_char_start/end`），采用精确/模糊/关键短语三级匹配，未匹配自动降级置信度并红色高亮待审 |
| **长文档分块并行提取** | 超过 2 万字符的文献按段落边界分块、并行调用 LLM 提取，结果自动合并去重 |
| **强 Schema 约束** | LLM 输出经 JSON Schema 校验（省份枚举、阳性率 0-100% 范围、GMC 正值等），字段违规自动降级置信度 |
| **数据审核与编辑** | 人工审核（通过/驳回）、行内编辑（疾病、地区、年龄段、数值、**原文依据、溯源字符区间**等字段）、**手动新增数据点**（提取失败时补录） |
| **地图可视化** | 全国/省级/市级交互式抗体水平热力地图，点击省份钻取市级数据、**时间序列动画自动年份范围**、底部统计区分**已审核通过**（绿色）与**未审核**（橙色）两组数据点/覆盖省份/样本量 |
| **数据分析** | 逐年趋势、区域对比、年龄分层、**免疫屏障评估**（复用 FOI 模块 R0/HIT 计算，新增年龄分层分析与省份对比矩阵，HIT 阈值优先级：FOI 估算>WHO 建议>文献 R0）、**数据覆盖度分析**、**多表单 Excel 数据导出**、**FOI 感染力分析**（催化模型 + R0 估算 + 群体免疫阈值 HIT，支持不选择疾病进行全量分析）、**疫苗效果 VE 分析**（已接种/未接种亚组拆分 + 保护率估算）、**接种率双轨分析**（NIP 参考表 + 血清阳性率反推隐含接种率） |
| **报告生成** | LLM 生成抗体分析报告和疫苗接种策略研判报告，支持在线编辑和下载；**报告生成时可选模型**（本地 Ollama 模型 / 远程 API 模型，支持自定义 API Key 和 Base URL） |
| **文件夹监控** | 定期监测指定文件夹，自动导入新文件并触发信息提取 |
| **Edge 浏览器插件** | 参考 Mendeley 设计，在浏览器中一键将文献添加到数据库并触发 AI 提取；支持 15+ 学术站点元数据自动识别、PDF 智能抓取上传、URL 网页导入、右键菜单、桌面通知 |
| **多格式预览** | PDF 使用 pdf.js 渲染；TXT/HTML/DOCX/PPTX/XLSX/EPUB 显示解析后文本；CAJ 提示下载，支持分栏布局、面板折叠/展开 |

### 支持的疾病

麻疹、腮腺炎、风疹、百日咳、白喉、破伤风、乙肝（乙型病毒性肝炎）、甲肝、丙肝、丁肝（丁型肝炎/丁型病毒性肝炎）、戊肝、脊髓灰质炎、流感、新冠、流行性脑脊髓膜炎、水痘、手足口病、轮状病毒（疫苗可预防/重点传染病）；肾综合征出血热、登革热、寨卡病毒、黄热病毒、乙脑、马尔尼菲篮状菌、李斯特菌、弓形虫、疟疾、血吸虫、华支睾吸虫、蛔虫、钩虫、丝虫、包虫、囊虫（法定传染病和常见血清流行病学研究病种）。**疾病名称自动标准化**：麻腮风/MMR→麻疹、丁型病毒性肝炎→丁型肝炎、丙肝（丙型病毒性肝炎）→丙肝、戊型病毒性肝炎→戊肝、乙型脑炎→乙脑等，自动合并同一疾病的不同名称。

### 支持的文件格式

PDF、CAJ、EPUB、DOCX、PPTX、XLSX、TXT、HTML（支持中文文献和外文文献，解析采用**策略模式**：各格式独立解析器 + 统一注册表分发）

### 智能特性

- **疾病名称标准化**：自动合并同一疾病的不同名称（如乙肝/乙型病毒性肝炎、甲肝/甲型病毒性肝炎、乙脑/流行性乙型脑炎、丙肝/丙型病毒性肝炎、戊肝/戊型病毒性肝炎、丁肝/丁型病毒性肝炎、麻腮风/MMR→麻疹、流行性出血热/汉坦病毒→肾综合征出血热等）；含 40+ 法定传染病及常见血清流行病学病种映射（登革热、寨卡、疟疾、血吸虫、包虫、囊虫等）；提供 `backend/scripts/normalize_diseases.py` 迁移脚本，一键规范化数据库中已有的历史非标准疾病名称
- **文献重复检测**：基于 DOI、标题、作者、PDF 哈希等多维度自动检测重复文献
- **文件夹自动监控**：配置本地文件夹后，系统自动监测新文件并导入提取
- **扫描件 OCR 兜底**：文字层缺失或损坏的扫描 PDF 自动触发 Tesseract OCR（中文+英文），失败可回退云端 OCR
- **交互式溯源查看**：点击数据点可查看原文上下文并高亮定位字符区间，方便人工核验 LLM 提取结果
- **元数据自动聚合**：AI 提取完成后自动从数据点聚合文献的年份（取众数）和省份信息，同步到文献列表；支持批量同步历史文献的缺失元数据
- **多格式导入导出与跨电脑迁移**：文献列表支持 CSV / Excel / JSON 三种格式导出；JSON 格式可完整包含数据点（含审核状态、estimate_type、溯源字段），在另一台电脑通过「导入文献」按钮一键导入，自动保留审核状态并在地图、分析模块中正常展示；支持仅导出选中的文献数据

## 技术栈

| 层级 | 技术 |
|------|------|
| **前端** | React 18 + TypeScript, Vite 6, Ant Design 5, ECharts 5, pdfjs-dist, Zustand, React Router 6 |
| **后端** | Python 3.10+, FastAPI + Uvicorn, SQLAlchemy 2.0 (async), Celery + Redis, Pydantic 2.0 |
| **数据库** | PostgreSQL 15 |
| **存储** | MinIO 对象存储 / 本地文件系统双模式 |
| **AI/LLM** | OpenAI SDK 兼容协议，支持 DeepSeek / OpenAI / 通义千问 (Qwen) / **本地 Ollama** 多厂商；JSON Schema 强约束 + 精确字符级溯源；**报告生成支持模型选择**（本地 + 远程 API，可配置 API Key/Base URL） |
| **文档解析** | 策略模式解析器注册表：PyMuPDF (fitz) + pdfplumber、python-docx、python-pptx、openpyxl、ebooklib、BeautifulSoup、caj2pdf |
| **OCR** | Tesseract OCR (中文/英文，自动探测安装路径) + 百度 OCR 云端回退 |
| **运维** | Docker Compose (PostgreSQL + Redis + MinIO), start.sh / start.ps1 一键启动 |

## 项目结构

```
antibody_map01/
├── docker-compose.yml              # Docker 基础设施编排 (PostgreSQL, Redis, MinIO)
├── start.sh / stop.sh              # 一键启动 / 停止脚本
├── start.ps1 / stop.ps1            # Windows 一键启动 / 停止脚本
├── .env.example                    # 环境变量配置模板
├── docs/                           # 文档
│   └── tesseract_setup.md          # Tesseract OCR 部署配置指南
├── browser-extension/              # Edge 浏览器插件（参考 Mendeley）
│   ├── manifest.json
│   ├── background.js
│   ├── content-script.js
│   ├── popup.html / popup.js
│   ├── options.html / options.js
│   ├── styles.css
│   ├── icons/
│   └── README.md
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
│   │   │   ├── llm_extractor.py    # LLM 提取器 (多厂商 + 指数退避重试 + 长文档分块并行)
│   │   │   ├── extraction_grounding.py # 精确字符级溯源 + 强 Schema 校验
│   │   │   ├── document_parser.py  # 多格式文档解析分发 (策略模式注册表)
│   │   │   ├── processors/         # 各格式解析器 (docx/pptx/xlsx/epub/html/txt + @register_parser)
│   │   │   ├── pdf_parser.py       # PDF 文本解析 (PyMuPDF, 乱码/空文本自动走 OCR)
│   │   │   ├── ocr_service.py      # OCR 服务 (Tesseract 本地 + 百度 OCR 云端回退)
│   │   │   ├── url_fetcher.py      # URL/HTML 网页抓取与标题提取
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
    │   ├── components/              # 公共组件 (PdfViewer, FilePreview, PdfPreviewModal, 选择器等)
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
| POST | `/literatures/upload` | 上传文献（支持 PDF/CAJ/EPUB/DOCX/PPTX/XLSX/TXT/HTML） |
| POST | `/literatures/from-url` | 从 URL 抓取 HTML 网页创建文献 |
| GET | `/literatures` | 文献列表 (分页 + 关键词/疾病筛选) |
| GET | `/literatures/export` | 导出文献列表，支持 `format=csv/xlsx/json`、`include_data_points=true`（含数据点）、`literature_ids=id1,id2`（仅导出指定文献） |
| POST | `/literatures/import` | 从 JSON 导出文件批量导入文献和数据点（支持跳过重复/更新已有） |
| GET | `/literatures/{id}` | 文献详情 |
| PUT | `/literatures/{id}` | 更新文献元信息 |
| DELETE | `/literatures/{id}` | 删除文献 |
| GET | `/literatures/{id}/file` | 获取文献文件流 (在线预览) |
| GET | `/literatures/{id}/download` | 下载原文件 (attachment) |
| GET | `/literatures/{id}/source-text` | 获取溯源文本（按字符区间截取，供溯源高亮） |
| POST | `/literatures/check-duplicate` | 检查单个文献是否重复 |
| POST | `/literatures/scan-duplicates` | 扫描全库重复文献 |
| POST | `/literatures/merge/preview` | 合并前预览冲突 |
| POST | `/literatures/{id}/merge` | 合并重复文献 |

### 数据提取与审核

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/literatures/{id}/extraction` | 触发 AI 数据提取 (可指定模型/API Key/Base URL) |
| POST | `/literatures/extraction/batch` | 批量触发 AI 数据提取（多选文献、统一模型、自动跳过 processing 中的文献） |
| POST | `/literatures/{id}/extraction/stop` | **手动停止单篇文献提取**（强制将 `processing` 重置为 `failed`，适用于任务卡住场景） |
| POST | `/literatures/extraction/reset-stuck` | **一键批量重置所有卡在 `processing` 状态的文献为 `failed`**（适用于服务器重启后任务丢失场景） |
| GET | `/literatures/{id}/extraction/status` | 查询提取任务状态 |
| GET | `/literatures/{id}/extraction` | 获取提取的数据点列表 |
| GET | `/literatures/{id}/extraction/export` | 导出数据点 CSV |
| POST | `/literatures/{id}/extraction/data-points` | 手动新增数据点 |
| PUT | `/literatures/{id}/extraction` | 编辑数据点字段 + 审核状态更新 |
| POST | `/literatures/{id}/extraction/confirm` | 批量审核通过 |
| POST | `/literatures/{id}/extraction/dispute` | 批量驳回 |
| POST | `/literatures/{id}/sync-metadata` | 同步单篇文献元数据（从数据点聚合年份/省份） |
| POST | `/literatures/sync-metadata-batch` | 批量同步所有缺元数据的已完成文献 |

### 地图数据

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/map/province-data` | 省级抗体水平地图数据 |
| GET | `/map/city-data` | 市级抗体水平数据 |
| GET | `/map/summary` | 全国汇总统计（含已审核通过与未审核两组：`point_count/study_count/province_count/total_sample` 以及 `unapproved_point_count/unapproved_province_count/unapproved_total_sample`） |
| GET | `/map/yearly-data` | 逐年地图数据（时间序列动画） |
| GET | `/map/available-years` | 可用年份列表 |
| GET | `/map/export-data-points` | 导出已审核数据点 CSV（跟随地图筛选条件） |

### 数据分析

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/analysis/trend` | 逐年趋势分析 |
| GET | `/analysis/region-compare` | 区域对比分析 |
| GET | `/analysis/age-stratify` | 年龄分层分析 |
| GET | `/analysis/immune-barrier` | **免疫屏障评估**（复用 FOI 模块 R0/HIT 计算，新增年龄分层分析与省份对比矩阵，HIT 阈值优先级：FOI 估算 > WHO 建议 > 文献 R0） |
| GET | `/analysis/summary` | 汇总统计 |
| GET | `/analysis/approved-data-points` | 已审核数据点列表 |
| GET | `/analysis/data-gaps` | 数据覆盖度分析（含数据缺失提醒，按完善度排序） |
| GET | `/analysis/foi-herd-immunity` | **P0: FOI 感染力 + 群体免疫阈值分析**（催化模型 λ = -ln(1-SP)/age、R0、HIT） |
| GET | `/analysis/vaccine-effectiveness-coverage` | **P1: 疫苗效果 VE + 接种率分析**（亚组 VE、NIP 参考表、隐含接种率、覆盖率矩阵） |
| GET | `/analysis/export` | 导出分析数据 Excel（多工作表） |

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
文献上传 (PDF/CAJ/EPUB/DOCX/PPTX/XLSX/TXT/HTML) 或 URL 网页导入
    │
    ▼
多格式文档解析 (策略模式注册表：PyMuPDF + pdfplumber / python-docx / python-pptx / openpyxl / ebooklib / bs4 / caj2pdf)
    │
    ▼
文本预处理 (清洗 OCR 乱码；文字层缺失或损坏自动触发 Tesseract OCR，可回退云端 OCR)
    │
    ▼
LLM 结构化提取 (疾病 / 省份 / 阳性率 / GMC / 年龄段 / 样本量 / 采集年份；长文档 >2 万字符分块并行)
    │
    ▼
精确字符级溯源 + 强 Schema 校验 (三级匹配定位原文字符区间；省份枚举/数值范围校验，违规降级置信度)
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
生成 DataPoint 记录 (review_status = pending, 低置信度红色高亮)
    │
    ▼
人工审核 + 行内编辑 (支持手动新增数据点 / 修订溯源字符区间) → approved / rejected
    │
    ▼
地图可视化 (全国 / 省份 / 城市) + 多维度分析 + 数据导出 (CSV / Excel)
    │
    ▼
数据覆盖度分析 (数据缺失提醒 + 按完善度排序，所有疾病均展示)
    │
    ▼
FOI 感染力分析 (催化模型 → R0 → 群体免疫阈值 HIT) + VE 疫苗效果分析 (亚组拆分 + 保护率)
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
| llm_model_used | TEXT | 提取使用的大模型名称 |
| total_tokens | INT | 本次提取消耗的总 Token 数 |
| llm_cost_usd | NUMERIC(10,6) | 估算费用（美元） |
| prompt_tokens | INT | 输入 Token 数 |
| completion_tokens | INT | 输出 Token 数 |
| llm_call_count | INT | LLM 调用次数 |
| llm_usage_detail | JSON | 按模型细分的 Token 用量明细 |

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

### v1.6.9 (2026-08-13)

#### 新功能
- **登录页面全新设计**：参考设计稿 V4 重写登录页面，左侧品牌区加入中国地图 SVG 发光轮廓、等轴测图标（DNA/文档/芯片/病毒/图表）、橙色热点动画、粒子光点，右侧登录卡片采用自定义表单（无 Ant Design 依赖），保留密码可见切换、记住我功能。

### v1.6.8 (2026-08-13)

#### 安全加固

- **SECRET_KEY 随机化**：`SECRET_KEY` 从空值修复为随机 43 字符密钥，JWT 签名和 API Key 加密不再使用硬编码 fallback 密钥。
- **全局 API 认证保护**：所有非认证 API 路由（文献、提取、地图、分析、报告、文件夹监控、模型配置等）均需 JWT 认证才能访问，解决此前未登录即可操作全部数据的严重漏洞。
- **JWT 令牌安全增强**：Access Token 有效期从 24 小时缩短至 2 小时；新增 Refresh Token（7 天有效期）和 `/auth/refresh` 端点，实现安全的令牌续期机制；每个令牌携带唯一 `jti` 标识，支持后续吊销。
- **退出登录/Token 吊销**：新增 `/auth/logout` 端点，退出登录时通过 Redis 黑名单吊销当前令牌，已吊销的令牌在有效期内也会被拒绝访问。
- **密码强度校验**：新增密码复杂度要求（至少 8 位、包含大写字母、小写字母、数字），创建用户、修改密码、管理员重置密码均强制执行。
- **默认密码不再明文返回**：创建用户 API 响应中不再返回默认密码明文，日志中也不再记录密码。
- **登录速率限制**：登录接口增加 5 次/分钟/IP 的速率限制，防止暴力破解。
- **管理员权限收敛**：远程模型配置（含 API Key 管理）的创建、更新、删除操作要求管理员权限，普通用户仅可查看列表。
- **审计日志系统**：新增 `audit_log` 数据表和审计日志工具，登录、登出、修改密码、用户创建/更新/删除等关键操作均记录操作人、操作类型、目标和 IP 地址。

#### 新增接口

- `POST /api/v1/auth/refresh`：用 Refresh Token 换取新的 Access Token。
- `POST /api/v1/auth/logout`：退出登录，吊销当前令牌。

#### 新增文件

| 文件 | 说明 |
|------|------|
| `backend/app/core/rate_limiter.py` | 内存滑动窗口速率限制器 |
| `backend/app/core/token_revocation.py` | Redis Token 黑名单吊销服务 |
| `backend/app/core/audit.py` | 审计日志工具函数 |
| `backend/app/models/audit_log.py` | AuditLog 数据模型 |

#### 修改文件

| 文件 | 变更说明 |
|------|----------|
| `.env` | `SECRET_KEY` 填入随机安全密钥 |
| `backend/app/core/security.py` | Access Token 缩短至 2h，新增 Refresh Token 7d、jti 令牌 ID、token 类型字段 |
| `backend/app/api/v1/router.py` | 路由拆分：auth + health 为公开路由，其余全部需 JWT 认证 |
| `backend/app/api/v1/auth.py` | 新增 refresh/logout 端点；密码强度校验 8 位+大小写+数字；移除密码明文泄露；接入审计日志 |
| `backend/app/api/deps.py` | `get_current_user` 增加 Token 黑名单检查 |
| `backend/app/api/v1/model_config.py` | 创建/更新/删除远程配置添加 `require_admin` |
| `backend/app/models/__init__.py` | 注册 `AuditLog` 模型 |

### v1.6.7 (2026-08-13)

#### 新功能

- **用户认证与登录系统**：新增完整用户认证体系，基于 JWT 令牌 + bcrypt 密码哈希。所有页面（除 `/login` 外）均需登录才能访问，未登录用户自动跳转登录页。登录后右上角显示当前账户名称和角色（管理员/普通用户），提供「修改密码」和「退出登录」下拉菜单。Token 过期或无效时自动跳转至登录页。
- **用户管理（仅管理员）**：管理员可在侧边栏「用户管理」页面创建、编辑、删除用户，编辑用户可修改显示名、启用/禁用账号、调整管理员权限。新用户使用系统默认密码，管理员也可在「重置密码」弹窗中为任意用户设置新密码。
- **修改密码**：所有用户登录后可在右上角下拉菜单「修改密码」弹窗中自行修改登录密码，需验证原密码，新密码至少 6 个字符。
- **路由守卫**：前端新增 `RequireAuth` 组件，包装所有需要登录的路由，未登录时自动重定向到 `/login`；API 响应拦截器检测到 401 状态码时自动清除 Token 并跳转登录页。

#### 新增接口

- `POST /api/v1/auth/login`：用户登录，返回 JWT 令牌 + 用户名/显示名/管理员标识。
- `GET /api/v1/auth/me`：获取当前登录用户信息（含 ID、用户名、角色、状态等）。
- `POST /api/v1/auth/change-password`：当前用户修改自己的密码，需验证原密码。
- `GET /api/v1/auth/users`：管理员获取所有用户列表。
- `POST /api/v1/auth/users`：管理员创建新用户（使用系统默认密码）。
- `PUT /api/v1/auth/users/{user_id}`：管理员更新用户信息或重置密码。
- `DELETE /api/v1/auth/users/{user_id}`：管理员删除用户（不能删除自己）。

#### 新增文件

| 文件 | 说明 |
|------|------|
| `backend/app/core/security.py` | bcrypt 密码哈希 + JWT 令牌签发/验证 |
| `backend/app/models/user.py` | User 数据模型 |
| `backend/app/api/v1/auth.py` | 认证 API（登录/用户管理/修改密码） |
| `frontend/src/components/RequireAuth.tsx` | 路由守卫组件 |
| `frontend/src/pages/UserManagement.tsx` | 用户管理页面 |
| `frontend/src/pages/LoginPage.css` | 登录页样式 |
| `frontend/src/pages/LoginPage.tsx` | 登录页面 |

#### 优化

- 左侧菜单布局调整：管理员用户额外显示「用户管理」菜单项，普通用户不可见。
- API 响应拦截器增强：401 状态码自动清除 Token 并跳转登录页，提升安全性。
- 登录页左侧品牌区展示抗体 Y 形分子 SVG 和数据点阵背景，右侧卡片式表单。

### v1.6.6 (2026-08-12)

#### 新功能

- **报告生成模型选择**：报告生成时支持选择 LLM 模型，区分「本地 Ollama 模型」和「远程 API 模型」两种类型；远程模型支持自定义 API Key 和 Base URL，可在新增的「模型管理」弹窗中添加/编辑/删除常用远程模型配置（DeepSeek、OpenAI、Qwen 等），生成的报告会记录所用模型（`report.llm_model` 字段）并在报告列表/详情中展示。
- **MinerU PDF 解析器集成**：新增 `ENABLE_MINERU_PDF_PARSER` 配置项，开启后优先使用 MinerU 解析 PDF（对复杂排版、表格、扫描件效果更好），失败自动回退到 PyMuPDF；首次使用会自动下载模型（约 2-3GB）。
- **LLM 并发提取配置**：新增 `LLM_CONCURRENCY`（并发请求数上限，需与 Ollama 的 `OLLAMA_NUM_PARALLEL` 对齐）、`LLM_CHUNK_THRESHOLD`/`LLM_CHUNK_SIZE`/`LLM_CHUNK_OVERLAP`（长文档分块参数）、`LLM_REQUEST_TIMEOUT`（本地模型推理超时，默认 600 秒）、`TEXT_PREPROCESS_MAX_CHARS`（预处理截断上限）等配置项，提升本地大模型的提取吞吐量。
- **文献列表「文档」列排序**：文献列表「文档」列支持表头点击排序，前端配置 `sorter`/`sortOrder` 并在排序下拉菜单新增「文档」选项，后端 `sort_map` 映射到 `Literature.file_path` 字段（空值排最后）。

#### 优化

- **本地 Ollama 模型默认改用 qwen2.5:14b**：相比 qwen3:32b，在 24GB VRAM 下显存占用从 ~29GB（超显存触发 CPU 交换）降至 ~15GB（完全 fit），GPU 利用率从 79% 提升至 100%，单篇文献提取耗时从 >10 分钟降至约 1.8 分钟，Token 用量从 39,462（3 次重试）降至 14,466（1 次成功），数据点提取从 0 个提升至 10 个。
- **禁用 qwen3 系列的 thinking 模式**：通过 `extra_body={"think": False}` 关闭推理链输出，避免推理时间增加 3 倍且输出被思考链 token 截断。
- **解除 Ollama `num_predict` 上限**：本地模型调用时显式设置 `num_predict=16384`，避免服务端默认上限覆盖 SDK 的 `max_tokens` 导致输出被截断。
- **OllamaProvider 次级版本号匹配**：`matches()` 支持 `qwen2.5` 匹配 `qwen2` 这类次级版本号场景，避免模型识别失败。
- **智能 JSON 解析兜底**：新增 `_smart_truncate_and_close` 函数，对 LLM 返回的截断 JSON 采用逐字符扫描 + 维护字符串/括号状态 + 回退最近 checkpoint + 按括号栈逆序补齐的策略，显著提升结构化字段解析成功率。
- **模型切换 timeout 透传**：AsyncOpenAI 客户端在模型切换时显式传递 `timeout` 参数，避免使用默认超时导致本地模型调用被提前中断。

#### 新增接口

- `GET /api/v1/model-configs`：获取所有远程 API 模型配置列表。
- `POST /api/v1/model-configs`：新增远程 API 模型配置（含名称、厂商、API Key、Base URL）。
- `PUT /api/v1/model-configs/{id}`：更新指定远程模型配置。
- `DELETE /api/v1/model-configs/{id}`：删除指定远程模型配置。
- `POST /api/v1/reports/generate` 新增 `model` 查询参数：指定报告生成所用的模型名称（本地 Ollama 模型名或远程模型配置 ID）。

#### 数据库迁移

- `add_api_model_config`：新增 `api_model_config` 表，存储远程 API 模型配置（名称、厂商、API Key 加密存储、Base URL、是否默认等）。
- `add_report_llm_model`：为 `report` 表新增 `llm_model` 字段，记录每份报告生成时所用的 LLM 模型。

#### 文档与配置

- 更新 README「核心功能」和「技术栈」，补充报告生成模型选择和本地 Ollama 支持的描述。
- `.env.example` 新增 LLM 并发提取相关配置项的注释说明。
- `backend/app/config.py` 的 `.env` 文件路径改为基于项目根目录的绝对路径，避免从 backend 子目录启动时读取失败。

### v1.6.5 (2026-08-12)

#### 新功能

- **文献格式标识列**：文献列表新增「文档」列，使用彩色 Tag 显示文献的本地文档格式（PDF/CAJ/EPUB/DOCX/PPTX/XLSX/TXT/HTML/URL），不同格式对应独立颜色和图标；无本地文档的文献显示「无」灰色虚线 Tag。点击 Tag 可直接预览：HTML 在新标签页打开，其它格式走内置预览弹窗，便于快速识别文献来源类型并预览/下载。
- **手动停止单篇提取**：文献列表操作列在文献状态为 `processing` 时新增红色「停止提取」按钮（带二次确认弹窗），点击后调用接口强制将该文献状态重置为 `failed`，可立即重新触发提取。适用于单篇文献卡住的场景，避免无限等待。
- **一键重置所有卡住的提取状态**：文献管理工具栏新增「重置卡住的提取」按钮（带二次确认弹窗），点击后批量将所有 `processing` 状态的文献重置为 `failed`。典型场景：服务器重启导致异步提取任务丢失但状态未更新，文献永久显示「提取中」。重置后可在文献列表使用「批量AI提取」统一重新触发。

#### 新增接口

- `POST /literatures/{id}/extraction/stop`：手动停止单篇文献提取，将 `processing` 强制重置为 `failed`，返回最新状态；若当前状态非 `processing` 则返回无需停止提示。
- `POST /literatures/extraction/reset-stuck`：批量重置所有 `processing` 状态文献为 `failed`，返回 `reset_count` 和重置的 `literature_ids` 列表；无卡住任务时返回 `reset_count=0`。

#### 修复

- **提取状态永久「提取中」**：修复服务器重启或任务异常退出后，异步提取任务丢失但 `extraction_status` 未更新的问题，新增上述两个接口手动恢复状态。

### v1.6.4 (2026-08-12)

#### 新功能

- **地图总览底部统计区分已审核/未审核**：三个统计卡片（总数据点数、覆盖省份数、总样本量）主数字改为绿色「已审核通过」值，下方新增橙色「未审核」小字（含对应数量和样本量），0 时自动隐藏；筛选条件（疾病、年份、年龄等）改变时两组数字同步刷新。
- **疾病名称统一化**：在 `term_normalizer.py` 新增 40+ 法定传染病及常见血清流行病学病种的映射，覆盖「麻腮风/MMR → 麻疹」「丁型病毒性肝炎 → 丁型肝炎」「流行性出血热/汉坦病毒 → 肾综合征出血热」「登革热/登革病毒/DEN → 登革热」「寨卡/Zika → 寨卡病毒」「马尔尼菲青霉菌 → 马尔尼菲篮状菌」以及乙肝/丙肝/戊肝/乙脑/疟疾/血吸虫/包虫/囊虫/丝虫/华支睾吸虫/蛔虫/钩虫等常见别名；提供 `backend/scripts/normalize_diseases.py` 迁移脚本一键规范化数据库历史数据。

#### 新增接口

- `GET /map/summary` 新增未审核字段：`unapproved_point_count`、`unapproved_province_count`、`unapproved_study_count`、`unapproved_total_sample`（跟随 disease / data_type 筛选参数）

#### 新增脚本

- `backend/scripts/normalize_diseases.py`：遍历 `data_points` 表所有疾病名称并通过 `normalize_disease()` 规范化，自动打印变更前后对照和影响行数，幂等可重复执行。

### v1.6.3 (2026-08-12)

#### 新功能

- **失败文献批量AI重新提取**：文献列表新增多选（复选框），工具栏新增「批量AI提取」按钮，多选失败/待提取的文献后可统一选择模型进行批量重新提取；对话框顶部显示已选数量，并对正在 `processing` 中的文献自动跳过避免重复提交。
- **多格式文献导出**：原有「导出 CSV」扩展为下拉菜单，支持 7 种导出选项：导出全部 CSV / Excel（仅文献元信息）、导出全部 JSON / Excel（含数据点）、导出选中 CSV / JSON / Excel（含数据点，未选中时禁用）。JSON 格式包含 `export_version`、时间戳、文献数、数据点数等头信息，便于版本化管理。
- **文献+数据点跨电脑导入**：新增「导入文献」按钮，上传 `导出 JSON（含数据点）` 生成的 `.json` 文件，系统会自动创建文献记录及其所有数据点，完整保留 `review_status`（approved/pending）、`estimate_type`（primary/subgroup）、置信度、溯源字符区间等关键字段；支持「跳过重复」开关（按 DOI / 标题匹配，可切换为更新已有记录）。导入后，审核通过的数据点自动在地图热力图、时间序列动画、FOI/VE 分析、免疫屏障评估等所有模块中正常展示，满足本地审核后迁移到新笔记本的需求。

#### 新增接口

- `GET /literatures/export` 新增参数：`format`（csv/xlsx/json）、`include_data_points`（bool）、`literature_ids`（逗号分隔UUID，仅导出指定文献）
- `POST /literatures/import`：JSON 文件上传 + 数据点批量导入，返回 imported_count / skipped_count / data_point_count / errors
- `POST /literatures/extraction/batch`：批量触发AI提取，返回 submitted / skipped / errors 明细

#### 测试

- 新增 `tests/test_export_import.py` 测试套件，6项测试全部通过：JSON结构验证、27字段数据点字段映射、默认值处理、2篇文献+5个数据点 round-trip（麻疹2approved+1pending、腮腺炎2approved）、地图/分析模块兼容性（`approved + primary` 筛选）、重复检测逻辑。

### v1.6.2 (2026-08-06)

#### 新功能

- **文献元数据自动同步**：AI 提取完成后自动从数据点聚合文献的年份（`collection_year` 众数）和省份信息，同步到文献列表显示，无需进入详情页即可看到更新后的元数据。
- **批量同步元数据**：文献管理工具栏新增"批量同步元数据"按钮，一键同步所有提取完成但缺少年份/省份的文献，支持二次确认和进度反馈。
- **单篇同步按钮**：文献列表操作列对已完成且缺元数据的文献显示同步按钮，支持单篇手动触发。
- **省份详情面板疾病列**：点击省份后右侧"历年数据"和"城市分布"表格新增疾病列，显示中文名称；未指定疾病筛选时按城市/年份+疾病分组，每种疾病独立显示一行；散点图 tooltip 和城市详情弹窗同步显示疾病信息。

#### 修复

- **年份聚合字段映射错误**：修复提取任务中元数据聚合逻辑错误使用 `sample_year`/`study_end_year`/`study_start_year` 字段导致聚合失败的问题，改为正确的 `collection_year` 字段。
- **FOI 分析空值崩溃**：修复 FOI 和 VE 矩阵为 null 时前端渲染崩溃的问题，增加空值检查。
- **VE 响应字段缺失**：修复 VE 分析响应中部分字段未正确返回的问题。
- **GMC 平均值计算**：修复 GMC 平均值未过滤 None 值导致计算异常的问题。
- **CSV 导出零值处理**：修复 CSV 导出时零值被错误过滤的问题。
- **模型名称回退**：修复文献详情页 LLM 模型名称显示时的回退逻辑。
- **R0 范围 null 处理**：修复免疫屏障评估中 R0 范围为 null 时的前端处理。
- **省份详情面板疾病标签**：地图省份详情面板顶部新增蓝色疾病名称标签，显示当前筛选的疾病信息。
- **新疆县级数据点显示**：新增 80+ 新疆县城坐标和 34 个省份中心坐标，未收录县城自动回退到省份中心，确保所有县级数据点均可在地图上显示。
- **同步元数据 API 响应解析**：修复前端 `syncMetadata` 函数重复解包 `data` 字段导致 `pub_year_updated` 属性读取失败的问题。

#### 优化

- **FOI 感染力分析支持不选择疾病**：FOI 分析的疾病选择器新增 `allowClear` 属性，用户可取消选择疾病进行全量分析。
- **AI 提取模型选择界面**：修复 Select.Option 多行渲染导致的高度计算异常，模型描述改为动态显示的灰色小字。
- **默认模型可选**：上传文献和手动提取时，支持用户重新选定某一个模型为默认模型，而非锁定不可修改。
- **疾病名称中文显示**：地图省份详情中的疾病列统一使用中文名称（如 `measles` → `麻疹`），通过前端 `DISEASES` 常量构建反向映射。
- 清理 Analysis.tsx、MapOverview.tsx、Literature.tsx 中的未使用导入。

### v1.6.1 (2026-08-05)

#### 新功能

- **LLM Token 用量与费用统计**：AI 提取完成后可选显示本次提取消耗的 Token 数、估算费用及使用的 LLM 模型；支持按模型细分（多模型调用时分别统计）；作者可配置是否在提取完成时显示此信息（`showUsageOnComplete` 本地偏好）。数据库新增 `llm_model_used`、`total_tokens`、`llm_cost_usd` 等字段，后端 `llm_extractor.py` 新增 `_accumulate_usage` / `get_usage_summary` 方法跟踪 6 个 Provider（OpenAI / DeepSeek / Qwen / Ollama 等）的实时用量与定价。

- **免疫屏障评估优化**（参考 serotracker 项目）：
  - 复用 FOI 模块的催化模型（λ = -ln(1-SP)/age）估算 FOI，反推 R0 ≈ λ·L，计算 HIT = 1 - 1/R0
  - HIT 阈值优先级：FOI 估算 > WHO 硬编码 > 文献 R0（`R0_REFERENCE` 15 种疾病），输出 `hit_target_source` 标识
  - 新增年龄分层分析（`age_groups`）：5 个标准年龄组（<1岁、1-4岁、5-14岁、15-59岁、≥60岁），含各组的阳性率、FOI、免疫屏障状态
  - 新增省份对比矩阵（`province_matrix`）：每省含数据点数、样本量、阳性率、FOI、估算 R0、屏障状态，支持排序与状态筛选
  - 前端新增年龄筛选输入框、年龄分层柱状图（含阈值参考线和状态颜色编码）、FOI/R0/HIT 统计卡片、省份矩阵表格

- **Edge 浏览器插件**（参考 Mendeley 浏览器插件设计）：
  - Manifest V3 架构，存放于 `browser-extension/` 目录
  - 支持 15+ 学术站点元数据自动识别（PubMed / PMC / Nature / Science / Cell / Springer / Wiley / Lancet / BMJ / medRxiv / arXiv / 知网 / 万方 / 维普 等）
  - 智能判断提交策略：PDF 文件直接抓取上传；页面含 PDF 链接则自动抓取；否则走 URL 导入（保存 HTML）
  - 弹窗展示元数据预览（标题/作者/DOI/期刊/年份/摘要/提交方式），支持编辑后提交
  - 提交后自动触发 AI 提取，弹窗内实时轮询提取状态（每 3 秒，最多 60 次）
  - 右键菜单「添加到抗体图谱数据库」、桌面通知、设置页（后端地址/默认省份/LLM 模型配置）
  - 通过 `host_permissions` + background service worker 绕过 CORS 限制

#### 优化

- 新增 7 个数据库字段（Alembic 迁移文件 `add_llm_token_usage.py`）
- 免疫屏障评估 API 响应扩展：新增 `r0_reference`、`age_groups`、`province_matrix`、`summary.hit_target_used_percent` 等字段
- 前端导航菜单中"文件夹监控"模块调整到最后一位
- 后端 `py_compile` 语法检查通过，前端 `tsc` 类型检查无新增错误

### v1.6.0 (2026-08-05)

#### 新功能

- **P0: FOI 感染力 + 群体免疫阈值分析**：基于催化模型（λ = -ln(1-SP)/age）估算各年龄段 FOI，推算 R0 ≈ λ·L（L=75 年），计算 HIT = 1 - 1/R0 并与 WHO 阈值对比；输出省×疾病 FOI 热力矩阵与群体免疫状态（reached / near / not_reached）。

- **P1: 疫苗效果 VE + 接种率综合分析**：根据 DataPoint.population 中「已接种/未接种」关键词自动拆分亚组，计算 VE = 1 - SP_vax / SP_unvax（疫苗诱导抗体时返回 None 并给出解读）；内置 14 种疫苗可预防疾病的 NIP 接种率参考表（国家级 + 省一级）；从整体血清阳性率反推隐含接种率；输出省×疾病覆盖率矩阵（on_track / near / below）。

- **数据覆盖度分析增强**：所有疾病（包括已全覆盖的标杆疾病如麻疹）均展示在缺失提醒面板中，按完善度（missing_count 升序）排列，新增完整度百分比显示。

#### 优化

- 新增 2 个 API 端点：`/analysis/foi-herd-immunity`、`/analysis/vaccine-effectiveness-coverage`
- 新增测试 50 项（P0 26 项 + P1 24 项），全库 283 项测试全部通过
- 修复前端 vite 代理端口配置错误（8080 → 8000），消除人群选项 500 错误
- 修复 antd Progress width 废弃警告，改用 size 属性
- 新增人口选项、疫苗 VE 测试套件，完善回归测试体系

### v1.5.0 (2026-08-04)

#### 新功能

- **精确字符级溯源（Grounding）**：每个数据点锚定到原文的精确字符区间（`source_char_start` / `source_char_end`），采用精确匹配、模糊匹配、关键短语匹配三级策略定位，LLM 幻觉产物自动标记 `is_grounded=false`；详情页新增"溯源查看"功能，可在原文中高亮定位字符区间。

- **强 Schema 约束**：LLM 提取结果经结构化校验（省份枚举归一化、血清阳性率 0-100% 范围、GMC/滴度正值校验等），字段违规自动降级置信度等级并红色高亮待审，显著降低无效数据入库。

- **长文档分块并行提取**：超过 2 万字符的文献按段落边界自动分块，并行调用 LLM 提取后合并去重，解决超长文献"大海捞针"导致的提取遗漏。

- **多格式扩展与解析重构**：新增 PPTX / XLSX 文献支持；文档解析重构为**策略模式**（`processors/` 目录 + `@register_parser` 注册表分发）；新增 **URL/HTML 网页导入**（`/literatures/from-url`），自动提取网页标题。

- **云端 OCR 回退**：Tesseract 本地 OCR 基础上新增百度 OCR 云端回退，扫描版文献识别成功率提升。

- **数据导出**：文献列表 CSV、数据点 CSV、地图数据点 CSV、分析结果多工作表 Excel（4 个导出接口）。

- **上传流程优化**：上传文献时可选择**不自动触发 AI 提取**，后续在详情页手动启动。

- **手动新增数据点**：提取失败或遗漏时，可在文献详情页手动补录数据点。

- **多格式在线预览**：非 PDF 文件（TXT/HTML/DOCX/PPTX/XLSX/EPUB）在详情页可查看解析后文本，CAJ 提示下载查看。

#### 优化

- 数据点行内编辑支持修订"原文依据"（页码 + 上下文）与溯源字符区间
- 上传 / 预览核心链路新增详细日志输出，便于异常排查
- 新增测试：P0 溯源与 Schema（7 项）、P1 多格式功能（47 项）、P2 分块与可视化（39 项）、日志链路（9 项），累计 100+ 项全部通过

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
