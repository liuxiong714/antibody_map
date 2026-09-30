"""test_migration_drift.py — Batch 0 硬性检查：alembic current == heads。

触发时机：pytest 全量回归 + backend 启动 lifespan。
失败即 AssertionError 带清晰指引，不会静默漂移。

根因背景（2026-09-30 Session 暴露并修复）：
env.py 用 Base.metadata.create_all 兜底 + mergepoint 迁移脚本无 DDL +
幂等 ALTER TABLE IF NOT EXISTS → alembic_version 表版本号可能滞后于实际 heads。
不检查的话后续任何 schema 改动都可能因"以为已 apply 其实没写版本号"出问题。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


BACKEND_DIR = Path(__file__).resolve().parent.parent


def _run_alembic(*args: str) -> str:
    """子进程跑 alembic，stdout 正常返回，stderr 抛异常。"""
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=str(BACKEND_DIR),
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"alembic {' '.join(args)} 失败 (rc={result.returncode}):\n"
            f"stdout:\n{result.stdout[-800:]}\nstderr:\n{result.stderr[-800:]}"
        )
    return result.stdout


def _parse_heads(output: str) -> set[str]:
    """从 `alembic heads` 输出解析所有 head revision id。"""
    heads: set[str] = set()
    for line in output.strip().splitlines():
        # 输出形如: "add_kg_triple_source (head)" 或 mergepoint 多个
        line = line.strip()
        if not line or line.startswith("INFO"):
            continue
        rev = line.split()[0]
        if rev and rev.isidentifier():
            heads.add(rev)
    return heads


def _parse_current(output: str) -> set[str]:
    """从 `alembic current` 输出解析当前 revision id(s)。"""
    currents: set[str] = set()
    for line in output.strip().splitlines():
        line = line.strip()
        if not line or line.startswith("INFO"):
            continue
        # alembic current 对 mergepoint 会输出多行
        rev = line.split()[0]
        if rev and rev.isidentifier():
            currents.add(rev)
    return currents


@pytest.mark.migration
@pytest.mark.integration
def test_alembic_current_equals_heads():
    """硬性断言：DB 已 apply 的 revision 集合 == 脚本链 heads 集合。

    失败时清晰列出 missing/extra，指向 `alembic upgrade heads` 或
    `alembic stamp <head>` 作为修复方案。
    """
    heads_out = _run_alembic("heads", "--quiet") if False else _run_alembic("heads")
    current_out = _run_alembic("current")

    heads = _parse_heads(heads_out)
    currents = _parse_current(current_out)

    assert heads, "未找到任何 alembic head 脚本 — migrations/versions/ 是否为空？"

    missing = heads - currents   # heads 中但 DB 未 apply
    extra = currents - heads     # DB 中但脚本链已无（不应发生）

    assert not missing and not extra, (
        f"\n=== Alembic 迁移链漂移！===\n"
        f"脚本链 heads:   {sorted(heads)}\n"
        f"DB 当前 version: {sorted(currents)}\n"
        f"缺失 (head 未 apply):  {sorted(missing) if missing else '(无)'}\n"
        f"多余 (DB 有但脚本无):  {sorted(extra) if extra else '(无)'}\n\n"
        f"修复步骤（选其一）:\n"
        f"  1. 如果 DDL 已手动执行过，只需同步版本号:\n"
        f"     alembic stamp {list(heads)[0]}\n"
        f"  2. 如果 DDL 还没执行:\n"
        f"     alembic upgrade heads\n"
    )
