"""
批量关联脚本：将指定文件夹中的文件与数据库已有文献进行关联（不新建文献记录）。

用途：
  数据库中有文献记录但无文件（has_fulltext=False），将本地文件匹配后关联到文献。

用法：
  cd backend
  python -m scripts.associate_files

匹配策略（按优先级）：
  1. 精确匹配：归一化标题完全相同
  2. 模糊匹配：Jaccard 词集相似度 >= 0.7
  3. 去作者后缀匹配：去除文件名末尾的 _作者名 后匹配
  4. 去作者模糊匹配：去作者后缀后仍然模糊匹配
"""

import asyncio
import hashlib
import logging
import os
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

import sys
# 将 backend 目录加入 sys.path，确保能 import app
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.models.literature import Literature
from app.config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("associate_files")

# ── 文件匹配相关常量 ──────────────────────────────────────

# 文件扩展名
_EXT_PATTERN = re.compile(r"\.(pdf|caj|doc|docx|txt|epub|pptx|xlsx|ps|wps|md)$", re.IGNORECASE)
# 年份前缀
_YEAR_PREFIX = re.compile(r"^(19\d{2}|20\d{2})\s*[ _\-\.,;:]\s*")
# 作者后缀：末尾 _2~4个中文字符（常见于中文文献文件名）
_AUTHOR_SUFFIX = re.compile(r"_(?:[\u4e00-\u9fff]{2,4})$")

# 本地存储目录（与 literature_service.py 中的 LOCAL_STORAGE_DIR 一致）
LOCAL_STORAGE_DIR = BACKEND_DIR / "data" / "pdfs"


def normalize_title(title: str) -> str:
    """标题归一化：小写 + 连字符替换为空格 + 去标点 + 压缩空格"""
    if not title:
        return ""
    t = title.lower().strip()
    t = re.sub(r"[-–—]", " ", t)
    t = re.sub(r"[^\w\s]", "", t)
    t = re.sub(r"\s+", " ", t)
    return t


def clean_filename(filename: str) -> str:
    """从文件名中提取干净标题，并尝试去除作者后缀"""
    t = filename.strip()
    t = _EXT_PATTERN.sub("", t).strip()
    # 去除年份前缀
    while True:
        new_t = _YEAR_PREFIX.sub("", t).strip()
        if new_t == t:
            break
        t = new_t
    # 去除末尾标点
    t = t.strip(" ._-,;:")
    return t if t else filename


def generate_candidates(filename: str) -> list[str]:
    """生成多个候选标题用于匹配"""
    base = clean_filename(filename)
    candidates = [base]

    # 尝试去除作者后缀
    m = _AUTHOR_SUFFIX.search(base)
    if m:
        no_author = base[:m.start()].strip(" ._-,;:")
        if no_author and no_author != base:
            candidates.append(no_author)

    # 也尝试直接去除第一个 _ 后面的部分（年份前缀已去除，剩下的 _ 很可能是作者）
    if "_" in base:
        parts = base.split("_")
        if len(parts) >= 2:
            # 尝试取第一个 _ 前的部分
            first_part = parts[0].strip(" ._-,;:")
            if first_part and first_part != base:
                candidates.append(first_part)
            # 也尝试拼接所有非作者部分
            # 如果最后一部分是 2-4 个中文字符，则去掉
            if re.match(r"^[\u4e00-\u9fff]{2,4}$", parts[-1]):
                joined = "_".join(parts[:-1]).strip(" ._-,;:")
                if joined and joined != base:
                    candidates.append(joined)

    return list(dict.fromkeys(candidates))  # 去重保持顺序


def jaccard_similarity(a: str, b: str) -> float:
    """Jaccard 词集相似度"""
    sa, sb = set(a.split()), set(b.split())
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def find_best_match(candidates: list[str], lit_map: dict[str, "Literature"]) -> tuple:
    """在已有文献中找最佳匹配，返回 (Literature, score, matched_candidate)"""
    best_lit = None
    best_score = 0.0
    best_candidate = None

    for candidate in candidates:
        norm_candidate = normalize_title(candidate)
        if not norm_candidate:
            continue
        # 1. 精确匹配
        if norm_candidate in lit_map:
            return lit_map[norm_candidate], 1.0, candidate

        # 2. 模糊匹配
        for norm_title, lit in lit_map.items():
            score = jaccard_similarity(norm_candidate, norm_title)
            if score > best_score:
                best_score = score
                best_lit = lit
                best_candidate = candidate

    if best_score >= 0.7:
        return best_lit, best_score, best_candidate
    return None, 0.0, None


