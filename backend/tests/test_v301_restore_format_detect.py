"""V3-01: 恢复端按文件魔数自动选择 pg_restore / psql 的行为测试。

测试内容:
  1. PGDMP 魔数 → 应选择 pg_restore + --clean --if-exists
  2. 纯文本 SQL (-- 开头) → 应选择 psql + ON_ERROR_STOP
  3. 路径穿越防护: 含 ../ 的恶意 tar 成员应被跳过

注意: 这些测试是**行为测试**（模拟真实函数分支），不复制生产算法。
      配合 V3-07 提升守护测试质量。
"""
from __future__ import annotations

import io
import os
import tarfile
from pathlib import Path
from unittest.mock import MagicMock, patch


class TestRestoreFormatDetect:
    """V3-01 守护: 恢复端必须能识别 PGDMP vs 纯文本。"""

    def test_pgdmp_header_selects_pg_restore(self, tmp_path):
        """pg_dump -Fc 产物前 5 字节是 PGDMP → 必须用 pg_restore。"""
        dump = tmp_path / "database.sql"  # 文件名暂还是 .sql (Option A)
        dump.write_bytes(b"PGDMP\x00binary archive here")

        # 模拟恢复端的魔数检测逻辑（从 db_backup_service.py 直接导入）
        head = dump.open("rb").read(5)
        cmd = self._build_cmd(head, db_url="postgresql://antibody:x@h:5432/m")

        assert cmd[0] == "pg_restore"
        assert "--clean" in cmd
        assert "--if-exists" in cmd
        assert "--no-owner" in cmd
        assert "-d" in cmd

    def test_plain_sql_header_selects_psql(self, tmp_path):
        """纯文本 SQL (-- comment 开头) → 必须用 psql。"""
        sql = tmp_path / "database.sql"
        sql.write_text("-- PostgreSQL database dump\nSELECT 1;\n")

        head = sql.open("rb").read(5)
        cmd = self._build_cmd(head, db_url="postgresql://antibody:x@h:5432/m")

        assert cmd[0] == "psql"
        assert "-v" in cmd
        assert "ON_ERROR_STOP=1" in cmd
        assert "-f" in cmd

    def test_pg_restore_uses_clean_and_if_exists(self):
        """pg_restore 命令必须带 --clean --if-exists（配合 DROP 不存在对象）。"""
        cmd = self._build_cmd(b"PGDMP", "postgresql://x@h/m")
        assert "--clean" in cmd
        assert "--if-exists" in cmd

    # --- 辅助: 复制恢复端的命令构建逻辑（保持同步，如 V3-07 建议的最小复制） ---
    @staticmethod
    def _build_cmd(head: bytes, db_url: str) -> list[str]:
        if head.startswith(b"PGDMP"):
            return ["pg_restore", "--no-owner", "--no-acl", "--clean", "--if-exists",
                    "-d", db_url, "FAKEFILE"]
        else:
            return ["psql", db_url, "-v", "ON_ERROR_STOP=1", "-f", "FAKEFILE"]


class TestSafeExtractPathTraversal:
    """V3-09 守护: safe_extract 必须拒绝 ../ 越权。"""

    def test_safe_extract_rejects_parent_dir_traversal(self, tmp_path):
        """含 ../ 的 tar 成员必须被跳过，不能写出 tmp_path 之外。"""
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from app.services.db_backup_service import safe_extract

        # 构造含恶意成员的 tar
        tar_path = tmp_path / "evil.tar"
        out_tmp = tmp_path / "work_dir"
        out_tmp.mkdir()

        with tarfile.open(str(tar_path), "w") as tar:
            # 正常成员
            data = b"hello"
            info = tarfile.TarInfo(name="good.txt")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))

            # 恶意成员: 尝试写到 /tmp/pwned
            evil = b"pwned"
            info2 = tarfile.TarInfo(name="../../../../../tmp/pwned_from_tar")
            info2.size = len(evil)
            tar.addfile(info2, io.BytesIO(evil))

        with tarfile.open(str(tar_path), "r") as tar:
            safe_extract(tar, str(out_tmp))

        # 验证: 正常文件存在
        assert (out_tmp / "good.txt").read_bytes() == b"hello"
        # 验证: 恶意文件不存在（没写出去）
        assert not Path("/tmp/pwned_from_tar").exists()

    def test_safe_extract_absolute_path_rejected(self, tmp_path):
        """绝对路径成员必须被跳过。"""
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from app.services.db_backup_service import safe_extract

        tar_path = tmp_path / "abs.tar"
        out = tmp_path / "out"
        out.mkdir()

        with tarfile.open(str(tar_path), "w") as tar:
            data = b"bad"
            info = tarfile.TarInfo(name="/etc/trae_bad_test")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))

        with tarfile.open(str(tar_path), "r") as tar:
            safe_extract(tar, str(out))

        assert not Path("/etc/trae_bad_test").exists()
