# 抗体地图 (Antibody Map)

血清抗体流行病学数据可视化与分析平台

![平台预览](docs/screenshots/dashboard.png)

## 简介

抗体地图是一个面向公共卫生和流行病学领域的**血清抗体水平数据管理、可视化与分析平台**。支持上传流行病学文献，通过 LLM 自动提取结构化的血清抗体数据点，经人工审核后在交互式中国地图上可视化展示，并支持多维度数据分析、空间统计和 AI 报告生成。

## 核心功能

- **文献管理** — PDF/CAJ/DOCX/EPUB/PPTX/XLSX/TXT/HTML 上传，URL 导入，RIS/EndNote/PubMed/WoS 题录批量导入，PDF 在线预览，重复检测与合并，回收站
- **AI 数据提取** — LLM 自动提取血清阳性率/GMC 等数据点，支持 DeepSeek/OpenAI/Qwen/本地 Ollama，长文档分块并行，精确字符级溯源，强 Schema 校验，历次提取历史可追溯（模型/耗时/Token/费用）；**追加模式安全**：强制 append 禁用 replace，防止误删既有数据点
- **数据审核** — 人工审核（通过/驳回），行内编辑，批量操作，「LLM 原始 vs 人工修改」diff 留痕
- **地图可视化** — 全国/省/市/区县四级交互式抗体热力地图，时间序列动画，热点分析
- **数据分析** — 逐年趋势、区域对比、分区对比、年龄分层、FOI 感染力、VE 疫苗效果、Meta 分析（森林图/漏斗图）、空间热点/冷点（Moran's I + Getis-Ord Gi*）、免疫屏障模拟与达标概率、出生队列、省间公平性
- **流行特征（流行病学 + 病原学）** — 发病率/发病人数/死亡率/死亡数聚合展示；独立病原学监测表存储基因型/血清型/谱系/变异位点/检出率，与血清抗体数据互补；PathogenPanel 嵌入文献详情
- **多域数据扩展** — 单一 data_point Schema 覆盖 immunology / epidemiology / pathogen 三大领域，病原学字段与 disease 解耦
- **抗原图谱** — HI/VNT/ELISA 滴度矩阵 metric MDS 降维，2D 抗原图谱
- **知识图谱** — 13 种实体 + 18 种关系的多维语义网络，计算式推导 + LLM 抽取（特性开关），ECharts 力导向图可视化，实体搜索、路径推理、智能咨询问答
- **报告生成** — 抗体分析 / 疫苗接种策略 / 免疫屏障评估三类报告，后台异步生成，支持在线编辑与 Markdown/Word/PDF 下载
- **PDF 解析增强** — MinerU（GPU 加速）+ AnyDoc（Rust，毫秒级转 GFM Markdown）+ pdf-inspector（损坏修复），自动回退
- **数据库备份与还原** — pg_dump 逻辑备份，上传还原（前置备份 + 失败回滚），跨设备数据迁移
- **文献批量选中与编组** — 支持从 TXT/CSV 导入匹配（UUID 精确 / 标题-作者模糊匹配），批量打 Tag 分组，便于大规模文献筛选与分析
- **提取历史一致性审计** — 管理员可一键扫描 extraction_history 声明的数据点数 vs data_point 实际行数，自动标记并修正不一致记录
- **文件夹监控 / PubMed 检索 / AI 准确度自测** — 文件夹自动监控导入、PubMed 检索批量纳入、合成文献自测多模型提取准确度

> 完整功能细节见 [核心功能文档](https://antibody-map.readthedocs.io/zh-cn/latest/guide/features/)，版本演进见 [变更日志](https://antibody-map.readthedocs.io/zh-cn/latest/changelog/)。

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

# 或手动启动 — CPU（默认）：
docker compose up -d
# GPU（追加 overlay）：
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d
# 已有数据卷复用（本地开发保留 postgres 数据）：
docker compose -f docker-compose.yml -f docker-compose.reuse.yml up -d
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