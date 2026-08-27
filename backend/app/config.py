import os
import warnings
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# .env 文件位于项目根目录（backend/ 的父目录）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM — 默认配置（向后兼容）
    LLM_API_KEY: str = ""  # 必须通过环境变量或 .env 文件配置
    LLM_BASE_URL: str = "https://api.deepseek.com"
    LLM_MODEL: str = "qwen3:32b"

    # LLM — 按模型厂商独立配置（可选，未配置时回退到 LLM_API_KEY / LLM_BASE_URL）
    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"
    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    QWEN_API_KEY: str = ""
    QWEN_BASE_URL: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    # P1-3：本地 LLM（Ollama）配置
    # Ollama 暴露 OpenAI 兼容 API（/v1/chat/completions），无需 API Key
    # 常用本地模型：llama3, qwen2.5, glm4, mistral 等
    OLLAMA_API_KEY: str = "ollama"  # 占位 key（Ollama 不校验）
    OLLAMA_BASE_URL: str = "http://localhost:11434/v1"

    # P0-2：多趟提取趟数（1=单趟，2=双趟查漏补缺，3=三趟）
    # 趟数越多召回率越高但 API 调用成本线性增加，推荐 2
    LLM_EXTRACTION_PASSES: int = 2

    # P1-2：PDF 内自动识别 DOI 并回填 Crossref 元数据（默认开启）
    CROSSREF_DOI_BACKFILL: bool = True

    # 本地大模型（如 32B/70B）推理慢，请求超时需放宽，单位：秒
    LLM_REQUEST_TIMEOUT: int = 600

    # P2-B1：LLM 并发提取配置
    # 并发请求数上限，需与 Ollama 的 OLLAMA_NUM_PARALLEL 环境变量对齐
    # RTX 4090/5090 实测 4 并发为吞吐与延迟最优拐点（参考 2026 基准测试）
    LLM_CONCURRENCY: int = 4

    # F11：单任务 token 预算 / 日配额熔断 / 全局并发上限（0 = 关闭对应限制）
    # - LLM_MAX_TOKENS_PER_TASK: 单篇文献提取累计 token 超过后中止（防异常长文档失控计费）
    # - LLM_DAILY_QUOTA: 全平台单日累计 token 上限（按自然日、基于 Redis 计数，超出熔断）
    # - LLM_GLOBAL_CONCURRENCY: 进程内所有提取任务共享的全局并发上限（跨任务限流）
    LLM_MAX_TOKENS_PER_TASK: int = 0
    LLM_DAILY_QUOTA: int = 0
    LLM_GLOBAL_CONCURRENCY: int = 0

    # 连接容错：主 base_url 连接失败时的备用地址（逗号分隔，可选）。
    # 场景：WSL 重启导致 Ollama 网关 IP 漂移 / 远程 API 短暂不可达时自动切换。
    LLM_FALLBACK_BASE_URLS: str = ""
    # 连接类错误（DNS/连接/超时）的快速重试次数（短退避 2s/5s），
    # 仅作用于连接错误，不消耗 token；非连接错误不重试。
    LLM_CONNECT_RETRIES: int = 2

    # P2：长文档分块阈值（字符数），超过此值触发分块并发提取
    LLM_CHUNK_THRESHOLD: int = 20000
    # P2：单块最大字符数
    LLM_CHUNK_SIZE: int = 15000
    # P2：分块重叠字符数（保持上下文连贯）
    LLM_CHUNK_OVERLAP: int = 500

    # 文本预处理最大保留字符数（仅作极长文本的安全兜底，须 > LLM_CHUNK_THRESHOLD，否则分块逻辑永不触发）。
    # 分块的主导参数是 LLM_CHUNK_THRESHOLD/SIZE/OVERLAP：长文本先按块逐块交给 LLM，
    # 默认 600000 可覆盖绝大多数综述/长文，避免超 6 万字符时尾部数据在进入 LLM 前被丢弃。
    TEXT_PREPROCESS_MAX_CHARS: int = 600000

    # MinerU 增强 PDF 解析（需安装 PyTorch + mineru 包，首次使用会自动下载模型约 2-3GB）
    ENABLE_MINERU_PDF_PARSER: bool = False
    # MinerU 解析超时（秒）。首次解析需下载模型，CPU/GPU 推理较慢，超时后回退 PyMuPDF
    MINERU_PARSE_TIMEOUT: int = 600

    # AnyDoc 文档解析增强（firecrawl/anydoc：任意文档 → GFM Markdown，表格质量高）。
    # 默认关闭，保证与现有解析行为完全一致（零回归）。开启后先试 AnyDoc，
    # 失败/超时自动回退现有策略解析器（PDF 走 PyMuPDF/OCR/MinerU）。
    ENABLE_ANYDOC: bool = False
    # AnyDoc 解析超时（秒），超时后回退现有解析链
    ANYDOC_TIMEOUT: int = 60
    # pdf-inspector 增强 PDF 解析开关（默认开启）：PDF 优先用 pdf-inspector 提取，
    # 遇到文件尾部损坏时自动用 PyMuPDF 修复后再提取，失败回退现有解析链
    ENABLE_PDF_INSPECTOR: bool = True

    # ===== 孤儿文件清理配置 =====
    # 是否启用后台定时清理（backend/data/pdfs 中已不在数据库的残留文件）
    ORPHAN_CLEANUP_ENABLED: bool = True
    # 后台定时清理间隔（秒），默认每天一次
    ORPHAN_CLEANUP_INTERVAL: int = 86400
    # 孤儿文件回收目录（默认 backend/data/pdf_orphan_trash），可自定义绝对路径
    ORPHAN_TRASH_DIR: str = ""
    # 回收目录保留天数，超过后自动物理删除，默认 30 天
    ORPHAN_TRASH_RETENTION_DAYS: int = 30
    # 是否真实移动孤儿文件（默认 False=仅 dry-run 报告；显式开启后后台循环才会真正移入回收）
    ORPHAN_AUTO_MOVE: bool = False
    # 冷静期（天）：文件 mtime 距今小于该天数则跳过，避免误判监控/上传/提取中的文件
    ORPHAN_COOLING_DAYS: int = 7

    # PubMed 开放获取 PDF 下载目录；为空时回退到 LOCAL_STORAGE_DIR
    PDF_DOWNLOAD_DIR: str = ""

    # ===== 提取准确度 & 性价比优化配置 =====
    # A3：grounding 模糊匹配阈值（0-1，越高越严格）
    GROUNDING_FUZZY_THRESHOLD: float = 0.72
    # A3：grounding 失败时是否用 LLM 重新提取 source_context
    GROUNDING_LLM_REGROUND: bool = True

    # B5：分级模型策略（留空则不启用，统一用 LLM_MODEL）
    LLM_MODEL_LIGHT: str = ""   # 简单文献用（短文本+无表格），如 "deepseek-chat"
    LLM_MODEL_STRONG: str = ""  # 复杂文献用（长文本+复杂表格），如 "deepseek-reasoner"

    # A1：结构化表格优先提取（有表格时先单独从表格提取一轮）
    LLM_TABLE_FIRST_EXTRACTION: bool = True

    # A2：两阶段提取（先抽骨架再填数值，默认关闭，适合对准确度要求极高的场景）
    LLM_TWO_PHASE_EXTRACTION: bool = False

    # B8：多趟提取智能调度（第1趟覆盖率>90%则跳过后续趟）
    LLM_ADAPTIVE_PASSES: bool = True

    # B9：审核反馈闭环（将 rejected 数据点作为 few-shot 注入 prompt）
    LLM_FEEDBACK_FEW_SHOT: bool = True
    LLM_FEEDBACK_FEW_SHOT_COUNT: int = 5

    # ===== 提取结果缓存（降低 LLM API 成本）=====
    # 是否启用 Redis 提取结果缓存（命中时跳过 LLM 调用直接重建数据点）
    EXTRACTION_CACHE_ENABLED: bool = True
    # 缓存有效期（小时），默认 7 天
    EXTRACTION_CACHE_TTL_HOURS: int = 168

    # ===== 4.5：统计最小样本护栏 =====
    # 省份/年度做 Meta 合并时，研究数少于该值则标记"证据不足"，避免产出易误导的合并值
    MIN_STUDIES_FOR_META: int = 2
    # 累计样本量少于该值同样标记"证据不足"
    MIN_SAMPLE_FOR_META: int = 30

    # 免疫屏障不确定性量化（Monte Carlo）采样次数，越大结果越稳但越慢
    IMMUNITY_MC_SAMPLES: int = 1000

    # Database (默认值适用于 Docker Compose 本地开发环境)
    DATABASE_URL: str = "postgresql+asyncpg://antibody:antibody123@localhost:5432/antibody_map"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # MinIO (默认值适用于 Docker Compose 本地开发环境)
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "antibody"
    # 凭据统一从 MINIO_ROOT_PASSWORD 读取（.env 中配置）；MINIO_SECRET_KEY 为旧名回退
    MINIO_ROOT_PASSWORD: str = ""
    MINIO_SECRET_KEY: str = ""
    MINIO_BUCKET_LITERATURE: str = "antibody-literature"

    # Celery
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"
    # Prometheus 指标采集的 Celery 队列（逗号分隔，默认 celery），用于 queue_depth 指标
    CELERY_QUEUES: str = "celery"

    # OCR
    # Tesseract 可执行文件路径（默认自动探测：PATH 或 Windows 常见安装位置）
    TESSERACT_CMD: str = ""
    # Tesseract 语言数据目录（tessdata），默认取可执行文件同目录下的 tessdata
    TESSERACT_DATA_DIR: str = ""

    # App
    SECRET_KEY: str = ""  # 必须通过环境变量或 .env 文件配置
    APP_ENV: str = "production"
    APP_DEBUG: bool = False
    # 应用版本号（单一版本源，main.py 与 /health 端点均引用此值）
    APP_VERSION: str = "1.21.0"
    CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:5173"]
    MAX_UPLOAD_SIZE: int = 52428800
    # 提取状态卡死阈值（分钟）：processing/queued 超过此时间未变，列表查询时自动重置为 failed
    EXTRACTION_STALE_MINUTES: int = 30
    # F14：worker 心跳刷新间隔（秒）。提取进行中每间隔刷新一次 worker_heartbeat，
    # 超时回收据此区分"长任务"（心跳新鲜）与"真卡死"（心跳停止）。须远小于 EXTRACTION_STALE_MINUTES。
    EXTRACTION_HEARTBEAT_INTERVAL: int = 60

    # ===== 分析快照 =====
    # 快照行保留天数，超过后由后台循环清理（回收 response_json 占用的存储）
    SNAPSHOT_TTL_DAYS: int = 30
    # 快照清理后台循环间隔（秒），默认每天一次
    SNAPSHOT_CLEANUP_INTERVAL: int = 86400

    # ===== 数据库备份 =====
    # pg_dump 导出文件存放目录（容器内路径，宿主机通过 docker-compose 卷映射到项目 backups/）
    BACKUP_DIR: str = "/app/backend/backups"
    # 单次备份超时（秒）
    BACKUP_TIMEOUT: int = 300

    # ===== Prometheus 指标 =====
    # 是否启用 /metrics 端点与指标采集；关闭后 endpoint 不注册且访问返回 403
    METRICS_ENABLED: bool = True
    # 非开发环境下允许访问 /metrics 的客户端 IP（逗号分隔）。
    # 留空表示仅开发环境(APP_ENV==development)可访问，生产环境默认拒绝
    METRICS_ALLOW_IPS: str = ""

    @model_validator(mode="after")
    def _validate_constraints(self) -> "Settings":
        """交叉校验配置项之间的约束关系，在启动时即发现配置错误。"""
        # 核心结构性约束：预处理截断必须大于分块阈值，否则分块并发逻辑永不触发
        if self.TEXT_PREPROCESS_MAX_CHARS <= self.LLM_CHUNK_THRESHOLD:
            raise ValueError(
                "TEXT_PREPROCESS_MAX_CHARS 必须大于 LLM_CHUNK_THRESHOLD，"
                f"当前 {self.TEXT_PREPROCESS_MAX_CHARS} <= {self.LLM_CHUNK_THRESHOLD}，"
                "否则长文档分块并发逻辑将永不触发"
            )

        # 单块大小必须大于重叠区，否则分块无意义
        if self.LLM_CHUNK_SIZE <= self.LLM_CHUNK_OVERLAP:
            raise ValueError(
                "LLM_CHUNK_SIZE 必须大于 LLM_CHUNK_OVERLAP，"
                f"当前 {self.LLM_CHUNK_SIZE} <= {self.LLM_CHUNK_OVERLAP}"
            )

        # 分块阈值应不小于单块大小（否则首块即超过阈值，逻辑退化）
        if self.LLM_CHUNK_THRESHOLD < self.LLM_CHUNK_SIZE:
            warnings.warn(
                f"LLM_CHUNK_THRESHOLD ({self.LLM_CHUNK_THRESHOLD}) 小于 "
                f"LLM_CHUNK_SIZE ({self.LLM_CHUNK_SIZE})，分块逻辑可能退化",
                stacklevel=2,
            )

        if self.LLM_CONCURRENCY < 1:
            raise ValueError(f"LLM_CONCURRENCY 必须 >= 1，当前 {self.LLM_CONCURRENCY}")

        if self.LLM_FEEDBACK_FEW_SHOT_COUNT < 1:
            raise ValueError(
                f"LLM_FEEDBACK_FEW_SHOT_COUNT 必须 >= 1，当前 {self.LLM_FEEDBACK_FEW_SHOT_COUNT}"
            )

        # 所有环境都必须配置强密钥（>=32 字符）
        if len(self.SECRET_KEY) < 32:
            raise ValueError(
                f"SECRET_KEY 必须 >= 32 字符，当前长度 {len(self.SECRET_KEY)}，"
                "请使用 openssl rand -base64 32 生成密钥"
            )

        # 非开发环境禁止使用默认数据库口令（config.py 默认 DATABASE_URL 含弱口令 antibody123）。
        # 防呆：若 .env 漏配 DATABASE_URL，生产会静默连上默认弱口令库。
        if self.APP_ENV != "development" and "antibody123@localhost" in self.DATABASE_URL:
            raise ValueError(
                "非开发环境禁止使用默认数据库口令 antibody123，"
                "请在 .env 中配置 DATABASE_URL，并使用强口令（openssl rand -base64 24 生成）"
            )

        # 非开发环境禁止使用空 MinIO 主密码（默认 MINIO_ROOT_PASSWORD 为空字符串）
        if self.APP_ENV != "development" and not self.MINIO_ROOT_PASSWORD:
            raise ValueError(
                "非开发环境必须配置 MINIO_ROOT_PASSWORD（openssl rand -base64 24 生成）"
            )

        # 本地 Ollama 并发一致性：若设置了 OLLAMA_NUM_PARALLEL，应与 LLM_CONCURRENCY 对齐
        ollama_parallel = os.getenv("OLLAMA_NUM_PARALLEL")
        if ollama_parallel and int(ollama_parallel) != self.LLM_CONCURRENCY:
            warnings.warn(
                f"OLLAMA_NUM_PARALLEL ({ollama_parallel}) 与 LLM_CONCURRENCY "
                f"({self.LLM_CONCURRENCY}) 不一致，可能导致本地模型并发异常",
                stacklevel=2,
            )

        return self


settings = Settings()
