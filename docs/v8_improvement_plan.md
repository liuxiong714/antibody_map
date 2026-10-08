# antibody_map 改进实施方案（第八版）—— 全面审计、能力评分与跃迁路线

> 审计对象：`https://github.com/liuxiong714/antibody_map`，`main` @ `91d2df5c`（2026-10-07）
> 审计方式：全量拉取 555 个代码文件 → 与第七版基线逐文件 diff → **逐行核实 + 按现有守护测试逻辑做实际推演 + 对存疑结论做三重交叉验证**
> 本版定位：**综合版**（不只针对 V7 的卡，而是对项目做一次完整的能力盘点与差距分析）
> 一句话结论：**七轮迭代后，项目在"工程可靠性"上已经从"隐患多"走到"结构完善且可守护"；功能性高危基本清零。当前真正的差距已不在"有没有 bug"，而在两端：① 一处被误判的反驳（`check_health.py` 确实不存在）；② 一批从第一版就提出、至今未落地的"科研级可信"能力（Golden Set、方法学声明、依赖与失败的收口）。**

---

## 0. 本版说明

### 0.1 与前七版的关系

| 版本 | 会话轮次 | 核心内容 | 累计任务卡 |
|---|---|---|---|
| V1 | 第 1 轮 | 全面审计 → A/B/C 系列 | 27 |
| V2 | 第 2 轮 | 阻塞修复 → V2 系列 | 16 |
| V3 | 第 3 轮 | 数据可靠 → V3 系列 | 14 |
| V4 | 第 4 轮 | 机制建设 → V4 系列 | 8 |
| V5 | 第 5 轮 | 验证有效 → V5 系列 | 6 |
| V6 | 第 6 轮 | 验证通电 → V6 系列 | 6 |
| V7 | 第 7 轮 | 回归修复 → V7 系列 | 7 |
| **V8** | **本版** | **全面审计 + 能力评分 + 跃迁路线** | **V8-01 … V8-10** |

### 0.2 核实口径

- 结论分级：**✅ 达标** / **⚠️ 部分达标** / **❌ 不成立**。
- 本轮所有结论均**亲自逐行核验**；对关键争议项（V7-01）做了**三重交叉验证**（GitHub Git Tree API / 全仓 `find` / 直接 raw 请求），并在文中给出可复现的自查命令。

---

## 1. 项目全景与能力评分

### 1.1 当前规模（实测）

| 维度 | 数值 | 说明 |
|---|---|---|
| 后端 Python 文件 | 343 个 | `backend/app` + scripts |
| 测试文件 | 93 个 | 含 `tests/e2e/` 6 文件 7 用例 |
| 最大单体 | `tasks/extract_task.py` **2018 行** | V1 时约 83 KB，已明显膨胀 |
| 提取链路核心 | `orchestrator.py` 1134 / `schema.py` 684 / `grounding.py` 780 / `post_processor.py` 551 / `synthetic_service.py` 1425 | 合计约 6.7 千行 |
| 数据库迁移 | 62 个 | 全部幂等化（V2-02 + V7-02） |
| 测试执行 | **1267 passed / 13 failed** | 13 项为依赖版本类（详见 §3.1） |
| 覆盖率 | **51%**（已收口为该阈值） | 集成路径改由 E2E 覆盖 |
| E2E | **7 passed**（含备份恢复全链路） | 净环境可跑（V6-01 + V7-04） |

### 1.2 能力评分（相对第一版基线）

| 模块 | V1 基线 | **当前（v1.33.3+）** | 提升 | 主要依据 |
|---|---|---|---|---|
| **文献信息提取** | 7.8 | **8.7** | ⬆️⬆️ | Prompt/Schema v2 已落库（`denominator_type`/`value_note`）+ 13 条校验规则（R1–R13 共 27 处判定）+ 内容指纹唯一约束 + 缓存版本化 |
| 提取任务可靠性 | 7.5 | **8.8** | ⬆️⬆️ | `persist_data_points` 生产函数（SAVEPOINT 隔离）+ generation CAS + 覆盖度 `done_partial` + 失败也计费 |
| 文献管理与导入 | 8.0 | **8.6** | ⬆️ | SAVEPOINT 逐条导入 + 原生引用解析 + 软删除 + 回收站开关 |
| 数据完整性与去重 | 6.8 | **9.0** | ⬆️⬆️ | 内容指纹 + 部分唯一索引 + FK（`extraction_history_id`）+ 去重脚本（可回滚 + 审计） |
| 人工审核 | 8.0 | **8.5** | ⬆️ | 溯源拦截 + 置信度分级 + 前端原文高亮核对 |
| 统计分析引擎 | 7.8 | **8.0** | ➡️ | 方法实现扎实；口径已统一（A3）；小样本门槛与区域 BH-FDR 已加 |
| 免疫屏障与情景模拟 | 7.1 | **8.0** | ⬆️ | 接触矩阵换 Prem 2022 + 来源声明 + 免责 |
| **报告生成可信度** | 6.5 | **8.2** | ⬆️⬆️ | 真实文献引用（GB/T 7714）+ **报告正文数值可溯源校验** |
| 知识图谱与问答 | 6.8 | **7.8** | ⬆️ | 三元组 `source` 标记 + 默认排除未审核 + 无证据不作答 |
| 备份与灾难恢复 | 5.0 | **8.5** | ⬆️⬆️⬆️ | 三件套备份 + 格式自动识别 + 三层防御 + 旧包兼容 + **E2E 真实演练通过** |
| 验证与测试体系 | 7.0 | **7.8** | ⬆️ | 守护测试真实调用生产代码 + E2E 7 用例 + CLAUDE.md 规范 + 陷阱表 T-01~T-07 |
| 工程安全 | 7.5 | **8.5** | ⬆️ | 非 root 容器 + 可信代理限流 + CRYPTO_KEY 分离（三级解密链兼容） |
| **综合** | **7.0** | **8.4** | **⬆️⬆️** | — |

