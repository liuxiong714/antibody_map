"""V3-05 守护: 唯一索引迁移必须有规模判断 + CONCURRENTLY 脚本。"""
from __future__ import annotations

import re
from pathlib import Path


def _alembic_versions_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "alembic" / "versions"


def _read_migration(name: str) -> str:
    for p in _alembic_versions_dir().glob(f"{name}.py"):
        return p.read_text(encoding="utf-8")
    raise FileNotFoundError(f"迁移文件未找到: {name}")


class TestV305MigrationSizeGate:
    """迁移文件必须含规模判断（大表跳过事务内建索引）。"""

    def test_size_threshold_exists(self):
        src = _read_migration("uq_dp_content_fingerprint")
        # 规模阈值常量
        assert "_SIZE_THRESHOLD" in src, "规模阈值常量缺失"
        # count(*) 查询
        assert "SELECT count(*) FROM data_point" in src, "行数检查查询缺失"
        # 跳过分支日志
        assert "跳过" in src, "大表跳过分支日志缺失"

    def test_concurrently_script_path_referenced(self):
        src = _read_migration("uq_dp_content_fingerprint")
        # 引用 concurrently.sql 脚本
        assert "concurrently.sql" in src.lower() or "CONCURRENTLY" in src, \
            "迁移未引用 CONCURRENTLY 脚本或关键字"

    def test_downgrade_idempotent(self):
        src = _read_migration("uq_dp_content_fingerprint")
        downgrade_body = re.search(r"def downgrade\(\).*?(?=\nif __name__|\Z)",
                                   src, re.DOTALL)
        assert downgrade_body, "downgrade 函数缺失"
        body = downgrade_body.group(0)
        assert "DROP INDEX IF EXISTS" in body, \
            "downgrade 非幂等 (缺 IF EXISTS)"

    def test_upgrade_has_two_paths(self):
        """upgrade 必须有两条路径: 小表(事务内) + 大表(跳过+提示)。"""
        src = _read_migration("uq_dp_content_fingerprint")
        # 找 CREATE UNIQUE INDEX (事务内) — 出现两次: 脚本注释 + f-string op.execute
        assert src.count("CREATE UNIQUE INDEX") >= 1, \
            "小表路径事务内 CREATE INDEX 缺失"
        # 找 CONCURRENTLY 提示引用 (引用脚本名即可)
        assert "concurrently" in src.lower(), \
            "大表路径 CONCURRENTLY 提示缺失"


class TestV305ConcurrentlyScriptExists:
    """CONCURRENTLY SQL 脚本必须存在且含正确语法。"""

    def test_script_file_exists(self):
        p = Path(__file__).resolve().parent.parent / "scripts" / "create_index_concurrently.sql"
        assert p.exists(), f"CONCURRENTLY 脚本缺失: {p}"

    def test_script_uses_concurrently(self):
        p = Path(__file__).resolve().parent.parent / "scripts" / "create_index_concurrently.sql"
        content = p.read_text(encoding="utf-8").lower()
        assert "create unique index concurrently" in content, \
            "脚本未用 CONCURRENTLY 关键字"

    def test_script_idempotent(self):
        p = Path(__file__).resolve().parent.parent / "scripts" / "create_index_concurrently.sql"
        content = p.read_text(encoding="utf-8").lower()
        # DROP INDEX IF EXISTS (幂等)
        assert "drop index if exists" in content, \
            "脚本非幂等 (缺 DROP IF EXISTS)"

    def test_script_precheck_sql(self):
        p = Path(__file__).resolve().parent.parent / "scripts" / "create_index_concurrently.sql"
        content = p.read_text(encoding="utf-8")
        # 前置检查 SQL (HAVING count(*)>1)
        assert "having count" in content.lower() or "having count(*)" in content.lower(), \
            "脚本缺前置重复检查 SQL"

    def test_script_txn_warning(self):
        p = Path(__file__).resolve().parent.parent / "scripts" / "create_index_concurrently.sql"
        content = p.read_text(encoding="utf-8").lower()
        # 必须有"事务外"或"不能用 BEGIN"之类的警告
        assert "事务外" in content or "不能用 begin" in content or \
               "outside transaction" in content, \
            "脚本缺 CONCURRENTLY 事务限制警告"
