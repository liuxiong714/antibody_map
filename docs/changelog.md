## 变更日志

## v1.27.0 (2026-09-17)

### 新增

- **系统设置 · 系统活动 Tab（审计日志落库 + 关键路径全覆盖）** — 原「后台日志」Tab 仅展示进程 stdout（运维排障用），普通用户看不出系统最近在干什么。新增独立「系统活动」Tab 消费 `audit_log` 表，Tab 宽面板（max-width: 1400px）保证所有 Tab 一行铺开。审计核心改造：
  1. `backend/app/core/audit.py` 从纯 stdout 双通道升级为 **stdout + asyncpg DB 落库**；独立 async engine 与 base.py 主 engine 解耦，Celery worker 与 FastAPI 进程通用；落库失败自动降级仅写 stdout，不反制业务。
  2. 覆盖关键用户关注路径：
     - 文献 AI 提取 **完成 / 失败**（`extraction_completed` / `extraction_failed`，含模型 / 数据点数量 / 错误类型）
     - 三类报告（抗体分析 / 免疫屏障 / 疫苗接种策略）**生成成功 / 失败**（`report_generated`，含 kind / disease / model）
     - 知识图谱抽取 **完成 / 失败**（`kg_extraction_completed` / `kg_extraction_failed`，含 processed / written 三元组数）
     - 文件夹监控 **扫描**（`folder_monitor_scanned`，含 scanned / imported / skipped / failed 统计）
     - 数据库备份 / 还原 / 下载、登录 / 登出 / 登录失败、数据点审核、MinIO 清理、特性开关调整 —— 全部自动落库
  3. 后端新端点 `GET /api/v1/system/audit-logs`：分页 + action / username / keyword 过滤 + 27 种 action 友好中文标签映射。
  4. 前端 Settings.tsx 新 Tab：Table（时间 / 彩色 Tag 动作 / 用户 / 目标）+ 工具条筛选 + 展开详情（目标 / 详情 / IP / 实体 / 原值 / 新值）。

- **疫苗接种策略报告 · 任务时间日历选择器** — 报告生成页 StrategyReportForm 的「任务时间」字段从手动输入框升级为 antd `DatePicker.RangePicker`，点击弹出双月日历拖拽选起止日期，序列化为 `YYYY-MM-DD 至 YYYY-MM-DD` 与后端 `task_time` 字符串兼容；内置 `parseTaskTimeToRange()` 反向解析器，加载历史报告时可把旧格式（`2026年8-10月` / `2026-08-01~2026-10-31`）回填到日历控件。
- **Model 层字段级归一化（ORM @validates）** — `DataPoint` / `Literature` 模型新增 SQLAlchemy `@validates` 自动校验，province/disease/method 字段在任何 ORM 入库路径（提取管线、题录导入、合成自测、手工写入）都统一走 `term_normalizer` 归一化，**从根本上杜绝 import/synthetic 等旁路写入脏数据**。

### 修复

- **省份字段重复（北京 vs 北京市、广东 vs 广东省、全国 vs 中国）** — 根因是 import/synthetic 等旁路未调用 `normalize_province`、只有 post_processor 做了归一化。修复：① PROVINCE_MAP 新增 `中国/中华人民共和国 → 全国` 条目；② 数据库 28 条脏数据一次性 SQL 修正（北京市→北京 12 行、广东省→广东 15 行、中国→全国 1 行）；③ Model 层 `@validates("province")` 兜底未来所有入库。
- **英文 SCI 文献自动路由英文提示词** — extract_task.py 硬编码 language='zh'，detect_language 检测到英文后仍走中文 PROMPT。修复：import detect_language，文本预处理后动态检测语言并传给 extractor，PROMPT_EN 分支打通。端到端验证：香港育龄妇女水痘 VZV 血清流行率英文文献成功提取 4 条数据点。
- **重复文献合并后 extraction_status 元数据不同步** — duplicates.py 合并时重算 extracted_count 但未同步 extraction_status，导致 `done_no_data` 但有 ≥1 条 DataPoint 的矛盾状态。修复：合并时根据 DataPoint 行数重算 status；crud.py 新增 `align_literature_terminal_state()` 在列表查询时自动对齐，防止新脏数据积累。已清理 6 条存量脏数据。
- **知识图谱三列布局** — 中间 EChart 自适应 Canvas 宽高（ResizeObserver 监听容器尺寸变化），右侧面板贴紧浏览器右边框 + 可手动拖拽调宽 + 可隐藏；默认开启「全节点」开关。

