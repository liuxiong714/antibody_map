"""db_backup_service 单测（mock subprocess / asyncpg / minio / tarfile，无需真实基础设施）。

目标：将 services/db_backup_service.py 从 0% 提升至 65%+。
"""
from __future__ import annotations

import glob
import subprocess
import tarfile
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.services import db_backup_service as svc


# ---------------------------------------------------------------------------
# helpers / fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def _patch_backup_dir(tmp_path, monkeypatch):
    backup_dir = tmp_path / "backups"
    monkeypatch.setattr("app.services.db_backup_service.settings.BACKUP_DIR", str(backup_dir))
    monkeypatch.setattr("app.services.db_backup_service.settings.DATABASE_URL",
                        "postgresql+asyncpg://antibody:secret@postgres:5432/antibody_map")
    monkeypatch.setattr("app.services.db_backup_service.settings.BACKUP_TIMEOUT", 60)
    monkeypatch.setattr("app.services.db_backup_service.settings.AUTO_BACKUP_KEEP_LAST", 3)
    return backup_dir


def _fake_completed(rc=0, stderr="", stdout=""):
    return SimpleNamespace(returncode=rc, stderr=stderr, stdout=stdout)


def _make_fake_run_ok(dump_file: Path, content: bytes = b"-- pg dump\n"):
    """返回一个 subprocess.run 的 side_effect：先创建 dump_file，再返回成功。"""
    def fake_run(*a, **kw):
        # args 里的 cmd[cmd.index("--file") + 1] 就是 dump 路径
        cmd = a[0] if a else kw.get("args", [])
        if "--file" in cmd:
            idx = cmd.index("--file")
            p = Path(cmd[idx + 1])
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(content)
        return _fake_completed(rc=0)
    return fake_run


def _fixed_now():
    return datetime(2026, 9, 30, 12, 0, 0)


# ---------------------------------------------------------------------------
# _pg_dump
# ---------------------------------------------------------------------------

class TestPgDump:

    def test_success_creates_dump_and_latest(self, _patch_backup_dir):
        backup_dir = _patch_backup_dir
        with patch("subprocess.run", side_effect=_make_fake_run_ok(
            backup_dir / "auto_backup_20260930_120000.sql"
        )), patch("app.services.db_backup_service.datetime") as m_dt:
            m_dt.now.return_value = _fixed_now()
            ok, msg = svc._pg_dump()

        assert ok is True
        assert "auto_backup_20260930_120000.sql" in msg
        assert (backup_dir / "auto_backup_20260930_120000.sql").exists()
        assert (backup_dir / "latest_backup.sql").exists()

    def test_timeout(self, _patch_backup_dir):
        with patch("subprocess.run",
                   side_effect=subprocess.TimeoutExpired(cmd="pg_dump", timeout=60)):
            ok, msg = svc._pg_dump()
        assert ok is False
        assert "timeout" in msg

    def test_pg_dump_not_found(self, _patch_backup_dir):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            ok, msg = svc._pg_dump()
        assert ok is False
        assert "not found" in msg

    def test_pg_dump_nonzero_returncode_deletes_small_dump(self, _patch_backup_dir):
        backup_dir = _patch_backup_dir

        def fake_run_bad(*a, **kw):
            cmd = a[0] if a else kw.get("args", [])
            if "--file" in cmd:
                idx = cmd.index("--file")
                p = Path(cmd[idx + 1])
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(b"-- truncated\n")  # small file → 应被清理
            return _fake_completed(rc=1, stderr="FATAL: connection refused")

        with patch("subprocess.run", side_effect=fake_run_bad), \
             patch("app.services.db_backup_service.datetime") as m_dt:
            m_dt.now.return_value = _fixed_now()
            ok, msg = svc._pg_dump()

        assert ok is False
        assert "FATAL" in msg
        # 小文件应该被删掉
        dump = backup_dir / "auto_backup_20260930_120000.sql"
        assert not dump.exists(), "小半截文件应被清理"

    def test_pg_dump_nonzero_keeps_large_failure(self, _patch_backup_dir):
        backup_dir = _patch_backup_dir

        def fake_run_big(*a, **kw):
            cmd = a[0] if a else kw.get("args", [])
            if "--file" in cmd:
                idx = cmd.index("--file")
                p = Path(cmd[idx + 1])
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(b"x" * 2048)  # > 1KB → 保留供人工排查
            return _fake_completed(rc=1, stderr="some warning")

        with patch("subprocess.run", side_effect=fake_run_big), \
             patch("app.services.db_backup_service.datetime") as m_dt:
            m_dt.now.return_value = _fixed_now()
            ok, msg = svc._pg_dump()

        assert ok is False
        dump = backup_dir / "auto_backup_20260930_120000.sql"
        assert dump.exists(), "较大的半截备份应保留"


