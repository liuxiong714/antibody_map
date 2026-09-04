import os
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.minio_client import delete_file
from app.models.data_point import DataPoint
from app.models.literature import Literature
from app.services.literature._common import (
    _dp_to_dict,
    _first_author_surname,
    _is_dp_conflict,
    _title_similarity,
    logger,
    normalize_title,
)
from app.services.literature.crud import (
    get_literature,
)


async def check_duplicates(
    db: AsyncSession,
    literature_id: uuid.UUID | None = None,
    *,
    title: str | None = None,
    doi: str | None = None,
    authors: str | None = None,
    pdf_hash: str | None = None,
) -> dict:
    """检查重复文献。
    两种模式：
      - 传 literature_id：以该记录为基准查重
      - 传 title/doi/authors/pdf_hash：预检（未落库时）
    返回 {"literature_id": str|None, "duplicates": [...], "total": int}
    """
    if literature_id:
        r = await db.execute(select(Literature).where(Literature.id == literature_id))
        base = r.scalar_one_or_none()
        if not base:
            raise ValueError("文献不存在")
        title = base.title
        doi = base.doi
        authors = base.authors
        pdf_hash = base.pdf_hash

    norm_title = normalize_title(title)
    first_author = _first_author_surname(authors)

    # 候选集：用 DOI / pdf_hash 走索引预筛 + 全表扫标题
    candidates: dict[uuid.UUID, Literature] = {}

    if doi:
        r = await db.execute(select(Literature).where(Literature.doi == doi))
        for m in r.scalars():
            if literature_id and m.id == literature_id:
                continue
            candidates[m.id] = m
    if pdf_hash:
        r = await db.execute(select(Literature).where(Literature.pdf_hash == pdf_hash))
        for m in r.scalars():
            if literature_id and m.id == literature_id:
                continue
            candidates[m.id] = m

    # 标题精确匹配：title_norm 生成列走索引，避免全表扫描
    exact_title_hit = False
    if norm_title:
        r = await db.execute(
            select(Literature).where(Literature.title_norm == norm_title)
        )
        for m in r.scalars():
            if literature_id and m.id == literature_id:
                continue
            candidates.setdefault(m.id, m)
            exact_title_hit = True

    # 模糊匹配回退（Jaccard >= 0.7 且首作者一致）：仅精确未命中时全表扫描
    if norm_title and not exact_title_hit and first_author:
        r = await db.execute(select(Literature))
        for m in r.scalars():
            if literature_id and m.id == literature_id:
                continue
            nm = normalize_title(m.title)
            if nm and _title_similarity(norm_title, nm) >= 0.7 \
                    and first_author == _first_author_surname(m.authors):
                candidates.setdefault(m.id, m)

    # 逐候选项判定命中原因
    duplicates = []
    for m in candidates.values():
        reasons: list[str] = []
        values: dict[str, str] = {}
        if doi and m.doi and m.doi.lower() == doi.lower():
            reasons.append("doi")
            values["doi"] = m.doi
        nm = normalize_title(m.title)
        if norm_title and nm == norm_title:
            reasons.append("title")
            values["title"] = norm_title
        elif norm_title and nm and _title_similarity(norm_title, nm) >= 0.7 \
                and first_author == _first_author_surname(m.authors):
            reasons.append("title+authors")
            values["title"] = norm_title
        if pdf_hash and m.pdf_hash == pdf_hash:
            reasons.append("pdf_hash")
            values["pdf_hash"] = pdf_hash
        if reasons:
            duplicates.append({
                "literature": m,
                "match_reasons": reasons,
                "match_values": values,
            })
    return {
        "literature_id": str(literature_id) if literature_id else None,
        "duplicates": duplicates,
        "total": len(duplicates),
    }


