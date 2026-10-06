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