# ---------------------------------------------------------------------------
# _cleanup_old_backups
# ---------------------------------------------------------------------------

class TestCleanupOldBackups:

    def test_keeps_recent_n(self, tmp_path):
        import os
        files = []
        for i in range(5):
            p = tmp_path / f"auto_backup_20260930_{i:06d}.sql"
            p.write_text(f"-- dump {i}\n")
            os.utime(p, (i, i))
            files.append(p)

        svc._cleanup_old_backups(tmp_path, keep=2)
        remain = sorted(glob.glob(str(tmp_path / "auto_backup_*.sql")))
        assert len(remain) == 2

    def test_oserror_swallows(self, tmp_path, monkeypatch):
        p = tmp_path / "auto_backup_x.sql"
        p.write_text("x")

        def broken_unlink(self, *a, **kw):
            raise OSError("disk full")

        monkeypatch.setattr(Path, "unlink", broken_unlink)
        svc._cleanup_old_backups(tmp_path, keep=0)
        assert p.exists()

    def test_empty_dir_noop(self, tmp_path):
        svc._cleanup_old_backups(tmp_path, keep=10)


# ---------------------------------------------------------------------------
# do_backup_sync
# ---------------------------------------------------------------------------

class TestDoBackupSync:

    def test_delegates_to_pg_dump(self, _patch_backup_dir):
        with patch("app.services.db_backup_service._pg_dump", return_value=(True, "ok.sql")) as m:
            res = svc.do_backup_sync()
        assert res == (True, "ok.sql")
        m.assert_called_once()


# ---------------------------------------------------------------------------
# _get_minio_client
# ---------------------------------------------------------------------------

class TestGetMinioClient:

    def test_no_minio_module(self):
        with patch.dict("sys.modules", {"minio": None}, clear=False):
            # 让 import minio 抛 ImportError
            with patch("builtins.__import__",
                       side_effect=lambda name, *a, **kw: (_ for _ in ()).throw(ImportError)
                       if name == "minio" else __import__(name, *a, **kw)):
                client = svc._get_minio_client()
        assert client is None

    def test_missing_credentials(self, monkeypatch):
        monkeypatch.delenv("MINIO_ACCESS_KEY", raising=False)
        monkeypatch.delenv("MINIO_SECRET_KEY", raising=False)
        monkeypatch.delenv("MINIO_ROOT_USER", raising=False)
        monkeypatch.delenv("MINIO_ROOT_PASSWORD", raising=False)

        fake_minio = MagicMock()
        fake_minio.Minio = MagicMock(return_value=MagicMock())
        with patch.dict("sys.modules", {"minio": fake_minio}):
            client = svc._get_minio_client()
        assert client is None

    def test_list_buckets_fails(self, monkeypatch):
        monkeypatch.setenv("MINIO_ACCESS_KEY", "u")
        monkeypatch.setenv("MINIO_SECRET_KEY", "p")
        fake_client = MagicMock()
        fake_client.list_buckets.side_effect = Exception("connection refused")
        fake_minio = MagicMock()
        fake_minio.Minio.return_value = fake_client

        with patch.dict("sys.modules", {"minio": fake_minio}):
            client = svc._get_minio_client()
        assert client is None

    def test_success_returns_client(self, monkeypatch):
        monkeypatch.setenv("MINIO_ACCESS_KEY", "u")
        monkeypatch.setenv("MINIO_SECRET_KEY", "p")
        fake_client = MagicMock()
        fake_client.list_buckets.return_value = []
        fake_minio = MagicMock()
        fake_minio.Minio.return_value = fake_client

        with patch.dict("sys.modules", {"minio": fake_minio}):
            client = svc._get_minio_client()
        assert client is fake_client


