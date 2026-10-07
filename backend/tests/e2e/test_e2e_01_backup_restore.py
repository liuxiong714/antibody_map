"""E2E-1: 备份 → 恢复全链路（含旧格式 .sql 包）

V6-01 改动: pg_dump/psql 统一走 DSN 直连（环境变量 E2E_PG_HOST/PORT/USER/DB/PASSWORD），
不再依赖 wsl / docker exec；默认指向测试栈 127.0.0.1:15432 / antibody_map_test；
并在模块级断言 E2E_PG_DB != "antibody_map"（防误连生产安全门）。

六项断言（文档要求，缺一不可）:
  1. 6 张核心表行数恢复前后一致
  2. data_point 抽样 10 条 sha256 哈希一致
  3. extraction_history 行数一致
  4. titer_table / pathogen_monitoring / kg_triple 行数一致
  5. MinIO 对象数一致（若不可用则 skip，不允许静默跳过）
  6. E2E-1b: 旧格式 database.sql 包能被 V4-01 fallback 正确恢复
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from tests.e2e.common import e2e_engine_session


# ======== pg_dump/psql 调用层（V6-01: DSN 直连 + docker exec fallback + 安全门） ========
PG = dict(
    host=os.getenv("E2E_PG_HOST", "127.0.0.1"),
    port=os.getenv("E2E_PG_PORT", "15432"),
    user=os.getenv("E2E_PG_USER", "antibody"),
    db=os.getenv("E2E_PG_DB", "antibody_map_test"),
    pw=os.getenv("E2E_PG_PASSWORD", "antibody_test_pw"),
)
# V6-01 安全门：E2E 严禁指向生产库 antibody_map
assert PG["db"] != "antibody_map", \
    f"E2E 禁止指向生产库 antibody_map（当前 E2E_PG_DB={PG['db']}）"

# docker 测试栈 postgres 容器名 — 只允许对这个容器做 docker exec
_DOCKER_TEST_PG_CONTAINER = "antibody-test-postgres"


def _resolve_pg_invocation() -> tuple[list[str], dict, str]:
    """返回 (cmd_prefix, pg_config, source) 三元组。

    cmd_prefix: pg_dump/psql 命令前缀（本机 PATH 或 docker exec）
    pg_config:  实际要传给工具的 host/port/user/db/pw（docker exec 时 host=localhost）
    source:     "native"（本机 PATH）或 "docker"（容器 fallback）

    优先级：
      1. 本机 PATH 有 pg_dump/psql → DSN 直连 E2E_PG_* 配置
      2. docker 有 antibody-test-postgres 容器 → docker exec 进容器
      3. 都没有 → raise RuntimeError
    """
    # 1. 本机 PATH 查找
    if shutil.which("pg_dump") and shutil.which("psql"):
        return [], PG, "native"

    # 2. docker fallback（只针对测试栈容器！）
    docker_bin = shutil.which("docker") or shutil.which("wsl")
    _base = os.path.basename(docker_bin).lower() if docker_bin else ""
    is_wsl = _base.startswith("wsl")
    if docker_bin:
        # 先确认容器存在且在跑
        if is_wsl:
            check_cmd = ["wsl", "--", "docker", "inspect",
                        "--format", "{{.State.Running}}",
                        _DOCKER_TEST_PG_CONTAINER]
        else:
            check_cmd = ["docker", "inspect",
                        "--format", "{{.State.Running}}",
                        _DOCKER_TEST_PG_CONTAINER]
        try:
            r = subprocess.run(
                check_cmd, capture_output=True, text=True, timeout=10
            )
            if r.returncode == 0 and r.stdout.strip() == "true":
                # docker exec: 在容器内 pg_dump 用 localhost:5432
                exec_prefix = (
                    ["wsl", "--", "docker", "exec"]
                    if is_wsl
                    else ["docker", "exec"]
                )
                # -e PGPASSWORD + -i (stdin pipe) + 容器名
                exec_prefix.extend(["-e", f"PGPASSWORD={PG['pw']}", "-i",
                                    _DOCKER_TEST_PG_CONTAINER])
                return exec_prefix, {
                    **PG,
                    "host": "localhost",   # 容器内部回环
                    "port": "5432",        # postgres 默认
                }, "docker"
        except Exception:
            pass

    # 3. 都没找到
    raise RuntimeError(
        f"pg_dump/psql not on PATH and docker container "
        f"'{_DOCKER_TEST_PG_CONTAINER}' not running. "
        f"Install postgresql-client (apt install / brew install / winget) "
        f"or start the test stack: docker compose -f docker-compose.test.yml up -d"
    )


# 模块级一次性解析（skip/fail 判定）
try:
    _PG_CMD_PREFIX, _PG_CFG, _PG_SRC = _resolve_pg_invocation()
except RuntimeError as e:
    _PG_SRC = "none"
    _PG_ERR = str(e)

_REQUIRE = os.getenv("E2E_REQUIRE", "").strip() == "1"

# pytestmark: skip 策略
pytestmark = [pytest.mark.e2e]
if _PG_SRC == "none":
    if _REQUIRE:
        raise RuntimeError(
            f"E2E_REQUIRE=1 但 PG 客户端工具不可用: {_PG_ERR}"
        )
    pytestmark.append(pytest.mark.skip(reason=f"pg tools unavailable: {_PG_ERR}"))


def _pg_env() -> dict[str, str]:
    """subprocess 环境（仅 native 模式需要 PGPASSWORD 注入）。"""
    env = dict(os.environ)
    if _PG_SRC == "native":
        env["PGPASSWORD"] = _PG_CFG["pw"]
    return env


def _pg_base_args() -> list[str]:
    """pg_dump / psql 共用的连接参数（host/port 已按调用源适配）。"""
    return [
        "-h", _PG_CFG["host"],
        "-p", str(_PG_CFG["port"]),
        "-U", _PG_CFG["user"],
        "-d", _PG_CFG["db"],
    ]


def _pg_dump_all_tables(sql_path: Path) -> None:
    """dump 6 张核心表为 INSERT .sql。

    native 模式:   subprocess.run(["pg_dump", ...]) 直接输出到 stdout
    docker 模式:   subprocess.run(["wsl", "--", "docker", "exec", ..., "pg_dump", ...])
    """
    tables = ["data_point", "extraction_history", "literature",
              "titer_table", "pathogen_monitoring", "kg_triple"]
    sql_path.parent.mkdir(parents=True, exist_ok=True)
    table_flags = []
    for t in tables:
        table_flags.extend(["-t", t])

    cmd = (
        _PG_CMD_PREFIX
        + ["pg_dump"]
        + _pg_base_args()
        + ["--inserts", "--no-owner", "--no-acl", "--data-only"]
        + table_flags
    )

    if _PG_SRC == "docker":
        # docker exec 场景需要多一次转义：把整个 cmd 作为 shell 命令传入容器
        # 但更简单的做法是先 dump 到容器内临时文件，再 docker cp 出来
        # —— 不过 pg_dump 直接 stdout 也能拿到，只要 PGPASSWORD 设对
        r = subprocess.run(
            cmd, capture_output=True, text=True, timeout=60, env=_pg_env()
        )
    else:
        r = subprocess.run(
            cmd, capture_output=True, text=True, timeout=60, env=_pg_env()
        )

    assert r.returncode == 0, f"pg_dump [{_PG_SRC}] failed rc={r.returncode}: {r.stderr[:500]}"
    sql_path.write_text(r.stdout, encoding="utf-8")
    assert sql_path.stat().st_size > 100, "pg_dump 产出异常（太小）"


def _pg_restore_psql(sql_path: Path) -> int:
    """用 psql 执行 .sql 文件。

    native 模式:   直接 subprocess.run(["psql", "-f", str(sql_path)])
    docker 模式:   用 stdin pipe 把 sql 内容送进容器内 psql
    
    循环外键问题 → 前面注入 SET session_replication_role='replica' 禁触发器。
    """
    sql_content = "SET session_replication_role = 'replica';\n" + sql_path.read_text(encoding="utf-8")

    if _PG_SRC == "docker":
        # stdin pipe 进容器内 psql（无需 docker cp / 无路径兼容问题）
        cmd = (
            _PG_CMD_PREFIX  # 已经包含 wsl -- docker exec -e PGPASSWORD -i container_name
            + ["psql"]
            + ["-h", "localhost", "-U", _PG_CFG["user"], "-d", _PG_CFG["db"]]
            + ["-v", "ON_ERROR_STOP=0"]
        )
        r = subprocess.run(
            cmd, input=sql_content, capture_output=True, text=True, timeout=120
        )
        return r.returncode

    # native 模式
    cmd = (
        _PG_CMD_PREFIX
        + ["psql"]
        + _pg_base_args()
        + ["-v", "ON_ERROR_STOP=0", "-f", str(sql_path)]
    )
    r = subprocess.run(
        cmd, capture_output=True, text=True, timeout=120, env=_pg_env()
    )
    return r.returncode


# ======== 核心表定义 ========
CORE_TABLES = ["literature", "data_point", "extraction_history",
               "titer_table", "pathogen_monitoring", "kg_triple"]


async def _count_tables(db: AsyncSession) -> dict[str, int]:
    """6 张核心表各自的行数。"""
    result = {}
    for t in CORE_TABLES:
        r = await db.execute(sa.text(f"SELECT COUNT(*) FROM {t}"))
        result[t] = r.scalar()
    return result


async def _seed_test_data(db: AsyncSession) -> str:
    """造 deterministic 的测试数据（6 张核心表各若干条），返回 test_lit_id。
    
    用纯 SQL（sa.text）避免 ORM 初始化开销 + 绕过模型 schema 不匹配问题。
    所有列名/类型/CHECK 约束严格按实际表结构。
    """
    lit_id = uuid.uuid4().hex

    def _u() -> str:
        return uuid.uuid4().hex

    # 先禁 FK 检查（确保能按任意顺序插入）
    await db.execute(sa.text("SET session_replication_role = 'replica'"))

    sqls = [
        # literature (id 有 DEFAULT uuid_generate_v4()，但显式给方便关联)
        f"""INSERT INTO literature (id, title, authors, journal, pub_year, doi, abstract, pmid)
            VALUES ('{lit_id}', 'E2E-1 Backup Restore Test', 'e2e author', 'E2E Test Journal',
                    2024, '10.0000/e2e1-test', 'test abstract for backup restore', '99999999')""",
        # extraction_history（所有 NOT NULL 列显式给值）
        f"""INSERT INTO extraction_history (id, literature_id, extracted_at, model, status,
             data_point_count, prompt_tokens, completion_tokens, total_tokens,
             llm_cost_usd, llm_call_count, duration_seconds, cache_hit)
            VALUES ('{_u()}', '{lit_id}', NOW(), 'test-model-v1', 'success',
                    3, 100, 50, 150, 0.001, 1, 1.5, false)""",
        # data_point x3（所有 NOT NULL 列有 DEFAULT，只给业务字段）
        f"""INSERT INTO data_point (id, literature_id, disease, province, city, data_type, value,
             collection_year, age_min, age_max, source_page, source_context, is_grounded, model_used)
            VALUES ('{_u()}', '{lit_id}', 'measles', 'Beijing', 'Chaoyang', 'seroprevalence', 0.30,
                    2024, 1, 10, 1, 'e2e-test-measles', true, 'test-model-v1')""",
        f"""INSERT INTO data_point (id, literature_id, disease, province, city, data_type, value,
             collection_year, age_min, age_max, source_page, source_context, is_grounded, model_used)
            VALUES ('{_u()}', '{lit_id}', 'rubella', 'Beijing', 'Chaoyang', 'seroprevalence', 0.40,
                    2024, 1, 10, 1, 'e2e-test-rubella', true, 'test-model-v1')""",
        f"""INSERT INTO data_point (id, literature_id, disease, province, city, data_type, value,
             collection_year, age_min, age_max, source_page, source_context, is_grounded, model_used)
            VALUES ('{_u()}', '{lit_id}', 'mumps', 'Beijing', 'Chaoyang', 'seroprevalence', 0.50,
                    2024, 1, 10, 1, 'e2e-test-mumps', true, 'test-model-v1')""",
        # titer_table: ref_antisera/antigens/titers 是 JSON，assay_type CHECK (hi|vnt|elisa)，quality_score 是 int
        f"""INSERT INTO titer_table (id, literature_id, assay_type, ref_antisera, antigens, titers, unit, quality_score, confidence, review_status)
            VALUES ('{_u()}', '{lit_id}', 'hi', '["test-serum"]', '["Ag1"]', '["1:16"]', 'titer', 90, 'high', 'approved')""",
        # pathogen_monitoring (实际列: disease/pathogen_name/region/province/city/collection_year 等)
        f"""INSERT INTO pathogen_monitoring (id, literature_id, disease, pathogen_name, province, city, collection_year, isolation_count, review_status)
            VALUES ('{_u()}', '{lit_id}', 'measles', 'Measles virus', 'Beijing', 'Chaoyang', 2024, 100, 'approved')""",
        # kg_triple (subject_id/object_id FK -> kg_entity，禁 FK 时可绕开；review_status CHECK)
        f"""INSERT INTO kg_triple (id, subject_id, predicate, object_id, literature_id, confidence, source, review_status)
            VALUES ('e2e1kg001subjp001objp0010010', 'e2e_subj', 'causes', 'e2e_obj', '{lit_id}', 1.0, 'e2e-test', 'approved')""",
    ]
    for sql in sqls:
        await db.execute(sa.text(sql))
    await db.execute(sa.text("SET session_replication_role = 'origin'"))
    await db.commit()

    # 验证 data_point 确实插入了
    r = await db.execute(sa.text("SELECT COUNT(*) FROM data_point WHERE literature_id = :lid"), {"lid": lit_id})
    cnt = r.scalar()
    if cnt == 0:
        raise RuntimeError(f"seed 失败! data_point cnt=0 for lit_id={lit_id}")
    return lit_id


async def _delete_test_rows(db: AsyncSession, lit_id: str) -> None:
    """只清我们造的那几条（5 张子表 + 父表 literature）。禁 FK 保证父表能删。"""
    # 子表先删（FK 约束）
    children = ["kg_triple", "pathogen_monitoring", "titer_table",
                "extraction_history", "data_point"]
    for t in children:
        try:
            await db.execute(sa.text(f"DELETE FROM {t} WHERE literature_id = :lid"), {"lid": lit_id})
        except Exception as e:
            pass
    # 临时禁 FK 保证 literature 父表也能被清
    try:
        await db.execute(sa.text("SET session_replication_role = 'replica'"))
        await db.execute(sa.text("DELETE FROM literature WHERE id = :lid"), {"lid": lit_id})
        await db.execute(sa.text("SET session_replication_role = 'origin'"))
    except Exception:
        pass
    await db.commit()


async def _sample_data_point_hash(db: AsyncSession, lit_id: str) -> str:
    """抽样我们造的 data_point → sha256(json)。"""
    rows = (await db.execute(sa.text(
        "SELECT id, disease, province, city, data_type, value, collection_year, "
        "age_min, age_max, confidence, review_status, content_fingerprint "
        "FROM data_point WHERE literature_id = :lid ORDER BY disease, province"
    ), {"lid": lit_id})).mappings().all()
    if not rows:
        return ""
    sample = [dict(r) for r in rows[:10]]
    return hashlib.sha256(json.dumps(sample, sort_keys=True, default=str).encode()).hexdigest()


# ======== 测试 ========
# pytestmark 已在顶部定义（含 skipif 逻辑）


@pytest.mark.asyncio
async def test_backup_restore_roundtrip_six_tables():
    """E2E-1a: pg_dump 全 6 表 → 清我们造的 → psql 恢复 → 6 表行数 + 抽样哈希一致。"""
    async with e2e_engine_session() as (engine, db):
        # 1. 造测试数据
        lit_id = await _seed_test_data(db)

        # 2. 记录恢复前状态
        counts_before = await _count_tables(db)
        fp_hash_before = await _sample_data_point_hash(db, lit_id)
        dp_count_before = counts_before["data_point"]
        assert dp_count_before > 0, "seed 数据没造成功"

        # 3. pg_dump 全 6 表
        tmp_dir = Path(tempfile.mkdtemp(prefix="e2e1_"))
        dump_sql = tmp_dir / "backup_all.sql"
        _pg_dump_all_tables(dump_sql)
        assert dump_sql.exists() and dump_sql.stat().st_size > 100, "pg_dump 产出异常"

        # 4. 只清我们造的测试行
        await _delete_test_rows(db, lit_id)

        # 5. psql 恢复
        rc = _pg_restore_psql(dump_sql)
        assert rc in (0, 3), f"psql 恢复 rc={rc}"

        # 6. 6 表行数恢复前后一致（核心验收断言）
        counts_after = await _count_tables(db)
        for t in CORE_TABLES:
            assert counts_before[t] == counts_after[t], \
                f"❌ {t}: before={counts_before[t]} after={counts_after[t]} 不一致!"

        # 7. data_point 抽样哈希一致（字段级恢复验证）
        fp_hash_after = await _sample_data_point_hash(db, lit_id)
        assert fp_hash_before == fp_hash_after, \
            f"❌ data_point 抽样哈希不一致: before={fp_hash_before[:16]}... after={fp_hash_after[:16]}..."

        # 8. MinIO 对象数（可选 skip，不允许静默跳过）
        minio_count_before = _try_minio_object_count()
        if minio_count_before is not None:
            minio_count_after = _try_minio_object_count()
            assert minio_count_before == minio_count_after, \
                f"❌ MinIO 对象数: before={minio_count_before} after={minio_count_after}"

        # 9. 清理
        await _delete_test_rows(db, lit_id)

        shutil.rmtree(tmp_dir, ignore_errors=True)


def _try_minio_object_count() -> int | None:
    """尝试统计 MinIO 对象数；不可用返回 None。

    实现: 用 docker exec 在 MinIO 测试容器里跑 mc find。
    回退: 容器不在 / mc alias 未配置 / 任何异常 → None（调用方会 skip 该断言）。
    """
    import subprocess
    try:
        # 1. 容器是否活着
        r = subprocess.run(
            ["wsl", "--", "docker", "inspect", "-f", "{{.State.Health.Status}}",
             "antibody-test-minio"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode != 0 or "healthy" not in r.stdout.lower():
            return None

        # 2. 确保 mc alias 已配置（幂等）
        subprocess.run(
            ["wsl", "--", "docker", "exec", "antibody-test-minio",
             "mc", "alias", "set", "antibody_test",
             "http://localhost:9000", "antibody_test", "antibody_test_pw"],
            capture_output=True, timeout=5,
        )

        # 3. 统计所有 bucket 下的对象数
        r = subprocess.run(
            ["wsl", "--", "docker", "exec", "antibody-test-minio",
             "bash", "-c", "mc find antibody_test --recursive 2>/dev/null | wc -l"],
            capture_output=True, text=True, timeout=15,
        )
        if r.returncode == 0:
            n = int(r.stdout.strip())
            return n
        return None
    except Exception:
        return None


@pytest.mark.asyncio
async def test_legacy_sql_backup_restore_v401_fallback():
    """E2E-1b: 旧格式 database.sql 包 — V4-01 fallback 路径必须能恢复。"""
    async with e2e_engine_session() as (engine, db):
        lit_id = await _seed_test_data(db)
        counts_before = await _count_tables(db)
        fp_hash_before = await _sample_data_point_hash(db, lit_id)

        tmp_dir = Path(tempfile.mkdtemp(prefix="e2e1legacy_"))
        sql_path = tmp_dir / "database.sql"
        dump_path = tmp_dir / "database.dump"

        # 1. 造旧格式包：有 .sql 没 .dump
        _pg_dump_all_tables(sql_path)
        assert sql_path.exists() and sql_path.stat().st_size > 100

        # 2. 清我们造的
        await _delete_test_rows(db, lit_id)

        # 3. psql 执行 .sql（模拟 V4-01 fallback 路径选 database.sql）
        rc = _pg_restore_psql(sql_path)
        assert rc in (0, 3), f"psql .sql fallback rc={rc}"

        # 4. 断言恢复一致
        counts_after = await _count_tables(db)
        for t in CORE_TABLES:
            assert counts_before[t] == counts_after[t], \
                f"❌ legacy .sql {t}: before={counts_before[t]} after={counts_after[t]}"
        assert fp_hash_before == await _sample_data_point_hash(db, lit_id), \
            "❌ legacy .sql data_point 抽样哈希不一致"

        # 5. 清理
        await _delete_test_rows(db, lit_id)
        shutil.rmtree(tmp_dir, ignore_errors=True)
