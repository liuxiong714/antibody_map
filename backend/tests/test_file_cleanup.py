#!/usr/bin/env python
"""孤儿文件清理安全测试：冷静期跳过、dry_run 不移动、真移动仅限过期且未被引用的文件。

运行方式（Windows PowerShell）:
  cd backend
  python tests/test_file_cleanup.py
  或:  pytest tests/test_file_cleanup.py
"""
import os
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

# ── 路径修正 ──
_backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

_passed = 0
_failed = 0


def _ok(label: str, detail: str = ""):
    global _passed
    _passed += 1
    print(f"  ✓ {label}{(' — ' + detail) if detail else ''}")


def _fail(label: str, detail: str = ""):
    global _failed
    _failed += 1
    msg = f"  ✗ {label}{(' — ' + detail) if detail else ''}"
    print(msg)
    raise AssertionError(msg)


# ─────────────────────────────────────────────────────────
# 工具：在临时目录中构造本地存储目录
# ─────────────────────────────────────────────────────────
def _make_local_dir() -> tuple[Path, Path]:
    tmp = Path(tempfile.mkdtemp(prefix="orphan_test_"))
    local = tmp / "pdfs"
    local.mkdir(parents=True, exist_ok=True)
    return tmp, local


def _make_file(local: Path, name: str, mtime_days_ago: float = 0.0) -> Path:
    """创建文件；mtime_days_ago=0 表示最近（冷静期内），>7 表示过期。"""
    p = local / name
    p.write_bytes(b"%PDF-1.4 test")
    if mtime_days_ago > 0:
        t = time.time() - mtime_days_ago * 86400
        os.utime(p, (t, t))
    return p


# ─────────────────────────────────────────────────────────
# 测试 1：被 DB 引用的文件（basename 命中）→ 不判为孤儿
# ─────────────────────────────────────────────────────────
def test_scan_referenced_file_not_orphan():
    print("\n" + "=" * 60)
    print("【测试 1】DB 引用的文件不被判为孤儿")
    print("=" * 60)
    from app.services import file_cleanup_service as svc

    tmp, local = _make_local_dir()
    _make_file(local, "uuid_a.pdf", mtime_days_ago=10)  # 过期但被引用
    db = AsyncMock()
    refs = {"uuid_a.pdf", "data/pdfs/uuid_a.pdf"}
    import asyncio

    with patch.object(svc, "LOCAL_STORAGE_DIR", local), patch.object(
        svc, "collect_referenced", AsyncMock(return_value=(refs, {"1"}))
    ), patch.object(svc, "_collect_minio_object_names", AsyncMock(return_value=set())):
        scan = asyncio.run(svc.scan_orphan_files(db))

    if "uuid_a.pdf" in scan["referenced"] and "uuid_a.pdf" not in scan["orphan"]:
        _ok("被引用文件归入 referenced", f"orphan={scan['orphan']}")
    else:
        _fail("被引用文件不应判为孤儿", f"scan={scan}")


# ─────────────────────────────────────────────────────────
# 测试 2：冷静期——近期变更文件（含 DB 未引用）一律跳过
# ─────────────────────────────────────────────────────────
def test_scan_recent_file_not_orphan():
    print("\n" + "=" * 60)
    print("【测试 2】冷静期：近期变更文件不被判为孤儿")
    print("=" * 60)
    import asyncio
    from app.services import file_cleanup_service as svc

    tmp, local = _make_local_dir()
    _make_file(local, "uuid_b.pdf", mtime_days_ago=0)  # 最近创建，冷静期内
    db = AsyncMock()
    with patch.object(svc, "LOCAL_STORAGE_DIR", local), patch.object(
        svc, "collect_referenced", AsyncMock(return_value=(set(), set()))
    ), patch.object(svc, "_collect_minio_object_names", AsyncMock(return_value=set())):
        scan = asyncio.run(svc.scan_orphan_files(db))

    if "uuid_b.pdf" in scan["cooldown"] and "uuid_b.pdf" not in scan["orphan"]:
        _ok("近期文件进入冷静期", f"cooldown={scan['cooldown']}")
    else:
        _fail("近期文件应进入冷静期而非孤儿", f"scan={scan}")