# ---------------------------------------------------------------------------
# _minio_export / _minio_restore
# ---------------------------------------------------------------------------

class TestMinioExport:

    def test_no_client(self, tmp_path):
        with patch("app.services.db_backup_service._get_minio_client", return_value=None):
            total, skipped = svc._minio_export(tmp_path)
        assert total == 0
        assert "(minio not available)" in skipped

    def test_success(self, tmp_path):
        work = tmp_path / "work"
        client = MagicMock()
        client.list_buckets.return_value = [SimpleNamespace(name="literature")]
        client.list_objects.return_value = [SimpleNamespace(object_name="literature/abc.pdf")]

        with patch("app.services.db_backup_service._get_minio_client", return_value=client):
            total, skipped = svc._minio_export(work)

        assert total == 1
        client.fget_object.assert_called()

    def test_bucket_failure(self, tmp_path):
        work = tmp_path / "work"
        client = MagicMock()
        client.list_buckets.return_value = [SimpleNamespace(name="bad")]
        client.list_objects.side_effect = Exception("boom")

        with patch("app.services.db_backup_service._get_minio_client", return_value=client):
            total, skipped = svc._minio_export(work)
        assert "bad" in skipped

    def test_list_buckets_failure(self, tmp_path):
        work = tmp_path / "work"
        client = MagicMock()
        client.list_buckets.side_effect = Exception("no connection")
        with patch("app.services.db_backup_service._get_minio_client", return_value=client):
            total, skipped = svc._minio_export(work)
        assert total == 0
        assert "list_failed" in skipped


class TestMinioRestore:

    def test_no_client(self, tmp_path):
        with patch("app.services.db_backup_service._get_minio_client", return_value=None):
            total, skipped = svc._minio_restore(tmp_path)
        assert total == 0
        assert "(minio not available)" in skipped

    def test_dir_missing(self, tmp_path):
        with patch("app.services.db_backup_service._get_minio_client", return_value=MagicMock()):
            total, skipped = svc._minio_restore(tmp_path / "nonexistent")
        assert "no_dir" in skipped

    def test_success(self, tmp_path):
        work = tmp_path / "work"
        (work / "literature" / "sub").mkdir(parents=True)
        (work / "literature" / "a.pdf").write_text("pdf")
        (work / "literature" / "sub" / "b.pdf").write_text("pdf2")

        client = MagicMock()
        client.bucket_exists.return_value = False
        with patch("app.services.db_backup_service._get_minio_client", return_value=client):
            total, skipped = svc._minio_restore(work)
        assert total == 2
        assert client.make_bucket.call_count == 1
        assert client.fput_object.call_count == 2


# ---------------------------------------------------------------------------
# _data_dir_export / _data_dir_restore
# ---------------------------------------------------------------------------

class TestDataDirExportRestore:

    def test_src_missing_returns_false(self, tmp_path):
        work = tmp_path / "work"
        work.mkdir()
        # 让 Path("/app/backend/data").exists() 返回 False
        with patch("app.services.db_backup_service.Path.exists", return_value=False):
            assert svc._data_dir_export(work) is False

    def test_shutil_failure(self, tmp_path, monkeypatch):
        import shutil
        work = tmp_path / "work"
        work.mkdir()
        monkeypatch.setattr(shutil, "make_archive",
                            lambda *a, **kw: (_ for _ in ()).throw(OSError("no space")))
        with patch("app.services.db_backup_service.Path.exists", return_value=True):
            assert svc._data_dir_export(work) is False

    def test_data_tar_missing_restore(self, tmp_path):
        assert svc._data_dir_restore(tmp_path / "no_such.tar.gz") is False

    def test_restore_corrupt(self, tmp_path, monkeypatch):
        data_tar = tmp_path / "data.tar.gz"
        data_tar.write_bytes(b"fake")

        import tarfile as _tf
        class _BadTar:
            def __enter__(self): raise _tf.ReadError("corrupt")
            def __exit__(self, *a): return False
        monkeypatch.setattr(_tf, "open", lambda *a, **kw: _BadTar())
        assert svc._data_dir_restore(data_tar) is False


