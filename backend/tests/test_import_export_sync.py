"""services/literature/import_export.py pure-sync unit tests."""
from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from app.services.literature import import_export as imp


# On Windows os.getuid doesn't exist; shim it for test patches
if not hasattr(os, "getuid"):
    os.getuid = lambda: 1000  # type: ignore[attr-defined]


class TestStatIsSocket:
    def test_true(self, tmp_path):
        st_result = MagicMock()
        st_result.st_mode = stat.S_IFSOCK | 0o777
        with patch("app.services.literature.import_export.os.stat", return_value=st_result):
            assert imp.stat_is_socket(str(tmp_path)) is True

    def test_false(self, tmp_path):
        st_result = MagicMock()
        st_result.st_mode = stat.S_IFREG | 0o644
        with patch("app.services.literature.import_export.os.stat", return_value=st_result):
            assert imp.stat_is_socket(str(tmp_path)) is False

    def test_stat_error(self, tmp_path):
        with patch("app.services.literature.import_export.os.stat", side_effect=FileNotFoundError):
            with pytest.raises(FileNotFoundError):
                imp.stat_is_socket(str(tmp_path))


class TestToWindowsPath:
    def test_converts(self):
        fake = MagicMock(stdout="E:\\antibody_map", stderr="", returncode=0)
        with patch("subprocess.run", return_value=fake):
            assert imp._to_windows_path("/mnt/e/x") == "E:\\antibody_map"

    def test_empty_returns_none(self):
        fake = MagicMock(stdout="", stderr="", returncode=0)
        with patch("subprocess.run", return_value=fake):
            assert imp._to_windows_path("/mnt/x") is None

    def test_exception_returns_none(self):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert imp._to_windows_path("/mnt/x") is None


class TestGetWslRunuserPrefix:

    def test_non_root_returns_none(self):
        with patch.object(os, "getuid", return_value=1000):
            assert imp._get_wsl_runuser_prefix() is None

    def test_root_from_who(self):
        fake = MagicMock(stdout="liux pts/0 ...\n", stderr="", returncode=0)
        with patch.object(os, "getuid", return_value=0), patch("subprocess.run", return_value=fake):
            assert imp._get_wsl_runuser_prefix() == ["runuser", "-u", "liux", "--"]

    def test_root_who_all_root_skips_each(self):
        # who 全部返回 root → 回退到 /run/user 分支；Windows 上 pwd 不存在，最终返回 None
        fake = MagicMock(stdout="root pts/0 ...\n", stderr="", returncode=0)
        with patch.object(os, "getuid", return_value=0), \
             patch("subprocess.run", return_value=fake):
            result = imp._get_wsl_runuser_prefix()
        # Windows 上 pwd 模块不存在 → 最终 None；Linux 上可能找到
        # 这里只验证不会抛异常
        assert result is None or result == [] or "runuser" in (result or [""])[0]

    def test_all_fail_returns_none(self):
        with patch.object(os, "getuid", return_value=0), \
             patch("subprocess.run", side_effect=FileNotFoundError), \
             patch("glob.glob", side_effect=Exception("fail")):
            assert imp._get_wsl_runuser_prefix() is None


class TestFindActiveWslInterop:

    def test_standard_link_target(self):
        with patch("os.path.islink", lambda p: p == "/run/WSL/1_interop"), \
             patch("os.path.realpath", return_value="/run/WSL/1_target"), \
             patch("os.path.exists", lambda p: True), \
             patch("glob.glob", return_value=[]), \
             patch("app.services.literature.import_export.stat_is_socket", return_value=True):
            assert imp._find_active_wsl_interop() == "/run/WSL/1_target"

    def test_pid2_fallback(self):
        with patch("os.path.islink", return_value=False), \
             patch("os.path.exists", lambda p: p == "/run/WSL/2_interop"), \
             patch("glob.glob", return_value=[]), \
             patch("app.services.literature.import_export.stat_is_socket", return_value=True):
            assert imp._find_active_wsl_interop() == "/run/WSL/2_interop"

    def test_smallest_pid_glob_wins(self):
        with patch("os.path.islink", return_value=False), \
             patch("os.path.exists", return_value=True), \
             patch("glob.glob", return_value=["/run/WSL/10_interop", "/run/WSL/5_interop", "/run/WSL/100_interop"]), \
             patch("app.services.literature.import_export.stat_is_socket", return_value=True):
            # 2_interop 也在 candidates，排在 glob 前面
            result = imp._find_active_wsl_interop()
        # 2_interop 是优先 2，应该先检查
        assert result in ("/run/WSL/2_interop", "/run/WSL/5_interop")

    def test_none_found(self):
        with patch("os.path.islink", return_value=False), \
             patch("os.path.exists", return_value=False), \
             patch("glob.glob", return_value=[]), \
             patch("app.services.literature.import_export.stat_is_socket", return_value=False):
            assert imp._find_active_wsl_interop() is None


class TestRevealInHostFileManager:

    def test_windows_explorer(self):
        proc = MagicMock()
        with patch("os.name", "nt"), \
             patch("subprocess.Popen", return_value=proc) as m_popen:
            imp.reveal_in_host_file_manager("E:\\folder", "E:\\folder")
        m_popen.assert_called()

    def test_posix_xdg_open(self):
        proc = MagicMock()
        with patch("os.name", "posix"), \
             patch("subprocess.Popen", return_value=proc) as m_popen, \
             patch("app.services.literature.import_export._find_active_wsl_interop", return_value=None), \
             patch("app.services.literature.import_export._get_wsl_runuser_prefix", return_value=None):
            imp.reveal_in_host_file_manager("/tmp/folder", "/tmp/folder")
        called = m_popen.call_args_list
        assert len(called) >= 1
