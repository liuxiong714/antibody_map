"""import_export.py sync 工具函数测试（Windows-safe：mock os.getuid / pwd）。"""
from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

# Windows 上 os.getuid 不存在，补一个
if not hasattr(__import__("os"), "getuid"):
    import os as _os
    _os.getuid = lambda: 1000  # type: ignore[attr-defined]


from app.services.literature.import_export import (
    reveal_in_host_file_manager,
    _to_windows_path,
    _get_wsl_runuser_prefix,
    _find_active_wsl_interop,
    stat_is_socket,
)


def _fake_run(rc=0, stdout="", stderr=""):
    return SimpleNamespace(returncode=rc, stdout=stdout, stderr=stderr)


# ===== _to_windows_path =====

def test_to_windows_path_success():
    with patch("subprocess.run", return_value=_fake_run(rc=0, stdout="E:\\folder\\a.pdf")):
        assert _to_windows_path("/mnt/e/folder/a.pdf") == "E:\\folder\\a.pdf"


def test_to_windows_path_empty_stdout_returns_none():
    with patch("subprocess.run", return_value=_fake_run(rc=0, stdout="   ")):
        assert _to_windows_path("/mnt/e/x") is None


def test_to_windows_path_exception_returns_none():
    with patch("subprocess.run", side_effect=FileNotFoundError("wslpath")):
        assert _to_windows_path("/mnt/e/x") is None


def test_to_windows_path_timeout_returns_none():
    import subprocess
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="x", timeout=10)):
        assert _to_windows_path("/mnt/e/x") is None


# ===== stat_is_socket =====

def test_stat_is_socket_true():
    import stat as _stat
    fake_st = SimpleNamespace(st_mode=_stat.S_IFSOCK | 0o777)
    with patch("os.stat", return_value=fake_st):
        assert stat_is_socket("/tmp/x.sock") is True


def test_stat_is_socket_false_for_file():
    import stat as _stat
    fake_st = SimpleNamespace(st_mode=_stat.S_IFREG | 0o644)
    with patch("os.stat", return_value=fake_st):
        assert stat_is_socket("/tmp/x.txt") is False


def test_stat_is_socket_false_for_dir():
    import stat as _stat
    fake_st = SimpleNamespace(st_mode=_stat.S_IFDIR | 0o755)
    with patch("os.stat", return_value=fake_st):
        assert stat_is_socket("/tmp/") is False


def test_stat_is_socket_os_error_raises():
    with patch("os.stat", side_effect=OSError("no such file")):
        with pytest.raises(OSError):
            stat_is_socket("/nonexistent")


# ===== _get_wsl_runuser_prefix (mock os.getuid + pwd) =====

@pytest.fixture(autouse=True)
def _mock_unix_only_stuff():
    """Windows safe：ensure os.getuid 和 pwd 可用。"""
    import os as _os
    if not hasattr(_os, "getuid"):
        _os.getuid = lambda: 1000  # type: ignore[attr-defined]
    # pwd 在函数内部 import，sys.modules patch 即可
    fake_pwd = MagicMock()
    fake_pwd.getpwuid = MagicMock(return_value=SimpleNamespace(pw_name="liux"))
    with patch.dict("sys.modules", {"pwd": fake_pwd}):
        yield


def test_get_wsl_runuser_prefix_not_root():
    import os
    with patch.object(os, "getuid", return_value=1000):
        assert _get_wsl_runuser_prefix() is None


def test_get_wsl_runuser_prefix_root_who_succeeds():
    import os
    with patch.object(os, "getuid", return_value=0), \
         patch("subprocess.run",
               return_value=_fake_run(rc=0, stdout="liux pts/0 2025-01-01\nroot pts/1\n")):
        result = _get_wsl_runuser_prefix()
    assert result == ["runuser", "-u", "liux", "--"]


def test_get_wsl_runuser_prefix_root_who_all_root():
    import os
    with patch.object(os, "getuid", return_value=0), \
         patch("subprocess.run", return_value=_fake_run(rc=0, stdout="root pts/0\n")):
        result = _get_wsl_runuser_prefix()
    # 走 glob fallback
    assert result is None  # glob 没 mock → 异常 → None


def test_get_wsl_runuser_prefix_root_who_exception_then_fallback():
    """who 抛异常后走 glob + pwd fallback。"""
    import os, glob
    with patch.object(os, "getuid", return_value=0), \
         patch("subprocess.run", side_effect=FileNotFoundError), \
         patch.object(glob, "glob", return_value=["/run/user/1000"]):
        result = _get_wsl_runuser_prefix()
    assert result == ["runuser", "-u", "liux", "--"]


def test_get_wsl_runuser_prefix_root_fallback_no_user_over_1000():
    import os, glob
    with patch.object(os, "getuid", return_value=0), \
         patch("subprocess.run", side_effect=FileNotFoundError), \
         patch.object(glob, "glob", return_value=["/run/user/0", "/run/user/999"]):
        result = _get_wsl_runuser_prefix()
    assert result is None


# ===== _find_active_wsl_interop =====

def test_find_active_wsl_interop_link_exists_and_target_socket():
    with patch("os.path.islink", return_value=True), \
         patch("os.path.realpath", return_value="/run/WSL/2_interop"), \
         patch("os.path.exists", return_value=True), \
         patch("app.services.literature.import_export.stat_is_socket", return_value=True):
        result = _find_active_wsl_interop()
    assert result == "/run/WSL/2_interop"


