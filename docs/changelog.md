# 变更日志

## v1.17.0 (2026-08-22)

### AnyDoc 文档解析增强（firecrawl/anydoc）

- **AnyDoc 解析器**：基于 firecrawl/anydoc（Rust 实现，Python 绑定），支持 docx/pptx/xlsx/epub/html/txt/pdf 等格式毫秒级转 GFM Markdown，天然输出高质量表格，直接提升 LLM 数据提取准确率。
- **渐进式接入**：`ENABLE_ANYDOC` 配置项（默认关闭），零回归保证；开启后文本层 PDF 优先用 AnyDoc 解析，失败/超时自动回退现有策略解析器。
- **表格提取增强**：pdf_table_parser 的 `extract_tables_markdown` 接入 AnyDoc 分支，GFM 表格直接注入 LLM，复用 B6 哈希缓存。
- **降级链完整**：AnyDoc 失败/超时/不可用 → 依次回退：现有策略解析器 → PDF 的 OCR/MinerU。
- **下载固化**：Dockerfile 改用 BuildKit 缓存挂载，避免反复下载。

### 提取队列状态

- 新增 `queued` / `processing` 状态区分，Celery 任务开始实际提取时自动变更状态。
- 批量提取时跳过 `queued` 状态的文献，避免重复提交。
- 前端新增「提取状态」按钮，Modal 展示待处理/排队中/提取中/已完成/失败统计及文献列表。

### 疫苗接种策略报告模型选择

- 与抗体分析报告一致，新增模型选择下拉框（本地/远程分组），不选则使用系统默认模型。

### 文献标题修正增强

- 规则清理支持末尾 `_作者姓名` 删除（如 `血清学调查_苏中华` → `血清学调查`）。
- AI 验证标题：从文献文档中提取文本 → 调用 LLM 提取真实标题 → 与存储标题比对，标记差异。

### 修改文件

| 文件 | 变更说明 |
|------|----------|
| `backend/app/core/processors/anydoc_parser.py` | 新增 AnyDoc 解析器 |
| `backend/app/core/document_parser.py` | 增加 AnyDoc 分支 |
| `backend/app/core/pdf_table_parser.py` | 表格提取接入 AnyDoc |
| `backend/app/config.py` | 新增 `ENABLE_ANYDOC` / `ANYDOC_TIMEOUT` |
| `backend/requirements.txt` | 新增 `firecrawl-anydoc>=0.1.9` |
| `backend/Dockerfile` | BuildKit pip 缓存 |
| `backend/tests/test_anydoc_parser.py` | AnyDoc 离线单测 |
| `backend/app/api/v1/extraction.py` | 新增 queued 状态 |
| `backend/app/api/v1/literature.py` | 新增 fix-titles / ai-verify-titles 端点 |
| `backend/app/models/literature.py` | 新增 queued 状态 |
| `backend/app/services/literature_service.py` | 标题修正 + AI 验证 |
| `backend/app/services/extraction_service.py` | queued 状态处理 |
| `frontend/src/pages/Literature.tsx` | 提取状态面板、标题修正按钮 |
| `frontend/src/services/literature.ts` | 新增 API |
| `frontend/src/utils/constants.ts` | 新增 queued 状态元数据 |

## v1.16.0 (2026-08-22)

### 文献回收站（软删除）

- 软删除机制：文献删除改为软删除，移入回收站保留 30 天。
- 回收站管理：列表/还原/永久删除/清空 API。
- 后台自动清理：每 86400 秒检查并永久删除超过 30 天的文献。
- 前端回收站弹窗：搜索、分页、还原、永久删除、清空。
- 批量删除适配：多选删除同样改为软删除。

### 修改文件

| 文件 | 变更说明 |
|------|----------|
| `backend/app/models/literature.py` | 新增 `deleted_at` / `deleted_by` |
| `backend/app/schemas/literature.py` | 序列化新增字段 |
| `backend/app/services/literature_service.py` | 回收站 CRUD + 自动清理 |
| `backend/app/api/v1/literature.py` | 回收站接口 |
| `backend/app/main.py` | 回收站清理后台任务 |
| `frontend/src/pages/Literature.tsx` | 回收站弹窗 |
| `frontend/src/services/literature.ts` | 回收站 API |

## 更早版本

### v1.15.0 (2026-08-22)

- LLM 提取器模块化（`extraction/` 包）、分析服务模块化（`analysis/` 包）
- 统一异常体系（`exceptions.py`）
- Prometheus 业务指标
- 报告模板管理（`ReportTemplate` 模型 + CRUD）
- 前端 Meta 森林图组件、文献摘要列、题录导入预览确认
- 清理无文件文献、QualityBadge 增强
- CAJ2PDF 包装脚本、Dockerfile 优化

### v1.14.0 (2026-08-21)

- 数据审核与编辑：审核意见、审核人/时间自动记录、批量驳回强制意见
- 统计分析扩展：空间热点/冷点（Moran's I + Getis-Ord Gi*）、免疫屏障模拟、年龄-抗体曲线、出生队列分析
- 全列排序与筛选（标题/作者/创建时间/文档格式）
- 远程模型配置管理
- 文献文件下载（JWT 认证）
- 修改关联文件
- 审核统计仪表盘
- Docker 构建加速（清华 TUNA 镜像）

### 更早版本

- **v1.13.0**：URL 抓取功能、CAJ 格式支持、提取结果缓存、文件夹打开接口
- **v1.12.0**：抗原图谱（metric MDS）、多表单 Excel 导出、数据质量评分
- **v1.11.0**：Edge 浏览器插件、多格式预览、手动新增数据点
- **v1.10.0**：文献重复检测与合并、批量删除、元数据批量同步
- **v1.9.0**：疫苗接种策略报告、模型选择统一、多源检索
- **v1.8.0**：MinerU 增强解析、FOI 感染力分析、免疫屏障评估
- **v1.7.0**：文献多格式导入导出、跨电脑迁移、文件夹自动监控
- **v1.6.0**：长文档分块并行提取、强 Schema 约束、批量 AI 提取
- **v1.5.0**：精确字符级溯源、数据审核与行内编辑
- **v1.4.0**：本地 Ollama 模型支持、多厂商 LLM
- **v1.3.0**：PubMed 检索集成、题录批量导入
- **v1.2.0**：地图可视化、多维度数据分析
- **v1.1.0**：AI 数据提取、报告生成
- **v1.0.0**：初始版本—文献管理、基础 API