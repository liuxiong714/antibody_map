"""V2-02 幂等迁移守护测试。

覆盖点:
  1) 所有 op.add_column 必须是 IF NOT EXISTS 形式
  2) 所有 op.drop_column 必须是 IF EXISTS 形式
  3) 所有 op.create_index 必须有 if_not_exists=True
  4) 无重复的 revision id
"""
from __future__ import annotations

import os
import re
from pathlib import Path

VERSIONS = Path(__file__).parent.parent / "alembic" / "versions"


class TestAllMigrationsCompile:
    """V2-02 守护：所有 alembic 版本文件必须能编译。"""

    def test_all_files_compile(self):
        import py_compile
        failures = []
        for f in sorted(VERSIONS.glob("*.py")):
            if f.name.startswith("__"):
                continue
            try:
                py_compile.compile(str(f), doraise=True)
            except py_compile.PyCompileError as e:
                failures.append((f.name, str(e)[:100]))
        assert not failures, f"编译失败: {failures}"


class TestAddColumnIdempotent:
    """V2-02 守护：所有 add_column 必须 IF NOT EXISTS。"""

    def test_no_raw_op_add_column(self):
        """迁移文件不应出现原始 op.add_column（非 IF NOT EXISTS 版本）。"""
        bad = []
        for f in sorted(VERSIONS.glob("*.py")):
            if f.name.startswith("__"):
                continue
            content = f.read_text(encoding="utf-8")
            if "op.add_column(" in content:
                # 检查是否用了 IF NOT EXISTS 的 op.execute 形式
                if "IF NOT EXISTS" not in content and "if_not_exists" not in content:
                    # 有些文件可能自己手写 _col_exists 函数做幂等，那也算
                    if "_col_exists" not in content:
                        bad.append(f.name)
        assert not bad, f"以下文件仍有非幂等 op.add_column: {bad}"

    def test_no_raw_op_drop_column(self):
        """迁移文件不应出现原始 op.drop_column（非 IF EXISTS 版本）。"""
        bad = []
        for f in sorted(VERSIONS.glob("*.py")):
            if f.name.startswith("__"):
                continue
            content = f.read_text(encoding="utf-8")
            if "op.drop_column(" in content:
                if "DROP COLUMN IF EXISTS" not in content and "if_exists" not in content:
                    if "_col_exists" not in content:  # 用了 _col_exists 就自己幂等了
                        bad.append(f.name)
        assert not bad, f"以下文件仍有非幂等 op.drop_column: {bad}"


class TestCreateIndexIdempotent:
    """V2-02 守护：所有 create_index 必须 if_not_exists=True。"""

    def test_no_raw_op_create_index(self):
        bad = []
        for f in sorted(VERSIONS.glob("*.py")):
            if f.name.startswith("__"):
                continue
            content = f.read_text(encoding="utf-8")
            # 找 op.create_index 的每一段 block
            idx = 0
            while True:
                pos = content.find("op.create_index(", idx)
                if pos == -1:
                    break
                # 从 pos 找 block 末尾
                depth = 1
                j = pos + len("op.create_index(")
                while j < len(content) and depth > 0:
                    if content[j] == "(":
                        depth += 1
                    elif content[j] == ")":
                        depth -= 1
                    j += 1
                block = content[pos:j]
                if "if_not_exists" not in block:
                    bad.append((f.name, content[pos:pos+80].replace("\n", " ")))
                idx = j
        assert not bad, f"以下 create_index 缺 if_not_exists: {bad[:5]}"


class TestRevisionIdsUnique:
    """迁移 revision id 必须唯一。"""

    def test_no_dup_revision(self):
        rev_map = {}
        for f in sorted(VERSIONS.glob("*.py")):
            if f.name.startswith("__"):
                continue
            m = re.search(r'revision\s*=\s*"([^"]+)"', f.read_text(encoding="utf-8"))
            if m:
                rev_map.setdefault(m.group(1), []).append(f.name)
        dups = {k: v for k, v in rev_map.items() if len(v) > 1}
        assert not dups, f"重复 revision: {dups}"
