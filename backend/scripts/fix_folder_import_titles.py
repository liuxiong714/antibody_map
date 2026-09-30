"""修复文献标题（文件名来源导致的脏数据）。

扫描所有文献标题，对疑似文件名来源的标题应用修正：
1. 去除路径前缀、文件扩展名
2. 去除年份/日期前缀（如 2014_、2025-01-01_）
3. 去除序号后缀（如 (1)、_副本）
4. 中文字符间下划线 → 斜杠（如 麻疹_风疹 → 麻疹/风疹）
5. 首尾多余空白/标点清理

适用场景：
    - 从文件夹监控或批量导入时，标题被错误使用了文件名（含年份前缀、路径前缀等）
    - 数据库中标题类似 2014_中国2012年麻疹_风疹实验室网络运转情况分析
    - 实际标题应为 中国2012年麻疹/风疹实验室网络运转情况分析

使用方式：

    # 1. 预览（默认，不修改数据库，安全先行）
    python -m scripts.fix_folder_import_titles

    # 2. 实际执行修正
    python -m scripts.fix_folder_import_titles --apply

    在 worker 容器内执行：
        docker compose exec worker python -m scripts.fix_folder_import_titles [--apply]

    通过 WSL 执行：
        wsl docker compose -f /mnt/e/01-liuxiong/trae/antibody_map/docker-compose.yml exec worker python /app/backend/scripts/fix_folder_import_titles.py [--apply]

注意事项：
    - 默认 dry-run 模式仅预览，不会修改数据库
    - 确认无误后添加 --apply 参数再执行一次
    - 该脚本可重复运行，已修正的标题不会再次修改
    - 建议每次批量导入新文献后，用 dry-run 检查是否有脏数据
"""
import argparse
import asyncio
import logging
import re
import sys
from pathlib import Path

# 确保 backend 目录在 sys.path 中，以便导入 app 模块
_backend_dir = Path(__file__).resolve().parent.parent
if str(_backend_dir) not in sys.path:
    sys.path.insert(0, str(_backend_dir))

from app.models.literature import Literature  # noqa: E402
from app.services.literature_service import (  # noqa: E402
    _TITLE_SUFFIX,
    _TITLE_YEAR_PREFIX,
    _propose_title_fix,
)
from sqlalchemy import select, update  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

logger = logging.getLogger("uvicorn")

# 任意文件扩展名（含不在白名单中的 .html/.caj 等），用于判定“看起来像文件名”
_ANY_EXT_PATTERN = re.compile(r"\.[A-Za-z0-9]{1,10}$")


def _fix_title(raw: str) -> str:
    """修复疑似文件名来源的标题，且不误伤真实含斜杠的标题（如 and/or）。

    判定为文件名来源的条件（满足其一）：
    - 末段带任意文件扩展名（如 .pdf / .html / .caj）
    - 末段含下划线（文件名常见写法，如 measles_2023）
    - 年份/日期前缀（如 2014_xxx）

    真实标题（无扩展名、无下划线，如 and/or study）保持不变。

    例：ref/measles_2023.pdf → measles_2023；webpage/result.html → result；
        and/or study → and/or study（不误伤）。
    """
    t = raw.strip()
    base = t.replace("\\", "/").rsplit("/", 1)[-1]
    is_filename = bool(_ANY_EXT_PATTERN.search(base)) or "_" in base or bool(_TITLE_YEAR_PREFIX.match(t))
    if not is_filename:
        return t
    # 文件名净化：取 basename、去扩展名、去序号后缀、去年份前缀
    t = _ANY_EXT_PATTERN.sub("", base).strip()
    t = _TITLE_SUFFIX.sub("", t).strip()
    while True:
        new_t = _TITLE_YEAR_PREFIX.sub("", t).strip()
        if new_t == t:
            break
        t = new_t
    t = t.strip(" ._-,;:")
    return t if t else raw


async def main():
    parser = argparse.ArgumentParser(
        description="修复文献标题（文件名来源的年份前缀、路径前缀、中文字符间下划线等）"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="实际执行修改（默认仅 dry-run 预览）",
    )
    args = parser.parse_args()

    engine = create_async_engine(
        "postgresql+asyncpg://antibody:antibody123@postgres:5432/antibody_map"
    )
    SessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    db = SessionLocal()

    try:
        stmt = select(Literature).order_by(Literature.created_at)
        result = await db.execute(stmt)
        records = result.scalars().all()

        to_update = []
        for lit in records:
            fixed = _propose_title_fix(lit.title)
            if fixed == lit.title:
                continue
            to_update.append((lit.id, lit.title, fixed))

        if not to_update:
            print("[FixTitles] 所有文献标题均无需修正。")
            return

        print(f"[FixTitles] 发现 {len(to_update)} 条文献标题可修正：")
        print("-" * 80)
        for lit_id, old_title, new_title in to_update:
            print(f"  [FIX]  id={lit_id}")
            print(f"    原: {old_title}")
            print(f"    新: {new_title}")
        print("-" * 80)
        print(f"  共 {len(to_update)} 条待修正")

        if args.apply:
            for lit_id, old_title, new_title in to_update:
                await db.execute(
                    update(Literature)
                    .where(Literature.id == lit_id)
                    .values(title=new_title)
                )
            await db.commit()
            print(f"\n[FixTitles] 成功修正 {len(to_update)} 条文献标题。")
        else:
            print(f"\n[FixTitles] DRY-RUN 模式 — 未实际修改。")
            print("  加 --apply 参数执行修正。")

    finally:
        await db.close()
        await engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    asyncio.run(main())