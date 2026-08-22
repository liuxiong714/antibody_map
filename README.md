# 抗体地图 (Antibody Map)

血清抗体流行病学数据可视化与分析平台

![平台预览](docs/screenshots/dashboard.png)

## 项目简介

抗体地图是一个面向公共卫生和流行病学领域的**血清抗体水平数据管理、可视化与分析平台**。系统支持上传流行病学相关的 PDF 文献，通过 LLM 自动提取结构化的血清抗体数据点，经过人工审核后在交互式中国地图上可视化展示，并支持多维度数据分析和 AI 报告生成。

### 核心功能

| 模块 | 功能 |
|------|------|
| **文献管理** | 上传 PDF/CAJ/EPUB/DOCX/PPTX/XLSX/TXT/HTML 文献、**URL 网页导入**、**题录批量导入**（RIS / EndNote(.enw) / PubMed 文本 / WoS 纯文本 / WoS CSV / 读秀超星 多格式自动识别，按 PMID/DOI 查重）、元数据管理、关键词/疾病/省份筛选、在线预览、**表头点击排序**、**文献重复检测与合并**、**多格式导入导出**（CSV/Excel/JSON，JSON 含数据点可跨电脑迁移导入、支持仅导出选中文献）、**元数据批量同步**（从数据点自动聚合年份/省份）、**文档格式标识列**（彩色 Tag 显示 PDF/CAJ/DOCX/HTML 等格式，点击即可预览）、**全列排序与筛选**（标题/作者模糊筛选、创建时间范围、文档格式下拉，筛选状态本地缓存）、**文献文件下载**（带 JWT 认证自动下载）、**修改关联文件**（替换已关联本地文档）、**软删除回收站**（删除后移入回收站，30 天内可还原，到期自动清理）、**批量删除**（多选后移入回收站） |
| **PubMed 检索** | 侧边栏「PubMed 检索」页支持关键词检索 PubMed（NCBI E-utilities）、**多源检索**（Crossref / OpenAlex / Europe PMC 来源下拉切换，统一结果结构）、勾选结果一键**纳入数据库**（写入文献库）与**下载开放获取 PDF**（Europe PMC 全文直链，下载目录可配置 `PDF_DOWNLOAD_DIR`） |
| **AI 数据提取** | LLM 自动从文献提取血清阳性率、GMC 等数据点，支持 DeepSeek/OpenAI/Qwen 多厂商，支持**上传后手动选择是否自动提取**、**上传/提取时可重新选定默认模型**、**批量AI提取**（多选文献后统一设置模型重新提取，自动跳过 processing 中的文献）、**手动停止提取**（单篇卡住的 processing 强制重置为 failed）、**一键重置所有卡住的提取状态**（适用于服务器重启后任务丢失的场景）；提取完成后可选显示**Token 用量、费用估算及使用的大模型**；本地 Ollama 走**原生 JSON Schema 结构化输出强约束**，并做**关键数值回验**（阳性率/GMC/样本量必须在原文中可定位，否则自动降级低置信）；**模型选择统一**——文献提取、文件夹监控、报告生成的本地模型候选项统一来自后端 `/models`（系统设置「本地模型配置」维护），各功能始终一致 |
| **精确字符溯源** | 每个数据点锚定到原文的精确字符区间（`source_char_start/end`），采用精确/模糊/关键短语三级匹配，未匹配自动降级置信度并红色高亮待审 |
| **长文档分块并行提取** | 超过 2 万字符的文献按段落边界分块、并行调用 LLM 提取，结果自动合并去重 |
| **强 Schema 约束** | LLM 输出经 JSON Schema 校验（省份枚举、阳性率 0-100% 范围、GMC 正值等），字段违规自动降级置信度 |
| **数据审核与编辑** | 人工审核（通过/驳回）、**审核意见**（可留存每条数据点的审核批注）、**审核人与审核时间自动记录**（操作者身份与审核时间随审核落库）、**批量驳回强制填写意见**、行内编辑（疾病、地区、年龄段、数值、**原文依据、溯源字符区间、审核意见**等字段）、**手动新增数据点**（提取失败时补录） |
| **地图可视化** | 全国/省级/市级交互式抗体水平热力地图，点击省份钻取市级数据、**时间序列动画自动年份范围**、底部统计区分**已审核通过**（绿色）与**未审核**（橙色）两组数据点/覆盖省份/样本量 |
| **数据分析** | 逐年趋势、区域对比、年龄分层、**免疫屏障评估**（复用 FOI 模块 R0/HIT 计算，新增年龄分层分析与省份对比矩阵，HIT 阈值优先级：FOI 估算>WHO 建议>文献 R0）、**数据覆盖度分析**、**多表单 Excel 数据导出**、**FOI 感染力分析**（催化模型 + R0 估算 + 群体免疫阈值 HIT，支持不选择疾病进行全量分析）、**疫苗效果 VE 分析**（已接种/未接种亚组拆分 + 保护率估算）、**接种率双轨分析**（NIP 参考表 + 血清阳性率反推隐含接种率）、**省间公平性分析**（基尼系数/变异系数/达标省）、**数据质量评估**（主估计 A/B/C 分级+CI/溯源占比）、**目标达成追踪**（逐年达标省进度）、**年龄-抗体曲线**（惩罚样条平滑+年龄别 FOI）、**出生队列分析**（代际免疫/计划免疫史解读）、**同省多研究 Meta 合并**、**多文献 Meta 分析**（森林图/漏斗图/亚组）、**检测方法异质性**、**空间热点/冷点分析**（Moran's I + Getis-Ord Gi*）、**免疫屏障模拟**、**审核状态统计**、**审核统计仪表盘**（按疾病/审核人聚合审核量、通过率、平均审核时间），各统计均附 95% CI 与方法学脚注 |
| **数据质量评分** | 每个数据点按六项信号（样本量/抽样方式/检测方法/人群代表性/调查级别/溯源置信度）自动打分（0-100 分 + A/B/C 三级），审核通过后异步重算，前端 Tooltip 展示六项得分明细 |
| **分析快照与引用** | 每个分析请求生成带数据指纹（data_hash）的快照 token，同参数自动去重复用；支持 **GBT7714 / BibTeX** 引用文本导出，确保分析结果可复现、可溯源 |
| **抗原图谱** | 基于 HI/VNT/ELISA 滴度矩阵（titer_table 表）的 **metric MDS 降维**，将抗原与抗血清映射到 2D 平面（参考 Smith 2004 / racmacs），前端独立「抗原图谱」页交互展示 |
| **报告生成** | LLM 生成抗体分析报告和疫苗接种策略研判报告，支持在线编辑和下载；**报告生成时可选模型**（本地 Ollama 模型 / 远程 API 模型，支持自定义 API Key 和 Base URL），自动拼接统一方法学脚注 |
| **文件夹监控** | 定期监测指定文件夹，自动导入新文件并触发信息提取（可指定提取模型，候选项与文献提取/报告生成统一） |
| **系统设置** | 集中管理平台配置：**远程模型配置**（API Key/Base URL，仅管理员）、**本地模型配置**（新增 `local_model_config` 表，增删改查本地 Ollama 模型，`/models` 统一读取，各功能模型候选项一致）、**后台日志**（loguru 按日落盘 `backend/logs/`，支持文件切换/级别筛选/关键字搜索/自动滚动）、**系统信息**（版本号/运行环境/功能特性动态展示） |
| **Edge 浏览器插件** | 参考 Mendeley 设计，在浏览器中一键将文献添加到数据库并触发 AI 提取；支持 15+ 学术站点元数据自动识别、PDF 智能抓取上传、URL 网页导入、右键菜单、桌面通知 |
| **多格式预览** | PDF 使用 pdf.js 渲染；TXT/HTML/DOCX/PPTX/XLSX/EPUB 显示解析后文本；CAJ 提示下载，支持分栏布局、面板折叠/展开 |

### 支持的疾病

麻疹、腮腺炎、风疹、百日咳、白喉、破伤风、乙肝（乙型病毒性肝炎）、甲肝、丙肝、丁肝（丁型肝炎/丁型病毒性肝炎）、戊肝、脊髓灰质炎、流感、新冠、流行性脑脊髓膜炎、水痘、手足口病、轮状病毒（疫苗可预防/重点传染病）；肾综合征出血热、登革热、寨卡病毒、黄热病毒、乙脑、马尔尼菲篮状菌、李斯特菌、弓形虫、疟疾、血吸虫、华支睾吸虫、蛔虫、钩虫、丝虫、包虫、囊虫（法定传染病和常见血清流行病学研究病种）。**疾病名称自动标准化**：麻腮风/MMR→麻疹、丁型病毒性肝炎→丁型肝炎、丙肝（丙型病毒性肝炎）→丙肝、戊型病毒性肝炎→戊肝、乙型脑炎→乙脑等，自动合并同一疾病的不同名称。

### 支持的文件格式

PDF、CAJ、EPUB、DOCX、PPTX、XLSX、TXT、HTML（支持中文文献和外文文献，解析采用**策略模式**：各格式独立解析器 + 统一注册表分发；PDF 可选 **MinerU 增强解析**，结构化输出保留表格/公式，超时自动回退 PyMuPDF；可选 **AnyDoc 增强解析**（firecrawl/anydoc，Rust 实现），文本层 PDF 优先用 AnyDoc 毫秒级转 GFM Markdown，天然输出高质量表格，失败自动回退现有解析链）

### 智能特性

- **疾病名称标准化**：自动合并同一疾病的不同名称（如乙肝/乙型病毒性肝炎、甲肝/甲型病毒性肝炎、乙脑/流行性乙型脑炎、丙肝/丙型病毒性肝炎、戊肝/戊型病毒性肝炎、丁肝/丁型病毒性肝炎、麻腮风/MMR→麻疹、流行性出血热/汉坦病毒→肾综合征出血热等）；含 40+ 法定传染病及常见血清流行病学病种映射（登革热、寨卡、疟疾、血吸虫、包虫、囊虫等）；提供 `backend/scripts/normalize_diseases.py` 迁移脚本，一键规范化数据库中已有的历史非标准疾病名称
- **文献重复检测**：基于 DOI、标题、作者、PDF 哈希等多维度自动检测重复文献
- **文件夹自动监控**：配置本地文件夹后，系统自动监测新文件并导入提取
- **扫描件 OCR 兜底**：文字层缺失或损坏的扫描 PDF 自动触发 Tesseract OCR（中文+英文），失败可回退云端 OCR
- **交互式溯源查看**：点击数据点可查看原文上下文并高亮定位字符区间，方便人工核验 LLM 提取结果
- **元数据自动聚合**：AI 提取完成后自动从数据点聚合文献的年份（取众数）和省份信息，同步到文献列表；支持批量同步历史文献的缺失元数据
- **多格式导入导出与跨电脑迁移**：文献列表支持 CSV / Excel / JSON 三种格式导出；JSON 格式可完整包含数据点（含审核状态、estimate_type、溯源字段），在另一台电脑通过「导入文献」按钮一键导入，自动保留审核状态并在地图、分析模块中正常展示；支持仅导出选中的文献数据
- **纯函数统计引擎**：全局置信区间（CI）引擎统一计算 Wilson/Clopper-Pearson 二项置信区间、样本量加权率、几何均数 GMC、双比例检验、年龄曲线样条与年龄别 FOI、Meta 合并（固定/随机效应 + I²/Q/τ²）、基尼系数、Moran's I / Getis-Ord Gi*、直接标准化率（标准人口归一）等，全部为无副作用纯函数且配套单元测试
- **数据驱动常量表**：标准人口（中国 2020）、省份邻接矩阵、疾病解读注释等存于 `backend/app/core/reference_data/*.json`，带版本字段便于更新

