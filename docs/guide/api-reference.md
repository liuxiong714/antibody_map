# 项目结构

## 项目结构

```
antibody_map/
├── docker-compose.yml              # Docker 基础设施编排
├── start.sh / stop.sh              # 一键启动 / 停止脚本
├── start.ps1 / stop.ps1            # Windows 一键启动 / 停止脚本
├── .env.example                    # 环境变量配置模板
├── docs/                           # 文档（ReadTheDocs）
├── browser-extension/              # Edge 浏览器插件
├── backend/
│   ├── app/
│   │   ├── main.py                 # FastAPI 应用入口
│   │   ├── config.py               # 全局配置 (pydantic-settings)
│   │   ├── api/                    # API 路由层
│   │   │   ├── deps.py             # 依赖注入
│   │   │   └── v1/                 # 版本 1 路由
│   │   ├── core/                   # 核心引擎
│   │   │   ├── llm_extractor.py    # LLM 提取器
│   │   │   ├── extraction/         # 提取器模块包
│   │   │   ├── document_parser.py  # 多格式文档解析分发
│   │   │   ├── processors/         # 各格式解析器
│   │   │   ├── pdf_parser.py       # PDF 文本解析
│   │   │   ├── ocr_service.py      # OCR 服务
│   │   │   ├── stats_engine.py     # 统计引擎（纯函数）
│   │   │   ├── reference_data/     # 常量表（标准人口、邻接矩阵等）
│   │   │   └── ...                 # 其他核心模块
│   │   ├── models/                 # SQLAlchemy ORM 模型
│   │   ├── services/               # 业务逻辑层
│   │   │   ├── analysis/           # 分析服务模块包
│   │   │   └── ...
│   │   ├── schemas/                # Pydantic 数据模型
│   │   └── tasks/                  # Celery 异步任务
│   ├── tests/                      # 单元测试
│   ├── scripts/                    # 运维脚本
│   └── requirements.txt
└── frontend/
    ├── src/
    │   ├── App.tsx                 # 前端路由配置
    │   ├── layouts/                # 全局布局
    │   ├── pages/                  # 页面组件
    │   ├── components/             # 公共组件
    │   ├── services/               # API 服务层
    │   ├── store/                  # Zustand 状态管理
    │   ├── types/                  # TypeScript 类型定义
    │   └── utils/                  # 工具函数
    └── package.json
```

## 技术栈

见 [使用指南 — 核心功能](features.md)。

## 数据流

```
文献上传 (PDF/CAJ/EPUB/DOCX/PPTX/XLSX/TXT/HTML) 或 URL 网页导入
    │
    ▼
多格式文档解析 (策略模式注册表)
    │
    ▼
文本预处理 (清洗 OCR 乱码；文字层缺失自动触发 OCR)
    │
    ▼
LLM 结构化提取 (疾病/省份/阳性率/GMC/年龄段/样本量/采集年份)
    │
    ▼
精确字符级溯源 + 强 Schema 校验
    │
    ▼
疾病名称标准化 + 术语标准化
    │
    ▼
文献重复检测 (DOI/标题/作者/PDF 哈希)
    │
    ▼
生成 DataPoint 记录 (review_status = pending)
    │
    ▼
人工审核 + 行内编辑 → approved / rejected
    │
    ▼
地图可视化 + 多维度分析 + 数据导出
    │
    ▼
FOI 感染力分析 + VE 疫苗效果分析
    │
    ▼
LLM 生成免疫学报告 + 疫苗接种策略报告
```

## API 接口一览

