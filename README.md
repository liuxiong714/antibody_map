# 抗体地图 (Antibody Map)

血清抗体流行病学数据可视化与分析平台

![平台预览](docs/screenshots/dashboard.png)

## 简介

抗体地图是一个面向公共卫生和流行病学领域的**血清抗体水平数据管理、可视化与分析平台**。支持上传流行病学文献，通过 LLM 自动提取结构化的血清抗体数据点，经人工审核后在交互式中国地图上可视化展示，并支持多维度数据分析、空间统计和 AI 报告生成。

## 核心功能

### 端到端工作流

![学术主题工作流](docs/screenshots/workflow-academic-navy.svg)

五步闭环：**文献与数据导入 → AI 自动提取 → 人工审核修订 → 地图可视化与多维分析 → 报告生成与导出**。完整功能细节见 [核心功能文档](docs/guide/features.md)。

上图为高保真学术主题设计稿，重点刻画五个阶段的关键能力：

| 阶段 | 输入 / 模型 / 输出 | 核心说明 |
|------|---------------------|----------|
| ① 文献与数据导入 | PDF · CAJ · DOCX · XLSX · URL | 支持主流学术文献格式 + CNKI CAJ 专属解析器，URL 批量抓取；TXT/CSV 导入匹配 + 批量 Tag 编组 |
| ② AI 自动提取 | Qwen3.8 · DeepSeek · OpenAI · Muse · Ollama | **策略模式模型注册表**：按任务自动路由最佳模型，GPU 可用 MinerU / AnyDoc 加速文档解析；**追加模式安全**（禁用 replace）+ enable_thinking 思维链开关 |
| ③ 人工审核修订 | 通过 / 驳回 / 编辑 / 补充 | 多人协作审核工作台，版本留痕，字段级差异对比；提取历史 vs 数据点一致性审计（自动修正 `[DP_DROPPED]`） |
| ④ 地图可视化与多维分析 | 知识图谱 · 空间统计 · Meta 分析 · 抗原图谱 | 六类分析端点 + **免疫屏障 R_eff NGM 残差法**（真正 R_eff < 1 判据）+ 多情景批量模拟 × VE 疫苗效率 + 参考常量 JSON 化（WHO HIT / R0 / NIP 全覆盖 citation） |
| ⑤ 报告生成与导出 | Word · PDF · Markdown | 可配置报告模板，自动引用 HIT 阈值三族 citation、R_eff 补种缺口等定量结论 |

> 平台价值：**把文献数据变成结构化数据，把数据变成地图和分析结果，帮助更快完成研判与报告。**

> 版本演进见 [变更日志](docs/changelog.md)。

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

#### Windows 安装：磁盘路径与空间预留（必读）

本项目基于 Docker Compose（WSL2 模式），磁盘占用分布在**四个不同位置**，单一克隆目录映射无法全部挪到 D 盘。下表帮你提前规划：

| 组件 | 默认位置 | 占用规模 | 是否可改到 D 盘 |
|------|----------|----------|------------------|
| ① WSL2 发行版（Ubuntu） | `C:\Users\<你>\AppData\Local\Packages\Canonical...Ubuntu-22.04` | 首次 ~8 GB，含 Postgres/Redis/MinIO 数据 | ⚠️ 需用 `wsl --export` + `wsl --import` 迁移发行版 |
| ② Docker Desktop 镜像层 | `C:\Users\<你>\AppData\Local\Docker\wsl` | ~3-5 GB（全部镜像下载完） | ✅ Docker Desktop Settings → Resources → Disk image location |
| ③ Ollama 模型缓存 | Windows 原生：`C:\Users\<你>\.ollama`<br>WSL 内：`~/.ollama` | **每模型 2-31 GB**（qwen3.8:27b 约 15 GB） | ✅ Windows 设系统环境变量 `OLLAMA_MODELS=D:\ollama`；WSL 内 `export OLLAMA_MODELS=/mnt/d/ollama` |
| ④ 项目代码 + MinIO 数据卷 | 由你 `git clone` 路径决定 | ~300 MB 代码 + 用户上传文献 | ✅ 直接 clone 到 D 盘即可 |

**首次安装建议预留空间**：
- 不跑 GPU 加速（仅 CPU）：**D 盘至少 15 GB**（发行版迁移 + 镜像 + 1 个中等模型）
- 跑 MinerU GPU 解析：**D 盘至少 25 GB**（额外 MinerU 模型 ~8 GB）
- 额外模型（如 qwen3.8:27b）：每加一个 +15 GB

**典型安装耗时参考**（首次，网络正常）：

| 步骤 | 耗时 | 说明 |
|------|------|------|
| Docker Desktop + WSL2 安装 | 30-60 分钟 | 取决于下载速度，期间可能需要重启 |
| `docker compose up -d` 拉镜像 | 10-30 分钟 | 7 个镜像，总计约 3 GB |
| `ollama pull qwen3.8:27b` | 10-20 分钟 | 仅需首次下载，后续启动秒级 |

**三步骤把 Docker + WSL2 挪到 D 盘**（避免 C 盘暴增）：

```powershell
# 步骤 1：Docker Desktop 镜像目录改到 D 盘
# Settings → Resources → Disk image location → D:\docker-data
# 改完点 Apply & Restart

# 步骤 2：WSL2 发行版整体迁移到 D 盘
wsl --shutdown
wsl --export Ubuntu-22.04 D:\wsl\Ubuntu-22.04.tar
wsl --unregister Ubuntu-22.04
wsl --import Ubuntu-22.04 D:\wsl\Ubuntu-22.04 D:\wsl\Ubuntu-22.04.tar --version 2
del D:\wsl\Ubuntu-22.04.tar
```

> 💡 如果不想折腾上述路径迁移，**TraeCode / Docker Desktop 一键式安装**（保持默认 C 盘位置）也是可行的——对于小型测试场景（1-2 个模型、几十篇文献），C 盘 20 GB 预留即可。只有模型数量多、文献规模大时才需要认真规划 D 盘。

#### 克隆项目与配置

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