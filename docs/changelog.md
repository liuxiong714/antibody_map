## 变更日志

## v1.32.0 (2026-09-26)

### 核心新功能

- **AI 提取 Prompt 大升级：三类数据全覆盖 + 动态引导**（`backend/app/core/extraction/schema.py` + `orchestrator.py`）：
  - 系统 Prompt 从「只提取血清学数据」改为「同时提取血清学 + 流行病学监测 + 病原学三类数据」，覆盖 incidence_rate / case_count / mortality_rate / death_count 等流行病学字段
  - **三类指标判别规则**：positivity_rate（分母=血清样本量） vs incidence_rate（分母=人口数） vs case_count（整数病例总数），消除模型混淆
  - **动态文本类型引导**：`_detect_text_profile()` 检测前 8000 字符中的血清学/流行病学信号词密度，纯流行病学文献自动注入「血清学字段全 null + 强制输出 incidence/case/mortality」引导段，混合型文献注入「两类都要」双重覆盖提示
  - **否定指令（anti-hallucination）**：纯流行病学文献严禁编造血清学字段（IgM、ELISA、阳性率等幻觉）
  - **强制输出指令**：有流行病学数据就必须输出，纯流行病学文献即使无血清学也不得返回空 data_points
  - **source_context 硬约束**：≤25 字关键数字短语（✅"阳性率84.3%" / ❌完整句子）
  - **Token 预算硬约束**：completion ≤ 6000，source_context 合计 ≤ 300 tokens

- **提取历史表格指标全展开 + VRAM/GPU→CPU 可视化**（`LiteratureDetail.tsx` + `extract_task.py` + `ollama_provider.py`）：
  - 表格从 15 列扩展至 20+ 列：新增 VRAM 峰值（GB，悬停看 ctx/max_out）、GPU→CPU 泄露（绿色 Tag=全 GPU，橙色 Tag=有泄露）、ctx、max_out、tps、Decode（GPU 纯生成耗时）、TTFT（首 token 延迟）、Prompt/Completion 分项
  - `ollama_provider.sample_peak_vram()` 新增 processor 判定：根据 size_vram / size 比例输出 "100% GPU" / "GPU+CPU 混合" / "主要在 CPU"
  - `extract_task.py` timing_detail 新增 processor / gpu_leak_to_cpu / num_ctx / num_predict 字段写入
  - 所有列标题加 Tooltip 解释
  - 表格滚动改为 `scroll={{ x: 'max-content' }}` 自适应（窗口够宽无横向滚动，窄则自动出现）

- **提取历史指标 CSV 批量导出 API**（`GET /api/v1/extraction/export-history` + 前端 LiteratureDetail + literature.ts）：
  - 支持按模型（LIKE 模糊）、状态、日期、文献过滤，返回 17 列指标
  - 文献详情页新增「📥 导出历史指标 CSV」按钮，供多模型横向对比分析

- **AI 提取自测文献选择器服务端分页**（`ExtractionSelfTest.tsx`）：
  - 从硬编码 100 条客户端分页改为服务端分页，pageSizeOptions [10, 20, 50, 100]
  - `preserveSelectedRowKeys: true` 保留跨页选中项

- **模型名标准化函数**（`providers/base.py` + `__init__.py`）：
  - `normalize_model_name()` 自动补全 `<provider>:` 前缀（如 `qwen3.8:27b` → `ollama:qwen3.8:27b`）
  - extract_task.py 的 effective_model 使用此函数统一处理

- **后处理器补全流行病学字段白名单**（`post_processor.py`）：
  - incidence_unit / mortality_unit / death_unit / case_count / death_count / incidence_rate / mortality_rate 全部进入白名单

- **整数清洗函数增强**（`extract_task.py` `_pm_int()`）：
  - 支持范围串归一化："677-678" → 677、"2007-2009" → 2007、"2018年" → 2018

### 测试覆盖

- 新增 `backend/tests/test_sample_peak_vram.py`（峰值显存采样测试）

### 文档（本次同步更新）

