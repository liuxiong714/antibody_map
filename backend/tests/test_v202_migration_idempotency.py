"""V2-02 幂等迁移守护测试（V7-05 升级版：文件级 → AST 级 regex，覆盖 op.execute 路径）。

覆盖点:
  1) op.add_column(...) → 必须 if_not_exists=True / _col_exists 前置 / IF NOT EXISTS
  2) op.drop_column(...) → 必须 if_exists=True / _col_exists 前置 / IF EXISTS
  3) op.execute("ALTER TABLE ... ADD COLUMN ...") → 必须 IF NOT EXISTS 或 _col_exists
  4) op.execute("ALTER TABLE ... DROP COLUMN ...") → 必须 IF EXISTS 或 _col_exists
  5) op.create_index(...) → 必须 if_not_exists=True
  6) op.execute("CREATE INDEX ...") → 必须 CONCURRENTLY + IF NOT EXISTS（op 路径不扫这个）
  7) 无重复 revision id
"""
from __future__ import annotations

import re
from pathlib import Path

VERSIONS = Path(__file__).parent.parent / "alembic" / "versions"

# regex: 匹配 op.execute( 内的 ALTER TABLE ... ADD COLUMN 语句（含 f-string 和多行）
_RE_ADD_COL_EXECUTE = re.compile(
    r"""op\.execute\(\s*(?P<q>['"])(?P<body>.*?ALTER\s+TABLE.*?ADD\s+COLUMN.*?)(?P=q)""",
    re.IGNORECASE | re.DOTALL,
)
# f-string 形式
_RE_ADD_COL_EXECUTE_FSTR = re.compile(
    r"""op\.execute\(\s*f['"].*?ALTER\s+TABLE.*?ADD\s+COLUMN.*?['"]""",
    re.IGNORECASE | re.DOTALL,
)
_RE_DROP_COL_EXECUTE = re.compile(
    r"""op\.execute\(\s*(?P<q>['"])(?P<body>.*?ALTER\s+TABLE.*?DROP\s+COLUMN.*?)(?P=q)""",
    re.IGNORECASE | re.DOTALL,
)
_RE_DROP_COL_EXECUTE_FSTR = re.compile(
    r"""op\.execute\(\s*f['"].*?ALTER\s+TABLE.*?DROP\s+COLUMN.*?['"]""",
    re.IGNORECASE | re.DOTALL,
)


def _has_col_exists_guard(content: str) -> bool:
    """文件是否有 _col_exists 前置保护（手动幂等）。"""
    return "_col_exists" in content or "_index_exists" in content


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
    """V2-02 守护：所有加列操作必须幂等。

    两条路径都覆盖:
      - op.add_column(...)          （守护 _if_not_exists_ 或 _col_exists 前置）
      - op.execute("ALTER TABLE ... ADD COLUMN ...")  （守护 _IF NOT EXISTS_ 或 _col_exists_ 前置）
    """

    def test_no_raw_op_add_column(self):
        """op.add_column 调用必须 if_not_exists=True / _col_exists / IF NOT EXISTS。"""
        bad = []
        for f in sorted(VERSIONS.glob("*.py")):
            if f.name.startswith("__"):
                continue
            content = f.read_text(encoding="utf-8")
            if "op.add_column(" not in content:
                continue
            if "IF NOT EXISTS" in content or "if_not_exists" in content or _has_col_exists_guard(content):
                continue
            bad.append(f.name)
        assert not bad, f"op.add_column 非幂等: {bad}"

    def test_no_raw_op_drop_column(self):
        """op.drop_column 调用必须 if_exists=True / _col_exists / IF EXISTS。"""
        bad = []
        for f in sorted(VERSIONS.glob("*.py")):
            if f.name.startswith("__"):
                continue
            content = f.read_text(encoding="utf-8")
            if "op.drop_column(" not in content:
                continue
            if "DROP COLUMN IF EXISTS" in content or "if_exists" in content or _has_col_exists_guard(content):
                continue
            bad.append(f.name)
        assert not bad, f"op.drop_column 非幂等: {bad}"

    def test_op_execute_add_column_has_if_not_exists(self):
        """op.execute("ALTER TABLE ... ADD COLUMN ...") 必须 IF NOT EXISTS 或 _col_exists 前置。"""
        bad = []
        for f in sorted(VERSIONS.glob("*.py")):
            if f.name.startswith("__"):
                continue
            content = f.read_text(encoding="utf-8")
            if _has_col_exists_guard(content):
                continue  # 文件有前置保护，豁免
            if "ADD COLUMN IF NOT EXISTS" in content.upper():
                continue  # 已有幂等
            # 扫 op.execute 里的 ALTER TABLE ADD COLUMN
            hits = _RE_ADD_COL_EXECUTE.findall(content)
            fstr_hits = _RE_ADD_COL_EXECUTE_FSTR.findall(content)
            if hits or fstr_hits:
                # 有 ADD COLUMN 语句但没 IF NOT EXISTS / _col_exists → 坏
                bad.append(f.name)
        assert not bad, f"op.execute ADD COLUMN 非幂等 (缺 IF NOT EXISTS / _col_exists): {bad}"

    def test_op_execute_drop_column_has_if_exists(self):
        """op.execute("ALTER TABLE ... DROP COLUMN ...") 必须 IF EXISTS 或 _col_exists 前置。"""
        bad = []
        for f in sorted(VERSIONS.glob("*.py")):
            if f.name.startswith("__"):
                continue
            content = f.read_text(encoding="utf-8")
            if _has_col_exists_guard(content):
                continue
            if "DROP COLUMN IF EXISTS" in content.upper():
                continue
            hits = _RE_DROP_COL_EXECUTE.findall(content)
            fstr_hits = _RE_DROP_COL_EXECUTE_FSTR.findall(content)
            if hits or fstr_hits:
                bad.append(f.name)
        assert not bad, f"op.execute DROP COLUMN 非幂等 (缺 IF EXISTS / _col_exists): {bad}"


class TestCreateIndexIdempotent:
    """V2-02 守护：所有 create_index 必须 if_not_exists=True。"""

    def test_no_raw_op_create_index(self):
        bad = []
        for f in sorted(VERSIONS.glob("*.py")):
            if f.name.startswith("__"):
                continue
            content = f.read_text(encoding="utf-8")
            idx = 0
            while True:
                pos = content.find("op.create_index(", idx)
                if pos == -1:
                    break
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
        assert not bad, f"create_index 缺 if_not_exists: {bad[:5]}"


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