# ─────────────────────────────────────────────────────────
# 测试 3：过期且未被引用的文件 → 判为孤儿
# ─────────────────────────────────────────────────────────
def test_scan_old_unreferenced_file_is_orphan():
    print("\n" + "=" * 60)
    print("【测试 3】过期且未被引用的文件判为孤儿")
    print("=" * 60)
    import asyncio
    from app.services import file_cleanup_service as svc

    tmp, local = _make_local_dir()
    _make_file(local, "stale.pdf", mtime_days_ago=10)  # 过期、无引用
    db = AsyncMock()
    with patch.object(svc, "LOCAL_STORAGE_DIR", local), patch.object(
        svc, "collect_referenced", AsyncMock(return_value=(set(), set()))
    ), patch.object(svc, "_collect_minio_object_names", AsyncMock(return_value=set())):
        scan = asyncio.run(svc.scan_orphan_files(db))

    if "stale.pdf" in scan["orphan"]:
        _ok("过期无引用文件判为孤儿")
    else:
        _fail("过期无引用文件应判为孤儿", f"scan={scan}")


# ─────────────────────────────────────────────────────────
# 测试 4：dry_run 不产生任何移动
# ─────────────────────────────────────────────────────────
def test_dry_run_no_move():
    print("\n" + "=" * 60)
    print("【测试 4】dry_run 仅报告、不移动")
    print("=" * 60)
    import asyncio
    from app.services import file_cleanup_service as svc

    tmp, local = _make_local_dir()
    _make_file(local, "stale.pdf", mtime_days_ago=10)
    db = AsyncMock()
    with patch.object(svc, "LOCAL_STORAGE_DIR", local), patch.object(
        svc, "collect_referenced", AsyncMock(return_value=(set(), set()))
    ), patch.object(svc, "_collect_minio_object_names", AsyncMock(return_value=set())), patch.object(
        svc, "log_audit", AsyncMock()
    ):
        result = asyncio.run(svc.cleanup_orphan_files(db, dry_run=True))

    if result.get("dry_run") is True and "moved" not in result and (local / "stale.pdf").exists():
        _ok("dry_run 不移动文件", f"result={result}")
    else:
        _fail("dry_run 不应移动文件", f"result={result}")


# ─────────────────────────────────────────────────────────
# 测试 5：真移动仅移动过期孤儿；冷静期文件即使 dry_run=False 也不动
# ─────────────────────────────────────────────────────────
def test_real_move_respects_cooldown():
    print("\n" + "=" * 60)
    print("【测试 5】真移动：过期孤儿移动、冷静期文件不动")
    print("=" * 60)
    import asyncio
    from app.services import file_cleanup_service as svc

    tmp, local = _make_local_dir()
    _make_file(local, "stale.pdf", mtime_days_ago=10)   # 过期 → 应移动
    _make_file(local, "fresh.pdf", mtime_days_ago=0)     # 冷静期 → 不应移动
    db = AsyncMock()
    with patch.object(svc, "LOCAL_STORAGE_DIR", local), patch.object(
        svc, "collect_referenced", AsyncMock(return_value=(set(), set()))
    ), patch.object(svc, "_collect_minio_object_names", AsyncMock(return_value=set())), patch.object(
        svc, "log_audit", AsyncMock()
    ):
        result = asyncio.run(svc.cleanup_orphan_files(db, dry_run=False))

    trash = tmp / "pdf_orphan_trash"
    if (
        result["moved"] == 1
        and not (local / "stale.pdf").exists()
        and (trash / "stale.pdf").exists()
        and (local / "fresh.pdf").exists()
    ):
        _ok("过期孤儿移入回收、冷静期文件保留", f"moved={result['moved']}, trash={trash.name}")
    else:
        _fail("移动结果不符合预期", f"result={result}, stale_in_local={(local/'stale.pdf').exists()}, fresh_in_local={(local/'fresh.pdf').exists()}")


# ─────────────────────────────────────────────────────────
# 测试 6：MinIO 反向校验——同名对象仍存在 → 不判为孤儿（档位三）
# ─────────────────────────────────────────────────────────
def test_minio_object_still_exists_not_orphan():
    print("\n" + "=" * 60)
    print("【测试 6】MinIO 有同名对象：本地文件不被判为孤儿")
    print("=" * 60)
    import asyncio
    from app.services import file_cleanup_service as svc

    tmp, local = _make_local_dir()
    _make_file(local, "somefile.pdf", mtime_days_ago=10)  # 过期、DB 未引用
    db = AsyncMock()
    with patch.object(svc, "LOCAL_STORAGE_DIR", local), patch.object(
        svc, "collect_referenced", AsyncMock(return_value=(set(), set()))
    ), patch.object(
        svc, "_collect_minio_object_names", AsyncMock(return_value={"somefile.pdf", "literatures/somefile.pdf"})
    ):
        scan = asyncio.run(svc.scan_orphan_files(db))

    if (
        "somefile.pdf" in scan["minio_protected"]
        and "somefile.pdf" not in scan["orphan"]
    ):
        _ok("MinIO 同名对象保护", f"minio_protected={scan['minio_protected']}")
    else:
        _fail("MinIO 同名对象应保护而非孤儿", f"scan={scan}")


