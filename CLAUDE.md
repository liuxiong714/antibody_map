# CLAUDE.md — antibody_map 项目协作规范

> V4-04 引入：基于 V3/V4 卡实施过程中发现的"meta-test 完全失效"教训

## 0. 当前执行上下文（V8 / 2026-10-08）

- 最新版本: **v1.34.0** — V8 全面审计与跃迁路线，11 张任务卡 **9/11 完整达标**
- pytest: **1270 passed / 0 failed**（5 xfail / 11 skipped 为已知版本兼容项）
- CI: .github/workflows/ci.yml 已加 on: [push, pull_request] 门禁
- **V8 审计基线文档**: docs/v8_improvement_plan.md（本版实施方案，含 11 张卡验收标准与实测对照表）
- **V8 增量改动范围**（10 commits）: check_health.py / pytest 13→0 / MinIO SDK / Golden Set export / 方法学声明 / BH-FDR 工具化 / goal_thresholds JSON / dedup_utils 拆分 / Prompt 对齐 / CI push 门禁
- 剩余缺口: V8-05 import_golden_set.py（需人工标注）、V8-09 Step 2/3（persistence/state 层拆分）
（如 test_v302
> 反转 rollback 断言、test_v213 仅断言 flag 存在不测真实 subprocess 路径）。

## 1. 测试编写：优先行为测试，谨慎 meta-test

### ✅ 推荐：行为测试（运行时验证）

```python
# 好: 用真实 ORM + 真 PG 引擎跑完整链路
async def test_integrity_error_preserves_prior_points():
    engine = create_async_engine(PG_URL)
    async with AsyncSession(engine) as db:
        await db.execute(insert(DataPoint).values(id=uuid4(), content_fingerprint="FP_A", ...))
        await db.commit()
        # 第二条指纹冲突（触发 UNIQUE 约束）
        with pytest.raises(IntegrityError):
            await db.execute(insert(DataPoint).values(id=uuid4(), content_fingerprint="FP_A", ...))
        # 关键断言: 冲突前的第一条应该还在
        count = (await db.execute(select(func.count(DataPoint.id)))).scalar()
        assert count == 1, "冲突前的数据点被 SAVEPOINT 回滚丢了"
```

### ⚠️ 禁止（除非明确标记为"最低屏障"并配行为测试）：源码字符串断言

```python
# 差: 只检查源码里有没有 "rollback"，extract_task 其他地方的 rollback 会误命中
def test_rollback_in_error_path():
    src = inspect.getsource(extract_task)
    assert "rollback" in src  # V4-02 证伪: 这个断言在修复后仍通过！
```

**例外情况**：可接受纯 meta-test 的前提：
- 同时有至少 1 条行为测试覆盖同一段代码路径
- 或代码是纯配置/纯声明（如路由注册、依赖注入 wiring）
- 且必须精确到函数内窗口（不能搜整个模块），如：
  ```python
  window = src[src.find("except IntegrityError"):src.find("except IntegrityError")+1500]
  assert "await db.rollback()" not in window  # 精确窗口，排除其他地方的 rollback
  ```

### 🔴 绝对禁止

1. 只做源码字符串搜索、不跑任何真实数据库/外部依赖的测试作为**唯一**守护
2. 断言 `"X" in src` 但 `src` 范围是整个模块（容易被其他同名符号误命中）
3. mock 掉被测函数本身的测试（那是测 mock，不是测代码）

## 2. 数据库测试规范

### 2.1 真实 PG 优先

- **IntegrityError、SAVEPOINT、UNIQUE/FOREIGN KEY 约束**：必须用真实 PostgreSQL
- SQLite 在这些场景下**不完全兼容**（JSONB/ARRAY/UUID/SAVEPOINT 行为差异）
- DATABASE_URL: `postgresql+asyncpg://antibody:antibody123@localhost:5432/antibody_map`

### 2.2 不污染真实库

- 每条测试用独立的 `create_async_engine` + 临时 schema 或临时表
- 或用 `TRUNCATE ... RESTART IDENTITY` 清理（只限测试用专用 schema）
- **绝对不**在生产/开发共用库里跑破坏性测试

### 2.3 CHAR(32) UUID 注意

- `literature.id`, `data_point.id`, `extraction_history.id` 都是 `CHAR(32)`（hex UUID 无连字符）
- 用 `uuid.uuid4().hex` 生成，**不要**用 `str(uuid.uuid4())`（带连字符会 FK 失败）

## 3. 代码改动自检清单（每条卡必过）

按 V4-08 约束：改完跑这 6 项再 commit：

- [ ] `cd backend && python -m pytest tests -q` 全绿（预先存在的 minio mock / sklearn 版本问题可忽略）
- [ ] 不删除/改写任何已有数据行（涉及数据修正需 `--dry-run`）
- [ ] 数据库结构变更只走 `ADD COLUMN ... NULL` / `CREATE INDEX CONCURRENTLY`
- [ ] 新增约束用 `NOT VALID` + 后台 `VALIDATE CONSTRAINT`
- [ ] commit message: `fix(P0-XX): ...` 格式，附 V4-XX 卡号
- [ ] 改动若涉及多文件/多函数，加对应行为测试

## 4. 环境变量文档化

- 每次新增 Settings 类字段后跑 `python scripts/check_env_diff.py` 检查
- 🟢 用户需配置 / 🟡 可选覆盖 → 必须在 `.env.example` 里（非注释）
- ⚪ 内部豁免 → 白名单在 `scripts/check_env_diff.py` 的 `INTERNAL_FIELDS` 里

## 5. E2E 测试（`backend/tests/e2e/`）

- 全链路测试（备份→恢复、提取→落库→报告）走 E2E 目录
- E2E 测试默认 skip（`@pytest.mark.e2e`），需显式 `--run-e2e`
- **本地跑**：`pytest tests/e2e -v --run-e2e` — 当前 **7 passed / 0 skipped**
- **pg_dump/psql 宿主无关调用**（关键！）：
  - **不要**在宿主 Windows 上找 pg_dump/pg_restore — postgres:15-alpine 镜像自带
  - 用 `wsl -- docker exec antibody-postgres pg_dump -U antibody -d antibody_map ...`
  - 或 Python subprocess：`['wsl', '--', 'docker', 'exec', '-i', 'antibody-postgres', 'pg_dump', ...]`
- **不要用 `docker compose down -v` 清 test compose** — 会连带清共享网络；`docker-compose.test.yml` 已加 `name: antibody_test` 隔离
- **CI workflow**：`.github/workflows/e2e.yml` — 手动触发 + weekly nightly；CI 环境 postgres 镜像自带 pg_dump 工具链，不需要 docker exec 迂回
- **注意**：E2E-02 (重复写入) 已改用 V5-01 的 `persist_data_points()` 生产函数，不再复刻写库循环（V5-01 消除影子测试）