def test_find_active_wsl_interop_no_link_uses_candidates():
    with patch("os.path.islink", return_value=False), \
         patch("app.services.literature.import_export.stat_is_socket", return_value=True):
        result = _find_active_wsl_interop()
    assert result == "/run/WSL/2_interop"


def test_find_active_wsl_interop_stat_exception_skips():
    def _fake_stat(p):
        if p == "/run/WSL/2_interop":
            raise OSError("bad")
        return True
    with patch("os.path.islink", return_value=False), \
         patch("app.services.literature.import_export.stat_is_socket", _fake_stat):
        import glob as _glob
        with patch.object(_glob, "glob", return_value=["/run/WSL/3_interop"]):
            result = _find_active_wsl_interop()
    assert result == "/run/WSL/3_interop"


def test_find_active_wsl_interop_none_found():
    with patch("os.path.islink", return_value=False), \
         patch("app.services.literature.import_export.stat_is_socket", return_value=False):
        assert _find_active_wsl_interop() is None


def test_find_active_wsl_interop_glob_exception_returns_none():
    import glob as _glob
    with patch("os.path.islink", return_value=False), \
         patch.object(_glob, "glob", side_effect=Exception("glob broken")), \
         patch("app.services.literature.import_export.stat_is_socket", return_value=False):
        assert _find_active_wsl_interop() is None


# ===== reveal_in_host_file_manager =====

def test_reveal_windows_platform():
    with patch.object(sys, "platform", "win32"), \
         patch("subprocess.Popen") as m_popen:
        reveal_in_host_file_manager("E:\\a.pdf", "E:\\")
    m_popen.assert_called_once()


def test_reveal_darwin_platform():
    with patch.object(sys, "platform", "darwin"), \
         patch("subprocess.Popen") as m_popen:
        reveal_in_host_file_manager("/tmp/a.pdf", "/tmp")
    m_popen.assert_called_once_with(["open", "-R", "/tmp/a.pdf"])


def test_reveal_wsl_with_win_path():
    import os
    with patch.object(sys, "platform", "linux"), \
         patch.object(os, "getuid", return_value=1000), \
         patch("app.services.literature.import_export._to_windows_path", return_value="E:\\a.pdf"), \
         patch("app.services.literature.import_export._find_active_wsl_interop", return_value=None), \
         patch("app.services.literature.import_export._get_wsl_runuser_prefix", return_value=None), \
         patch("subprocess.Popen") as m_popen:
        reveal_in_host_file_manager("/mnt/e/a.pdf", "/mnt/e")
    m_popen.assert_called()


def test_reveal_wsl_with_runuser_root():
    import os
    with patch.object(sys, "platform", "linux"), \
         patch.object(os, "getuid", return_value=0), \
         patch("app.services.literature.import_export._to_windows_path", return_value="E:\\a.pdf"), \
         patch("app.services.literature.import_export._find_active_wsl_interop", return_value="/run/WSL/2_interop"), \
         patch("app.services.literature.import_export._get_wsl_runuser_prefix",
               return_value=["runuser", "-u", "liux", "--"]), \
         patch("subprocess.Popen") as m_popen:
        reveal_in_host_file_manager("/mnt/e/a.pdf", "/mnt/e")
    m_popen.assert_called()


def test_reveal_no_win_path_falls_back_to_xdg_open():
    import os
    with patch.object(sys, "platform", "linux"), \
         patch.object(os, "getuid", return_value=1000), \
         patch("app.services.literature.import_export._to_windows_path", return_value=None), \
         patch("subprocess.Popen") as m_popen:
        reveal_in_host_file_manager("/some/file.pdf", "/some")
    call_args = m_popen.call_args
    assert call_args[0][0][0] == "xdg-open"


def test_reveal_wsl_explorer_exception_falls_back_xdg():
    import os
    popen_seq = {"n": 0}
    def _side_effect(*a, **kw):
        if popen_seq["n"] == 0:
            popen_seq["n"] += 1
            raise OSError("explorer.exe not found")
        popen_seq["n"] += 1
        return SimpleNamespace(pid=123)
    with patch.object(sys, "platform", "linux"), \
         patch.object(os, "getuid", return_value=1000), \
         patch("app.services.literature.import_export._to_windows_path", return_value="E:\\a.pdf"), \
         patch("app.services.literature.import_export._find_active_wsl_interop", return_value=None), \
         patch("app.services.literature.import_export._get_wsl_runuser_prefix", return_value=None), \
         patch("subprocess.Popen", side_effect=_side_effect):
        reveal_in_host_file_manager("/mnt/e/a.pdf", "/mnt/e")
    assert popen_seq["n"] == 2


def test_reveal_noop_on_xdg_open_exception():
    """xdg-open 也失败时不抛异常。"""
    import os
    with patch.object(sys, "platform", "linux"), \
         patch.object(os, "getuid", return_value=1000), \
         patch("app.services.literature.import_export._to_windows_path", return_value=None), \
         patch("subprocess.Popen", side_effect=OSError("xdg-open not found")):
        reveal_in_host_file_manager("/x", "/x")
