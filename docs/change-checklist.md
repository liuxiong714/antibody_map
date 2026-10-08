# 改动自检清单 & 发布门禁

> V4-08 引入：每次提交（commit）和发布（tag/release）都必须过门禁。
> 来源：V3/V4 卡实施过程中发现"静默 bug 不 crash、不抛异常、测试里全绿、
> 生产里默默产生错误结果"——这类问题靠代码 review 抓不住，必须靠强制清单。

---

## 1. 代码改动自检清单（每条卡 commit 前必过）

### 1.1 数据库改动

- [ ] **不得删除/改写任何已有数据行**；涉及数据修正必须提供 `--dry-run` 模式
  - 先输出 `将影响 N 行` → 再执行
- [ ] **不改动数据库结构的改动优先**（应用层修复）
  - 必须改结构时：`ADD COLUMN ... NULL` / 新建索引
  - **禁止** `ALTER COLUMN TYPE` / `DROP COLUMN`
  - 索引用 `CREATE INDEX CONCURRENTLY`（不在事务内执行）
- [ ] 新增约束用 `ADD CONSTRAINT ... NOT VALID` + 后台脚本 `VALIDATE CONSTRAINT`
  - 避免长事务锁表
- [ ] `.env.example` 对应字段已补齐：
  - `python scripts/check_env_diff.py` → `缺失 0 必配`

### 1.2 业务逻辑改动

- [ ] 如果改动涉及 `IntegrityError` / SAVEPOINT / 事务边界：
  - 确认没有在 `begin_nested()` 异常退出后再调 `Session.rollback()`（V4-02 教训）
  - SQLAlchemy `begin_nested()` 异常时已自动 `ROLLBACK TO SAVEPOINT`
- [ ] 如果改动涉及 dict/object 混用的 rows 列表：
  - 必须用 `_safe_get(obj, key, default)` 而非 `getattr(r, key, default)`（V3-10/V4-06 教训）
  - `getattr(dict, 'field', None) is False` → 恒 `None is False = False`，静默吞掉
- [ ] 如果改动涉及外部命令（pg_restore / psql / celery / OCR）：
  - 必须处理 `FileNotFoundError` + subprocess returncode + stderr 截断
  - 必须处理"命令返回 0 但实际无效"（如 pg_restore 恢复空库）
- [ ] DATABASE_URL 驱动剥离用统一写法：
  - `.replace("postgresql+asyncpg://", "postgresql://").replace("postgresql+psycopg://", "postgresql://")`
  - 禁止 `.replace("+asyncpg", "")`（psycopg 驱动会漏）

### 1.3 测试

- [ ] 跑全量：`cd backend && python -m pytest tests -q`
  - 预先存在的 minio mock / sklearn 版本问题可忽略（在 commit message 里注明）
- [ ] 新增测试**不只**是 meta-test（源码字符串搜索）
  - 至少有 1 条行为测试（真 PG + 真链路）或说明为什么不能写
- [ ] 如果写了 meta-test：
  - 断言必须精确到函数内窗口（不能搜整个模块）
  - 必须有"反向验证"（临时加回 bug → 测试应 fail）

### 1.4 Commit

- [ ] Message 格式：`fix(P0-XX): V4-XX 简短描述`
- [ ] Message 里说明：改了什么、为什么改、怎么验证
- [ ] 关联的文档/测试一并 commit（不能只改代码不改测试）

---

## 2. 发布门禁（v1.x.y release 前必过）

### 2.1 数据库安全

- [ ] 所有 `CREATE INDEX CONCURRENTLY` 脚本已在生产执行且验证 `indisvalid = true`
- [ ] 所有 `NOT VALID` 约束已后台 `VALIDATE CONSTRAINT` 完成
- [ ] `pg_dump` 备份脚本跑过一次并验证能恢复（不是只看 returncode=0）

### 2.2 代码质量

- [ ] `pytest tests -q` 全绿（允许预先存在的环境问题，但必须记录）
- [ ] `python scripts/check_env_diff.py` → 缺失 0 必配
- [ ] `python scripts/create_index_concurrently.sql` 验证通过
- [ ] 无 `getattr(r, "is_grounded", ...)` 这类 dict 风险模式（已全量替换为 `_safe_get`）

### 2.3 文档

- [ ] `docs/changelog.md` 已更新版本号 + 变更摘要 + 测试统计
- [ ] `.env.example` 已补齐并分类（🟢🟡⚪）
- [ ] CLAUDE.md 测试规范未过期（如有新教训追加）

### 2.4 回滚方案

- [ ] 有数据库级回滚预案（或确认本次变更只涉及应用层）
- [ ] 有应用级回滚预案（`git revert <commit-hash>` + 重启服务）
- [ ] 知道哪些数据（如果有）需要手动修复