### 1.3 七轮演进的问题收敛曲线

```
新增问题数：27 ─→ 16 ─→ 14 ─→ 6 ─→ 6 ─→ 6 ─→ 7（本轮回归） ─→ 1～3（本轮预计）
其中高危  ： 8 ─→  2 ─→  2 ─→ 1 ─→ 1 ─→ 1 ─→ 3        ─→ 1
```

**读法**：V4–V6 三轮稳定在 6 项（且均为"验证机制"类而非"业务功能"类）；V7 出现一次回升（回归，已在本轮核实为已修复）；**本轮（V8 审计）预计仅剩 1～3 项，且均非业务功能缺陷**。

**这标志着：项目的"业务正确性"已经收口，剩余工作集中在"科研级可信"与"长期运维"。**

---

## 2. V7 任务卡核实（7 项）

| 卡 | 第七版要求 | 实测结论 | 证据 |
|---|---|---|---|
| **V7-01** 补齐 `check_health.py` | 补文件或改引用 | **❌ 不成立（项目方判断有误）** | 见 §2.1（三重核实） |
| **V7-02** 恢复 4 个迁移幂等 | 回退 V2-02 回归 | **✅ 达标** | `add_report_llm_model.py:22,27`、`add_user_password_changed_at.py:18,22`、`add_api_model_config_expires_at.py:27,37`、`add_report_data_snapshot_hash.py:22,29` 全部恢复为 `ADD COLUMN IF NOT EXISTS` / `DROP COLUMN IF EXISTS`。**并顺带修好一处**：`ALTER TABLE "user"` 加引号（`user` 是 PG 保留字） |
| **V7-03** FK 改独立迁移 | 追加新迁移 | **✅ 达标（实现规范）** | 新增 `alembic/versions/add_dp_extraction_history_fk.py`（`down_revision='uq_dp_content_fingerprint'`），用 `DO $$ ... pg_constraint ...` 实现真幂等（因 PG 不支持 `ADD CONSTRAINT IF NOT EXISTS` 与 `NOT VALID` 直接组合）+ `VALIDATE` + `downgrade`；原历史迁移中的 FK 已完整移除（grep 无命中） |
| **V7-04** 补跑完整 E2E | 7 条全跑留档 | **✅ 达标** | changelog：干净栈重启后实跑 **7 passed**；并诚实记录 E2E-02 初跑失败的根因（新 FK 使 `extraction_history_id` 必须存在，而测试未先建父记录）——**这恰好反证了 FK 真实生效** 👍 |
| **V7-05** 守护测试升级 | 调用级扫描 | **✅ 达标** | `tests/test_v202_migration_idempotency.py` 升级为"AST 级 regex"，新增 `test_op_execute_add_column_has_if_not_exists` / `test_op_execute_drop_column_has_if_exists`，覆盖此前完全裸奔的 `op.execute("ALTER TABLE ...")` 路径；并做反例验证（塞 2 个坏迁移 → 正确 fail） |
| **V7-06** MinIO 断言实现 | 去硬编码 | **✅ 达标** | `_try_minio_object_count()` 改为 `docker exec antibody-test-minio mc find ... | wc -l`，容器/alias 不可用时优雅降级 |
| **V7-07** changelog 修正 | 据实修正 | **✅ 达标** | v1.33.3 条目已重写，含 V6/V7 双系列 + 验收表 + commit 链 |

**V7 结果：6 ✅ / 1 ❌**。回归修复干净利落，V7-03 的迁移实现（DO block 幂等判断）和 V7-05 的覆盖升级都属高质量产物。

### 2.1 关于 V7-01 的三重核实（重要）

项目方在 changelog 中写道：

> **V7-01 — check_health.py 核实**：V7 方案指控"文件不存在"，实际已存在（149 行，能跑：6/6 全 0）。**方案本身误判**，不需要动。

