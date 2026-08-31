# 配置参考

## LLM 配置

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `LLM_API_KEY` | 通用 LLM API 密钥 | - |
| `LLM_BASE_URL` | 通用 LLM API 地址 | `https://api.deepseek.com` |
| `LLM_MODEL` | 默认模型名称 | `qwen3:32b` |
| `DEEPSEEK_API_KEY` | DeepSeek 独立 API 密钥 | 回退到 `LLM_API_KEY` |
| `OPENAI_API_KEY` | OpenAI 独立 API 密钥 | 回退到 `LLM_API_KEY` |
| `QWEN_API_KEY` | 通义千问独立 API 密钥 | 回退到 `LLM_API_KEY` |
| `LLM_FALLBACK_BASE_URLS` | 备用地址（逗号分隔） | - |
| `LLM_CONNECT_RETRIES` | 连接错误快速重试次数 | `2` |
| `LLM_REQUEST_TIMEOUT` | 请求超时（秒） | `600` |
| `LLM_CONCURRENCY` | 并发提取数 | `2` |

## 数据库与存储

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `DATABASE_URL` | PostgreSQL 连接串 | `postgresql+asyncpg://antibody:antibody123@localhost:5432/antibody_map` |
| `REDIS_URL` | Redis 连接串 | `redis://localhost:6379/0` |
| `CELERY_BROKER_URL` | Celery 消息队列 | `redis://localhost:6379/1` |
| `MINIO_ENDPOINT` | MinIO 地址 | `localhost:9000` |

## 其他

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `CORS_ORIGINS` | 跨域白名单 (Python 列表语法，如 `["http://a.com","http://b.com"]`) | `["http://localhost:3000","http://localhost:5173"]` |
| `TESSERACT_CMD` | Tesseract 可执行文件路径 | 自动探测 |
| `TESSERACT_DATA_DIR` | Tesseract 语言包目录 | 自动探测 |
| `PDF_STORAGE` | PDF 存储模式 | `local` (或 `minio`) |
| `PDF_DOWNLOAD_DIR` | PubMed 开放获取 PDF 下载目录 | 回退 `LOCAL_STORAGE_DIR` |
| `ENABLE_MINERU_PDF_PARSER` | 启用 MinerU 增强解析 | `false` |
| `ENABLE_ANYDOC` | 启用 AnyDoc 增强解析 | `false` |
| `ORPHAN_CLEANUP_ENABLED` | 是否启用后台定时清理孤儿文件 | `true` |
| `ORPHAN_CLEANUP_INTERVAL` | 后台清理间隔（秒） | `86400` |
| `ORPHAN_TRASH_DIR` | 孤儿文件回收目录 | `backend/data/pdf_orphan_trash` |
| `ORPHAN_TRASH_RETENTION_DAYS` | 回收目录保留天数 | `30` |
| `EXTRACTION_CACHE_ENABLED` | 提取结果缓存 | `true` |
| `EXTRACTION_CACHE_TTL_HOURS` | 缓存 TTL（小时） | `168` |
| `ENABLE_KG_EXTRACTION` | 启用知识图谱 LLM 三元组抽取 | `false` |
| `EXTRACTION_STALE_MINUTES` | 提取状态卡死回收阈值（分钟） | `30` |
| `APP_ENV` | 运行环境 | `development` |

## 本地 Ollama 模型配置

### 显卡显存与推荐配置

| 显存容量 | 推荐模型 | 推荐并发数 | 说明 |
|----------|----------|-----------|------|
| 8-12 GB | qwen2.5:7b / llama3.1:8b | 1 | 小模型，推理速度较快 |
| 16 GB | qwen2.5:14b | 1-2 | 平衡性能与精度 |
| 24 GB | qwen2.5:14b | 2-4 | 实测最优吞吐拐点 |
| 32 GB+ | qwen3:32b / llama3:70b (量化) | 2-4 | 大模型精度更高但推理更慢 |

> **注意**：`qwen3:32b` 在 24GB 显存下会因显存不足触发 CPU/GPU 数据交换，推理速度骤降 10-50 倍。
> 配置 `LLM_CONCURRENCY` 时必须与 Ollama 的 `OLLAMA_NUM_PARALLEL` 环境变量保持一致。

### 启动 Ollama 服务

```bash
# 拉取模型
ollama pull qwen2.5:14b

# 设置并发数并启动服务（Windows 需在系统环境变量中设置）
OLLAMA_NUM_PARALLEL=4 ollama serve

# 验证 API
curl http://localhost:11434/v1/chat/completions
```

启用本地模型后，在 `.env` 中将 `LLM_MODEL` 设置为 `ollama:qwen2.5:14b`，或在上传/提取时在模型选择弹窗中手动选择。

## CAJ 格式支持

### 安装 caj2pdf

```bash
git clone https://github.com/caj2pdf/caj2pdf.git
cd caj2pdf
pip install .
```

### 安装 mutool（mupdf-tools）

**Windows**：下载 mupdf，将 `mupdf/bin/mutool.exe` 所在目录添加到系统 PATH。

**macOS**：`brew install mupdf`

**Linux**：`sudo apt install mupdf mupdf-tools`

未安装以上依赖时，CAJ 文件会显示「无法转换」的错误提示，其他格式不受影响。

## 项目脚本一览

| 脚本 | 平台 | 作用 |
|------|------|------|
| `start.ps1` / `stop.ps1` | Windows | 一键启动/停止所有服务 |
| `start.sh` / `stop.sh` | macOS/Linux | 一键启动/停止所有服务 |
| `scripts/backup_db.ps1` | Windows | 导出数据库备份 |
| `scripts/restore_db.ps1` | Windows | 从备份恢复数据库 |

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
| extraction_status | ENUM | pending / queued / processing / done / done_no_data / failed |
| extracted_count | INT | 已提取数据点数量 |
| approved_count | INT | 已审核通过数量 |
| llm_model_used | TEXT | 提取使用的大模型名称 |
| total_tokens | INT | 本次提取消耗的总 Token 数 |
| llm_cost_usd | NUMERIC(10,6) | 估算费用（美元） |

### DataPoint (数据点)

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 主键 |
| literature_id | UUID | 外键 → Literature |
| disease | TEXT | 疾病名称 |
| province / city | TEXT | 省 / 市 |
| data_type | TEXT | seroprevalence / gmc |
| value / unit | FLOAT / TEXT | 数值 / 单位 |
| sample_size | INT | 样本量 |
| age_min / age_max | FLOAT | 年龄段 |
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