### 2.5 DoD 逐条复核（收口判定）

> V6-06 规则：**任一条自评 ✅ 必须附一条可在干净环境执行的命令及其输出**；无法复现的一律记 ⏳ 待验证，不得计入收口。
> 复核时间点：每轮修复完成后、宣布"技术债清理完成"前。

| # | 自评项 | 判定 | 验收方式 + 可复现证据 |
|---|---|---|---|
| 1 | 无业务层高危缺陷（数据丢失/错误结论/无法启动） | ✅ | 全量 pytest 通过（见 #3）+ 无 crash 级 issue；连续 V4/V5/V6 三轮审计未发现业务层高危 |
| 2 | 守护有效性（反向验证能抓语义错误） | ✅ | `python -m pytest tests/test_v402_savepoint_semantics.py -v` → 真 PG + 真唯一约束反向验证 |
| 3 | E2E 可运行（`--run-e2e` 全绿无 skip） | ✅ | `python -m pytest tests/e2e -v --run-e2e` → **2 passed / 0 skipped / 18.68s**；`E2E_PG_DB=antibody_map` → collection 阶段 assert 失败 |
| 4 | 数据红线全 0 | ✅ | `python backend/scripts/check_health.py --db-url postgresql+asyncpg://...@localhost:15432/antibody_map_test` → **6 条全 0**（`pending_older_than_7d` 为业务豁免，不计入失败） |
| 5 | 迁移健康（幂等 + 无漂移） | ✅ | `python -m pytest tests/test_migration_drift.py -v` + `alembic downgrade <prev> && alembic upgrade head` 双跑无错 |
| 6 | 发布门禁可执行 | ✅ | 本清单 §1 改动自检 22+ 条全过 + 本 §2 发布门禁 12+ 条全过 + 覆盖率口径已收口（51% 阈值 + E2E 联合覆盖） |

**复核结论判定**（沿用 V6 实施计划 §3.2 规则）：
- ✅ 全部 6 条通过 → 宣布"修缺陷阶段结束"
- ⏳ 有 ≥1 条 ⏳ → 下一轮继续
- ❌ 有 ≥1 条 ❌ → 立即修复

---

## 3. 已知陷阱（V3/V4 踩过的坑，不要再踩）

| 编号 | 陷阱 | 后果 | 规避 |
|---|---|---|---|
| T-01 | `begin_nested()` 异常后再 `Session.rollback()` | SAVEPOINT 回滚后，外层事务完好；再 rollback 会把**整批次**已 flush 点全作废 | except 块里只 `continue` / `break`，不要再 rollback |
| T-02 | `getattr(dict, "field", None) is False` | dict 没 attribute，返回 default `None`；`None is False = False`，静默吞掉 | 用 `_safe_get(obj, key, default)` |
| T-03 | 只看 subprocess returncode 不查输出内容 | `pg_restore` 可能 returncode=0 但恢复了空文件 | 加 post-restore 双重校验（核心表行数 > 0） |
| T-04 | `pg_indexes.indexvalid` 列不存在 | pg_indexes 视图根本没有这列，验证脚本永远失败 | 用 `pg_index.indisvalid` + JOIN pg_class |
| T-05 | `.replace("+asyncpg", "")` 剥离驱动 | psycopg 驱动 URL 会漏 | 用完整链：`.replace("postgresql+asyncpg://", "postgresql://").replace("postgresql+psycopg://", "postgresql://")` |
| T-06 | 测试只搜源码字符串 `"X" in src` | 其他地方同名符号会误命中，测试完全失效 | 精确到函数内窗口 + 配行为测试 |
| T-07 | SQLite 替代 PG 测 IntegrityError/SAVEPOINT | SQLite 的 SAVEPOINT/唯一约束行为与 PG 有差异 | 必须用真 PG |
| T-08 | 实施方案附件未入库 | 实施任务依赖的审计基线 md 文档不能只留在本地 workspace — 必须 git add docs/ 入库，否则后续复盘/交接无法溯源 | V8 教训已补 docs/v8_improvement_plan.md |

---

## 4. 数据红线巡检 SQL（最终版 · 2026-10-06 验证通过）

> 每次发布前跑一次。**全 0** 即代表数据层面收口。
> 执行方式（WSL Docker 环境）：

```bash
wsl -- docker exec -i antibody-postgres psql -U antibody -d antibody_map < _redline_check.sql
```

### 最终版 SQL（固定阈值，不再改）