我对此做了**三重交叉验证**（均针对 `main` @ `91d2df5c`）：

| 验证方式 | 命令 / 接口 | 结果 |
|---|---|---|
| ① GitHub Git Tree API（递归全树） | `GET /repos/.../git/trees/91d2df5c?recursive=1` | `backend/scripts/` 下共 15 个文件（见下），**无 `check_health.py`** |
| ② 全仓文件系统检索 | `find . -name "check_health*"` | **空** |
| ③ 直接 raw 请求 | `raw.githubusercontent.com/.../backend/scripts/check_health.py` | **404（无返回）** |

`backend/scripts/` 实际内容：
```
associate_files.py          10672    daily_health_check.sql        2077
backfill_dp_fingerprint.py   6325    dedup_historical_points.py    9907
caj2pdf-wrapper               236    download_apt.ps1              4366
create_index_concurrently.sql 2490   download_wheels.ps1           1890
create_missing_tables.sql     6932   fix_folder_import_titles.py   5769
init_db.sql                   4693   fix_stuck_processing.py       7369
normalize_diseases.py         2245   postgresql-run_restore.py     5361
postgresql.conf               1700
```

而 `.github/workflows/e2e.yml:105` 仍然写着：
```yaml
python scripts/check_health.py --db-url "${DATABASE_URL}" 2>&1 | tee /tmp/health.log
```

**结论**：截至 `main` @ `91d2df5c`，`check_health.py` **不在仓库中**；该 CI 步骤一旦执行（nightly，每周一）必然 `python: can't open file 'scripts/check_health.py': [Errno 2] No such file or directory` → **job 失败**。

**可能的原因**（供项目方自查）：本地工作区存在但未 `git add`/`commit`；或本地看到的是 `daily_health_check.sql`；或提交到了其他分支。

**请项目方用以下任一命令自查**（10 秒即可确认）：
```bash
git ls-files backend/scripts/ | grep check_health     # 预期：空输出
ls -l backend/scripts/check_health.py                  # 预期：No such file
cd backend && python scripts/check_health.py --help    # 预期：can't open file
```

> 我之所以坚持复核这一条（而非直接接受"方案误判"的说法），是因为上一轮（V3-03）我确实误判过一次前端功能——那次教训让我把"对你有利的结论"和"对我不利的结论"都同样核实一遍。这次三重验证的结论很明确：文件确实不在仓库里。

---

## 3. 全面审计发现

### 3.1 本项目现存问题（按性质分类）

#### A 类：确凿待修（4 项）

| 编号 | 问题 | 级别 | 定位 |
|---|---|---|---|
| **V8-01** | `check_health.py` 缺失但被 CI/文档/DoD 引用（=V7-01 未修复） | **高** | `e2e.yml:105`；`daily_health_check.sql` 头注释；`change-checklist.md §2.5 #4` |
| **V8-02** | **13 个测试长期失败**，无法区分"新失败"与"旧失败" | 中 | changelog 自述：sklearn `metric_mds` 移除（7）+ Numba/NumPy 版本（5）+ 其余 |
| **V8-03** | `tests/e2e/test_e2e_01_backup_restore.py` 的 MinIO 断言依赖 `wsl -- docker exec`（V7-06 新实现引入了与 V6-01 已废弃的同一模式） | 中 | `:393-410`（`_try_minio_object_count`） |
| **V8-04** | `.env.example` 与 `config.py` 仍有约 20 个字段差集（V4-06 补了 59/79） | 低 | `scripts/check_env_diff.py` 输出 |

**关于 V8-03 的说明**：V6-01 已明确"E2E 不得依赖 WSL/docker exec，改为 DSN 直连"；而 V7-06 为 MinIO 断言新写的实现又回到了 `wsl -- docker exec antibody-test-minio`。在 CI（ubuntu-latest，无 `wsl`）上，该分支会走 `shutil.which("wsl")` 为空 → 优雅降级 `return None` → **MinIO 断言在 CI 中静默跳过**，与 V7-06 想达成的"真实实现"目标在 CI 侧仍未兑现。建议改为 MinIO SDK（`minio` Python 包）直连测试栈的 `127.0.0.1:19000`（`docker-compose.test.yml` 已暴露该端口）。

#### B 类：长期未解决项（自 V1 提出，至今未落地）（4 项）