# ---------------------------------------------------------------------------
# _verify_sha256
# ---------------------------------------------------------------------------

class TestVerifySha256:

    def test_no_sha_file_passes(self, tmp_path):
        ok, mis = svc._verify_sha256(tmp_path)
        assert ok is True
        assert any("no SHA256SUMS" in m for m in mis)

    def test_match(self, tmp_path):
        f = tmp_path / "a.txt"
        f.write_text("hello")
        import hashlib
        expect = hashlib.sha256(b"hello").hexdigest()
        (tmp_path / "SHA256SUMS").write_text(f"{expect}  a.txt\n")

        ok, mis = svc._verify_sha256(tmp_path)
        assert ok is True and mis == []

    def test_mismatch(self, tmp_path):
        f = tmp_path / "a.txt"
        f.write_text("hello")
        (tmp_path / "SHA256SUMS").write_text("deadbeef  a.txt\n")

        ok, mis = svc._verify_sha256(tmp_path)
        assert ok is False and "a.txt" in mis


# ---------------------------------------------------------------------------
# _check_target_nonempty
# ---------------------------------------------------------------------------

class TestCheckTargetNonempty:

    def test_query_failure_conservative_refuse(self):
        # asyncpg 已在 session 里加载，patch asyncio.run 让连接查询失败 → 保守拒绝
        with patch("asyncio.run", side_effect=Exception("connection refused")):
            nonempty, tables = svc._check_target_nonempty()
        assert nonempty is True
        assert len(tables) >= 1


# ---------------------------------------------------------------------------
# _compare_rowcounts / _write_rowcounts — 测分支
# ---------------------------------------------------------------------------

class TestRowcounts:

    def test_compare_no_rc_file(self, tmp_path):
        assert "no rowcounts.csv" in svc._compare_rowcounts(tmp_path)

    def test_compare_current_fails(self, tmp_path):
        rc = tmp_path / "rowcounts.csv"
        rc.write_text("relname,approx_rows\nliterature,100\n")
        # patch asyncio.run 让它抛异常（current 查询失败 → 回退到 baseline 摘要）
        with patch("asyncio.run", side_effect=Exception("db down")):
            summary = svc._compare_rowcounts(tmp_path)
        assert "current rowcounts query failed" in summary

    def test_write_rowcounts_connection_error_writes_header(self, tmp_path):
        out = tmp_path / "rowcounts.csv"
        with patch("asyncio.run", side_effect=Exception("db refused")):
            svc._write_rowcounts(out)
        content = out.read_text(encoding="utf-8")
        assert content.startswith("relname,approx_rows\n")


# ---------------------------------------------------------------------------
# do_full_backup_sync — 子函数 mock
# ---------------------------------------------------------------------------

class TestDoFullBackupSync:

    def test_pg_dump_fails_early(self, _patch_backup_dir):
        with patch("app.services.db_backup_service._pg_dump", return_value=(False, "boom")):
            ok, msg = svc.do_full_backup_sync()
        assert ok is False and "pg_dump 失败" in msg

    def test_success_pipeline(self, _patch_backup_dir):
        backup_dir = _patch_backup_dir
        fake_pg = backup_dir / "auto_backup_20260930_120000.sql"
        fake_pg.parent.mkdir(parents=True, exist_ok=True)
        fake_pg.write_text("-- pg dump\n")

        with patch("app.services.db_backup_service._pg_dump", return_value=(True, str(fake_pg))), \
             patch("app.services.db_backup_service._write_rowcounts"), \
             patch("app.services.db_backup_service._minio_export", return_value=(5, [])), \
             patch("app.services.db_backup_service._data_dir_export", return_value=True), \
             patch("shutil.rmtree"), \
             patch("app.services.db_backup_service.datetime") as m_dt:
            m_dt.now.return_value = _fixed_now()
            ok, msg = svc.do_full_backup_sync()

        assert ok is True
        assert "full_backup_20260930_120000.tar.gz" in msg