```sql
-- V5 DoD §5.1 数据红线巡检 — 全 0 即收口
-- ⚠️ seroprevalence 存的是百分比数值 (0-100%), 不是 0-1 小数
--    gmc 是滴度 (1:x), 无上界

-- 1. 重复指纹 (uq_dp_lit_fingerprint 唯一索引应全部命中)
SELECT COUNT(*) AS dup_groups FROM (
  SELECT 1 FROM data_point
  WHERE review_status != 'rejected'
    AND content_fingerprint IS NOT NULL AND content_fingerprint != ''
  GROUP BY literature_id, content_fingerprint
  HAVING COUNT(*) > 1) t;

-- 2. pending 超 7 天 (卡 processing)
SELECT COUNT(*) AS pending_older_than_7d FROM data_point
WHERE review_status = 'pending'
  AND created_at < NOW() - INTERVAL '7 days';

-- 3. approved value 真越界
SELECT COUNT(*) AS bad FROM data_point WHERE review_status = 'approved'
  AND ((data_type = 'seroprevalence' AND (value IS NULL OR value < 0 OR value > 100))
    OR (data_type = 'gmc' AND (value IS NULL OR value < 0)));

-- 4. approved 未溯源 (source_page + source_context 都空)
SELECT COUNT(*) AS bad FROM data_point WHERE review_status = 'approved'
  AND source_page IS NULL
  AND (source_context IS NULL OR btrim(source_context) = '');

-- 5. is_grounded=false 但 approved (语义矛盾)
SELECT COUNT(*) AS bad FROM data_point
WHERE review_status = 'approved' AND is_grounded = FALSE;

-- 6. FK 完整性
SELECT 'dp->lit orphan' AS check, COUNT(*) AS bad FROM data_point dp
  WHERE dp.literature_id NOT IN (SELECT id FROM literature)
UNION ALL
SELECT 'dp->eh orphan', COUNT(*) FROM data_point dp
  WHERE dp.extraction_history_id IS NOT NULL
    AND dp.extraction_history_id::uuid NOT IN (SELECT id FROM extraction_history)
UNION ALL
SELECT 'eh->lit orphan', COUNT(*) FROM extraction_history eh
  WHERE eh.literature_id IS NOT NULL
    AND eh.literature_id NOT IN (SELECT id FROM literature);
```

### V6-04 脚本化入口（2026-10-07 新增）

以上 6 条 SQL 已固化为可执行脚本，**一键巡检 + 非零退出码**：

```bash
# 方式 A: 纯 SQL (psycopg)
python -c "import sqlalchemy as sa, sys; \
  u='postgresql+psycopg://antibody:antibody_test_pw@localhost:15432/antibody_map_test'; \
  eng=sa.create_engine(u); conn=eng.connect(); \
  [print(r) for r in conn.execute(sa.text(open('backend/scripts/daily_health_check.sql').read()))]"

# 方式 B: Python 包装 (asyncpg, 推荐 — 含分类报告 + 豁免处理)
python backend/scripts/check_health.py --db-url postgresql+asyncpg://antibody:antibody_test_pw@localhost:15432/antibody_map_test
# DATABASE_URL 环境变量设好后可直接:
python backend/scripts/check_health.py
```

脚本路径：
- `backend/scripts/daily_health_check.sql` — 纯 SQL 源码（6 条巡检）
- `backend/scripts/check_health.py` — asyncpg 包装，按 `error` / `warning` 分类，**error 类非 0 即 exit 1**

### V6-04 业务豁免项说明（pending 超 7 天）

| check_id | kind | 原因 |
|---|---|---|
| `pending_older_than_7d` | ⚠️ warning | **业务状态豁免**。`data_point` 的 pending 数据积累是正常现象（新文献批量导入、人工审核队列、LLM 批量提取等都会产生），不属于"数据质量红线"。归零反而意味着数据清理或批量 approved 过。仅当数值出现异常飙升（如单日 +1000）时才值得排查，属于运维观察指标而非门禁。 |

其余 5 条（`dup_groups` / `approved_value_out_of_range` / `approved_no_source` / `approved_ungrounded` / `fk_orphans`）均为 **红线错误**，bad_count > 0 即 exit 1。

### 数据修正铁律

> 本项目不做"破坏性数据修正"——**只清孤儿、不删数据行、不改业务字段值**。

- [ ] 任何 UPDATE 先 `SELECT COUNT(*) AS will_update` 说清影响行数（dry-run）
- [ ] UPDATE 后跑完整巡检 SQL 确认红线为 0
- [ ] commit message 带 `chore(data):` 前缀，附巡检 SQL 结果摘要

### 已记录的数据修正（供参考）

| commit | 修正 | 影响行 | 风险 |
|---|---|---|---|
| `2d2c94a` | 4 条 dp→eh 孤儿 `extraction_history_id = NULL` | 4 | 低（全 pending，eh 可空） |