async def scan_duplicates(db: AsyncSession) -> dict:
    """全表扫描，使用并查集（union-find）合并重叠的重复对。
    返回 {"groups": [...], "total_groups": N, "total_duplicates": M}

    F21 优化：
      - 只投影查重所需列（id/title_norm/authors/doi/pdf_hash/created_at），
        避免整表加载 abstract 等大字段，降低内存占用；
      - 标题精确匹配按 title_norm 生成列分组（O(n)）；
      - 模糊匹配（Jaccard>=0.7 且首作者一致）按首作者分组，仅在同作者
        分组内做 O(group²) 比对，判定结果与原全量逐对比对完全一致
        （原模糊分支本就要求首作者相同），大幅缩小比对范围。
    """
    r = await db.execute(
        select(
            Literature.id, Literature.title_norm, Literature.authors,
            Literature.doi, Literature.pdf_hash, Literature.created_at,
        )
    )
    all_lits = list(r.all())
    parent = {lit.id: lit.id for lit in all_lits}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    pair_reasons: dict[tuple, set[str]] = defaultdict(set)

    # 1. DOI / pdf_hash 分组
    by_doi: dict[str, list] = defaultdict(list)
    by_hash: dict[str, list] = defaultdict(list)
    for lit in all_lits:
        if lit.doi:
            by_doi[lit.doi.lower()].append(lit)
        if lit.pdf_hash:
            by_hash[lit.pdf_hash].append(lit)
    for grp in by_doi.values():
        for i in range(1, len(grp)):
            union(grp[0].id, grp[i].id)
            pair_reasons[(grp[0].id, grp[i].id)].add("doi")
    for grp in by_hash.values():
        for i in range(1, len(grp)):
            union(grp[0].id, grp[i].id)
            pair_reasons[(grp[0].id, grp[i].id)].add("pdf_hash")

    # 2. 标题匹配（title_norm 复用生成列）
    # 2a. 精确标题：所有同 title_norm 的文献互连（跨作者也判为重复）
    title_bucket: dict[str, list] = defaultdict(list)
    for lit in all_lits:
        na = lit.title_norm or ""
        if na:
            title_bucket[na].append(lit)
    for members in title_bucket.values():
        for i in range(1, len(members)):
            union(members[0].id, members[i].id)
            pair_reasons[(members[0].id, members[i].id)].add("title")

    # 2b. 模糊标题（Jaccard>=0.7 且首作者一致）：按首作者分组缩小比对范围
    author_bucket: dict[str, list] = defaultdict(list)
    for lit in all_lits:
        fa = _first_author_surname(lit.authors)
        if fa:
            author_bucket[fa].append(lit)
    for members in author_bucket.values():
        n = len(members)
        for i in range(n):
            na = members[i].title_norm or ""
            if not na:
                continue
            for j in range(i + 1, n):
                nb = members[j].title_norm or ""
                if not nb:
                    continue
                if na == nb:
                    continue  # 已在 2a 记为 title
                if _title_similarity(na, nb) >= 0.7:
                    union(members[i].id, members[j].id)
                    pair_reasons[(members[i].id, members[j].id)].add("title+authors")

    # 3. 聚合
    groups_map: dict[uuid.UUID, list] = defaultdict(list)
    for lit in all_lits:
        groups_map[find(lit.id)].append(lit)

    groups = []
    for root, members in groups_map.items():
        if len(members) < 2:
            continue
        reasons: set[str] = set()
        for (a, _b), rs in pair_reasons.items():
            if find(a) == root:
                reasons |= rs
        representative = min(members, key=lambda x: x.created_at)
        groups.append({
            "literature_ids": [m.id for m in members],
            "match_reasons": sorted(reasons),
            "representative_id": representative.id,
        })
    total_dup = sum(len(g["literature_ids"]) for g in groups)
    return {
        "groups": groups,
        "total_groups": len(groups),
        "total_duplicates": total_dup,
    }


# 合并时可逐字段选择的字段列表
_MERGE_FIELDS = [
    "title", "title_en", "authors", "journal", "pub_year", "doi", "pmid",
    "abstract", "keywords", "region", "province", "publication_types",
    "source_db", "file_path",
]
_ARRAY_FIELDS = {"keywords", "publication_types"}


async def preview_merge(db: AsyncSession, source_id: uuid.UUID, target_id: uuid.UUID) -> dict:
    """预览合并：逐字段对比 + 数据点冲突检测"""
    source = await get_literature(db, source_id)
    target = await get_literature(db, target_id)
    if not source or not target:
        raise ValueError("源或目标文献不存在")

    field_comparison = []
    for f in _MERGE_FIELDS:
        sv = getattr(source, f, None)
        tv = getattr(target, f, None)
        field_comparison.append({
            "field": f,
            "source_value": sv,
            "target_value": tv,
            "differs": sv != tv,
        })

    s_dps = (await db.execute(
        select(DataPoint).where(DataPoint.literature_id == source_id))).scalars().all()
    t_dps = (await db.execute(
        select(DataPoint).where(DataPoint.literature_id == target_id))).scalars().all()

    conflicts = []
    total_conflicts = 0
    MAX_CONFLICTS = 50
    for s in s_dps:
        for t in t_dps:
            if _is_dp_conflict(s, t):
                total_conflicts += 1
                if len(conflicts) < MAX_CONFLICTS:
                    key = f"{s.disease}|{s.province}|{s.collection_year}|{s.data_type}"
                    conflicts.append({
                        "source_dp": _dp_to_dict(s),
                        "target_dp": _dp_to_dict(t),
                        "key": key,
                    })

    return {
        "field_comparison": field_comparison,
        "source_data_point_count": len(s_dps),
        "target_data_point_count": len(t_dps),
        "conflicts": conflicts,
        "total_conflicts": total_conflicts,
    }