## 技术栈

| 层级 | 技术 |
|------|------|
| **前端** | React 18 + TypeScript, Vite 6, Ant Design 5, ECharts 5, pdfjs-dist, Zustand, React Router 6 |
| **后端** | Python 3.10+, FastAPI + Uvicorn, SQLAlchemy 2.0 (async), Celery + Redis, Pydantic 2.0 |
| **统计/制图** | NumPy + SciPy + statsmodels + scikit-learn（统计引擎、Meta 分析、MDS 抗原制图、时间序列） |
| **数据库** | PostgreSQL 15 |
| **存储** | MinIO 对象存储 / 本地文件系统双模式 |
| **AI/LLM** | OpenAI SDK 兼容协议，支持 DeepSeek / OpenAI / 通义千问 (Qwen) / **本地 Ollama** 多厂商；JSON Schema 强约束 + 精确字符级溯源；**报告生成支持模型选择**（本地 + 远程 API，可配置 API Key/Base URL）；错误分类 + **URL 候选链自动切换** + 连接类错误短退避快速重试（防网关 IP 漂移导致提取失败） |
| **文档解析** | 策略模式解析器注册表：PyMuPDF (fitz) + pdfplumber、python-docx、python-pptx、openpyxl、ebooklib、BeautifulSoup、caj2pdf；**MinerU 增强解析**（PDF→结构化 Markdown，仅 worker 容器安装，**子进程隔离执行** + 模型缓存本地化，不拖垮 worker 主进程）；**AnyDoc 增强解析**（firecrawl/anydoc，Rust 实现，docx/pptx/xlsx/epub/pdf/html/txt 毫秒级转 GFM Markdown，配置开关 `ENABLE_ANYDOC`，默认关闭，开启后自动回退现有解析链） |
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
│   │   │   ├── processors/         # 各格式解析器 (docx/pptx/xlsx/epub/html/txt/anydoc + @register_parser)
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
- **CAJ 转换工具** (可选，用于解析 CAJ 格式文献，见下方 [CAJ 格式支持](#caj-格式支持) 说明)
- **NVIDIA GPU + NVIDIA Container Toolkit**（可选但推荐）：worker 容器通过 `deploy.resources.reservations` 透传 GPU，MinerU 文档解析 / torch 推理使用 GPU 加速（未配置则回退 CPU 模式，解析速度大幅下降）。Windows 下需在 WSL2 中安装 NVIDIA Container Toolkit 后重启 Docker。

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
| POST | `/literatures/import-references` | **导入题录**：解析 RIS / EndNote(.enw) / PubMed / WoS / 读秀超星 题录文本（`ref_text` + `fmt=auto` 自动探测），按 PMID/DOI 查重，返回 `imported/skipped/total/errors` |
| POST | `/literatures/batch-delete` | **批量删除**：按 `literature_ids` 列表批量删除文献及关联文件/数据点，自动跳过不存在的记录 |

### PubMed 检索

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/pubmed/search` | PubMed 检索（NCBI E-utilities esearch+esummary，返回 `items/total/page/page_size`） |
| GET | `/pubmed/search/multi` | **多源检索**：按 `source`（crossref / openalex / europepmc，缺省 crossref）调用对应服务，统一返回 `{items, total, page, page_size, source}` |
| GET | `/pubmed/abstract/{pmid}` | 获取 PubMed 摘要（efetch） |
| POST | `/pubmed/import` | 将 PMID 列表纳入文献库（esummary 取元数据），返回 `success_count/fail_count` |
| POST | `/pubmed/download-pdf` | 下载开放获取 PDF 到 `PDF_DOWNLOAD_DIR`（缺省回退 `LOCAL_STORAGE_DIR`），返回 `downloaded/no_oa/failed/dir` |

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
| GET | `/analysis/coverage-review` | 审核状态统计（按疾病统计点数/样本量/审核通过率，默认按待审核数降序） |
| GET | `/analysis/foi-herd-immunity` | **P0: FOI 感染力 + 群体免疫阈值分析**（催化模型 λ = -ln(1-SP)/age、R0、HIT） |
| GET | `/analysis/vaccine-effectiveness-coverage` | **P1: 疫苗效果 VE + 接种率分析**（亚组 VE、NIP 参考表、隐含接种率、覆盖率矩阵） |
| GET | `/analysis/equity` | 省间公平性分析（基尼系数、变异系数、最佳/最差省、对比 WHO 阈值的达标比例、Top/Bottom 排名） |
| GET | `/analysis/quality` | 数据质量评估（reliability_grade A/B/C/D 分级、高质量占比、带 CI / 原文溯源比例、单点估计省份预警） |
| GET | `/analysis/goal-tracking` | 目标达成追踪（按年追踪达标省比例、全国加权阳性率、相对 GOAL_THRESHOLDS/HIT 的缺口百分点） |
| GET | `/analysis/age-curve` | 年龄-抗体曲线（seroprevalence/gmc 随年龄变化，LOWESS 平滑 + 拐点定位） |
| GET | `/analysis/meta-merge` | 同省多研究 meta 合并（固定/随机效应逆方差合并，输出 I² 异质性、Q 统计量、τ²） |
| GET | `/analysis/assay-heterogeneity` | 检测方法(assay)异质性（按 assay 分层对比加权阳性率与 95% CI，跨 assay 的 I² 异质性） |
| GET | `/analysis/simulate` | 免疫屏障模拟（FOI 催化模型反推 R0/HIT，结合假设接种覆盖与加强针比例判定屏障状态、反推达标所需覆盖） |
| GET | `/analysis/export` | 导出分析数据 Excel（多工作表，含统计方法附录：加权率/GMC/95%CI/基尼/meta 合并等算法公式） |

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

### 模型配置

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/models` | 获取可用模型列表（本地 + 远程，本地优先读 `local_model_config` 表，空表回退静态列表） |
| GET | `/models/local` | 获取本地模型配置列表 |
| POST | `/models/local` | 新增本地模型配置（管理员，模型名唯一） |
| PUT | `/models/local/{config_id}` | 更新本地模型配置（名称/模型名/描述/启用状态，管理员） |
| DELETE | `/models/local/{config_id}` | 删除本地模型配置（管理员） |
| GET | `/models/remote` | 获取远程 API 模型配置列表 |
| POST | `/models/remote` | 新增远程模型配置（管理员，API Key 加密存储） |
| PUT | `/models/remote/{config_id}` | 更新远程模型配置（管理员） |
| DELETE | `/models/remote/{config_id}` | 删除远程模型配置（管理员） |

### 系统

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/system/info` | 系统信息（版本号、运行环境、功能特性、日志目录、仓库地址） |
| GET | `/system/logs` | 列出日志目录下所有日志文件（名称/大小/修改时间，倒序） |
| GET | `/system/logs/content` | 读取日志文件尾部内容（支持 `file/lines/level/keyword` 参数过滤，防路径穿越） |

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
| `LLM_FALLBACK_BASE_URLS` | 主 `LLM_BASE_URL` 连接失败时的备用地址（逗号分隔，可选） | - |
| `LLM_CONNECT_RETRIES` | 连接类错误（DNS/连接/超时）的快速重试次数（短退避，仅作用于连接错误，不消耗 token） | `2` |

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
| `PDF_DOWNLOAD_DIR` | PubMed 开放获取 PDF 下载目录（为空时回退 `LOCAL_STORAGE_DIR`） | - |
| `ORPHAN_CLEANUP_ENABLED` | 是否启用后台定时清理孤儿文献文件 | `true` |
| `ORPHAN_CLEANUP_INTERVAL` | 后台定时清理间隔（秒） | `86400`（每天） |
| `ORPHAN_TRASH_DIR` | 孤儿文件回收目录（可指定绝对路径） | `backend/data/pdf_orphan_trash` |
| `ORPHAN_TRASH_RETENTION_DAYS` | 回收目录保留天数，超过后自动物理删除 | `30` |

### CAJ 格式支持

系统支持 CAJ（中国知网专用格式）文献的解析和 AI 提取，但需要额外安装以下依赖：

#### 安装 caj2pdf

```bash
# 从 GitHub 克隆并安装
git clone https://github.com/caj2pdf/caj2pdf.git
cd caj2pdf
pip install .

# 或使用 pip 直接安装
pip install git+https://github.com/caj2pdf/caj2pdf.git
```

#### 安装 mutool（mupdf-tools）

**Windows**：
1. 下载 mupdf: https://mupdf.com/downloads/archive/mupdf-1.24.10-windows.zip
2. 解压后，将 `mupdf-1.24.10-windows/bin/mutool.exe` 所在目录添加到系统 PATH 环境变量
3. 在 PowerShell 中验证：`mutool --version`

**macOS**：
```bash
brew install mupdf
```

**Linux**：
```bash
sudo apt install mupdf mupdf-tools     # Ubuntu/Debian
sudo yum install mupdf                  # CentOS/RHEL
```

> 如果未安装以上依赖，系统对 CAJ 文件会显示「无法转换」的错误提示，其他格式（PDF、EPUB、DOCX 等）不受影响。

### 本地 Ollama 模型配置

系统支持通过 Ollama 本地部署大模型进行 AI 提取，无需联网和 API Key。不同显卡的显存直接影响可运行的模型和并发能力：

#### 显卡显存与推荐配置

| 显存容量 | 推荐模型 | 推荐并发数 (`LLM_CONCURRENCY`) | 说明 |
|----------|----------|-------------------------------|------|
| 8-12 GB | qwen2.5:7b / llama3.1:8b | 1 | 小模型，推理速度较快 |
| 16 GB | qwen2.5:14b | 1-2 | 平衡性能与精度 |
| 24 GB | qwen2.5:14b | 2-4 | 实测最优吞吐拐点（RTX 4090/5090） |
| 32 GB+ | qwen3:32b / llama3:70b (量化) | 2-4 | 大模型精度更高但推理更慢 |

> **注意**：`qwen3:32b` 在 24GB 显存下会因显存不足触发 CPU/GPU 数据交换，推理速度骤降 10-50 倍，建议改用 `qwen2.5:14b`。<br>
> 配置 `LLM_CONCURRENCY` 时必须与 Ollama 的 `OLLAMA_NUM_PARALLEL` 环境变量保持一致（Ollama 服务端默认值为 1，需在启动前设置）。

#### 启动 Ollama 服务

```bash
# 拉取推荐模型
ollama pull qwen2.5:14b

# 设置并发数并启动服务（Windows 需在系统环境变量中设置）
OLLAMA_NUM_PARALLEL=4 ollama serve

# 验证 API 可用性
curl http://localhost:11434/v1/chat/completions
```

> 启用本地模型后，需在 `.env` 文件中将 `LLM_MODEL` 设置为 `ollama:qwen2.5:14b`，或在上传/提取时在模型选择弹窗中手动选择。

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
| extraction_status | ENUM | pending / processing / done / done_no_data / failed |
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

### v1.15.0 (2026-08-22)

#### 后端核心重构：提取器模块化、分析服务拆分与统一异常体系

- **LLM 提取器模块化**：将原 `llm_extractor.py`（~2200 行）拆分为 `extraction/` 包——`llm_client.py`（LLM 调用封装、错误分类、URL 容错链）、`orchestrator.py`（提取调度主引擎）、`json_parser.py`（JSON 解析与智能截断修复）、`post_processor.py`（后处理与置信度降级）、`schema.py`（Schema 定义与校验）、`usage_tracker.py`（Token 用量追踪），各模块职责单一、可独立测试。
- **分析服务模块化**：将原 `analysis_service.py`（~3600 行）拆分为 `analysis/` 包——`basic.py`（基础统计与趋势）、`meta.py`（Meta 合并与异质性）、`infectious_disease.py`（FOI/VE/接种率）、`equity_quality.py`（公平性与质量评估）、`data_management.py`（数据管理与审核）、`export.py`（Excel 多表单导出）、`spatial.py`（空间热点/冷点）、`_common.py`（共享工具函数），各模块职责清晰、可独立维护。
- **统一异常体系**：新增 `exceptions.py`，定义 `AppError`（`code/status_code/message/details`）基类及 `LLMExtractionError`、`DocumentParseError`、`ExternalAPIError` 子类，全局异常处理器统一渲染标准 JSON 错误响应，消除散落各处的裸 `HTTPException`。

#### Prometheus 业务指标

- **自定义指标采集**：新增 `metrics.py`，采用惰性初始化（依赖缺失静默降级为 no-op），定义 `llm_extraction_total`、`llm_tokens_total`、`llm_cost_usd_total`、`extraction_duration_seconds`、`celery_task_queue_depth`、`data_point_count` 等指标，覆盖 LLM 提取、Token 消耗、费用估算、队列积压、数据点总量。
- **后台定时采集**：随 backend lifespan 启动 60 秒间隔的指标采集任务，持续更新 `data_point_count` 和 `celery_task_queue_depth`。
- **指标端点访问控制**：`/metrics` 端点通过 `metrics_access_guard` 中间件限制访问，仅在开发环境或 `METRICS_ALLOW_IPS` 白名单内可访问。
- **提取耗时与用量记录**：提取完成回调中记录 Token 用量、费用到 Prometheus 指标，提取耗时在 `extract_task.py` 中记录。

#### 报告模板管理

- **报告模板模型**：新增 `ReportTemplate` 模型（`report_template` 表），支持 `antibody_analysis` 与 `vaccination_strategy` 两类报告，通过 JSON `sections` 配置报告章节结构（标题/类型/排序/内容指引），支持 `is_default` 标记。
- **模板 CRUD 接口**：新增 `GET /report/templates`（列表，可按类型筛选）、`POST /report/templates`（创建，管理员）、`PUT /report/templates/{id}`（更新，管理员）、`DELETE /report/templates/{id}`（删除，管理员）四个接口。
- **默认模板种子**：lifespan 启动时自动检测并写入两类内置默认模板（抗体分析 5 章节 / 疫苗接种策略 4 章节），首次部署无需手动创建。
- **报告生成可选模板**：`POST /reports/generate` 和 `POST /reports/generate-vaccination-strategy` 新增 `template_id` 参数，缺省使用对应类型的默认模板。
- **前端模板管理器**：新增 `TemplateManager.tsx` 组件，支持模板列表、新建、编辑、删除、章节增删移、保存/校验；Report 页新增模板下拉选择与「管理模板」入口。

#### 前端增强

- **Meta 森林图组件**：新增 `ForestPlot.tsx`，基于 ECharts 渲染研究效应量、95% CI、合并效应菱形、I² 异质性标题、Tooltip 与响应式布局，直接对接 Meta 分析结果。
- **文献摘要列**：文献列表新增「摘要」列，用绿色标签「有」和灰色虚线标签「无」标识，支持筛选（有/无/全部）和列宽拖拽。
- **清理无文件文献**：文献工具栏新增「清理无文件文献」按钮，通过 `POST /literatures/cleanup-empty` 端点预览和删除既无文档文件又无摘要内容的空白文献记录。
- **题录导入预览确认**：`POST /literatures/import-references/preview` 接口解析题录文本并返回统计（总条数/重复/可导入），前端弹出确认对话框展示数据，用户确认后再执行实际导入。
- **QualityBadge 增强**：组件新增 `estimateGrade` 属性，展示调查级别（如国家级/省级/市级/县级），丰富质量评分卡片信息。

#### 基础设施

- **CAJ2PDF 包装脚本**：新增 `caj2pdf-wrapper` 脚本，切换到 `/opt/caj2pdf` 目录执行 `caj2pdf`，解决共享库相对路径加载问题，确保 CAJ 格式文献解析稳定。
- **Dockerfile 优化**：apt/pip 切换清华 TUNA 国内镜像源（已在 v1.14.0 基础上持续优化），构建缓存分层更精细。
- **测试矩阵扩展**：新增 `test_api_auth_matrix.py` 覆盖各 API 路由的认证鉴权矩阵测试。

#### 修改文件

| 文件 | 变更说明 |
|------|----------|
| `backend/app/core/exceptions.py` | 新增统一异常体系：`AppError` / `LLMExtractionError` / `DocumentParseError` / `ExternalAPIError` |
| `backend/app/core/extraction/` | 新增提取器模块包：`llm_client.py` / `orchestrator.py` / `json_parser.py` / `post_processor.py` / `schema.py` / `usage_tracker.py` |
| `backend/app/core/llm_extractor.py` | 提取逻辑迁移至 `extraction/` 包，保留兼容引用 |
| `backend/app/core/metrics.py` | 新增 Prometheus 业务指标（惰性初始化 + 后台采集） |
| `backend/app/services/analysis/` | 新增分析服务模块包：`basic.py` / `meta.py` / `infectious_disease.py` / `equity_quality.py` / `data_management.py` / `export.py` / `spatial.py` / `_common.py` |
| `backend/app/services/analysis_service.py` | 分析逻辑迁移至 `analysis/` 包，保留兼容引用 |
| `backend/app/services/literature_service.py` | 新增 `cleanup_empty_literatures`、import-references 预览支持 |
| `backend/app/api/v1/literature.py` | 新增 `POST /literatures/import-references/preview`、`POST /literatures/cleanup-empty`；文献列表新增 `has_abstract` 筛选 |
| `backend/app/api/v1/report.py` | 新增报告模板 CRUD 接口；`generate` 端点新增 `template_id` 参数 |
| `backend/app/api/v1/analysis.py` | 导入 `analysis/` 模块包；新增审核统计相关调用 |
| `backend/app/api/v1/extraction.py` | 导入 `extraction/` 模块包 |
| `backend/app/services/report_service.py` | 新增 `ReportTemplate` CRUD、`get_default_template`、`seed_default_templates` |
| `backend/app/services/extraction_service.py` | 导入 `extraction/` 模块包 |
| `backend/app/services/reference_parser.py` | 导入修复 |
| `backend/app/models/report_template.py` | 新增报告模板 ORM 模型 |
| `backend/app/models/__init__.py` | 注册 `ReportTemplate` |
| `backend/alembic/versions/add_report_template.py` | 数据库迁移：创建 `report_template` 表 |
| `backend/scripts/init_db.sql` | 补充 `report_template` 建表 SQL |
| `backend/scripts/caj2pdf-wrapper` | 新增 CAJ 转换包装脚本（共享库路径修复） |
| `backend/app/main.py` | lifespan 新增默认模板种子、指标后台采集；注册全局异常处理器；挂载 metrics 端点 |
| `backend/app/config.py` | 新增 Prometheus 相关配置项；APP_VERSION 升级至 1.15.0 |
| `backend/requirements.txt` | 新增 `prometheus-client` 依赖 |
| `backend/Dockerfile` | 构建优化（持续 TUNA 镜像源） |
| `backend/tests/test_api_auth_matrix.py` | 新增 API 认证鉴权矩阵测试 |
| `backend/tests/test_analysis_advanced.py` | 适配模块化重构 |
| `backend/tests/test_llm_extractor.py` / test_p0_* / test_p1_3_* | 适配模块化重构 |
| `frontend/src/components/ForestPlot.tsx` | 新增 Meta 森林图组件（ECharts 渲染） |
| `frontend/src/components/TemplateManager.tsx` | 新增报告模板管理器（列表/新建/编辑/删除/章节管理） |
| `frontend/src/components/QualityBadge.tsx` | 增强：新增 `estimateGrade` 调查级别展示 |
| `frontend/src/pages/Report.tsx` | 集成模板下拉选择与模板管理器入口 |
| `frontend/src/pages/Literature.tsx` | 新增摘要列（筛选/排序）、清理无文件文献按钮、题录导入预览确认 |
| `frontend/src/pages/LiteratureDetail.tsx` | 模板集成 |
| `frontend/src/pages/Analysis.tsx` | 分析模块重构适配 |
| `frontend/src/pages/PubmedSearch.tsx` | 导入预览确认适配 |
| `frontend/src/services/literature.ts` | 新增 `cleanupEmpty` / `previewImportReferences` |
| `frontend/src/services/api.ts` | 适配模块化 |
| `frontend/src/services/map.ts` | 新增 `listTemplates` / `createTemplate` / `updateTemplate` / `deleteTemplate` |
| `frontend/src/types/index.ts` | 新增 `ReportTemplate` / `CleanupEmptyResult` 类型 |
| `frontend/package.json` | 依赖更新 |
| `frontend/vite.config.ts` | 构建优化配置 |
| `docker-compose.yml` | 服务配置优化 |
| `README.md` | 核心功能补充报告模板/森林图/摘要列/清理空文献；新增 v1.15.0 变更日志 |

### v1.16.0 (2026-08-22)

#### 文献回收站（软删除）

- **软删除机制**：文献删除改为软删除（设置 `deleted_at` 时间戳），将文献移入回收站而非直接物理删除，保留文件，30 天内可随时还原。
- **回收站管理**：新增回收站列表（`GET /literatures/trash`，支持分页/关键词搜索）、还原（`POST /literatures/trash/{id}/restore`）、永久删除（`DELETE /literatures/trash/{id}`，含文件）、清空回收站（`POST /literatures/trash/empty`，支持按保留天数过滤）接口。
- **后台自动清理**：随 backend lifespan 启动回收站自动清理任务，每 86400 秒检查一次，永久删除超过 30 天的软删除文献及其关联文件。
- **前端回收站弹窗**：文献管理工具栏新增「回收站」按钮，弹出 Modal 展示回收站文献列表，支持搜索、分页、逐篇还原/永久删除、一键清空超过 30 天的回收站内容。
- **批量删除适配**：批量删除操作同样改为软删除，将选中文献移入回收站，统一受回收站管理约束。

#### 修改文件

| 文件 | 变更说明 |
|------|----------|
| `backend/app/models/literature.py` | Literature 模型新增 `deleted_at` / `deleted_by` 字段 |
| `backend/app/schemas/literature.py` | LiteratureResponse 新增 `deleted_at` / `deleted_by` 序列化字段 |
| `backend/scripts/init_db.sql` | 补充 `deleted_at` / `deleted_by` 字段 DDL |
| `backend/alembic/versions/add_soft_delete.py` | 数据库迁移：添加软删除字段与索引 |
| `backend/app/services/literature_service.py` | 新增 `list_trash_literatures` / `restore_literature` / `permanently_delete_literature` / `empty_trash` / `permanently_delete_all_trash` / `_trash_cleanup_loop`；修改 `delete_literature` / `batch_delete_literatures` 为软删除；`list_literature` 查询过滤已删除记录 |
| `backend/app/api/v1/literature.py` | 新增回收站 CRUD 接口：`GET /literatures/trash` / `POST /literatures/trash/{id}/restore` / `DELETE /literatures/trash/{id}` / `POST /literatures/trash/empty` |
| `backend/app/main.py` | lifespan 新增回收站自动清理后台任务 |
| `backend/app/config.py` | APP_VERSION 升级至 1.16.0 |
| `frontend/src/services/literature.ts` | 新增回收站 API：`listTrash` / `restoreLiterature` / `permanentlyDeleteLiterature` / `emptyTrash` |
| `frontend/src/pages/Literature.tsx` | 新增回收站弹窗（列表/搜索/还原/永久删除/清空）、工具栏回收站按钮 |
| `README.md` | 核心功能补充回收站/软删除；新增 v1.16.0 变更日志 |

### v1.17.0 (2026-08-22)

#### AnyDoc 文档解析增强（firecrawl/anydoc）

- **AnyDoc 解析器**：新增 `anydoc_parser.py`，基于 firecrawl/anydoc（Rust 实现，Python 绑定），支持 docx/pptx/xlsx/epub/html/txt/pdf 等格式毫秒级转 GFM Markdown，天然输出高质量表格，直接提升 LLM 数据提取准确率。
- **渐进式接入**：新增 `ENABLE_ANYDOC` 配置项（默认关闭），零回归保证；开启后文本层 PDF 优先用 AnyDoc 解析，失败/超时自动回退现有策略解析器（PyMuPDF/pdfplumber/OCR/MinerU），对扫描件无影响。
- **表格提取增强**：pdf_table_parser 的 `extract_tables_markdown` 接入 AnyDoc 分支，AnyDoc 的 GFM 表格直接作为 tables_md 注入 LLM，成功结果写入现有 B6 哈希缓存，避免重复解析。
- **降级链完整**：AnyDoc 失败/超时/不可用 → 依次回退：现有策略解析器 → PDF 的 OCR/MinerU；所有回退路径打印日志区分解析来源（`[解析路径=AnyDoc]` / `[回退=策略解析器]` / `[AnyDoc] 解析失败，回退现有解析链`）。
- **下载固化**：Dockerfile 三处 pip 安装步骤改用 BuildKit 缓存挂载 `--mount=type=cache,target=/root/.cache/pip`，并去掉 `PIP_NO_CACHE_DIR=1`，首次全量下载后下次重建直接复用，避免反复下载。

#### 修改文件

| 文件 | 变更说明 |
|------|----------|
| `backend/app/core/processors/anydoc_parser.py` | 新增 AnyDoc 解析器：惰性加载、`is_available` / `supports` / `to_markdown_bytes`（线程+超时降级） / `contains_table` |
| `backend/app/core/document_parser.py` | `extract_text` 开头增加 AnyDoc 分支，成功打 `[解析路径=AnyDoc]`，失败打 `[回退=策略解析器]` |
| `backend/app/core/pdf_table_parser.py` | `extract_tables_markdown` 接入 AnyDoc 分支，GFM 表格直供，成功写入 B6 缓存 |
| `backend/app/config.py` | 新增 `ENABLE_ANYDOC` / `ANYDOC_TIMEOUT` 配置项；APP_VERSION 升级至 1.17.0 |
| `backend/requirements.txt` | 新增 `firecrawl-anydoc>=0.1.9` |
| `backend/Dockerfile` | pip 安装改用 BuildKit 缓存挂载，去除 `PIP_NO_CACHE_DIR=1`，固化下载 |
| `backend/tests/test_anydoc_parser.py` | 新增 AnyDoc 离线单测（mock 绑定成功/失败/零回归/回退等 16 条） |
| `README.md` | 核心功能补充 AnyDoc 增强解析；新增 v1.17.0 变更日志 |

### v1.14.0 (2026-08-21)

#### 数据点审核工作流增强：审核意见、审核人/审核时间追踪与审核统计

- **数据点审核意见字段**：`data_point` 表新增 `review_comment`（Text，可空）字段，每条数据点可留存审核意见批注；前端数据点行内编辑支持填写/修改审核意见。
- **审核人与审核时间自动记录**：`data_point` 表新增 `reviewer_id`（UUID，外键 → `user.id`，用户删除时置空而非级联删数据点）与 `reviewed_at`（DateTime，带时区）。通过/驳回/行内审核变动时，自动写入当前操作者身份与审核时间，数据点表格新增「审核人」「审核时间」列展示。
- **批量驳回强制填写意见**：`POST /literatures/{id}/extraction/dispute` 的 `comment` 参数必填（空则 400），前端批量驳回模态框同步强制校验；批量通过 `confirm` 的 `comment` 为可选。新增 `confirmDataPoints` / `disputeDataPoints` 前端服务，批量审批改走专门端点（旧 `note` 字段保留兼容）。
- **审核统计仪表盘**：新增 `GET /analysis/review-stats` 端点，按**疾病/审核人**聚合已审核数据点的审核量、通过量、驳回量、通过率、平均审核时间；前端 Analysis 页新增「审核统计」Tab（KPI 卡片 + 按审核人/按疾病表格）。
- **抽取结果透出审核字段**：`GET /literatures/{id}/extraction` 序列化补充 `review_comment / reviewer_id / reviewer_name / reviewed_at`，供前端列表与详情展示。
- **数据库迁移**：新增 Alembic 迁移 `add_data_point_review_fields`，为 `data_point` 增加上述三字段、外键与索引；`init_db.sql` 同步补齐列定义。

#### Docker 构建加速（国内镜像源）

- **apt 切换清华 TUNA 源**：Dockerfile 在安装系统依赖前后将 `deb.debian.org` 替换为 `mirrors.tuna.tsinghua.edu.cn`（含后端基础层与 MinerU 运行时层），apt 包下载速度明显提升。
- **pip 切换清华 TUNA 源**：Dockerfile 通过 `pip config set global.index-url` 统一指向 `pypi.tuna.tsinghua.edu.cn/simple`，Python 依赖安装提速。

#### 修改文件

| 文件 | 变更说明 |
|------|----------|
| `backend/alembic/versions/add_data_point_review_fields.py` | 数据库迁移：`data_point` 新增 `review_comment/reviewer_id/reviewed_at` + 外键 + 索引 |
| `backend/app/models/data_point.py` | 模型同步新增审核字段 |
| `backend/scripts/init_db.sql` | `data_point` 建表 SQL 补齐审核列 |
| `backend/app/api/v1/extraction.py` | PUT 支持 `review_comment`；批量通过/驳回支持 `comment`（驳回必填）；审核变动自动写 `reviewer_id/reviewed_at` |
| `backend/app/services/extraction_service.py` | 新增 `review_data_points`（审核写入）、`get_review_stats`（审核统计）；抽取结果序列化补审核字段 |
| `backend/app/api/v1/analysis.py` | 新增 `GET /analysis/review-stats` 端点 |
| `frontend/src/services/literature.ts` | 新增 `confirmDataPoints` / `disputeDataPoints` |
| `frontend/src/services/map.ts` | 新增 `fetchReviewStats` |
| `frontend/src/pages/LiteratureDetail.tsx` | 编辑支持审核意见；批量驳回强制填意见并改走 confirm/dispute 端点；表格新增审核人/审核时间/审核意见列 |
| `frontend/src/pages/Analysis.tsx` | 新增「审核统计」Tab（KPI + 按审核人/疾病表格） |
| `frontend/src/types/index.ts` | DataPoint 补审核字段；新增 `ReviewStatsResult` 等类型 |
| `backend/Dockerfile` | apt / pip 切换清华 TUNA 国内镜像源加速构建 |
| `backend/app/config.py` | APP_VERSION 升级至 1.14.0 |
| `README.md` | 核心功能补充审核意见/审核统计；新增 v1.14.0 变更日志 |

### v1.13.1 (2026-08-20)

#### 批量提取支持无 PDF 的题录文献

- **批量提取双源校验修复**：`POST /literatures/extraction/batch` 此前对所有无 `file_path` 的文献一律跳过（提示"无关联文件，无法提取"），与单篇提取的双源逻辑不一致。现已放宽校验——**有 PDF 走全文提取，无 PDF 但有摘要的题录文献直接用摘要提取**，仅当既无 PDF 也无摘要时才跳过。文献管理模块现在可以一次批量提取多篇无 PDF 的题录导入文献。

#### 文献列表分页与列宽稳定性

- **去除虚拟滚动导致的列宽跳动**：此前 `virtual={pageSize > 20}` 使每页 50/100 条时启用虚拟滚动，其列宽按 `column.width` 严格渲染不拉伸，而 20 条/页的普通模式会拉伸列填满表格宽度，两种渲染模式交替导致各列宽度异常变化。已移除虚拟滚动，所有 pageSize 下渲染模式一致，列宽稳定。
- **修复 antd 分页警告**：切换每页条数时清空旧 dataSource，避免残留数据与新 pageSize 不匹配触发 `dataSource length is less than pagination.total but larger than pagination.pageSize` 警告。
- **分页总数稳定**：去掉加载中 `total` 临时取 `items.length` 的写法，直接用真实总数，消除切换页时的总数跳动。

#### 修改文件

| 文件 | 变更说明 |
|------|----------|
| `backend/app/api/v1/extraction.py` | 批量提取校验放宽：无 PDF 但有摘要的文献可提交（与单篇提取双源逻辑一致） |
| `frontend/src/pages/Literature.tsx` | 移除虚拟滚动、切换分页时清空旧数据、分页 total 用真实总数 |
| `backend/app/config.py` | APP_VERSION 升级至 1.13.1 |
| `README.md` | 新增 v1.13.1 变更日志 |

### v1.13.0 (2026-08-20)

#### 题录批量导入与统一解析器

- **统一题录解析器**：新增 `reference_parser.py`，支持 **7 种题录格式**自动识别与解析——RIS、EndNote(.enw)、PubMed 文本（PMID: 摘要）、PubMed「Save → RIS」、WoS 纯文本、WoS CSV/Excel、读秀/超星（duxiu）。`parse_references(text, fmt="auto")` 按内容特征自动探测格式（正则 `^TY\s*-` / `^%0` 等），统一输出 `title/authors/journal/year/doi/abstract/pmid/keywords/source` 字段，缺失字段安全回退空串。
- **多行字段续行拼接**：修复 RIS/EndNote 解析仅取首行问题，摘要(AB)、标题(TI)、期刊(JO) 等多行字段自动跨行拼接；PubMed 文本解析修正记录头切分逻辑（仅识别从 1 起的连续递增序号，识别 `©` 版权块），支持不定长标签（PMID/TI/AB/FAU/JT/DP/LID/PMC/AD 等）并提取 PMID、URL、DOI、PMCID、机构；WoS 纯文本与 CSV 提取 DE 关键词字段。
- **来源映射与查重**：`POST /literatures/import-references` 接收 `ref_text`（+ `fmt=auto` 显式指定），按统一字段构造文献入库；`source_db` 取解析来源（pubmed/cnki/wos/duxiu），`source_id` 取 PMID（为空则用 DOI）用于查重，标题为空自动跳过，返回 `imported/skipped/total/errors`。
- **前端导入入口**：PubMed 检索页「纳入数据库」新增来源下拉（自动识别 / PubMed / 知网 / Web of Science），支持读取本地上传题录文件后调用导入接口，展示导入/跳过结果。

#### 文献批量删除

- **后端接口**：新增 `POST /literatures/batch-delete`，接收 `literature_ids` 列表，复用现有删除逻辑批量删除文献及其关联文件/数据点，自动跳过不存在的记录，返回成功删除数量（幂等）。
- **前端入口**：文献列表工具栏新增危险样式「批量删除」按钮，勾选多篇后弹出二次确认，成功后清空选中并刷新列表。

#### 无 PDF 摘要提取

- **提取输入双源支持**：`extract_task.py` / `extraction_service.py` 放宽校验——无 PDF 但有摘要（`abstract` 非空）的文献直接用摘要文本作为 LLM 提取输入（此前无关联文件直接报错），PDF 文献仍走全文提取；仅当既无文件也无摘要时才判定无法提取。批量提取接口同步受益，可对纯题录导入（无 PDF）的文献触发提取。

#### 文献详情摘要展示

- 前端文献详情页新增「摘要」标签页展示完整摘要（多行题录导入文献也可查看），并调整行距提升可读性。

#### 修改文件

| 文件 | 变更说明 |
|------|----------|
| `backend/app/services/reference_parser.py` | 新增统一题录解析器：`parse_references` 自动探测 + RIS/ENW/PubMed/PubMed-RIS/WoS/WoS-CSV/读秀 子解析器 |
| `backend/app/api/v1/literature.py` | 新增 `POST /literatures/import-references`（题录导入，按 PMID/DOI 查重）、`POST /literatures/batch-delete`（批量删除） |
| `backend/app/api/v1/router.py` | 文献路由更新 |
| `backend/app/tasks/extract_task.py` | 提取输入双源支持：无 PDF 时用摘要提取 |
| `backend/app/services/extraction_service.py` | 校验放宽：无 PDF 但有摘要可提取 |
| `backend/app/config.py` | APP_VERSION 升级至 1.13.0 |
| `frontend/src/pages/PubmedSearch.tsx` | 纳入数据库来源下拉（自动/PubMed/知网/WoS）+ 题录文件导入入口 |
| `frontend/src/pages/Literature.tsx` | 工具栏新增「批量删除」按钮（二次确认） |
| `frontend/src/services/literature.ts` | 新增 `batchDeleteLiteratures` 服务 |
| `frontend/src/pages/LiteratureDetail.tsx` | 新增「摘要」标签页展示完整摘要 |
| `README.md` | 核心功能/API 一览补充题录导入与批量删除；新增 v1.13.0 变更日志 |

### v1.12.0 (2026-08-20)

#### PubMed 检索页 · 多源文献检索

- **PubMed 检索页（前端新增）**：侧边栏新增「PubMed 检索」入口，支持关键词检索 PubMed（NCBI E-utilities esearch + esummary）、勾选结果后一键「纳入数据库」（esummary 取元数据写入文献库）与「下载 PDF」（经 Europe PMC 查询开放获取全文直链并下载到本地目录），操作期间按钮 loading、无勾选时禁用。
- **多源文献检索服务**：新增 Crossref / OpenAlex / Europe PMC 三个异步检索服务（`crossref_service.py` / `openalex_service.py` / `europepmc_service.py`），统一输出 `{items, total, page, page_size}` 结构，item 字段固定为 `id/source/title/authors/year/journal/doi/abstract/oa_pdf_url`，缺失字段安全回退空值。
- **统一多源检索接口**：新增 `GET /pubmed/search/multi?source=&q=&page=&page_size=`，按 `source`（crossref / openalex / europepmc，缺省 crossref）分发到对应服务，不支持的来源返回 400。
- **检索来源下拉切换**：PubMed 检索页搜索框旁新增来源下拉（PubMed / Crossref / OpenAlex / Europe PMC，默认 PubMed）；选择非 PubMed 来源时自动调用 `/pubmed/search/multi`，结果表格新增「来源」列，原有 PubMed 检索、纳入/下载逻辑不受影响。
- **OA PDF 下载配置**：新增 `PDF_DOWNLOAD_DIR` 环境变量指定下载目录，未配置时回退到 `LOCAL_STORAGE_DIR`。

#### 安全加固

- **URL 抓取 SSRF 防护**：`url_fetcher.py` 新增 `_host_is_safe` 校验，拒绝访问内网 / 回环 / 链路本地地址（hostname 解析出任一不安全 IP 即拒绝）；`follow_redirects` 改为 `False`，防止 302 跳转绕过安检。
- **「打开文件夹」接口权限收紧**：仅管理员可调用，且仅在 `APP_ENV == "development"` 开发环境启用，生产环境返回 403。

#### 视觉多模态提取增强

- **视觉提取器骨架**：新增 `vl_extractor.py`，调用本地视觉模型（默认 `qwen3.8:27b`）直接读 PDF 页面图片、按 JSON Schema 输出 JSON；`LLMExtractor.extract_visual` 复用现有 `_parse_json` / `_post_process` 后处理逻辑，并对每个数据点做 grounding 溯源（回写 `is_grounded` / `source_char_start/end`）。
- **扫描页视觉增强**：PyMuPDF 解析扫描页时额外渲染页面图片（dpi=150）调用视觉提取器增强（OCR 之外的补充），失败静默忽略不影响主流程。

#### 修改文件

| 文件 | 变更说明 |
|------|----------|
| `backend/app/api/v1/pubmed.py` | 新增 PubMed 检索代理：`GET /pubmed/search`、`GET /pubmed/abstract/{pmid}`、`POST /pubmed/import`、`POST /pubmed/download-pdf`、`GET /pubmed/search/multi` |
| `backend/app/services/pubmed_service.py` | 新增 PubMed 检索服务（NCBI E-utilities esearch+esummary+efetch） |
| `backend/app/services/pubmed_pdf.py` | 新增 OA PDF 直链查询（Europe PMC REST）与下载 |
| `backend/app/services/crossref_service.py` | 新增 Crossref 检索服务 |
| `backend/app/services/openalex_service.py` | 新增 OpenAlex 检索服务 |
| `backend/app/services/europepmc_service.py` | 新增 Europe PMC 检索服务 |
| `backend/app/core/vl_extractor.py` | 新增视觉多模态提取器（读页面图片 + JSON Schema 强约束） |
| `backend/app/core/llm_extractor.py` | 新增 `extract_visual`（复用解析/后处理 + grounding 溯源回写） |
| `backend/app/core/pdf_parser.py` | 扫描页额外渲染图片调视觉提取器增强；明确 MinerU/PyMuPDF/OCR 路径日志 |
| `backend/app/core/url_fetcher.py` | URL 抓取 SSRF 防护（`_host_is_safe` + 关闭重定向） |
| `backend/app/api/v1/literature.py` | 「打开文件夹」接口增加管理员鉴权 + 仅开发环境 |
| `backend/app/api/v1/router.py` | 注册 pubmed 路由 |
| `backend/app/config.py` | 新增 `PDF_DOWNLOAD_DIR`；APP_VERSION 升级至 1.12.0 |
| `frontend/src/pages/PubmedSearch.tsx` | 新增 PubMed 检索页（检索/纳入/下载 + 来源下拉切换） |
| `frontend/src/App.tsx` | 注册 `/pubmed` 路由 |
| `frontend/src/layouts/MainLayout.tsx` | 侧边栏新增「PubMed 检索」菜单项 |
| `frontend/src/i18n/zh.json` / `en.json` | 新增 `nav.pubmed` 文案 |
| `README.md` | 核心功能补充 PubMed 检索；API 一览补充 pubmed 接口；新增 v1.12.0 变更日志 |

### v1.11.1 (2026-08-20)

#### worker 容器 NVIDIA GPU 透传

- **GPU 加速 MinerU 解析**：docker-compose 为 worker 服务新增 `deploy.resources.reservations` NVIDIA GPU 透传（`driver: nvidia` / `count: all` / `capabilities: [gpu]`），MinerU 文档解析与 torch 推理从 CPU 模式切换为 GPU 加速。修复此前 MinerU 检测到 `vram=1GB` 以 CPU 模式运行的性能问题。
- **前置条件**：宿主机需安装 NVIDIA Container Toolkit（Windows 在 WSL2 中安装后重启 Docker），未安装时该配置会被忽略，worker 回退 CPU 模式。
- **实测**：RTX 5090 Laptop（24GB）下容器内 `nvidia-smi` / `torch.cuda.is_available()` 均正常识别，50KB 3 页 PDF 解析成功输出结构化 Markdown，推理全程使用 GPU（显存占用约 23GB）。

#### 修改文件

| 文件 | 变更说明 |
|------|----------|
| `docker-compose.yml` | worker 服务新增 NVIDIA GPU 透传 `deploy.resources.reservations` |
| `backend/app/config.py` | APP_VERSION 升级至 1.11.1 |
| `README.md` | 环境要求补充 GPU + NVIDIA Container Toolkit 说明；新增 v1.11.1 变更日志 |

### v1.11.0 (2026-08-19)

#### 孤儿文件定时清理与回收

- **孤儿文件清理服务**：新增 `file_cleanup_service.py`，后台定时扫描 `backend/data/pdfs`，识别并清理已不在数据库中的残留文献文件。覆盖两类遗留场景——文献删除/合并后文件未随之一并删除（如合并保留 source 的 `file_path` 时 target 原文件成为孤儿）、提取文本 `{文献id}.txt` 对应文献已不存在。
- **回收目录安全策略**：清理时孤儿文件先移入回收目录（默认 `backend/data/pdf_orphan_trash`），保留 `ORPHAN_TRASH_RETENTION_DAYS`（默认 30）天后自动物理删除，误删可找回，不会立即释放空间造成不可恢复损失。
- **后台自动定时**：backend 启动时随 lifespan 启动清理循环（与文件夹监控同款模式），按 `ORPHAN_CLEANUP_INTERVAL`（默认每天一次）自动执行，可配置 `ORPHAN_CLEANUP_ENABLED=false` 关闭。
- **手动触发接口（管理员）**：`GET /literatures/cleanup-orphan-files/preview` 预览孤儿文件（不执行任何移动）；`POST /literatures/cleanup-orphan-files` 立即执行清理 + 清理过期回收文件。
- **识别机制**：以 `literature.file_path` 提取的文件名 + `{id}.txt` 模式 + 存在的文献 id 集合三重判定，兼容 Windows 绝对路径 / 容器相对路径两种存储形态。

#### 修改文件

| 文件 | 变更说明 |
|------|----------|
| `backend/app/services/file_cleanup_service.py` | 新增孤儿文件清理服务：`scan_orphan_files` / `cleanup_orphan_files` / `purge_trash` / `_cleanup_loop` |
| `backend/app/api/v1/literature.py` | 新增管理员接口：`GET /literatures/cleanup-orphan-files/preview`、`POST /literatures/cleanup-orphan-files` |
| `backend/app/main.py` | lifespan 启动/停止孤儿文件清理后台循环（受 `ORPHAN_CLEANUP_ENABLED` 控制） |
| `backend/app/config.py` | 新增 `ORPHAN_CLEANUP_ENABLED` / `ORPHAN_CLEANUP_INTERVAL` / `ORPHAN_TRASH_DIR` / `ORPHAN_TRASH_RETENTION_DAYS`；APP_VERSION 升级至 1.11.0 |
| `.env.example` | 补充孤儿文件清理配置说明 |

### v1.10.1 (2026-08-19)

#### 提取稳定性增强 · MinerU 子进程隔离 · 模型缓存本地化

- **LLM 错误分类机制**：新增 `_classify_llm_error` 对 LLM 调用异常分类（`connection_error` / `auth_error` / `rate_limit` / `json_error` / `other`，沿异常链收集消息），为不同错误类型制定差异化处理策略，日志诊断更清晰。
- **URL 候选链自动切换**：新增 `_build_url_chain` 构建「主地址 + 备用地址 + 自动探测地址」多级 URL 链；主地址连接失败时自动切换下一个候选，应对 WSL 重启导致 Ollama 网关 IP 漂移、远程 API 短暂不可达等场景。新增环境变量 `LLM_FALLBACK_BASE_URLS`（备用地址，逗号分隔）。
- **连接类错误快速重试**：连接类错误采用短退避（15s/30s/45s）跨候选 URL 快速重试，不消耗 token；非连接错误保留原有 60s/120s/240s 退避重试。新增 `LLM_CONNECT_RETRIES` 控制快速重试次数（默认 2）。
- **Celery 任务状态管理优化**：连接类错误重试期间保持文献 `processing` 状态，仅在快速重试耗尽时才标记 `failed`，避免瞬时网络故障误判失败；失败历史记录 `error_message` 带错误类型前缀便于排查。
- **MinerU 子进程隔离执行**：修复 MinerU 在 Celery prefork（daemonic）进程中无法运行的问题（内部 spawn 子进程触发 `daemonic processes are not allowed to have children`，静默回退 PyMuPDF）。新增独立子进程入口 `app/core/mineru_worker.py`，通过 `subprocess.Popen` 隔离执行（`start_new_session` 独立进程组 + 超时整组清理），MinerU 崩溃/超时不再拖垮 worker 主进程。
- **MinerU 模型缓存本地化**：docker-compose 将容器内 `/root/.cache/modelscope` 挂载到宿主机 `./backend/data/mineru_cache`，容器重建后无需重新下载模型（约 2.2G），避免反复下载。
- **SDK 兼容性修复**：修复 OpenAI SDK `client.base_url` 为 `URL` 对象而非字符串导致 `_is_ollama_model` 调用 `.lower()` 抛 `AttributeError` 的问题（先转字符串再判定）。

#### 修改文件

| 文件 | 变更说明 |
|------|----------|
| `backend/app/core/llm_extractor.py` | 新增 `_classify_llm_error` 错误分类、`_build_url_chain` URL 链构建；重构 `_call_llm_api` / `_fallback_http_call` 支持 URL 链切换与短退避重试；修复 `client.base_url` URL 对象 `.lower()` 报错 |
| `backend/app/tasks/extract_task.py` | 引入错误分类；连接类错误保持 `processing` 状态短退避快速重试，耗尽才标记 `failed`；失败历史带错误类型前缀 |
| `backend/app/core/pdf_parser.py` | MinerU 解析改为子进程隔离执行（`subprocess.Popen` 调用 `mineru_worker`，超时整组清理） |
| `backend/app/core/mineru_worker.py` | 新增 MinerU 解析独立子进程入口（非 daemonic，可正常派生进程，随 worker 镜像打包） |
| `backend/app/config.py` | 新增 `LLM_FALLBACK_BASE_URLS` / `LLM_CONNECT_RETRIES`；APP_VERSION 升级至 1.10.1 |
| `docker-compose.yml` | worker 新增 `./backend/data/mineru_cache:/root/.cache/modelscope` 挂载（MinerU 模型缓存持久化） |
| `.env.example` | 补充 `LLM_FALLBACK_BASE_URLS` / `LLM_CONNECT_RETRIES` 配置说明 |

### v1.10.0 (2026-08-18)

#### 本地模型配置 · 模型选择统一 · 系统信息与后台日志 · Celery 日志落盘

- **本地模型配置功能（系统设置新增标签页）**：新增 `local_model_config` 数据库表与 Alembic 迁移（含默认种子：Qwen3.8:27B、Qwen3:32B、Qwen2.5 系列、DeepSeek R1、Llama、Mistral、GLM 等）；系统设置新增「本地模型配置」标签页（`LocalModelManager` 组件），管理员可增删改查本地 Ollama 模型（显示名称 / 模型名 / 备注 / 启用状态），模型名唯一约束，删除后从下拉候选项即时生效。
- **模型选择统一**：后端 `/models` 改为优先从 `local_model_config` 表读取启用项（表为空时回退静态列表）；前端新增 `modelOptions.ts` 统一构建模型候选项（默认配置 + 静态远程 + 动态本地 + 自定义本地）；文献管理 AI 提取、文件夹监控自动提取等模块从硬编码静态 `MODEL_OPTIONS` 迁移为调用后端 `/models` API，与报告生成保持同一数据源——各功能模块的本地模型候选项始终一致；本地模型值统一带 `ollama:` 前缀，兼容原有 vendor 判定逻辑，不影响默认模型记忆与自定义本地模型。
- **系统信息标签页**：新增 `/system/info` 接口（版本号、运行环境、功能特性、日志目录、仓库地址），前端「系统信息」标签页动态渲染，仅需维护后端一处即可同步更新。
- **后台日志标签页**：新增 `/system/logs`（文件列表）与 `/system/logs/content`（尾部内容读取，支持 `file/lines/level/keyword` 过滤、防路径穿越）接口；前端「后台日志」标签页支持日志文件切换、级别筛选、关键字搜索、自动滚动到底部（向上滚动自动暂停）；日志由 loguru 按日写入 `backend/logs/`（大小轮转 + 7 天保留），docker-compose 挂载卷确保容器重启不丢失，前端可直接排查 AI 提取问题，无需再 `docker logs`。
- **Celery 日志落盘修复**：连接 `setup_logging` 信号阻止 Celery 默认日志配置覆盖 loguru 拦截器；连接 `worker_process_init` 信号在 ForkPoolWorker 子进程重建 loguru `enqueue` sink，AI 提取子进程日志不再因线程丢失而丢失，全部落盘可查。
- **容器时区统一**：backend / worker 容器设置 `TZ: Asia/Shanghai`，日志时间与系统时间（东八区）一致，不再相差 8 小时。
- **文献管理交互优化**：「操作」列「详情」文字按钮改为 FileTextOutlined 图标按钮（带 Tooltip）；列宽整体压缩（1395→1005px），标题/作者/期刊列 `ellipsis` 省略，操作列 `Space size={4}` 收紧并允许换行——默认无横向滚动即可完整展示全部 10 列。
- **远程模型配置保持**：远程模型 CRUD（`/models/remote`）与 API Key 加密存储逻辑不受影响，与本地模型配置在系统设置中并列展示。

#### 修改文件

| 文件 | 变更说明 |
|------|----------|
| `backend/app/models/local_model_config.py` | 新增本地模型配置模型（name/model_name 唯一/is_active/description） |
| `backend/alembic/versions/add_local_model_config.py` | 新增迁移：建表 + 默认种子本地模型 |
| `backend/app/models/__init__.py` | 注册 `LocalModelConfig` |
| `backend/app/schemas/model_config.py` | 新增 `LocalModelConfigCreate/Update/Response`（UUID→str 校验器） |
| `backend/app/api/v1/model_config.py` | `/models` 改读本地配置表（空表回退）；新增 `/models/local` CRUD（管理员，IntegrityError 去重） |
| `backend/app/api/v1/system.py` | 新增系统信息 + 后台日志接口（`/system/info`、`/system/logs`、`/system/logs/content`） |
| `backend/app/api/v1/router.py` | 挂载 system 路由 |
| `backend/app/tasks/celery_app.py` | 连接 `setup_logging` / `worker_process_init` 信号修复 Celery 日志落盘 |
| `docker-compose.yml` | backend/worker 设置 `TZ: Asia/Shanghai`；挂载 `./backend/logs` 卷 |
| `frontend/src/utils/modelOptions.ts` | 新增统一模型候选项构建器（默认+静态远程+动态本地+自定义） |
| `frontend/src/components/LocalModelManager.tsx` | 新增本地模型管理组件（增删改查/启用开关） |
| `frontend/src/services/system.ts` | 新增系统信息/日志接口封装 |
| `frontend/src/services/map.ts` | 新增 `listLocalModels/createLocalModel/updateLocalModel/deleteLocalModel` |
| `frontend/src/types/index.ts` | 新增 `LocalModelConfig` 类型 |
| `frontend/src/pages/Settings.tsx` / `Settings.css` | 新增「本地模型配置」「后台日志」「系统信息」标签页及样式 |
| `frontend/src/pages/Literature.tsx` | 模型候选项改用 `buildModelOptions`；列宽压缩 + ellipsis + 详情图标按钮 + `scroll.x=1045` |
| `frontend/src/pages/FolderMonitor.tsx` | 模型候选项改用 `buildModelOptions` |
| `frontend/src/pages/LiteratureDetail.tsx` | 模型候选与默认模型提示统一 |
| `backend/app/config.py` | APP_VERSION 升级至 1.10.0 |
| `.gitignore` | 补充临时脚本/调试文件忽略规则 |

### v1.9.0 (2026-08-18)

#### 文献全列排序筛选 · MinerU 增强解析固化 · 提取健壮性与安全加固

- **文献列表全列排序与筛选**：标题 / 作者模糊筛选、创建时间范围筛选、文档格式下拉筛选（PDF/CAJ/EPUB/DOCX/PPTX/XLSX/TXT/HTML/URL）；文档格式排序按派生格式名分组、无文件记录恒排最后；筛选状态本地缓存，刷新不丢失，不影响其他功能。
- **文献文件下载与关联替换**：新增带 JWT 认证的 blob 下载（避免裸跳转 401），自动解析服务器文件名；支持「修改关联文件」替换文献已关联的本地文档。
- **MinerU 增强 PDF 解析固化**：新增 `requirements-mineru.txt` 锁定版本（`mineru[pipeline]==3.4.5` + torch 2.13 + transformers 4.57 等），Dockerfile 新增 `INSTALL_MINERU` 构建参数（仅 worker 容器安装，backend 不装避免 torch 拖慢 API）；适配 MinerU 3.x 输出结构（官方 `union_make` 生成结构化 Markdown，保留表格/公式）；新增 `MINERU_PARSE_TIMEOUT` 超时保护，超时自动回退 PyMuPDF。
- **PDF 解析结果缓存**：按文件字节 sha256 缓存解析文本（`parse_cache.py`），命中直接复用，避免重复触发最慢的 MinerU / OCR。
- **OCR 并发与超时保护**：扫描页 OCR 改为并发执行（复用 `LLM_CONCURRENCY` 限流），单页 OCR 超时隔离、不再阻塞整篇。
- **Ollama 连接修复与强约束**：容器内 worker 的 `localhost`/`127.0.0.1:11434` 自动改写为配置的可达主机（如 WSL 网关 IP）；本地 Ollama 走原生 JSON Schema 结构化输出强约束（顶层 `format` 字段）；前端新增 Qwen3.8:27B 本地模型选项。
- **关键数值回验**：提取出的 `positivity_rate` / `gmc_value` / `sample_size` 必须在原文中可定位（多形态匹配），否则自动降级低置信，减少幻觉数据。
- **Celery 异步修复**：worker 任务改用常驻事件循环的 `run_async`（`async_runner.py`），修复 `asyncio.run` 复用 asyncpg 连接池失败问题。
- **安全加固**：移除 JWT 硬编码回退密钥（生产环境必须显式配置 `SECRET_KEY`，开发环境启动随机生成）；Swagger/Redoc 文档仅开发环境开放。
- **提取状态约束修复**：`literature.extraction_status` 校验补充 `done_no_data` 状态（`init_db.sql` 与数据库同步），修复无数据文献提取时报 CheckViolation 并无限重试的问题。
- **前端体验**：管理员菜单权限从 localStorage 同步初始化（避免延迟闪现）；Spin 加载提示适配新版 AntD（补充子元素避免控制台警告）。

#### 修改文件

| 文件 | 变更说明 |
|------|----------|
| `frontend/src/pages/Literature.tsx` | 全列排序/筛选（标题/作者/创建时间/文档格式）、下载按钮、修改关联文件 |
| `frontend/src/services/literature.ts` | 新增 `downloadLiteratureFile`（JWT blob 下载，解析 Content-Disposition 文件名） |
| `backend/app/services/literature_service.py` | 列表接口新增 title/authors/created_start/created_end/file_format 筛选；文档格式 CASE 派生排序（NULL 恒排最后） |
| `backend/app/api/v1/literature.py` | 列表筛选参数透传；溯源文本路径统一 `LOCAL_STORAGE_DIR`；「打开所在文件夹」支持 WSL/root 场景（runuser + interop socket） |
| `backend/app/core/pdf_parser.py` | MinerU 3.x `union_make` 适配 + 超时保护 + 解析缓存 + OCR 并发化 |
| `backend/app/core/parse_cache.py` | 新增 PDF 解析结果缓存（sha256 key） |
| `backend/app/core/ocr_service.py` | 新增 `ocr_tesseract_with_timeout` 超时包装 |
| `backend/app/core/llm_extractor.py` | `_normalize_ollama_url` 容器内可达主机改写；`EXTRACTION_JSON_SCHEMA` 原生结构化输出强约束 |
| `backend/app/core/extraction_grounding.py` | 关键数值回验 `validate_numeric_grounding`（未定位降级低置信） |
| `backend/app/tasks/async_runner.py` | 新增 Celery worker 常驻事件循环调度 `run_async` |
| `backend/app/tasks/extract_task.py` / `quality_task.py` | 改用 `run_async` 替代 `asyncio.run` |
| `backend/app/core/security.py` | 移除 JWT 硬编码回退密钥，生产环境强制显式配置 |
| `backend/app/main.py` | Swagger/Redoc 仅开发环境开放 |
| `backend/requirements-mineru.txt` | 新增 MinerU 增强解析依赖锁（仅 worker 安装） |
| `backend/Dockerfile` | 新增 `INSTALL_MINERU` 构建参数 + libgl1/libglib2.0-0 系统库 |
| `docker-compose.yml` | worker 服务传入 `INSTALL_MINERU: "true"` 构建参数 |
| `backend/scripts/init_db.sql` | `extraction_status` 约束补充 `done_no_data` |
| `backend/app/config.py` | 新增 `MINERU_PARSE_TIMEOUT`；APP_VERSION 升级至 1.9.0 |
| `frontend/src/layouts/MainLayout.tsx` | 管理员权限从 storage 同步初始化 |
| `frontend/src/utils/constants.ts` | 新增 Qwen3.8:27B 本地 Ollama 模型选项 |
| `frontend/src/App.tsx` / `FilePreview.tsx` / `LiteratureDetail.tsx` | Spin 加载提示适配新版 AntD |
| `frontend/package-lock.json` | 依赖锁更新 |

### v1.8.0 (2026-08-17)

#### 数据质量分级 · 抗原图谱 · 分析快照 · 统计引擎全面升级

- **数据点质量评分体系**：新增 `quality_service.py`，每个数据点按六项信号自动打分（样本量 30 / 抽样方式 25 / 检测方法 15 / 人群代表性 15 / 调查级别 10 / 溯源置信度 5，满分 100），输出 0-100 分 + A/B/C 三级（A≥75、B 50–74、C<50）及调查级别（estimate_grade）；审核通过后经 Celery 异步幂等重算，前端 QualityBadge 在 Tooltip 展开六项得分明细。
- **纯函数统计引擎 `stats_engine.py`**：统一实现趋势/区域/年龄/汇总端点的全局置信区间（CI）计算——Wilson / Clopper-Pearson 二项 CI、样本量加权率、几何均数 GMC（对数域 CI）、双比例检验、惩罚样条年龄曲线 P(a)+95% 置信带、年龄别 FOI λ(a)，以及 Meta 合并、Cochran-Armitage 趋势检验、直接标准化率（标准人口归一）、Moran's I / Getis-Ord Gi*、出生队列聚合等。
- **分析快照与引用**：新增 `snapshot_service.py`，每个 `/analysis/*` 请求自动生成带数据指纹（data_hash）的快照 token，同参数去重复用；`/analysis/snapshot/{token}` 原样重放缓存响应，`/analysis/snapshot/{token}/citation` 导出 **GBT7714 / BibTeX** 引用文本，确保分析结果可复现、可溯源。
- **统一方法学脚注**：新增 `methodology.py`，服务层与报告生成共用 `build_methodology_note()` 生成中文方法学段落，挂载到所有分析响应 `meta.methodology_note`，报告正文自动拼接「方法学」小节。
- **新增分析模块与接口**：省间公平性（基尼/变异系数）、数据质量评估与全量重算 rescore、目标达成追踪、血清阳性率-年龄曲线、出生队列、同省多研究 Meta 合并（I²/Q/τ²）、多文献 Meta 分析（森林图/漏斗图、group_by 亚组 + Q_between）、检测方法异质性、省级空间热点/冷点（Moran's I + Gi*）、免疫屏障模拟、审核状态统计；报告导出 Excel 附带统计方法附录。
- **数据驱动常量表**：新增 `backend/app/core/reference_data/`，含中国 2020 标准人口、省份邻接矩阵、疾病解读注释（计划免疫史分期提示）的 JSON，均带 version 字段。
- **抗原图谱**：新增 `titer_table` 表与 `antigenic_cartography.py`（metric MDS 降维，参考 Smith 2004 / racmacs），前端新增独立「抗原图谱」页面（`/antigenic-map`）交互查看假想 2D 制图，图谱页含标签显隐开关。
- **数据库迁移**：新增 `add_dp_quality_fields`（data_point 质量字段 + 索引）、`add_analysis_snapshot`、`add_titer_table` 三个迁移脚本。
- **前端重构**：新增 `chartBuilders.ts` 图表配置工厂、`ChartWithSnapshot`/`QualityBadge`/`SnapshotCitation` 组件，分析页新增公平性/数据质量/目标达成/高级分析/证据合成/出生队列等 Tab，文献详情页展示质量分级徽标与引用。
- **测试**：新增 `test_stats_engine`、`test_quality_service`、`test_snapshot_service`、`test_meta_analysis`、`test_antigenic_cartography`、`test_analysis_*` 等单元测试，统计核心均含已知答案解析用例。

#### 修改文件

| 文件 | 变更说明 |
|------|----------|
| `backend/app/core/stats_engine.py` | 新增全局 CI/统计纯函数引擎 |
| `backend/app/core/antigenic_cartography.py` | 新增抗原制图引擎（metric MDS） |
| `backend/app/core/methodology.py` | 新增统一方法学脚注生成 |
| `backend/app/core/reference_data/*.json` | 新增标准人口/省份邻接矩阵/疾病注释常量表 |
| `backend/app/services/quality_service.py` | 新增数据点质量评分（0-100 分 + A/B/C） |
| `backend/app/services/snapshot_service.py` | 新增分析快照（数据指纹/去重/重放/引用） |
| `backend/app/models/data_point.py` | 新增 quality_score/quality_grade/estimate_grade 字段 |
| `backend/app/models/analysis_snapshot.py` | 新增分析快照模型 |
| `backend/app/models/titer_table.py` | 新增滴度矩阵模型 |
| `backend/app/api/v1/analysis.py` | 新增 equity/quality/goal/age-curve/birth-cohort/meta-analysis/spatial-hotspots/assay/simulate/snapshot/titer-tables/antigenic-map 等接口 |
| `backend/app/services/analysis_service.py` | 新增对应分析函数，接入 CI 引擎与方法学脚注 |
| `backend/app/services/report_service.py` | 报告正文自动拼接方法学脚注 |
| `backend/app/tasks/quality_task.py` | 新增审核通过后异步质量打分任务 |
| `backend/alembic/versions/add_dp_quality_fields.py` 等 | 新增 3 个数据库迁移 |
| `backend/requirements.txt` | 新增 statsmodels 等依赖 |
| `frontend/src/pages/Analysis.tsx` | 新增公平性/质量/目标达成/高级分析/证据合成/出生队列 Tab |
| `frontend/src/pages/AntigenicMap.tsx` | 新增抗原图谱页面 |
| `frontend/src/utils/chartBuilders.ts` | 新增图表配置工厂 |
| `frontend/src/components/` | 新增 ChartWithSnapshot / QualityBadge / SnapshotCitation / AgeCurveChart |
| `frontend/src/layouts/MainLayout.tsx` | 新增「抗原图谱」导航项 |
| `backend/tests/` | 新增 stats_engine / quality / snapshot / meta / antigenic 等测试 |
| `backend/app/config.py` | APP_VERSION 升级至 1.8.0 |

### v1.7.5 (2026-08-14)

#### 文献管理交互优化与统计口径修复

- **PDF 预览「文件不存在」修复**：新增 `_resolve_literature_file` 文件路径解析函数，兼容数据库中存储的 Windows 绝对路径与容器内路径两种形态，解决后端运行环境与文件存储路径不一致时预览 404、无法显示本地已有文件的问题。
- **文献列表支持列宽拖拽调整**：引入 `react-resizable`，所有列均可手动拖拽调整宽度，可将标题、作者等列拖宽以完整展示内容。
- **文献列表列内容自动换行**：移除标题列省略号截断，各列在列宽不足时自动换行显示（含长英文/URL 断行），配合拖拽调整可完整查看全部信息。
- **新增「打开所在文件夹」功能**：操作列为有文档的文献新增文件夹按钮，调用后端接口在 Windows 资源管理器 / macOS Finder / Linux 桌面上打开文件所在文件夹并选中该文件。
- **GMC 几何均值口径修正**：`get_age_stratify` 与 `get_summary` 中 GMC（几何平均浓度）由算术平均改为几何均值计算（`geometric_mean_with_ci`），并补充 95% 置信区间字段。
- **免疫屏障阳性率聚合口径统一**：`get_immune_barrier_assessment` 的总体与逐年趋势均改用逆方差加权阳性率（`_calc_weighted_positivity`），与其他分析函数口径保持一致，并补充置信区间字段。

#### 修改文件

| 文件 | 变更说明 |
|------|----------|
| `backend/app/api/v1/literature.py` | 新增 `_resolve_literature_file` 路径解析 + `POST /literatures/{id}/open-folder` 打开文件夹端点 |
| `backend/app/services/analysis_service.py` | GMC 改几何均值计算、免疫屏障加权阳性率口径统一、补充置信区间 |
| `backend/app/config.py` | APP_VERSION 升级至 1.7.5 |
| `backend/tests/test_analysis_gmc_fix.py` | 新增 GMC 几何均值修复测试 |
| `frontend/package.json` | 新增依赖 `react-resizable` |
| `frontend/src/pages/Literature.tsx` | 列宽拖拽、列内容自动换行、操作列新增打开文件夹按钮 |
| `frontend/src/index.css` | 列宽拖拽手柄样式 + 单元格自动换行样式 |
| `frontend/src/services/literature.ts` | 新增 `openLiteratureFolder` 接口调用 |

### v1.7.4 (2026-08-14)

#### 统计分析框架与审核状态监控

- **新增统计方法库 `stats.py`**：实现 8 个纯 Python 统计算法（几何均数 GMC 及其 95% CI、加权阳性率（逆方差合并）与 Wilson CI、加权线性趋势、基尼系数、变异系数、LOWESS 平滑、固定/随机效应逆方差 Meta 合并与 I² 异质性、可靠性分级），并配套 44 个单元测试（含已知答案校验，如 `geometric_mean([1,10,100])≈10`）。
- **新增 7 个分析接口**：省间公平性分析（基尼/变异系数）、数据质量评估（A/B/C/D 分级）、目标达成追踪（对比 GOAL_THRESHOLDS/HIT 缺口）、年龄-抗体曲线（LOWESS 平滑+拐点）、同省多研究 Meta 合并（I²/Q/τ²）、检测方法异质性、免疫屏障模拟（FOI 反推 R0/HIT+假设覆盖）。
- **新增审核状态统计接口**：`/analysis/coverage-review` 按疾病维度统计点数/样本量/审核通过率（approved/pending/rejected），默认按待审核数降序。
- **导出增加「统计方法附录」sheet**：`/analysis/export` 新增第 6 个工作表，以「方法-公式-说明」三列说明加权率/GMC/95%CI/基尼/meta 合并等 10 种统计方法的算法。
- **前端「数据覆盖度」页新增审核状态监控**：新增审核状态统计卡片（概览 KPI + 堆叠柱状图 + 明细表格，含疾病筛选），并直接展示无需额外操作。
- **修复 Meta 合并 I² 低估 Bug**：`inverse_variance_meta` 对百分数单位的 CI 做 `>1 → /100` 归一，避免方差虚高导致 I² 被系统性低估。

#### 修改文件

| 文件 | 变更说明 |
|------|----------|
| `backend/app/core/stats.py` | 新增 8 个统计算法（GMC/加权率/基尼/Meta 合并等） |
| `backend/app/core/goal_thresholds.py` | 新增各病 HIT 保护目标阈值常量 |
| `backend/app/services/analysis_service.py` | 新增 fair/quality/goal/age/meta/assay/simulate/coverage-review 分析函数 |
| `backend/app/api/v1/analysis.py` | 新增 8 个分析路由 + `/analysis/export` 统计方法附录 sheet |
| `backend/app/schemas/analysis.py` | 新增 Coverage 相关 Pydantic 模型 |
| `backend/app/config.py` | APP_VERSION 升级至 1.7.4 |
| `backend/tests/test_stats.py` | 统计函数单元测试（含已知答案校验） |
| `backend/tests/test_analysis_advanced.py` | 新增分析 service 函数测试（26 条） |
| `frontend/src/components/` | 新增 KpiCards/EquityRadar/QualityPanel/TrendWithCI/AgeSmoothChart/TopBottomRank/GoalTrackingChart/SimulationPanel/CoverageReviewTable/CoverageReviewChart |
| `frontend/src/pages/Analysis.tsx` | 新增公平性/数据质量/目标达成/高级分析 tab + 覆盖度页审核状态监控 |
| `frontend/src/services/map.ts` | 新增对应接口调用函数 |
| `frontend/src/types/index.ts` | 新增对应响应类型定义 |

### v1.7.3 (2026-08-13)

#### 汇总分析与高级图表修复

- **省份筛选支持多选**：分析页省份筛选改为多选，可同时选择多个省份进行对比分析；后端分析接口（趋势/区域对比/年龄分层/FOI/疫苗/数据点等）支持逗号分隔的多省份参数。
- **修复高级图表无法使用的问题**：雷达图、箱线图原本需要 ≥3 个省份数据，但省份筛选为单选导致永远无法满足。现支持多选省份，且未选省份时默认展示全部省份，图表始终有足够的省份数据。
- **优化图表空态提示**：根据实际数据加载情况与省份选择数，给出更明确的提示（如"仅1个省份的数据不足，请多选几个省份或清除省份筛选"），避免误导用户。

#### 修改文件

| 文件 | 变更说明 |
|------|----------|
| `backend/app/services/analysis_service.py` | `_build_base_query` 支持逗号分隔多省份筛选 |
| `frontend/src/components/ProvinceSelector.tsx` | 支持单选/多选双模式（TS 泛型，不影响地图页单选用法） |
| `frontend/src/pages/Analysis.tsx` | 省份筛选改为多选，查询/导出参数传递逗号分隔多省份 |
| `frontend/src/components/AdvancedCharts.tsx` | 接收多省份，未选省份默认展示全部，优化空态提示 |

### v1.7.2 (2026-08-13)

#### 任务调度统一

- **统一使用 Celery 异步任务调度**：文献 AI 提取从进程内 `asyncio.create_task` 后台任务迁移为 Celery 任务队列调度，由独立 worker 进程消费，避免 API 进程阻塞与任务丢失。提取任务支持失败自动重试（指数退避，最多 3 次）。
- **新增 Celery worker 服务**：`docker-compose.yml` 新增 `worker` 服务，复用后端镜像，以 `--pool=prefork --concurrency=1` 启动，与本地 Ollama 单并发模型配置对齐。
- **提取保留审核数据开关适配 Celery**：批量/单选重新提取时的 `clear_existing_data` 参数已接入 Celery 任务，关闭时仅删除待审核/已驳回数据点，保留已通过数据点。

#### 前端数据缓存优化

- **新增前端 GET 请求缓存层**：新增 `apiCache.ts` 轻量缓存模块，以「URL + 排序后的 query 参数」为 key，支持 TTL（默认 60s）与并发去重（同一 key 的并发请求共享 Promise，避免重复发请求）。
- **地图/分析接口接入缓存**：省份数据、可用年份、人群选项、汇总等静态接口用 2 分钟 TTL；趋势、地区对比、年龄分层、免疫屏障、数据缺口、FOI/VE 等筛选接口用 30 秒 TTL，大幅减少筛选切换时的重复请求。
- **数据变更自动清除缓存**：数据点审核（通过/驳回）、编辑、手动新增后自动清除地图与分析接口缓存，保证地图/分析展示数据实时准确，避免因缓存导致数据过期。

#### 版本号统一

- **单一版本源**：新增 `APP_VERSION` 配置项（当前 1.7.2），`main.py` 的 OpenAPI version 与 `/health` 端点均引用该值，消除此前 main.py（1.7.1）与 /health（1.0.0）版本号不一致的问题，升级版本只需修改一处。

#### 数据库连接池调优

- **显式配置连接池**：为异步数据库引擎配置 `pool_size=20`、`max_overflow=10`、`pool_timeout=30s`、`pool_pre_ping=True`、`pool_recycle=1800s`，提升高并发下的连接复用与稳定性，避免默认连接池在高负载下不足或使用失效连接。

#### 修改文件

| 文件 | 变更说明 |
|------|----------|
| `backend/app/services/extraction_service.py` | 提取触发从 `asyncio.create_task` 改为 `process_literature.delay()` 提交 Celery 任务 |
| `backend/app/tasks/extract_task.py` | Celery 任务 `process_literature` 新增 `clear_existing_data` 参数 |
| `docker-compose.yml` | 新增 `worker` 服务（Celery worker，concurrency=1） |
| `frontend/src/lib/apiCache.ts` | 新增前端 GET 请求缓存层（TTL + 并发去重 + 手动失效） |
| `frontend/src/services/map.ts` | 地图/分析只读接口接入缓存，新增 `clearMapApiCache`/`clearAnalysisApiCache` |
| `frontend/src/pages/LiteratureDetail.tsx` | 数据点审核/编辑/新增后清除地图与分析缓存 |
| `backend/app/config.py` | 新增 `APP_VERSION` 单一版本源 |
| `backend/app/main.py` | OpenAPI version 引用 `settings.APP_VERSION` |
| `backend/app/api/v1/router.py` | `/health` 端点 version 引用 `settings.APP_VERSION` |
| `backend/app/models/base.py` | 显式配置数据库连接池（pool_size/max_overflow/pool_timeout/pool_pre_ping/pool_recycle） |

#### 启动说明

统一使用 Celery 后，需同时启动 API 服务与 worker：

```bash
# Docker 一键启动（含 worker）
docker compose up -d

# 或手动启动
uvicorn app.main:app --host 0.0.0.0 --port 8000
celery -A app.tasks.celery_app worker --loglevel=info --concurrency=1
```

### v1.7.1 (2026-08-13)

#### 优化与修复

- **修复前端构建类型错误**：新增 `pdfjs-dist.d.ts` 类型声明文件，解决 `pdfjs-dist/build/pdf` 模块的 TypeScript 类型缺失问题，前端构建恢复正常。
- **提取历史增加「重新提取」按钮**：提取历史弹窗每行记录末尾新增操作按钮，点击后自动预填该次使用的模型、关闭历史弹窗、打开提取设置弹窗，方便快速重试失败的提取。
- **文献列表增加提取状态筛选**：筛选工具栏新增提取状态下拉选择器（待处理/进行中/已完成/完成（无数据）/失败），支持按提取状态精确筛选文献列表，筛选状态在页面切换间自动缓存恢复。
- **完善 CAJ 安装文档与 Ollama 显存配置指南**：README 新增 `### CAJ 格式支持` 章节，详细说明 caj2pdf 和 mutool 的安装步骤（Windows/macOS/Linux 三平台）；新增 `### 本地 Ollama 模型配置` 章节，包含显卡显存推荐配置表（8GB-32GB+）。

#### 修改文件

| 文件 | 变更说明 |
|------|----------|
| `frontend/src/pdfjs-dist.d.ts` | 新增 pdfjs-dist/build/pdf 模块类型声明 |
| `frontend/src/pages/LiteratureDetail.tsx` | 提取历史弹窗新增「重新提取」按钮 |
| `frontend/src/pages/Literature.tsx` | 筛选工具栏新增提取状态下拉选择器，支持状态缓存与恢复 |
| `backend/app/services/literature_service.py` | `list_literature` 新增 `extraction_status` 筛选参数 |
| `backend/app/api/v1/literature.py` | 文献列表 API 新增 `extraction_status` 查询参数 |
| `README.md` | 新增 CAJ 格式支持、Ollama 显存配置指南章节 |

### v1.7.0 (2026-08-13)

#### 新功能

- **AI 提取历史记录**：每次 AI 提取完成后自动记录完整历史（提取时间、使用模型、状态、数据点数量、Token 用量、费用、错误信息），文献详情页新增「提取历史」按钮，弹窗表格展示历次提取记录，便于追溯每次提取的详细结果。
- **提取状态精细化**：新增 `done_no_data` 提取状态，区分「解读成功但未提取到数据点」（橙色/完成（无数据））和「解读成功且提取到数据点」（绿色/已完成），状态显式区分为三种情况：
  - `failed` — 文献无法阅读或解读失败（红色）
  - `done_no_data` — 解读成功但未提取到相关数据（橙色）
  - `done` — 解读成功且提取到抗体数据点（绿色）
- **手动合并文献**：文献列表工具栏新增「合并选中」按钮，支持用户手动勾选 2 篇文献后弹出合并对话框，逐字段选择保留源/目标文献的数据，处理数据点冲突，合并后自动迁移数据点并删除源文献。

#### 新增接口

- `GET /literatures/{literature_id}/extraction/history`：获取文献的历次 AI 提取历史记录（含模型、状态、数据点数、Token 用量、费用、错误信息等）。

#### 新增文件

| 文件 | 说明 |
|------|------|
| `backend/app/models/extraction_history.py` | ExtractionHistory 数据模型（记录历次提取历史） |
| `backend/alembic/versions/e1c07278aa97_add_extraction_history_and_done_no_data.py` | 数据库迁移：创建 extraction_history 表 + 更新 extraction_status 约束 |

#### 修改文件

| 文件 | 变更说明 |
|------|----------|
| `backend/app/models/literature.py` | extraction_status 新增 `done_no_data` 枚举值，扩展 CheckConstraint |
| `backend/app/tasks/extract_task.py` | 提取完成后根据数据点数量设置 `done`/`done_no_data`/`failed`，并写入提取历史记录 |
| `backend/app/services/extraction_service.py` | 新增 `get_extraction_history()` 服务函数 |
| `backend/app/api/v1/extraction.py` | 新增提取历史查询 API 端点 |
| `frontend/src/utils/constants.ts` | `EXTRACTION_STATUS_META` 新增 `done_no_data` 状态（橙色/完成（无数据）） |
| `frontend/src/services/literature.ts` | 新增 `ExtractionHistoryItem` 类型和 `getExtractionHistory()` API 函数 |
| `frontend/src/pages/LiteratureDetail.tsx` | 新增「提取历史」按钮和弹窗，以表格展示历次提取记录 |
| `frontend/src/pages/Literature.tsx` | 工具栏新增「合并选中」按钮，支持手动勾选 2 篇文献合并 |

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