- **docs/changelog.md** — 本 v1.32.0 条目
- **docs/guide/features.md** — §2.3 历次 AI 提取历史补充 VRAM/GPU→CPU 新列 + CSV 导出 + Prompt 三类数据升级 + 动态文本类型引导
- **docs/index.md** — 智能特性区补充三类数据 Prompt 升级、VRAM/GPU→CPU 指标、批量导出
- **README.md** — 端到端工作流核心功能要点补充

---

## v1.31.0 (2026-09-25)

### 核心新功能

- **免疫屏障 R_eff NGM 残差法**（`backend/app/core/effective_immunity.py` 新增 `r_eff()` 函数）：
  - 旧 `effective_barrier()`（接触矩阵加权汇总阳性率）标记 `@deprecated`
  - 新函数用**新世代矩阵（Next Generation Matrix, Diekmann & Heesterbeek 2000）**直接计算免疫后基本再生数 `R_eff`：
    ```
    K = NGM · diag(1 − p)    # 免疫后残差 NGM
    R_eff = r0 · ρ(K) / ρ(NGM)   # 归一化到传入的参考 R0
    ```
  - R_eff < 1 才是真正的群体免疫判据——effective_barrier 加权汇总阳性率并不直接等价于"是否阻断传播"
- **免疫屏障模拟 × VE 疫苗效率**（`infectious_disease.py` / `analysis.py`）：
  - `GET /analysis/simulation` 新增 `ve` 参数（默认 1.0 兼容旧行为）
  - 新公式 `protective = coverage × VE`；加强针作用于未被保护者：`effective = protective + (1 − protective/100) × booster`
  - 返回 protective_coverage_percent、ve_used、gain_from_booster_percent
- **多情景批量模拟 API**（`GET /analysis/barrier-scenarios`）：
  - 传入 `scenarios_json: [{"name":"baseline","coverage":80,"booster":0,"ve":1}]` 批量评估
  - 每条情景同时计算 effective、R_eff、是否达 HIT、反推所需覆盖、补种人数（七普全国总人口粗估）
- **参考常量 JSON 化（透明可审计）** — 新建 `backend/app/core/reference_data/immune_barrier_constants.json`：
  - `who_thresholds`：15 种疾病 HIT 阈值（measles 95%、mumps 90%、influenza 65% 等），每条带 `value / range / source / year / citation / applicable_population / version` 7 字段
  - `r0_reference`：15 种疾病 R0（含 range，measles 15 ± 3、influenza 2.5 ± 1.1 等）
  - `nip_coverage_reference`：中国 NIP 报告分省接种覆盖
  - 后端通过 `_load_ref_constants_json() + lru_cache` 加载，对外保持原字典接口，下游消费代码零改动；报告自动引用 citation 出处
- **出生队列加权投影** — `project_barrier()` 新增 `weights` 参数：
  - 可传接触矩阵 Perron-Frobenius 主特征向量权重、标准人口权重等，基线屏障 `= Σ w_i p_i / Σ w_i`
  - 缺省仍退化为各年龄组简单平均（保持旧行为不变）
- **HIT 阈值按家族分组** — 新增 `_build_hit_threshold_families()` 工具（GOAL/WHO 文献阈值 + R0 反算 + WHO 标准三族）

### 定价更新

- **DeepSeek 官方弃用 deepseek-chat / deepseek-reasoner**，主推 **deepseek-flash / deepseek-v4-pro**
- `.env.example` / `config.py` 默认模型改为 `deepseek-flash`
- `usage_tracker.py` / `deepseek_provider.py` 新模型名沿用同款价格，旧名保留兼容

### 测试覆盖

- 新增 6 个单元测试：`test_r_eff.py`（NGM 残差法）、`test_barrier_probability.py`（达标概率）、`test_barrier_scenarios.py`（多情景）、`test_hit_threshold_families.py`（阈值家族）、`test_projection_weights.py`（出生队列权重）、`test_ref_constants_json.py`（常量 JSON 加载）、`test_simulation_ve.py`（VE 模拟）

### 文档（同步更新）

- **README.md** — 重构为端到端工作流（五步闭环 + 表格），阶段 ④ 补充 R_eff / 多情景模拟 / 参考常量
- **docs/guide/features.md** — 新增功能速览（按五大模块归类）；§5 免疫屏障评估重写为 6 小节（核心内容 / R_eff NGM / VE × 多情景模拟 / 参考常量 JSON / 使用步骤 / DeepSeek 定价）
- **docs/index.md** — 智能特性区同步更新
- **docs/changelog.md** — 本 v1.31.0 条目