async def merge_literatures(
    db: AsyncSession,
    source_id: uuid.UUID,
    target_id: uuid.UUID,
    field_choices: dict,
    dp_conflict_strategy: str = "keep_both",
) -> dict:
    """执行合并：将 source 合并进 target，删除 source。
    field_choices: {字段名: "source"|"target"|"merge"}
    dp_conflict_strategy: "keep_both"|"prefer_target"|"prefer_source"
    """
    if source_id == target_id:
        raise ValueError("不能与自身合并")
    source = await get_literature(db, source_id)
    target = await get_literature(db, target_id)
    if not source or not target:
        raise ValueError("源或目标文献不存在")

    valid_strategies = {"keep_both", "prefer_target", "prefer_source"}
    if dp_conflict_strategy not in valid_strategies:
        raise ValueError(f"未知冲突策略: {dp_conflict_strategy}")

    # 1. 按 field_choices 更新 target 字段
    for f in _MERGE_FIELDS:
        if f not in field_choices:
            continue
        c = field_choices[f]
        if c == "source":
            setattr(target, f, getattr(source, f))
        elif c == "merge" and f in _ARRAY_FIELDS:
            tgt = list(getattr(target, f) or [])
            src = list(getattr(source, f) or [])
            merged = list(dict.fromkeys(tgt + src))  # 保序去重
            setattr(target, f, merged)
        # c == "target"：保持不变

    # 2. 迁移 DataPoint
    s_dps = (await db.execute(
        select(DataPoint).where(DataPoint.literature_id == source_id))).scalars().all()
    t_dps = (await db.execute(
        select(DataPoint).where(DataPoint.literature_id == target_id))).scalars().all()

    moved = 0
    deleted_conflicts = 0
    for s_dp in s_dps:
        conflict_tgts = [t for t in t_dps if _is_dp_conflict(s_dp, t)]
        if not conflict_tgts:
            s_dp.literature_id = target_id
            moved += 1
            continue
        if dp_conflict_strategy == "keep_both":
            s_dp.literature_id = target_id
            moved += 1
        elif dp_conflict_strategy == "prefer_target":
            await db.delete(s_dp)
            deleted_conflicts += 1
        elif dp_conflict_strategy == "prefer_source":
            for t in conflict_tgts:
                await db.delete(t)
                t_dps.remove(t)
            s_dp.literature_id = target_id
            moved += 1
            deleted_conflicts += len(conflict_tgts)

    # 3. 重算 target 计数
    total_dp = (await db.execute(
        select(func.count(DataPoint.id)).where(DataPoint.literature_id == target_id))).scalar() or 0
    approved = (await db.execute(
        select(func.count(DataPoint.id))
        .where(DataPoint.literature_id == target_id)
        .where(DataPoint.review_status == "approved"))).scalar() or 0
    target.extracted_count = total_dp
    target.approved_count = approved
    target.updated_at = datetime.now(timezone.utc)

    # 4. 文件处理：若选择保留 source 的文件，target.file_path 已被设为 source.file_path
    #    需要清理原 target 文件；删除 source 前置空 file_path 防误删
    source_file_to_delete = None
    if field_choices.get("file_path") != "source":
        source_file_to_delete = source.file_path

    source.file_path = None  # 避免 db.delete 触发文件删除逻辑
    await db.delete(source)
    await db.commit()

    # 删除源文件（仅当与 target 文件不同时）
    if source_file_to_delete and source_file_to_delete != target.file_path:
        p = Path(source_file_to_delete)
        if p.exists():
            try:
                os.remove(p)
            except Exception as e:
                logger.warning(f"删除源文件失败: {e}")
        else:
            delete_file(source_file_to_delete)

    await db.refresh(target)
    return {
        "merged_literature": target,
        "moved_data_points": moved,
        "deleted_conflict_data_points": deleted_conflicts,
        "deleted_source_id": str(source_id),
    }