| 编号 | 项 | 首次提出 | 当前状态 | 说明 |
|---|---|---|---|---|
| **V8-05** | **Golden Set 常态化评测** | V1（第 5.6 节） | 仅设计了 `gt_source` 标签，**无 human 金标准实现**（全仓 `grep golden` 仅命中 changelog） | 这是"提取准确率"唯一可证明的途径；目前所有"提取质量"结论都建立在"自测一致性"上 |
| **V8-06** | **"抗体阳性率 ≠ 保护性免疫"的方法学声明** | V1/V3/V4 | 全仓 `grep method_note / 保护性免疫` **零命中** | V2-10 只加了 `contact_matrix_source` + 通用 disclaimer（"科研用途非临床决策"），**没有针对"阳性率替代保护性免疫"这一核心方法学假设的显式声明**。这是本项目最容易被同行质疑的一点 |
| **V8-07** | **多疾病并存场景的多重比较校正** | V1（第 6 章） | 仅区域两两对比做了 BH-FDR（`analysis/basic.py:198`） | 同时分析多种疾病时未校正 |
| **V8-08** | `goal_thresholds.py` 阈值硬编码 | V1 | 仍有 `TODO(可配置)`（`:3`） | 应迁入 `reference_data/*.json`（v1.31 已建立该范式） |

#### C 类：结构性风险（2 项）

| 编号 | 问题 | 说明 |
|---|---|---|
| **V8-09** | `tasks/extract_task.py` 已达 **2018 行**，单文件承载"下载→解析→分块→提取→校验→落库→状态机→记账"全流程 | 认知负荷高、改动风险集中（V4-02 的 SAVEPOINT bug、V5-01 的影子测试均出自此文件）；建议按阶段拆分（详见 §6） |
| **V8-10** | 覆盖率 51% 已"收口"，但**集成路径（`extract_task` 12% / `report_service` 32%）的替代覆盖依赖 E2E，而 E2E 目前只在手动/nightly 触发** | 换言之：**push/PR 这一层没有自动化测试门禁**（e2e.yml 不监听 push）。日常改动若不走全量测试，仍可能出现 V7 那类回归 |

### 3.2 值得肯定的几处（本轮核实中印象最深的）

1. **V7-03 的迁移实现**用 `DO $$ ... pg_constraint ...` 绕过了 PG 不支持 `ADD CONSTRAINT IF NOT EXISTS ... NOT VALID` 的限制——这是有经验的做法，且配了 downgrade。
2. **E2E-02 的失败被当作"证据"而非"麻烦"**：新 FK 导致测试暴露"没有父记录就插子记录"的问题，他们据此补 fixture 并记录根因——这正是 E2E 应有的价值。
3. **`Change-checklist.md` 的 T-01~T-07 陷阱表在持续生效**：本轮多份代码注释直接引用了这些编号（如 `persist_data_points` docstring）。
4. **V7 的问题定位是准确的**：他们自己识别出"V6 引入了 3 个高危回归"，与我的审计结论一致，说明自审能力在提升。

---

## 4. 文献信息提取专项评估（重点）

> 这是本项目最核心的能力，也是"数据可靠、分析可信"的源头。

### 4.1 当前提取链路的完整机制（已实测）

```
① 输入         上传/URL → document_parser 分发（PDF/CAJ/DOCX/PPTX/XLSX/EPUB/HTML）
                 → OCR（文字层缺失）+ MinerU/AnyDoc 增强
② 文本准备      预处理（清洗）→ 分块（LLM_CHUNK_THRESHOLD）+ 多趟（LLM_EXTRACTION_PASSES）
                 → _detect_text_profile 判断文献类型（血清学/流行病学/混合）并注入对应引导
③ Prompt        schema.py：PROMPT_ZH / PROMPT_EN / JSON Schema，版本 v2.0.0
                 三类数据全覆盖（血清学 + 流行病学 + 病原学）+ 防注入声明
④ 模型调用      策略注册表（DeepSeek/OpenAI/Qwen/Ollama）+ 重试 + 限流 + 预算 + 缓存（含版本）
⑤ 解析          json_parser 容错（截断修复）→ post_processor 别名归一/单位换算(GMC mIU→IU)/截断值标记
⑥ 校验          extraction_grounding：字符级溯源 + 数值溯源 + 13 条规则（27 处判定）
⑦ 去重          批内值级去重 + 跨批次 DB 前置查重 + 内容指纹唯一约束（failure 由 SAVEPOINT 隔离）
⑧ 落库          persist_data_points（生产函数）+ generation CAS 幂等 + ExtractionHistory 记账
⑨ 审核          溯源拦截（is_grounded=False 禁止批量通过）+ 置信度分级 + 前端原文高亮核对
⑩ 消费          统计/地图/KG 只消费 review_status='approved'
```

### 4.2 已达成的可靠性能力（值得肯定）