所有接口挂载在 `/api/v1` 前缀下。完整接口文档见 [Swagger (开发环境)](http://localhost:8080/docs) 或 [Redoc](http://localhost:8080/redoc)。

### 字典接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/dictionary/diseases` | 获取疾病列表 |
| GET | `/dictionary/provinces` | 获取 34 个省级行政区 |
| GET | `/dictionary/methods` | 获取检测方法 |

### 文献管理

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/literatures/upload` | 上传文献 |
| POST | `/literatures/from-url` | 从 URL 导入 |
| GET | `/literatures` | 文献列表（分页+筛选） |
| GET | `/literatures/export` | 导出文献列表 |
| POST | `/literatures/import` | 批量导入文献和数据点 |
| POST | `/literatures/import-references` | 题录批量导入 |
| DELETE | `/literatures/{id}` | 删除文献 |
| POST | `/literatures/batch-delete` | 批量删除 |
| POST | `/literatures/check-duplicate` | 检查重复 |
| POST | `/literatures/scan-duplicates` | 扫描全库重复 |
| POST | `/literatures/merge/preview` | 合并预览 |
| POST | `/literatures/{id}/merge` | 合并重复文献 |
| DELETE | `/literatures/trash/{id}` | 永久删除 |
| POST | `/literatures/trash/{id}/restore` | 还原回收站文献 |
| POST | `/literatures/trash/empty` | 清空回收站 |
| POST | `/literatures/fix-titles` | 修正文献标题 |
| POST | `/literatures/ai-verify-titles` | AI 验证标题 |

### PubMed 检索

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/pubmed/search` | PubMed 检索 |
| GET | `/pubmed/search/multi` | 多源检索 |
| GET | `/pubmed/abstract/{pmid}` | 获取摘要 |
| POST | `/pubmed/import` | 纳入文献库 |
| POST | `/pubmed/download-pdf` | 下载开放获取 PDF |

### 数据提取与审核

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/literatures/{id}/extraction` | 触发 AI 提取 |
| POST | `/literatures/extraction/batch` | 批量触发提取 |
| GET | `/literatures/{id}/extraction` | 获取数据点列表 |
| PUT | `/literatures/{id}/extraction` | 编辑数据点 |
| POST | `/literatures/{id}/extraction/confirm` | 批量审核通过 |
| POST | `/literatures/{id}/extraction/dispute` | 批量驳回 |

### 地图数据

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/map/province-data` | 省级地图数据 |
| GET | `/map/city-data` | 市级数据 |
| GET | `/map/summary` | 全国汇总统计 |
| GET | `/map/yearly-data` | 逐年数据 |

### 知识图谱

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/kg/overview` | 知识图谱概览（实体/关系总数） |
| GET | `/kg/options` | 筛选选项（疾病/省份/数据类型/年份） |
| GET | `/kg/graph` | 图谱数据（节点+边，支持筛选） |
| GET | `/kg/entities/search` | 实体搜索（关键词+类型过滤） |
| GET | `/kg/query/path` | 路径推理（起点→终点，最大深度 3 跳） |
| GET | `/kg/stats` | 实体类型统计分布 |
| POST | `/kg/batch` | 批量触发 LLM 三元组抽取 |
| POST | `/kg/extraction/trigger` | 手动触发三元组抽取任务（自动筛选未处理文献，串行 LLM 抽取） |
| POST | `/kg/qa/ask` | 知识图谱咨询问答（模板命中或 LLM 兜底，回答绑定数据点证据） |

### 数据分析

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/analysis/trend` | 逐年趋势 |
| GET | `/analysis/region-compare` | 区域对比 |
| GET | `/analysis/age-stratify` | 年龄分层 |
| GET | `/analysis/immune-barrier` | 免疫屏障评估 |
| GET | `/analysis/foi-herd-immunity` | FOI 感染力分析 |
| GET | `/analysis/vaccine-effectiveness-coverage` | 疫苗效果 VE |
| GET | `/analysis/equity` | 省间公平性 |
| GET | `/analysis/quality` | 数据质量评估 |
| GET | `/analysis/meta-merge` | Meta 合并 |
| GET | `/analysis/age-curve` | 年龄-抗体曲线 |
| GET | `/analysis/simulate` | 免疫屏障模拟 |
| GET | `/analysis/spatial-hotspots` | 空间热点分析 |

### 报告

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/reports/generate` | 生成抗体分析报告 |
| POST | `/reports/generate-vaccination-strategy` | 生成疫苗接种策略报告 |
| GET | `/reports` | 报告列表 |
| GET | `/reports/{id}` | 报告详情 |
| PUT | `/reports/{id}` | 编辑报告 |
| DELETE | `/reports/{id}` | 删除报告 |

### 系统

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/system/info` | 系统信息 |
| GET | `/system/logs` | 日志列表 |
| GET | `/system/logs/content` | 日志内容 |
| GET | `/models` | 可用模型列表 |
| GET | `/health` | 健康检查 |