# ---------------------------------------------------------------------------
# do_full_restore_sync — 安全门
# ---------------------------------------------------------------------------

class _BackupFixture:
    @staticmethod
    def build(tmp_path: Path, content=b"-- empty sql\n") -> Path:
        """造一个最小的合法完整备份（SHA256 通过）。返回 tar.gz 路径。"""
        import hashlib
        work = tmp_path / "_work"
        work.mkdir()
        (work / "database.sql").write_bytes(content)
        h = hashlib.sha256(content).hexdigest()
        (work / "SHA256SUMS").write_text(f"{h}  database.sql\n")

        tar_path = tmp_path / "backup.tar.gz"
        with tarfile.open(str(tar_path), "w:gz") as tf:
            for f in work.iterdir():
                tf.add(str(f), arcname=f.name)
        return tar_path


class TestDoFullRestoreSync:

    def test_backup_missing(self):
        ok, msg = svc.do_full_restore_sync("/tmp/does_not_exist.tar.gz")
        assert ok is False and "不存在" in msg

    def test_verify_only_sha_ok(self, tmp_path, _patch_backup_dir):
        tar_path = _BackupFixture.build(tmp_path)
        with patch("shutil.rmtree"):
            ok, msg = svc.do_full_restore_sync(str(tar_path), verify_only=True)
        assert ok is True and "sha256=✓" in msg

    def test_verify_only_sha_mismatch(self, tmp_path, _patch_backup_dir):
        tar_path = _BackupFixture.build(tmp_path, content=b"-- will be overwritten\n")
        # 把 SHA256SUMS 改掉
        import tarfile as _tf
        import io
        # 简单方式：重新造一个 SHA256 不匹配的备份
        work2 = tmp_path / "_work2"
        work2.mkdir()
        (work2 / "database.sql").write_text("hi")
        (work2 / "SHA256SUMS").write_text("deadbeef  database.sql\n")
        tar_bad = tmp_path / "bad.tar.gz"
        with _tf.open(str(tar_bad), "w:gz") as tf:
            for f in work2.iterdir():
                tf.add(str(f), arcname=f.name)

        with patch("shutil.rmtree"):
            ok, msg = svc.do_full_restore_sync(str(tar_bad), verify_only=True)
        assert ok is False and "FAIL" in msg

    def test_target_nonempty_refuse(self, tmp_path, _patch_backup_dir):
        tar_path = _BackupFixture.build(tmp_path)
        with patch("shutil.rmtree"), \
             patch("app.services.db_backup_service._check_target_nonempty",
                   return_value=(True, ["literature", "data_point"])):
            ok, msg = svc.do_full_restore_sync(str(tar_path))
        assert ok is False and "TARGET_NONEMPTY" in msg

    def test_allow_nonempty_skips_check_runs_psql(self, tmp_path, _patch_backup_dir):
        tar_path = _BackupFixture.build(tmp_path)
        fake_psql = _fake_completed(rc=0)
        with patch("shutil.rmtree"), \
             patch("subprocess.run", return_value=fake_psql):
            ok, msg = svc.do_full_restore_sync(str(tar_path), allow_nonempty=True)
        assert ok is True and "pg=✓" in msg

    def test_sha_fail_aborts_restore(self, tmp_path, _patch_backup_dir):
        # SHA256 不匹配 → 应 abort，不调 psql
        work = tmp_path / "_w"
        work.mkdir()
        (work / "database.sql").write_text("hi")
        (work / "SHA256SUMS").write_text("deadbeef  database.sql\n")
        tar_bad = tmp_path / "bad.tar.gz"
        with tarfile.open(str(tar_bad), "w:gz") as tf:
            for f in work.iterdir():
                tf.add(str(f), arcname=f.name)

        with patch("shutil.rmtree"):
            ok, msg = svc.do_full_restore_sync(str(tar_bad), allow_nonempty=True)
        assert ok is False
        assert "sha256=FAIL" in msg or "FAIL(" in msg