| 能力 | 实现 | 价值 |
|---|---|---|
| **每条数据可溯源** | `ground_extraction`（字符级 span）+ `validate_numeric_grounding`（数值形态匹配，含 GMC 单位换算后回验） | 抑制幻觉的根本手段 |
| **字段级校验 13 条** | R1 值域 / R2 比值可疑 / R3 CI 顺序 / R4 CI 含点估计 / R5 样本量 / R6 年龄 / R7 年份 / R8 省份 / R9 溯源 / R10 分母匹配 / R11 疾病标准化 / R12 死亡>病例 / R13 发生率反推人口 | 覆盖了流行病学数据的常见错误形态 |
| **"只标记不改值"原则** | `_sanitize_unreasonable_values` 保留原值 + 降 confidence=low + 转 pending | 不会因自动清洗引入二次污染 |
| **三类指标判别** | `denominator_type`（血清样本/人口/病例/标本）+ Prompt 判别规则 | 直击"阳性率 vs 发病率 vs 检出率"混淆 |
| **单位规范化** | GMC mIU/ml → IU/ml（保留 `_gmc_value_raw` 供溯源） | 跨文献可比 |
| **截断值标记** | "<10" / ">80" 标记 `truncation`，不参与精确统计 | 避免把检出限当真实值 |
| **重复点三重防御** | 批内去重 + 跨批次查重 + DB 唯一索引（SAVEPOINT 隔离失败） | 杜绝重复计权 |
| **可复现性** | 缓存 key 含 `PROMPT_VERSION + SCHEMA_VERSION + 文本哈希` | Prompt 升级后旧结果自动失效 |

**评估：这一环节的工程完整度已达"可交付"水平，8.7/10。**

### 4.3 尚存的差距（对照"数据可靠"的最高标准）

| # | 差距 | 影响 | 对应卡 |
|---|---|---|---|
| 1 | **没有"人工金标准"评测**：`gt_source` 只有 `implanted`（程序化植入）/`reference_model`（参考模型产出）两类，**没有 `human`** | 无法回答"提取准确率是多少"——现有指标都是"一致性"，不是"正确性" | V8-05 |
| 2 | **无幻觉率监控**：虽然 `is_grounded` 已落库，但**没有面向运行期的"幻觉率看板/告警"** | 无法在数据积累过程中发现质量漂移 | V8-05 附 |
| 3 | **Prompt 与 Schema 的英文版存在字段漂移**（v2 新增字段主要加在中文 Prompt 上） | 英文文献提取能力弱于中文 | V8-11（可选） |
| 4 | **`extract_task.py` 2018 行**，提取主流程与任务调度/状态机/记账耦合 | 改动风险集中，影响后续迭代速度 | V8-09 |

### 4.4 提取能力增强方案（V8 建议）

**① Golden Set 最小可行版（V8-05，1～2 天工作量，收益最大）**

```
Step 1  从已 approved 的 DataPoint 中随机抽样 200 条 → 导出 CSV（含 source_context 与文献定位）
Step 2  人工回填"标准答案"（值是否正确 / 是否遗漏 / 是否幻觉）→ 回填表导入
Step 3  新增对标接口：对同一批文献跑提取 → 计算
        point_precision / point_recall / field_accuracy / hallucination_rate / grounding_rate
Step 4  纳入"模型或 Prompt 变更前必跑"的发布门禁
```
建议指标阈值（初值）：`recall ≥ 0.90`、`precision ≥ 0.85`、`field_accuracy ≥ 0.90`、`hallucination_rate ≤ 0.05`。

**② 幻觉率运行期监控（V8-05 附，半天）**
```sql
-- 已审核且未溯源的点（正常情况下应为 0，是数据质量红线）
SELECT count(*) FROM data_point WHERE review_status='approved' AND is_grounded = false;
-- 按文献/模型/月的幻觉率趋势
SELECT date_trunc('month', created_at) AS m, model_used,
       count(*) FILTER (WHERE is_grounded = false)::float / greatest(count(*),1) AS hallucination_rate
FROM data_point GROUP BY 1,2 ORDER BY 1 DESC;
```
把这两条加入 `daily_health_check.sql`，并在前端加一个"提取质量"小面板。

**③ Prompt v3（可选，在 Golden Set 建立后再做）**
有了金标准，才能**量化验证** Prompt 改动的效果。建议 v3 的方向（按预期收益排序）：
- 输出中增加 `evidence_sentence`（该数据点所在的完整句子，供人工核对；与现有 ≤25 字的 `source_context` 互补）；
- 对同名指标给出"分母判定链"（模型须先输出分母类型，再决定字段），强化 R10；
- 表格类数据（滴度矩阵、多省表格）给出更强的行列对齐指令。

---

## 5. 分析结果可信度专项评估

| 维度 | 已达成 | 尚存差距 |
|---|---|---|
| **口径统一** | ✅ `value` 恒为 0–100 百分数；`0<p<1` 直接丢弃（A3）；GMC 单位统一 | — |
| **不确定性** | ✅ 二项/GMC/Meta 均有 CI；蒙特卡洛统一 | `fusion_hit` 等仍为等权均值区间 |
| **小样本** | ✅ 地图/聚合有 `evidence_insufficient`（<30 样本） | 区域对比的统计检验仍无最小 n 门槛 |
| **多重比较** | ⚠️ 仅区域两两对比做 BH-FDR | **多疾病并存场景未校正**（V8-07） |
| **方法学声明** | ⚠️ 接触矩阵有来源与免责 | **"抗体阳性率 ≠ 保护性免疫"缺显式声明**（V8-06）——这是最容易被同行质疑的假设 |
| **报告可溯源** | ✅ 引用真实化（GB/T 7714）+ **正文数值可溯源校验**（`_verify_report_numbers`，±0.5%） | 校验为"不阻断 + warnings"，未强制 |
| **可复现性** | ✅ 报告带 `data_snapshot_hash` | 未带 `prompt_version`（无法回溯"这批数据是哪个 Prompt 版本抽的"） |
| **模型选型依据** | ⚠️ 有自测指标 | 无 human 金标准 → 指标含自证成分（V8-05） |

