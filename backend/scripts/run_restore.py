#!/usr/bin/env python3
"""run_restore.py — Batch 0 D1 备份恢复演练 + 校验脚本。

文档定义: `backend/scripts/restore_backup.sh --all --target-test`
本脚本是其 Python 等价物，通过 db_backup_service 统一实现。

用法:
    # 1. 只校验备份完整性（SHA256 + rowcounts 对比），不真恢复
    python -m scripts.run_restore --verify

    # 2. 列出所有可用完整备份
    python -m scripts.run_restore --list

    # 3. 恢复到目标库（默认拒绝覆盖非空库，演练需加 --target-test）
    python -m scripts.run_restore --backup-path backups/full_backup_YYYYMMDD_HHMMSS.tar.gz --target-test

    # 4. 强制恢复覆盖（极度危险！仅生产应急）
    python -m scripts.run_restore --backup-path backups/full_backup_*.tar.gz --force

Exit code:
    0 = 成功（verify 通过 / restore 完成）
    1 = 失败（sha256 mismatch / restore abort / 参数错误）
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# 把 backend 目录加到 sys.path，让脚本可独立运行
_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

from app.config import settings
from app.services.db_backup_service import (
    do_full_backup_sync,
    do_full_restore_sync,
)


def _list_backups() -> list[Path]:
    backup_dir = Path(settings.BACKUP_DIR)
    if not backup_dir.exists():
        return []
    return sorted(backup_dir.glob("full_backup_*.tar.gz"))


def _latest_full_backup() -> Path | None:
    backups = _list_backups()
    return backups[-1] if backups else None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Batch 0 D1: 备份恢复演练 + 校验（verify / restore / list）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--backup-path", "-b",
        help="完整备份 .tar.gz 路径（未指定时用最新一份）",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="只校验 SHA256 + 对比 rowcounts，不真恢复（演练模式）",
    )
    parser.add_argument(
        "--target-test",
        action="store_true",
        help="允许恢复到非空目标库（测试库演练用；否则非空即拒绝）",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="极度危险！允许覆盖非空目标库（生产应急时用）",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="列出所有可用完整备份并退出",
    )
    parser.add_argument(
        "--make-backup",
        action="store_true",
        help="先创建一份新的完整备份，再做 verify / restore",
    )

    args = parser.parse_args()

    if args.list:
        backups = _list_backups()
        if not backups:
            print("(无完整备份 — 用 --make-backup 先生成一份)")
            return 0
        print("可用完整备份:")
        for i, bp in enumerate(backups, 1):
            size_mb = bp.stat().st_size / (1024 * 1024)
            print(f"  [{i}] {bp.name}  ({size_mb:.1f} MB)")
        return 0

    # 先创建新备份？
    backup_path = args.backup_path
    if args.make_backup:
        print("=== 创建新的完整备份 ===")
        ok, result = do_full_backup_sync()
        if not ok:
            print(f"❌ 备份失败: {result}", file=sys.stderr)
            return 1
        backup_path = result
        print(f"✅ 备份完成: {backup_path}")

    # 没指定路径 → 找最新
    if not backup_path:
        backup_path = _latest_full_backup()
        if not backup_path:
            print(
                "❌ 未找到完整备份。先跑 --make-backup 或手动生成一份 full_backup_*.tar.gz\n"
                f"   搜索目录: {settings.BACKUP_DIR}",
                file=sys.stderr,
            )
            return 1
        print(f"使用最新备份: {Path(backup_path).name}")
    else:
        backup_path = Path(backup_path)
        if not backup_path.exists():
            print(f"❌ 备份文件不存在: {backup_path}", file=sys.stderr)
            return 1

    if args.verify:
        print(f"=== [D1-verify] 校验备份 {backup_path.name} ===")
        ok, summary = do_full_restore_sync(str(backup_path), verify_only=True)
        print(summary)
        if ok:
            print("✅ 备份完整性校验通过")
        else:
            print("❌ 备份校验失败 — sha256 不匹配", file=sys.stderr)
        return 0 if ok else 1

    # 真正恢复
    print(f"=== [D1-restore] 恢复 {backup_path.name} ===")
    if args.force and not args.target_test:
        print("⚠️  警告: --force 将覆盖目标库所有数据！")
        confirm = input("确认要继续吗？(yes/no): ").strip().lower()
        if confirm != "yes":
            print("已取消")
            return 1

    ok, summary = do_full_restore_sync(
        str(backup_path),
        verify_only=False,
        target_test=args.target_test,
        allow_nonempty=args.force,
    )
    print(summary)
    if ok:
        print("✅ 恢复完成")
    else:
        print("❌ 恢复失败/已被安全门拒绝", file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