### 文档

- **README / features.md** — 本版本前端/后端改动均属 bugfix+UX 层，未新增需功能文档描述的模块，故仅在本 changelog 记录。

---

## v1.26.0 (2026-09-16)

### 新增

- **远程大模型端到端验证** — deepseek-flash 远程模型完整通路验证通过：前端选远程模型 → 后端加密 API Key 存入 ApiModelConfig → Celery 队列传递 model_config_id → worker 从 DB 解密 → POST /v1/chat/completions → 解析入库。验证文献《2018年福建省流行性腮腺炎血清学及病毒基因型监测》成功提取 53 条数据点（26 血清阳性率 + 27 GMC），耗时约 4 分钟，费用 $0.015455。
- **Fernet 双版本 API Key 加密** — ackend/app/core/crypto.py 升级为 HKDF-SHA256 v2（salt=ntibody-map-apikey-v2），保留 legacy sha256 导出兼容；解密失败（InvalidToken）统一抛出 ValueError("API_KEY_DECRYPT_FAILED") 而非返回明文密文，下游 catcher 回退至「缺 key」安全路径。
- **API Key 来源双通道** — 提取任务支持系统级（.env 环境变量）与数据库加密存储（ApiModelConfig hybrid_property 自动加解密）两种来源，后者让前端自定义的 API Key 只以密文进入 DB、Redis 队列只传 model_config_id，明文永不落队列。
- **知识图谱特性开关显式化** — ENABLE_KG_EXTRACTION 默认关闭，需在 .env 中显式设为 	rue 并重启容器才开启 LLM 三元组抽取；关闭时任何触发 KG 的 API 直接返回 400 拒绝，避免用户误触额外计费。
- **Redis 滑动窗口限流** — ackend/app/core/rate_limiter.py 重写为 Redis 滑动窗口 + X-Forwarded-For 首 IP 为限流 key，Redis 不可用时自动降级到内存版；与登录端点集成，连续失败触发 429。
- **Docker compose 模式重构** — 基础 docker-compose.yml 默认 CPU-only（去掉 GPU 透传）；docker-compose.gpu.yml 追加 GPU overlay；新增 docker-compose.reuse.yml 供本地开发复用外部数据卷保留历史数据。一键脚本 docker-start.sh 按 GPU 探测结果追加对应 overlay。
- **metadata_validator** — 新增 ackend/app/core/metadata_validator.py：DOI ^10\.\d{4,9}/\S+$ 正则 + 长度 ≤128、PMID 1-9 位正整数、pub_year ∈ [1900, now+1]，无效值跳过并警告。
- **前端 usePolling Hook** — rontend/src/hooks/usePolling.ts 统一多处轮询逻辑（文献详情提取状态、报告生成、批量任务进度），内置 404 容忍（连续 4 次）、最多 200 次、shouldStop、onGiveUp 回调、组件卸载自动清理等防泄漏设计。
- **数据点表格分页** — 文献详情页数据点列表支持分页（pageSize=50，showSizeChanger 20/50/100），跨页保留 selectedRowKeys。
- **文献详情页上一篇 / 下一篇** — 详情页标题栏右侧新增「上一篇（LeftOutlined）」按钮，与已有「下一篇」共用一次列表请求（esolvePrevNext），首位/末位自动置灰。

### 修复