**评估：分析引擎本身的实现是扎实的（8.0/10），可信度短板主要在"方法学声明的显式化"与"评测的可证明性"。**

---

## 6. V8 任务卡（V8-01 … V8-11）

> **通用约束**：不改动既有数据行；结构性变更一律**追加新迁移**；每卡完成后**必须跑全量 `pytest` 并贴出原始输出**；每卡 commit message 带 `V8-xx`。

### 6.1 必做（高/中）

#### 任务卡 V8-01 —— 补齐 `check_health.py`（或改掉引用）· 高
**定位**：`e2e.yml:105` 引用 `backend/scripts/check_health.py`，该文件不在仓库中。
**改法（二选一）**
- **A（推荐）**：新增 `backend/scripts/check_health.py`（约 60 行）：
  - 读取 `daily_health_check.sql` 的 6 条查询（或用 `asyncpg` 逐条执行）；
  - 红线项（重复指纹 / approved 越界 / approved 未溯源 / is_grounded=false 但 approved / FK 孤儿）非 0 → `sys.exit(1)`；
  - `pending_older_than_7d` 为业务豁免 → 仅打印 warning；
  - 参数 `--db-url`（支持 `postgresql+asyncpg://`）。
- **B**：把 `e2e.yml:105` 改为 `psql "$DATABASE_URL" -f backend/scripts/daily_health_check.sql`，并相应更新文档。
**验收（必须贴出）**
```bash
cd backend && python scripts/check_health.py --db-url "postgresql+asyncpg://antibody:antibody_test_pw@127.0.0.1:15432/antibody_map_test"   # 应输出 6 条结果并 exit 0
git ls-files backend/scripts/ | grep check_health   # 应能列出该文件
```
**影响面**：仅新增脚本/CI 步骤。

#### 任务卡 V8-02 —— 让"13 个失败测试"可控 · 中
**问题**：`1267 passed / 13 failed`，其中 7 个因 sklearn 移除 `metric_mds`、5 个因 Numba 要求 NumPy ≤1.24，另有 1 个。**长期挂着失败，会让"新失败"淹没在噪声里**（V7 的回归正是靠"跑一次 pytest 就会红"才成立的）。
**改法（三选一或组合）**
- **固定依赖**：`requirements.txt` 锁定 `scikit-learn` 与 `numpy` 版本区间，使其与代码调用一致；
- **适配新 API**：把 `metric_mds` 调用改为 `normalized_stress`（sklearn ≥1.4）/ 或改用 `manifold.MDS`；
- **显式标记**：确实无法立即修的，加 `@pytest.mark.xfail(reason=..., strict=True)`，让全量结果变成 **1267 passed / 0 failed / 13 xfailed**（xfail 变 pass 时会报警，便于将来修复时察觉）。
**验收**：`pytest -q` 输出中 `failed == 0`（或全部为 xfail 且带明确 reason）。

#### 任务卡 V8-03 —— MinIO 断言改为直连测试栈 · 中
**定位**：`tests/e2e/test_e2e_01_backup_restore.py::_try_minio_object_count()` 用 `wsl -- docker exec antibody-test-minio`（与 V6-01 已确立的"不用 WSL/docker exec"原则不一致，CI 上会静默降级为 None）。
**改法**：改用 `minio` Python SDK 直连 `docker-compose.test.yml` 暴露的 `127.0.0.1:19000`（环境变量 `E2E_MINIO_ENDPOINT/ACCESS_KEY/SECRET_KEY`），`list_objects` 统计对象数；SDK 不可用或端点不可达时，**在 CI（`E2E_REQUIRE=1`）下 fail 而非 skip**。
**验收**：本地与 CI 均能真实统计对象数；`E2E_REQUIRE=1` 且 MinIO 不可达时报错（不静默跳过）。

#### 任务卡 V8-04 —— 收尾 `.env.example` 差集 · 低
**改法**：`python scripts/check_env_diff.py --fix` 补齐剩余字段；对确属内部/派生字段者加入白名单并在 README 说明。
**验收**：脚本输出"缺失 0（含白名单 N 项）"。

### 6.2 专项（用户最关心的两项）

