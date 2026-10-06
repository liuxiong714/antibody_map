# V3-08 历史迁移改写说明

> **目的**：记录 V3 系列中对 Alembic 历史迁移文件的改写内容、原因与边界条件。
> **约束**：后续**只追加新迁移、不改历史**。

---

## 1. 哪些 commit 改了哪些迁移

| Commit | 卡 | 改写范围 | 迁移数 | 内容 |
|---|---|---|---|---|
| `23fc6ba` | **V2-02 → V3-13** | 全量 36 个 alembic 版本 | 36 | `upgrade()` 内 `op.add_column`/`op.create_index` 补 `if not exists=True`；`downgrade()` 内 `op.drop_column`/`op.drop_index`/`op.drop_constraint` 补 `if_exists=True` |
| `3e4dfe1` | V2-05 | 新增 `uq_dp_content_fingerprint.py` | +1 | 新建唯一索引迁移（不涉及改写历史） |
| `d9a28bb` | V2-05 Step3 | 改写 `uq_dp_content_fingerprint.py` | 1 | 原迁移是"先 drop 再 create"，补 `CONCURRENTLY` 规模判断（见 V3-05） |
| `c9ab926` | V3-05 | 同上 | 0（重写而非新增） | 同上，把纯文本迁移改成规模判断 + 独立 SQL 脚本 |

**合计被改写过的历史迁移文件：35 个**（36 - 1 个是新建）。

---

## 2. 为什么可以改历史

### 2.1 Alembic 不校验 revision hash

Alembic 的 `alembic_version` 表只记录 `version_num`（revision id），不记录迁移文件内容的 hash。
因此**改写一个已存在的迁移文件不会让已跑过该迁移的环境报错**——它只看 version_num 是否已存在，不比对文件内容。

### 2.2 幂等改写是安全方向

V3-13 / V2-02 做的改动方向是**让迁移在目标对象已存在时静默通过**（`IF NOT EXISTS` / `if_exists=True`），
不会改变最终 schema 状态，只会让"重复跑"或"半跑失败后重跑"的场景不再报错。

### 2.3 改写类型总结

| 类型 | 数量 | 风险 | 说明 |
|---|---|---|---|
| `op.add_column(..., nullable=True)` → `op.add_column(..., nullable=True)` + `if not exists=True` | ~18 | 极低 | IF NOT EXISTS 是 PostgreSQL 原生语法 |
| `op.create_index` → 加 `if not exists=True` | ~8 | 极低 | 同上 |
| `op.drop_column` → 加 `if_exists=True` | ~5 | 极低 | 同上 |
| `op.drop_index` → 加 `if_exists=True` | ~3 | 极低 | 同上 |
| `op.create_unique_constraint` → 加 `if not exists=True` | ~1 | 极低 | PostgreSQL 15+ 原生支持 |
| `op.execute("DROP ...")` → 改 `DROP ... IF EXISTS` | ~2 | 极低 | 同上 |

**没有任何 `ALTER COLUMN TYPE` / `DROP COLUMN` / 重命名 / 重排顺序之类的破坏性改写。**

---

## 3. 风险与缓解

### 3.1 风险：新环境首跑行为差异

如果一个全新数据库**按时间顺序**跑所有迁移：
- 原迁移：正常建列/建索引（无 IF NOT EXISTS 分支）
- 改写后：建列/建索引（有 IF NOT EXISTS 分支，但首次跑时目标不存在，走正常路径）

**结论：首跑行为与原迁移完全一致。** IF NOT EXISTS 只在"重复跑"场景有区别，让它从"报错"变成"跳过"。

### 3.2 风险：部分环境 downgrade 不幂等

如果有人手动把 `alembic_version` 表回退几行，再跑 `alembic upgrade head`：
- 原迁移：`add_column` 会因为列已存在而抛 `ProgrammingError`
- 改写后：`add_column` 因为列已存在而静默跳过，继续执行

**结论：改写后反而更健壮。** 这就是 V2-02 / V3-13 的设计目标。

### 3.3 风险：团队不知情

新同事看到 Alembic 迁移文件被改过，可能误以为"Alembic 不允许这么干"。
**本文件就是要消除这个误解。**

---

## 4. 边界声明

### ✅ 允许的改写（已做过）
- `upgrade()` / `downgrade()` 内的 `if not exists` / `if_exists` 补充
- 把纯 SQL 的 `CREATE INDEX` 迁移改成 `CONCURRENTLY` + 规模判断（见 V3-05）
- 把 `DROP COLUMN` 改成 `DROP COLUMN IF EXISTS`

### ❌ 禁止的改写（后续）
- **改写 `down_revision` 链**（会断历史）
- **删除迁移文件**（会让 Alembic 无法从 `alembic_version` 追溯）
- **改变 `version` 字符串**（同理）
- **破坏迁移文件的幂等性**（去掉已补的 IF NOT EXISTS）
- **追加新操作**到已发布迁移（比如在旧迁移里加新列）

---

## 5. 参考

```
git show 23fc6ba --stat          # V3-13 幂等化全量
git show c9ab926 --stat          # V3-05 唯一索引 CONCURRENTLY 改造
git show d9a28bb --stat          # V2-05 Step3 backfill + 唯一索引
git log --oneline -- alembic/versions/ | head -20
```

## 6. 相关测试

- `tests/test_v202_migration_idempotency.py` — 断言迁移文件不含裸 `op.add_column` / `op.drop_column`（V2-02 验收）
- `tests/test_v305_index_concurrently.py` — 断言 CONCURRENTLY 逻辑（V3-05 验收）