# ─────────────────────────────────────────────────────────
# 测试 7：本地改名（{id}_v2.pdf）但 id 仍存在 → 不判为孤儿（档位三）
# ─────────────────────────────────────────────────────────
def test_local_renamed_file_id_still_exists_not_orphan():
    print("\n" + "=" * 60)
    print("【测试 7】本地改名但文献 id 仍存在：不被判为孤儿")
    print("=" * 60)
    import asyncio
    from app.services import file_cleanup_service as svc

    lit_id = "550e8400-e29b-41d4-a716-446655440000"
    tmp, local = _make_local_dir()
    _make_file(local, f"{lit_id}_v2.pdf", mtime_days_ago=10)  # 过期、DB basename 未命中
    db = AsyncMock()
    with patch.object(svc, "LOCAL_STORAGE_DIR", local), patch.object(
        svc, "collect_referenced", AsyncMock(return_value=({f"{lit_id}.pdf"}, {lit_id}))
    ), patch.object(svc, "_collect_minio_object_names", AsyncMock(return_value=set())):
        scan = asyncio.run(svc.scan_orphan_files(db))

    if (
        f"{lit_id}_v2.pdf" in scan["minio_protected"]
        and f"{lit_id}_v2.pdf" not in scan["orphan"]
    ):
        _ok("本地改名文件由 MinIO/文献 id 反向校验保护", f"minio_protected={scan['minio_protected']}")
    else:
        _fail("本地改名文件不应判为孤儿", f"scan={scan}")


# ─────────────────────────────────────────────────────────
# 工具：构造 MinIO mock 客户端（list_objects 返回给定对象清单）
# ─────────────────────────────────────────────────────────
_OLD_TS = datetime.now(timezone.utc) - timedelta(days=10)   # 已过冷静期
_FRESH_TS = datetime.now(timezone.utc) - timedelta(minutes=1)  # 冷静期内


def _make_minio_client(objects: list[tuple[str, datetime]]) -> MagicMock:
    """objects: [(object_name, last_modified)]；list_objects 返回这些对象。"""
    client = MagicMock()
    client.list_objects.return_value = [
        SimpleNamespace(object_name=name, last_modified=ts) for name, ts in objects
    ]
    return client


# ─────────────────────────────────────────────────────────
# 测试 8：MinIO 孤立对象被扫描报告为孤儿
# ─────────────────────────────────────────────────────────
def test_scan_minio_orphans():
    print("\n" + "=" * 60)
    print("【测试 8】MinIO 孤立对象被扫描报告为孤儿")
    print("=" * 60)
    import asyncio
    from app.services import file_cleanup_service as svc

    db = AsyncMock()
    client = _make_minio_client([("orphan_uuid.pdf", _OLD_TS)])
    with patch.object(svc, "collect_referenced", AsyncMock(return_value=(set(), set()))), patch.object(
        svc, "get_minio_client", MagicMock(return_value=client)
    ), patch.object(svc, "record_orphan_scan", MagicMock()):
        scan = asyncio.run(svc.scan_minio_orphans(db))

    if "orphan_uuid.pdf" in scan["orphan"] and scan.get("available") is True:
        _ok("MinIO 孤立对象判为孤儿", f"orphan={scan['orphan']}")
    else:
        _fail("MinIO 孤立对象应判为孤儿", f"scan={scan}")


# ─────────────────────────────────────────────────────────
# 测试 9：dry_run 不删除任何 MinIO 对象
# ─────────────────────────────────────────────────────────
def test_minio_dry_run_no_delete():
    print("\n" + "=" * 60)
    print("【测试 9】MinIO dry_run 仅报告、不删除")
    print("=" * 60)
    import asyncio
    from app.services import file_cleanup_service as svc

    db = AsyncMock()
    client = _make_minio_client([("orphan_uuid.pdf", _OLD_TS)])
    with patch.object(svc, "collect_referenced", AsyncMock(return_value=(set(), set()))), patch.object(
        svc, "get_minio_client", MagicMock(return_value=client)
    ), patch.object(svc, "record_orphan_scan", MagicMock()), patch.object(svc, "delete_file", MagicMock()) as df:
        result = asyncio.run(svc.delete_minio_orphan_objects(db, dry_run=True))

    if result.get("dry_run") is True and "deleted" not in result:
        df.assert_not_called()
        _ok("MinIO dry_run 不删除对象", f"result={result}")
    else:
        _fail("MinIO dry_run 不应删除对象", f"result={result}")


