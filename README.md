# 抗体地图 (Antibody Map)

血清抗体流行病学数据可视化与分析平台

![平台预览](docs/screenshots/dashboard.png)

## 简介

抗体地图是一个面向公共卫生和流行病学领域的**血清抗体水平数据管理、可视化与分析平台**。支持上传流行病学文献，通过 LLM 自动提取结构化的血清抗体数据点，经人工审核后在交互式中国地图上可视化展示，并支持多维度数据分析、空间统计和 AI 报告生成。

## 核心功能

- **文献管理** — 上传 PDF/CAJ/EPUB/DOCX/PPTX/XLSX/TXT/HTML 文献，URL 导入，题录批量导入（RIS/EndNote/PubMed/WoS/读秀超星），元数据管理，重复检测与合并，回收站软删除，**导入历史追踪**（基于 pdf_hash 文件指纹识别重复导入）
- **AI 数据提取** — LLM 自动提取血清阳性率/GMC 等数据点，支持 DeepSeek/OpenAI/Qwen/本地 Ollama，长文档分块并行提取，精确字符级溯源，强 Schema 校验；管线加固（API Key 加密存储、提示注入防护、token 预算/日配额/并发上限、幂等写库、状态超时自动回收）
- **数据审核** — 人工审核（通过/驳回），审核意见留痕，行内编辑，手动新增数据点；审核队列按置信度与质量分排序（低置信低质量优先），滴度矩阵审核衔接，「LLM 原始输出 vs 人工修改」diff 留痕
- **地图可视化** — 全国/省级/市级交互式抗体热力地图，时间序列动画
- **数据分析** — 逐年趋势、区域对比、年龄分层、FOI 感染力分析、VE 疫苗效果、Meta 分析（森林图/漏斗图）、空间热点/冷点（Moran's I + Getis-Ord Gi*）、免疫屏障模拟、出生队列分析、省间公平性
- **抗原图谱** — HI/VNT/ELISA 滴度矩阵的 metric MDS 降维，2D 抗原图谱
- **报告生成** — LLM 生成**抗体分析报告**、**疫苗接种策略报告**、**免疫屏障评估报告**，支持在线编辑和下载
- **PDF 解析增强** — **pdf-inspector**（Rust 实现，自动修复损坏 PDF 尾部结构后提取）+ **AnyDoc**（Rust 实现，毫秒级转 GFM Markdown），失败自动回退现有解析链
- **数据库备份与还原** — 系统设置集成 pg_dump 逻辑备份，备份文件浏览下载，上传还原（含前置备份保险与失败自动回滚），支持跨设备数据迁移
- **导入进度条** — PubMed 检索结果与题录文件分批导入，进度条从 0 到 100 逐步推进，汇总后写一条导入日志

详情见 **[完整文档](https://antibody-map.readthedocs.io/)**。

## 技术栈

| 层级 | 技术 |
|------|------|
| 前端 | React 18 + TypeScript, Vite 6, Ant Design 5, ECharts 5, pdfjs-dist |
| 后端 | Python 3.10+, FastAPI, SQLAlchemy 2.0 (async), Celery + Redis |
| 统计 | NumPy, SciPy, statsmodels, scikit-learn (esda, libpysal) |
| 数据库 | PostgreSQL 15, MinIO 对象存储 |
| AI/LLM | OpenAI SDK 兼容协议，支持 DeepSeek / OpenAI / Qwen / 本地 Ollama |
| 文档解析 | 策略模式注册表：PyMuPDF + pdfplumber / python-docx / python-pptx / openpyxl / ebooklib / bs4 / caj2pdf；**MinerU 增强**（GPU 加速）；**AnyDoc 增强**（Rust 实现） |
| OCR | Tesseract OCR (中文/英文) + 百度 OCR 云端回退 |
| 运维 | Docker Compose (PostgreSQL + Redis + MinIO) |

## 快速开始

### 前置条件

- [Docker Desktop](https://www.docker.com/products/docker-desktop/)（WSL2 模式，Windows）或 Docker Compose（Linux/macOS）
- NVIDIA GPU（可选，用于 MinerU 文档解析加速；无 GPU 自动退回 CPU 模式）

### 启动

```bash
git clone https://github.com/liuxiong714/antibody_map.git
cd antibody_map
cp .env.example .env       # Windows: copy .env.example .env
```

编辑 `.env` 文件，填入必要的配置项（`LLM_API_KEY`、`POSTGRES_PASSWORD`、`SECRET_KEY` 等）。

```bash
# 一键启动（自动探测 GPU，有 GPU 则加速，无 GPU 则 CPU）
bash docker-start.sh

# 或手动启动
# 有 GPU 时（默认）：
docker compose up -d
# 无 GPU 时：
docker compose -f docker-compose.yml -f docker-compose.cpu.yml up -d
```

启动后访问 `http://localhost:8080` 即可进入登录页面。

### 停止

```bash
bash docker-start.sh down
# 或
docker compose down
```

## 文档

- [快速开始](https://antibody-map.readthedocs.io/zh-cn/latest/guide/getting-started/)
- [核心功能](https://antibody-map.readthedocs.io/zh-cn/latest/guide/features/)
- [项目架构](https://antibody-map.readthedocs.io/zh-cn/latest/guide/architecture/)
- [配置参考](https://antibody-map.readthedocs.io/zh-cn/latest/guide/configuration/)
- [部署指南](https://antibody-map.readthedocs.io/zh-cn/latest/guide/deployment/)
- [变更日志](https://antibody-map.readthedocs.io/zh-cn/latest/changelog/)

## License

MIT

## 作者

**Liu Xiong** - [liuxiong714@163.com](mailto:liuxiong714@163.com)