### 新增静态资源

- `docs/screenshots/workflow-academic-navy.svg` — 学术主题高保真端到端工作流设计稿（供 README 引用）

---

## v1.30.0 (2026-09-24)

### 新增

- **SyntheticRun 新表 — 多模型串行评测历史**（`backend/app/models/synthetic_run.py`）：
  - 每次「单模型跑完全部文献」产生一条记录，不可覆盖；历史运行轨迹完整保留
  - 字段覆盖：task_id / model / run_index / 状态（pending/running/done/partial/failed）/ literatures_done+failed / **peak_vram_mb**（Ollama /api/ps 采样）/ summary_json（成功率、单篇耗时、首 token 延迟、tokens/s、数据点数等）/ 起止时间
  - 对应 Alembic 迁移 `add_synthetic_run_and_metrics.py`
- **多模型串行评测**（`backend/app/services/synthetic_service.py` + API `trigger_serial_multi_extraction`）：
  - 旧实现：多模型并行跑每个「模型×文献」批次 → 本地大模型 27B/30B 会 CPU 卸载、GPU 争抢
  - 新实现：**一个模型跑完全部文献 → 切换下一个**，确保 100% GPU 驻留；`SYN_MULTI_MODEL_TIMEOUT` 单模型×单文献纯抽取默认 1800s（config.py 新增）
  - 结果按 synthetic_run 分别存 synthetic_extraction，不互相覆盖
- **enable_thinking 模型原生推理开关**（贯通四层）：
  - API 层：`ExtractionRequest` / `BatchExtractionRequest` 新增 `enable_thinking: bool = False`
  - orchestrator 层：`LLMExtractor.extract_from_text()` 与 `extract_with_retry()` 新增参数并写入实例
  - `llm_client.py`：`_chat_once()` 透传到 Ollama extra_body（同时写顶层 `think` 与 options `think`，兼容 gemma4/granite 不同实现）
  - 新建 **gemma4-nothink.Modelfile**：`FROM gemma4:26b / PARAMETER think false`，供 gemma4 用户直接 pull 避免每次手动关闭思维链
- **效率指标埋点**（`llm_client.py`）：
  - `LLMClientMixin._record_timing()` 累加首 token 延迟、decode 时长、completion_tokens
  - `get_timing_summary()` 返回 calls / avg_first_token_ms / gen_seconds / tokens_per_sec
  - 自测报告 / 横向对比读取这些指标
- **自测支持编组 Tag 作为文献来源**（`synthetic.py` + `services/synthetic_service.resolve_literature_ids_by_tag()`）：
  - existing 来源可传 `tag_id`（UUID），系统自动拉取编组内全部文献；优先级：tag_id > 显式 literature_ids
  - 与 v1.29.0 新增的「文献批量选中与编组」模块打通，形成闭环

### 运维加固

- **PostgreSQL WAL 刷盘安全加固**：
  - `backend/scripts/postgresql.conf` 新建：显式 `fsync=on` + `synchronous_commit=on`
  - `docker-compose.yml`：postgres 挂载 conf + `command: ["postgres", "-c", "config_file=/etc/postgresql/postgresql.conf"]` + `stop_grace_period: 120s`
  - 容器被 SIGKILL/WSL 快速启动时最近写入也不丢
- **后台自动备份**（`backend/app/services/db_backup_service.py`）：
  - backend 启动时随 lifespan 启动后台循环（`AUTO_BACKUP_ENABLED=True` 默认开启）
  - 每 `AUTO_BACKUP_INTERVAL_MINUTES=60` 分钟执行一次 pg_dump，输出到 `BACKUP_DIR=backend/backups/`
  - 自动清理超过 `AUTO_BACKUP_KEEP_LAST=48` 份的旧备份（约保留 2 天）
  - 与 WAL 形成两层保险（最近 COMMIT 刷盘 + 每 1h SQL 快照），即便容器被强制终止也可恢复

### 迁移

- `backend/alembic/versions/add_synthetic_run_and_metrics.py` — 新建 `synthetic_run` 表 + 索引