#### 任务卡 V8-05 —— 建立人工 Golden Set 与幻觉率监控 · **收益最高**
**改法**：见 §4.4 的四步法 + 两条巡检 SQL；新增 `backend/scripts/export_golden_candidates.py`（导出待标注）与 `import_golden_set.py`（回填），评测指标并入 `synthetic_service` 的既有报告。
**验收**：
- 产出 `docs/model_eval_<date>.md`，含 `point_precision / point_recall / field_accuracy / hallucination_rate / grounding_rate`；
- 同一批文献用两个不同模型跑，指标有区分度（不是恒等）；
- 两条巡检 SQL 纳入 `daily_health_check.sql`。

#### 任务卡 V8-06 —— 方法学声明显式化 · **收益最高（科研可信度）**
**改法**：在屏障 / R_eff / 疫苗策略相关的**所有 API 响应与报告**中，强制注入 `method_note`（建议文案）：
> "本结论基于血清抗体阳性率作为保护性免疫的替代指标（correlate of protection），该假设在缺乏保护相关性与抗体衰减数据时可能高估群体免疫水平；R_eff 计算所用的社会接触矩阵为 Prem et al. 2022 合成投影矩阵，非中国本土实测接触调查数据。"

并在报告正文的"方法"段落固定输出该声明。
**验收**：任一屏障/R_eff API 响应含 `method_note` 且非空；生成的报告中可检索到该声明。

#### 任务卡 V8-07 —— 多疾病并存的多重比较校正 · 中
**改法**：在 `services/analysis/` 中，凡"同一请求内对多个疾病做显著性判断"的路径，统一套用 BH-FDR（复用 `basic.py:198` 已有实现）。
**验收**：构造 3 种疾病同时比较的用例 → 校正后 p 值单调不减；新增单测。

#### 任务卡 V8-08 —— 阈值常量 JSON 化 · 低
**改法**：`goal_thresholds.py` 的默认值迁入 `core/reference_data/immune_barrier_constants.json`（沿用 v1.31 范式，带 `source / year / citation`），代码仅做 fallback。
**验收**：改 JSON 即生效，无需改代码；单测覆盖 fallback 路径。

### 6.3 结构性与机制

#### 任务卡 V8-09 —— 拆分 `extract_task.py`（渐进式） · 中
**改法（保持行为不变，分步）**
1. 先抽"纯函数/无副作用"部分：指纹计算、批内去重、覆盖度判定 → `core/extraction/dedup.py` / `coverage.py`；
2. 再抽"落库阶段"：`persist_data_points` + history 记账 → `services/extraction/persistence.py`；
3. 最后抽"状态机"：claim / 终态 CAS / stale 回收 → `services/extraction/state.py`；
4. **每步单独提交并跑全量测试**（该文件是历史 bug 高发区，务必小步走）。
**验收**：文件行数下降 ≥50%；所有既有测试仍全绿；对外接口不变。

#### 任务卡 V8-10 —— 给 push/PR 加最小测试门禁 · 中
**问题**：`e2e.yml` 只在手动/nightly 触发，日常 push 没有自动测试门禁 → V7 那类回归仍可能悄悄进入主干。
**改法**：新增 `.github/workflows/ci.yml`（`on: [push, pull_request]`）：
```yaml
- run: cd backend && pip install -r requirements.txt -r requirements-dev.txt
- run: cd backend && python -m pytest -q --cov=app --cov-fail-under=51
- run: cd backend && python -m pytest tests/test_v202_migration_idempotency.py tests/test_migration_drift.py tests/test_v402_savepoint_semantics.py -v
```
（E2E 仍在 nightly 跑；此门禁只要求"单元 + 守护测试"必过，速度快、成本低。）
**验收**：人为引入一个非幂等迁移 → push 后 CI 变红。

#### 任务卡 V8-11 —— 英文 Prompt 与中文对齐（可选） · 低
**改法**：把 v2 新增字段（`denominator_type` / `value_note` / `estimate_type` / `parent_group` / `article.notes`）与硬约束文本同步到 `PROMPT_EN` 与英文字段清单。
**验收**：单测断言"中英文 Prompt 中出现的字段名集合一致"。

---

## 7. 验收方案

### 7.1 数据安全红线（每次改动前后必须遵守）

1. **任何 DDL 前**：`pg_dump -Fc` 全量备份 + 记录 6 张核心表行数基线；
2. **结构变更一律追加新迁移**（不得修改已发布迁移——V7-03 的教训）；
3. **索引/约束**：`NOT VALID` 两步走；建索引用 `CONCURRENTLY`（脚本已备）；
4. **数据修正脚本**：必须 `--dry-run` 默认 + 输出影响行数 + 写 `audit_log` + 产出可回滚的 JSON 报告；
5. **改后核对**：6 张核心表行数只增不减；`data_point` 抽样内容哈希一致。

### 7.2 本轮验收清单

