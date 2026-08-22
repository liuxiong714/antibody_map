# 项目架构

## 技术栈

| 层级 | 技术 |
|------|------|
| **前端** | React 18 + TypeScript, Vite 6, Ant Design 5, ECharts 5, pdfjs-dist, Zustand, React Router 6 |
| **后端** | Python 3.10+, FastAPI + Uvicorn, SQLAlchemy 2.0 (async), Celery + Redis, Pydantic 2.0 |
| **统计/制图** | NumPy + SciPy + statsmodels + scikit-learn |
| **数据库** | PostgreSQL 15 |
| **存储** | MinIO 对象存储 / 本地文件系统双模式 |
| **AI/LLM** | OpenAI SDK 兼容协议，支持 DeepSeek / OpenAI / 通义千问 (Qwen) / 本地 Ollama 多厂商 |
| **文档解析** | 策略模式解析器注册表：PyMuPDF + pdfplumber、python-docx、python-pptx、openpyxl、ebooklib、BeautifulSoup、caj2pdf；MinerU 增强解析；AnyDoc 增强解析 |
| **OCR** | Tesseract OCR (中文/英文) + 百度 OCR 云端回退 |
| **运维** | Docker Compose (PostgreSQL + Redis + MinIO), start.sh / start.ps1 一键启动 |

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

## 数据库模型

详见 [配置参考 — 数据库模型](configuration.md)。