### 文档

- **README.md** — AI 提取补充 enable_thinking；自测重写为串行 + SyntheticRun + tag_id；备份条目新增后台自动备份 + WAL；新增 gemma4 Modelfile 说明
- **docs/index.md** — 智能特性新增 4 条（串行评测、enable_thinking、WAL 加固、自动备份）
- **docs/guide/features.md** — 第 9 节（AI 自测）补充多模型串行、SyntheticRun 历史表、效率指标表、enable_thinking 小节（9.1）、gemma4 无思维链版本、tag_id 编组来源；第 13.4 节（备份）新增 WAL 刷盘加固和后台自动备份
- **docs/changelog.md** — 本 v1.30.0 条目

---

## v1.29.0 (2026-09-22)

### 新增

- **文献批量选中与编组（TXT/CSV 导入匹配）** — 新增路由 `backend/app/api/v1/literature/selection.py`：
  - 支持 `.txt`（每行一条）/ `.csv`（自动识别 uuid/标题/标题-作者-期刊 列）两种格式导入
  - 三层匹配策略：UUID 精确 → 标题+作者模糊 → 纯标题模糊，未匹配返回候选 TOP3 供前端二次确认
  - 批量打 Tag（新建/追加/覆盖三种模式），用于大规模文献分组（如"20 篇麻疹血清抗体"一次性编组分析）
- **提取历史一致性审计（extraction_history vs data_point）** — 新建服务 `backend/app/services/extraction_audit_service.py` + 新路由：
  - `GET /literatures/audit-extraction-consistency/preview`：管理员全局扫描，返回 mismatch 清单；支持按 literature_ids / model 限定，可选 only_unmarked（已修过的不再返回）
  - `POST /literatures/audit-extraction-consistency/fix`：批量修正，将 `eh.data_point_count` 改写为真实行数，未入表的记录在 `eh.error_message` 中追加 `[DP_DROPPED: eh=N, actual=0/M]` 保留审计痕迹
  - **事前校验**：`extract_task.py` 在 commit 前自动核对 batch 写入的数据点量 vs 预期数，超阈值拒绝落库
- **DISEASE_MAP 大幅扩充**（`backend/app/core/term_normalizer.py`）— 从 40+ 条目扩展到 60+：
  - 血清群合并：脑膜炎奈瑟菌 A/C/Y/W135 → 流脑
  - 结核亚型合并：肺/淋巴/潜伏/骨/淋巴结/儿童/自身免疫抗体 → 结核病
  - 新增病种：肺炎支原体、布鲁氏菌病（含牛/羊/猪型）、森林脑炎、口蹄疫（O/A/Asia1 型）、肺炎（含肺炎球菌/肺炎链球菌）、腺病毒感染、莱姆病、SFTS（发热伴血小板减少综合征）、斑点热、虫媒病毒、呼吸道感染、病毒性肝炎（泛称合并）
  - `@validates("disease")` 字段级归一化自动生效，覆盖所有 ORM 入库路径

### 修复

- **提取强制追加模式（禁用 replace）** — `extraction.py` 单篇 `POST /literatures/{id}/extraction` 和批量 `POST /literatures/extraction/batch` 两处均硬编码 `clear_existing_data=False`，忽略客户端传来的 `clear_existing_data=True`。synthetic 自测任务在服务内部直接调 `trigger_extraction` 不受此限制。防止误操作清空历史数据点
- **Literature.tsx 前端大升级**（+451 行）— 批量选中/筛选/Tag 管理 UI，配合新 selection API

### 文档

- **README.md** — AI 数据提取条目补充「追加模式安全」；新增「文献批量选中与编组」「提取历史一致性审计」
- **docs/index.md** — DISEASE_MAP 从 40+ 扩充到 60+，病种清单更新；智能特性新增 4 条（追加模式、一致性审计、批量编组、DISEASE_MAP 扩充）
- **docs/changelog.md** — 本 v1.29.0 条目

---

## v1.28.0 (2026-09-22)

### 新增