# ─────────────────────────────────────────────────────────
# 测试 10：被 DB 引用的 MinIO 对象绝不判为孤儿/删除
# ─────────────────────────────────────────────────────────
def test_minio_referenced_object_never_deleted():
    print("\n" + "=" * 60)
    print("【测试 10】DB 引用的 MinIO 对象绝不删除")
    print("=" * 60)
    import asyncio
    from app.services import file_cleanup_service as svc

    db = AsyncMock()
    refs = {"used_uuid.pdf", "data/pdfs/used_uuid.pdf"}
    client = _make_minio_client([("used_uuid.pdf", _OLD_TS)])
    with patch.object(svc, "collect_referenced", AsyncMock(return_value=(refs, {"1"}))), patch.object(
        svc, "get_minio_client", MagicMock(return_value=client)
    ), patch.object(svc, "record_orphan_scan", MagicMock()), patch.object(svc, "delete_file", MagicMock()) as df:
        scan = asyncio.run(svc.scan_minio_orphans(db))
        result = asyncio.run(svc.delete_minio_orphan_objects(db, dry_run=False))

    if "used_uuid.pdf" in scan["referenced"] and scan["orphan"] == []:
        df.assert_not_called()
        _ok("被引用对象进入 referenced，且真删不触发", f"scan_orphan={scan['orphan']}")
    else:
        _fail("被引用对象不应判为孤儿", f"scan={scan}")


# ─────────────────────────────────────────────────────────
# 测试 11：真删仅删孤儿对象；id 前缀保护对象不删；再次扫描孤儿为 0
# ─────────────────────────────────────────────────────────
def test_minio_real_delete_and_rescan():
    print("\n" + "=" * 60)
    print("【测试 11】真删仅删孤儿；id 前缀保护不删；再次扫描孤儿为 0")
    print("=" * 60)
    import asyncio
    from app.services import file_cleanup_service as svc

    lit_id = "550e8400-e29b-41d4-a716-446655440000"
    db = AsyncMock()

    # 模拟对象随删除而消失：list_objects 从剩余清单读取
    remaining: list[tuple[str, datetime]] = [
        ("orphan_x.pdf", _OLD_TS),
        (f"{lit_id}_v2.pdf", _OLD_TS),  # id 前缀保护，不应删除
    ]

    def fake_list(bucket, recursive=False):
        return [
            SimpleNamespace(object_name=name, last_modified=ts) for name, ts in remaining
        ]

    client = MagicMock()
    client.list_objects.side_effect = fake_list

    def fake_delete(obj):
        # 模拟删除生效：从剩余清单移除该对象（原地修改，无需 nonlocal）
        for i, (name, _) in enumerate(remaining[:]):
            if name == obj:
                remaining.pop(i)
                break
        return True

    with patch.object(
        svc, "collect_referenced", AsyncMock(return_value=({f"{lit_id}.pdf"}, {lit_id}))
    ), patch.object(svc, "get_minio_client", MagicMock(return_value=client)), patch.object(
        svc, "record_orphan_scan", MagicMock()
    ), patch.object(svc, "delete_file", MagicMock(side_effect=fake_delete)) as df, patch.object(
        svc, "log_audit", AsyncMock()
    ):
        result = asyncio.run(svc.delete_minio_orphan_objects(db, dry_run=False))
        scan_after = asyncio.run(svc.scan_minio_orphans(db))

    called_objects = [c.args[0] for c in df.call_args_list] if df.call_args_list else []
    if (
        result["deleted"] == 1
        and called_objects == ["orphan_x.pdf"]
        and f"{lit_id}_v2.pdf" in scan_after["protected"]
        and scan_after["orphan"] == []
    ):
        _ok(
            "仅删孤儿对象、保护对象保留、再次扫描孤儿为 0",
            f"deleted={result['deleted']}, called={called_objects}, scan_after_orphan={scan_after['orphan']}",
        )
    else:
        _fail(
            "真删行为不符合预期",
            f"result={result}, called={called_objects}, scan_after={scan_after}",
        )


# ─────────────────────────────────────────────────────────
def main():
    test_scan_referenced_file_not_orphan()
    test_scan_recent_file_not_orphan()
    test_scan_old_unreferenced_file_is_orphan()
    test_dry_run_no_move()
    test_real_move_respects_cooldown()
    test_minio_object_still_exists_not_orphan()
    test_local_renamed_file_id_still_exists_not_orphan()
    test_scan_minio_orphans()
    test_minio_dry_run_no_delete()
    test_minio_referenced_object_never_deleted()
    test_minio_real_delete_and_rescan()
    print("\n" + "=" * 60)
    print(f"孤儿文件清理安全测试完成: 通过 {_passed}，失败 {_failed}")
    print("=" * 60)
    if _failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