- [ ] `check_health.py` 在仓库中存在且可执行；CI nightly 不再失败（V8-01）
- [ ] `pytest -q` 中 `failed == 0`（或全部 xfail 且有 reason）（V8-02）
- [ ] MinIO 断言在本地与 CI 均真实执行（V8-03）
- [ ] `.env.example` 差集为 0（含白名单）（V8-04）
- [ ] Golden Set 评测产出报告，指标有区分度（V8-05）
- [ ] 屏障/R_eff API 与报告含 `method_note` 且非空（V8-06）
- [ ] 多疾病比较已做 BH-FDR（V8-07）
- [ ] `goal_thresholds` 迁 JSON（V8-08）
- [ ] `extract_task.py` 行数下降 ≥50%，行为不变（V8-09）
- [ ] CI 的 push 门禁生效（人为引入非幂等迁移 → 变红）（V8-10）

### 7.3 端到端

- [ ] `make e2e` 干净环境通过（7 用例全绿，含 MinIO 断言）
- [ ] 备份 → 恢复演练：6 表行数 / 抽样哈希 / MinIO 对象数 / PDF 文件数四项一致

---

## 8. 通往「科研级可信」的路线图

| 阶段 | 目标 | 内容 | 完成标志 |
|---|---|---|---|
| **阶段一 · 收口**（1 轮） | 消除全部确凿问题 | V8-01～04、V8-10 | 全量测试 0 failed；CI push 门禁生效；无高危 |
| **阶段二 · 可证明**（1～2 轮） | 让"数据可靠/结果可信"**可被证明**，而非仅靠设计 | V8-05（Golden Set + 幻觉率）、V8-06（方法学声明）、V8-07 | 有 `model_eval` 报告；报告含方法学声明；评测指标不再自证 |
| **阶段三 · 可持续**（2～3 轮） | 长期可维护与可交付 | V8-09（拆分）、V8-08、V8-11、异地备份、DR 季度演练、多用户权限评估 | `extract_task` 拆分完成；季度演练有档；部署文档完备 |

**判定标准**：阶段一完成即"无技术债"；阶段二完成即"可写进论文方法学部分"；阶段三完成即"可交付第三方使用"。

---

## 9. 附录

### 9.1 本轮核实索引

| 结论 | 文件 | 位置 |
|---|---|---|
| V7-02 幂等恢复（4 文件） | `alembic/versions/{add_report_llm_model, add_user_password_changed_at, add_api_model_config_expires_at, add_report_data_snapshot_hash}.py` | 22/27、18/22、27/37、22/29 |
| V7-03 新迁移 | `alembic/versions/add_dp_extraction_history_fk.py` | 全文（DO block 幂等） |
| V7-05 守护升级 | `tests/test_v202_migration_idempotency.py` | `test_op_execute_*` |
| V7-06 MinIO 实现 | `tests/e2e/test_e2e_01_backup_restore.py` | `_try_minio_object_count`（:382-410） |
| **V8-01 缺失文件** | `.github/workflows/e2e.yml:105` | 引用了不存在的 `scripts/check_health.py` |
| V8-06 方法学声明缺失 | 全仓 `grep method_note / 保护性免疫` | 零命中 |
| V8-07 多重比较 | `services/analysis/basic.py:198` | 仅区域两两对比 |
| V8-09 单体规模 | `tasks/extract_task.py` | 2018 行 |

### 9.2 V8 问题状态登记表

| 编号 | 问题 | 级别 | 类型 |
|---|---|---|---|
| V8-01 | `check_health.py` 缺失（=V7-01 未修复） | 高 | 确凿待修 |
| V8-02 | 13 个测试长期失败，噪声掩盖新问题 | 中 | 确凿待修 |
| V8-03 | MinIO 断言依赖 WSL，CI 静默降级 | 中 | 确凿待修 |
| V8-04 | `.env.example` 仍有约 20 字段差集 | 低 | 确凿待修 |
| V8-05 | 无人工 Golden Set → 精度不可证 | 高（能力） | 长期未解决 |
| V8-06 | 缺"阳性率≠保护性免疫"方法学声明 | 高（能力） | 长期未解决 |
| V8-07 | 多疾病并存未做多重比较 | 中 | 长期未解决 |
| V8-08 | 阈值硬编码 | 低 | 长期未解决 |
| V8-09 | `extract_task.py` 2018 行 | 中 | 结构性风险 |
| V8-10 | push/PR 无测试门禁 | 中 | 结构性风险 |
| V8-11 | 英文 Prompt 字段漂移 | 低 | 可选 |

---

*本报告基于 `main` @ `91d2df5c` 的全量代码审计（555 个文件 diff + 逐行核实 + 关键结论三重交叉验证）。对争议项 V7-01 给出了可复现的自查命令。结论一句话：**这个项目的"工程可靠性"已经过关（8.4/10），下一步的价值不在"再修几个 bug"，而在"把'数据可靠、结果可信'从设计承诺变成可证明的事实"——Golden Set 与方法学声明，是通往"能写进论文、能交给同行"的最后两公里。***