- **流行特征模块（流行病学 + 病原学监测）** — 在左侧菜单「数据分析」与「免疫屏障评估」之间新增「流行特征」入口（路由 `/epidemic`）。页面三张 Tab：
  1. **流行病学概览**：从 data_point 表中 data_type ∈ {incidence, case_count, mortality, death_count} 的已审核数据聚合展示四指标汇总卡片 + 省级分布表格（分页）。比率型（发病率/死亡率）取均值，求和型（发病人数/死亡数）直接累加，不套用阳性率的样本量加权逻辑。
  2. **病原学监测**：展示独立表 `pathogen_monitoring` 的数据，按疾病/审核状态筛选。字段覆盖病原体类型/名称、血清型、基因型、亚型、谱系（clade）、变异位点、检出率、分离株数、检测方法、标本类型、时空溯源等。
  3. **血清抗体联动**：从 data_point 拉取流行病学 data_type 明细。
- **PathogenMonitoring 独立表** — `backend/app/models/pathogen_monitoring.py` 新建，与 data_point 解耦；LLM 同一次提取调用中同步输出 pathogen_monitoring 数组（orchestrator.py 扩展 schema → post_processor 并行写入），无需额外触发一次提取任务；自带 `@validates("province")` 字段级归一化；审核状态 pending/approved/rejected。
- **多域数据扩展（data_point Schema 扩展）** — data_point 表新增字段支撑三大数据域：
  - `data_domain`（immunology/epidemiology/pathogen，默认 immunology 零迁移）、`indicator`、`numerator`/`denominator`、`period_type`（year/quarter/month/week）/`period_month`
  - `pathogen`/`serotype`/`genotype`/`lineage`/`typing_method`/`specimen_type`（病原学字段，与 disease 解耦）
  - `extra` JSONB 兜底非常规维度
  - CheckConstraint 新增 5 种 data_type：proportion / resistance_rate / positive_rate / attack_rate / secondary_attack_rate（加法扩展，不触碰既有 seroprevalence/gmc 数据）
- **数据点溯源** — data_point 新增 `model_used`（冗余直存，展示零 JOIN 开销）与 `extraction_history_id`（外键到 extraction_history，SET NULL 防级联删除）。import/synthetic/手动录入路径无 ExtractionHistory 时允许 NULL。
- **ExtractionHistory processing_status** — 提取历史表新增 `processing_status` 字段（queued/processing/completed/failed），记录批次在 Celery 队列中的实际处理阶段，与 data_point 的 extraction_status 解耦。
- **提取管线多维域扩展** — schema.py 新增 pathogen_monitoring schema 定义 + data_point 多域字段；orchestrator.py 提示词扩展同步提取病原学数据；post_processor.py 并行写 pathogen_monitoring 表；extract_task.py 任务流程扩展支持多域结果落库。
- **PathogenPanel 组件** — 嵌入 LiteratureDetail.tsx，展示单篇文献提取出的所有病原学监测数据点（基因型/血清型/谱系/检出率等）。
- **分析/详情页增强** — Analysis.tsx 多域 Tab；KnowledgeGraph.tsx 支持 pathogen 域实体；Literature.tsx 筛选/列表增强；LiteratureDetail.tsx 重写支持多域数据展示。
- **LiteraturePicker 增强** — 支持按模型/批次等多维度筛选勾选文献。

### 迁移

- `backend/alembic/versions/add_pathogen_monitoring.py` — 新建 pathogen_monitoring 表 + 索引
- `backend/alembic/versions/add_multidomain_extension.py` — data_point 新增 15 个字段 + CheckConstraint 扩展
- `backend/alembic/versions/add_datapoint_extraction_provenance.py` — data_point 新增 model_used + extraction_history_id
- `backend/alembic/versions/add_extraction_history_processing_status.py` — extraction_history 新增 processing_status

### 文档

- **README.md** — 核心功能列表新增「流行病学与病原学监测」「多域数据扩展」「数据点溯源」；AI 数据提取条目补充溯源说明
- **docs/index.md** — 快速导航新增「流行特征」，智能特性区新增 3 条
- **docs/guide/features.md** — 菜单顺序更新，新增第 4 节「流行特征」（流行病学指标 + 病原学监测 + PathogenPanel + 多域扩展字段表），后续章节顺延
- **docs/changelog.md** — 本 v1.28.0 条目

---

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