async def main():
    source_dir = Path(r"E:\01-liuxiong\antibody_map_ref\0803-ref")
    if not source_dir.exists():
        logger.error(f"源文件夹不存在: {source_dir}")
        return

    # ── 1. 收集源文件 ──
    all_files = []
    for f in sorted(source_dir.iterdir()):
        if f.is_file() and _EXT_PATTERN.search(f.name.lower()):
            all_files.append(f)
    logger.info(f"源文件夹共 {len(all_files)} 个文件")

    # ── 2. 连接数据库 ──
    db_url = settings.DATABASE_URL
    # 异步引擎，使用 asyncpg
    if db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif db_url.startswith("postgresql+psycopg2://"):
        db_url = db_url.replace("postgresql+psycopg2://", "postgresql+asyncpg://", 1)

    engine = create_async_engine(db_url, echo=False)
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with SessionLocal() as db:
        # ── 3. 查询所有 has_fulltext=False 的文献 ──
        result = await db.execute(
            select(Literature).where(Literature.has_fulltext == False)
        )
        no_file_lits = list(result.scalars().all())
        logger.info(f"数据库中共 {len(no_file_lits)} 篇文献无文件")

        # 构建归一化标题索引
        lit_map: dict[str, Literature] = {}
        for lit in no_file_lits:
            nt = normalize_title(lit.title)
            if nt:
                # 如果有重复的归一化标题，保留第一个
                if nt not in lit_map:
                    lit_map[nt] = lit

        logger.info(f"构建索引完成: {len(lit_map)} 个唯一标题")

        # ── 4. 逐文件匹配 ──
        matched = 0
        failed = 0
        skipped_has_file = 0
        not_found = 0
        details = []

        LOCAL_STORAGE_DIR.mkdir(parents=True, exist_ok=True)

        for file_path in all_files:
            filename = file_path.name
            candidates = generate_candidates(filename)
            lit, score, matched_candidate = find_best_match(candidates, lit_map)

            if lit is None:
                logger.info(f"[未匹配] {filename}")
                not_found += 1
                details.append({"filename": filename, "status": "not_found", "title": candidates[0]})
                continue

            if lit.has_fulltext:
                logger.info(f"[跳过已有文件] {filename} -> {lit.title} (id={lit.id})")
                skipped_has_file += 1
                details.append({"filename": filename, "status": "skipped_has_file", "literature_id": str(lit.id), "title": lit.title})
                continue

            # ── 5. 复制文件并关联 ──
            ext = file_path.suffix.lower()
            stored_name = f"{uuid.uuid4()}{ext}"
            stored_path = LOCAL_STORAGE_DIR / stored_name

            try:
                shutil.copy2(str(file_path), str(stored_path))
            except Exception as e:
                logger.error(f"[复制失败] {filename}: {e}")
                failed += 1
                details.append({"filename": filename, "status": "copy_error", "error": str(e)})
                continue

            # 计算文件哈希
            file_bytes = stored_path.read_bytes()
            pdf_hash = hashlib.sha256(file_bytes).hexdigest()

            # 更新数据库记录
            old_path = lit.file_path
            lit.file_path = str(stored_path)
            lit.pdf_hash = pdf_hash
            lit.has_fulltext = True
            lit.updated_at = datetime.now(timezone.utc)

            # 如果候选人标题更干净，也更新标题
            if matched_candidate and matched_candidate != lit.title:
                # 只有在候选人标题不是纯粹文件名清洗结果时才更新
                clean_candidate = matched_candidate.strip(" ._-,;:")
                if clean_candidate and len(clean_candidate) > 5:
                    old_title = lit.title
                    lit.title = clean_candidate
                    logger.info(f"  [标题更新] '{old_title}' -> '{clean_candidate}'")

            try:
                await db.commit()
                await db.refresh(lit)
                matched += 1
                logger.info(f"[匹配成功] {filename} -> {lit.title} (id={lit.id}, score={score:.2f}, candidate='{matched_candidate}')")
                details.append({
                    "filename": filename, "status": "matched", "literature_id": str(lit.id),
                    "title": lit.title, "score": round(score, 2), "matched_candidate": matched_candidate,
                })
            except Exception as e:
                logger.error(f"[数据库更新失败] {filename}: {e}")
                await db.rollback()
                # 清理已复制的文件
                try:
                    stored_path.unlink()
                except Exception:
                    pass
                failed += 1
                details.append({"filename": filename, "status": "db_error", "error": str(e)})

    # ── 6. 输出汇总 ──
    logger.info("=" * 60)
    logger.info(f"关联完成：总计 {len(all_files)} 个文件")
    logger.info(f"  匹配成功: {matched}")
    logger.info(f"  匹配失败(未找到): {not_found}")
    logger.info(f"  跳过(已有文件): {skipped_has_file}")
    logger.info(f"  失败(错误): {failed}")
    logger.info("=" * 60)

    # 输出失败的详情
    if not_found > 0:
        logger.info("\n--- 未匹配的文件 ---")
        for d in details:
            if d["status"] == "not_found":
                logger.info(f"  {d['filename']}  -> 候选标题: {d['title']}")


if __name__ == "__main__":
    asyncio.run(main())