- **P0-1 GMC 单位转换不破坏数值 grounding** — post_processor 转换 mIU/ml → IU/ml（÷1000）后，grounding 原文本中仍含原始值（如 965 mIU/ml），转换后数值 0.965 无法在原文匹配。修复：转换前把原始值/单位存 _gmc_value_raw / _gmc_unit_raw，alidate_numeric_grounding 新增 extra_values 参数同时用转换值 + 原始值做边界感知正则匹配。
- **P0-2 truncation 值排除统计聚合** — stats_engine.weighted_rate_ci 和 _common._calc_weighted_positivity / _calc_gmc / _meta_merge_cell 统一过滤 getattr(row, 'truncation', None) is None 的行，并在返回体标注 
_truncation_skipped。
- **P0-3 去重键扩展** — orchestrator._deduplicate_points 键扩展为 disease|province|city|sample_year|age_min|age_max|antibody_type|detection_method|data_kind|value，value 用 :.6g 精度归一，避免有效数据被误删。
- **P0-4 边界感知数值校验 + 千分位** — extraction_grounding._numeric_grounding_forms 对 ≥4 位整数追加千分位形式（"{int(num):,}"），alidate_numeric_grounding 用 (?<![0-9.]){form}(?![0-9]) 正则做边界检查，防止 84.3 误匹配进 184.35。
- **P0-5 DOI/PMID/年份元数据校验** — 提取回填段和 Crossref 段统一校验，摘要截断至 ≤5000 字符，无效值跳过并记录 warning。
- **S-2 备份/还原端点提升管理员权限** — POST /system/backup、GET /system/backups、GET /system/backup/download/{filename} 从 get_current_user 改为 equire_admin。
- **S-3 代理头 + 端口绑定** — backend Dockerfile CMD 追加 --proxy-headers --forwarded-allow-ips *；compose 端口改为 127.0.0.1:8000:8000 避免直连泄露。
- **S-4/S-5/S-6/S-7 CORS + /models 权限 + API Key 解密失败保护** — CORS_ORIGINS 含 * 时强制 CORS_ALLOW_CREDENTIALS=False 并警告；GET /models/GET /models/local/GET /models/remote 加 equire_admin；ApiModelConfig.api_key hybrid_property 的 setter 自动加密、getter 自动解密，失败不返回密文。
- **CI 字符串解析 fallback 次序** — post_processor._parse_ci_string 先显式匹配范围正则 (\d+(?:\.\d+)?)\s*[-–~至到]\s*(\d+(?:\.\d+)?)，再 fallback 到「取后两个数」逻辑，避免 (95% CI 16.2-19.5, P<0.05) 被解析成错误区间。
- **提取任务 value 统计口径统一** — stats_engine._as_percent 和 _meta_merge_cell 无条件 ÷100；0 < positivity_rate < 1 自动触发 suspected_fraction 问题并下调置信度至 low，供人工复核。
- **前端 API 401 导出修复** — 三个导出按钮从 window.open 改为统一的 blob 下载 service，随 Authorization header 携带 JWT。
- **文献列表 useEffect 依赖修复** — Literature.tsx 的空依赖数组 closure eslint 警告改为内联 eslint-disable-next-line react-hooks/exhaustive-deps（列表筛选参数在闭包生成时已全部就绪）。

### 文档

- README 启动命令修正：docker-compose.cpu.yml → 默认 CPU-only，GPU 用 docker-compose.gpu.yml 追加；新增 docker-compose.reuse.yml 本地开发说明；docker-start.sh GPU 探测逻辑同步改为追加 overlay。
- .env 新增 ENABLE_KG_EXTRACTION=true 样例（文档已记录，见 docs/guide/configuration.md）。

### 测试

- 新增 5 套回归测试：	est_dedup_key.py / 	est_gmc_grounding_regression.py / 	est_metadata_validator.py / 	est_numeric_grounding_boundary.py / 	est_truncation_stats.py，覆盖 P0 系列修复。
- 累计 220+ 条回归测试通过（包含既有 P0 地面真值/Schema 校验/多路径 LCS 等）。

## v1.25.0 (2026-09-14)
