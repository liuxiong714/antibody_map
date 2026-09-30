"""知识图谱实体消歧：ID 生成、标准化清洗、查重合并。

写入三元组前调用 resolve_and_persist 确保实体唯一性：
1. 标准化清洗 name（去空格、全角转半角、去冗余后缀）
2. 生成确定性 ID（MD5 哈希）
3. 查重：同 entity_type + 相似 name > 95% → 合并（merged_into 指向旧实体）
4. 返回最终 entity_id（可能是旧实体的 ID）
"""

import hashlib
import logging
import re
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.kg_entity import KGEntity

logger = logging.getLogger("kg")

# 冗余后缀（地理区域类实体名称常见）
_SUFFIX_RE = re.compile(r'[省市县区镇乡村]$')


def _normalize_name(name: str) -> str:
    """标准化实体名称：去首尾空格、全角转半角、压缩空白。"""
    if not name:
        return ""
    # 全角→半角（ASCII 范围）
    result = name.strip()
    result = result.replace("\u3000", " ")
    result = result.replace("：", ":").replace("，", ",").replace("（", "(").replace("）", ")")
    # 压缩多余空白
    result = re.sub(r"\s+", " ", result)
    return result


def _normalize_for_dedup(name: str) -> str:
    """用于查重的更激进标准化：去后缀、转小写。"""
    result = _normalize_name(name).lower()
    result = _SUFFIX_RE.sub("", result)
    return result.strip()


# 省级行政区枚举（geo_area 实体校验/标准化）
PROVINCE_NAMES = {
    "北京", "上海", "天津", "重庆", "河北", "山西", "辽宁", "吉林", "黑龙江",
    "江苏", "浙江", "安徽", "福建", "江西", "山东", "河南", "湖北", "湖南",
    "广东", "海南", "四川", "贵州", "云南", "陕西", "甘肃", "青海", "台湾",
    "内蒙古", "广西", "西藏", "宁夏", "新疆", "香港", "澳门",
}
# 常见地理大区（含 "region:" 前缀的内部标记）
REGION_NAMES = {"华东", "华北", "华南", "华中", "西南", "西北", "东北"}

_YEAR_RE = re.compile(r"(20\d{2}|19\d{2})")
_YEAR_RANGE_RE = re.compile(r"(20\d{2}|19\d{2})\s*[-~–至到]\s*(20\d{2}|19\d{2})")


def normalize_entity(
    entity_type: str, name: str, attributes: dict | None = None,
) -> tuple[str, dict]:
    """按实体类型做归一化：时间→年份规范化，地区→省级枚举校验。

    返回 (归一化后的 name, 补全后的 attributes)。
    """
    name = _normalize_name(name)
    attrs = dict(attributes or {})
    if entity_type == "time_period":
        # 年份规范化：名称统一为 "YYYY年"，attributes.year 存整数
        rm = _YEAR_RANGE_RE.search(name)
        m = rm or _YEAR_RE.search(name)
        if m:
            year = int(m.group(1))
            attrs["year"] = year
            name = f"{year}年"
    elif entity_type == "geo_area":
        base = name
        if base.startswith("region:"):
            region = base[len("region:"):]
            attrs["region"] = region
            return f"region:{region}", attrs
        base = re.sub(r"(省|市|自治区|特别行政区|地区|州|区|县)$", "", base)
        if base in PROVINCE_NAMES:
            # 省级行政区：统一不带行政后缀，记录 province 属性
            attrs["province"] = base
            name = base
        elif base in REGION_NAMES:
            attrs["region"] = base
    return name, attrs


def generate_entity_id(entity_type: str, name: str, attributes: dict | None = None) -> str:
    """生成确定性实体 ID：基于类型+标准化名称+排序属性 MD5 取前 16 位。"""
    normalized_name = _normalize_name(name)
    attr_str = ""
    if attributes:
        attr_str = str(sorted(attributes.items()))
    raw = f"{entity_type}_{normalized_name.lower()}_{attr_str}"
    return hashlib.md5(raw.encode()).hexdigest()[:16]


def _edit_distance_similarity(a: str, b: str) -> float:
    """基于编辑距离的相似度（0~1）。"""
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    m, n = len(a), len(b)
    # 剪枝：长度差异过大直接返回 0
    if abs(m - n) > max(m, n) * 0.5:
        return 0.0
    dp = list(range(n + 1))
    for i in range(1, m + 1):
        prev = dp[0]
        dp[0] = i
        for j in range(1, n + 1):
            tmp = dp[j]
            if a[i - 1] == b[j - 1]:
                dp[j] = prev
            else:
                dp[j] = 1 + min(dp[j], dp[j - 1], prev)
            prev = tmp
    dist = dp[n]
    return 1.0 - dist / max(m, n)


async def resolve_entity(
    db: AsyncSession,
    entity_type: str,
    name: str,
    attributes: dict | None = None,
    literature_id: uuid.UUID | None = None,
) -> str:
    """消歧并返回最终 entity_id。

    若同类型下存在相似度 > 95% 的已存在实体，返回旧实体 ID（不创建新实体）。
    否则创建新实体并返回其 ID。
    """
    normalized = _normalize_name(name)
    if not normalized:
        raise ValueError(f"实体名称不能为空: {name}")

    # 类型化归一化（时间→年份规范化，地区→省级枚举校验）
    normalized, attrs = normalize_entity(entity_type, normalized, attributes)

    dedup_key = _normalize_for_dedup(normalized)
    entity_id = generate_entity_id(entity_type, normalized, attrs)

    # 1. 精确匹配（按 ID）
    existing = await db.get(KGEntity, entity_id)
    if existing and not existing.merged_into:
        # 已存在且未被合并，更新属性
        if attrs:
            existing_attrs = existing.attributes or {}
            existing_attrs.update(attrs)
            existing.attributes = existing_attrs
        return entity_id

    if existing and existing.merged_into:
        return existing.merged_into

    # 2. 模糊匹配（同类型 + 相似度 > 95%）
    stmt = select(KGEntity).where(
        KGEntity.entity_type == entity_type,
        KGEntity.merged_into.is_(None),
    )
    result = await db.execute(stmt)
    candidates = result.scalars().all()

    for candidate in candidates:
        candidate_key = _normalize_for_dedup(candidate.name)
        sim = _edit_distance_similarity(dedup_key, candidate_key)
        if sim > 0.95:
            # 合并：新实体指向旧实体
            new_entity = KGEntity(
                id=entity_id,
                entity_type=entity_type,
                name=normalized,
                attributes=attrs,
                source_literature_id=literature_id,
                merged_into=candidate.id,
            )
            db.add(new_entity)
            await db.flush()
            logger.info(f"实体合并: '{normalized}' -> '{candidate.name}' (sim={sim:.3f})")
            return candidate.id

    # 3. 无匹配，创建新实体
    new_entity = KGEntity(
        id=entity_id,
        entity_type=entity_type,
        name=normalized,
        attributes=attrs,
        source_literature_id=literature_id,
    )
    db.add(new_entity)
    await db.flush()
    return entity_id


async def persist_triples(
    db: AsyncSession,
    entities: list[dict],
    triples: list[dict],
    literature_id: uuid.UUID | None = None,
) -> int:
    """批量消歧写入实体和三元组，返回写入的三元组数。

    entities: [{"id": ..., "type": ..., "name": ..., "attributes": {...}}]
    triples: [{"subject_id": ..., "predicate": ..., "object_id": ..., "confidence": ..., "source_context": ...}]

    注意：entities 中的 id 是 LLM 生成的临时 ID，需通过 resolve_entity 映射到最终 ID。
    """
    from app.models.kg_triple import KGTriple

    # 第一遍：消歧所有实体，建立 临时ID → 最终ID 映射
    id_map: dict[str, str] = {}
    for ent in entities:
        etype = ent.get("type", "")
        ename = ent.get("name", "")
        attrs = ent.get("attributes", {})
        temp_id = ent.get("id", "")
        if not etype or not ename:
            continue
        final_id = await resolve_entity(db, etype, ename, attrs, literature_id)
        if temp_id:
            id_map[temp_id] = final_id

    # 第二遍：写入三元组
    written = 0
    for tri in triples:
        subj_temp = tri.get("subject_id", "")
        obj_temp = tri.get("object_id", "")
        subj_id = id_map.get(subj_temp)
        obj_id = id_map.get(obj_temp)
        if not subj_id or not obj_id:
            logger.warning(f"三元组引用了未知实体: subj={subj_temp}, obj={obj_temp}")
            continue

        predicate = tri.get("predicate", "")
        if not predicate:
            continue

        triple_id = hashlib.md5(
            f"{subj_id}_{predicate}_{obj_id}_{literature_id}".encode()
        ).hexdigest()[:32]

        # 检查是否已存在（联合唯一约束）
        existing = await db.execute(
            select(KGTriple.id).where(KGTriple.id == triple_id)
        )
        if existing.scalar_one_or_none():
            continue

        triple = KGTriple(
            id=triple_id,
            subject_id=subj_id,
            predicate=predicate,
            object_id=obj_id,
            confidence=tri.get("confidence", 1.0),
            source_context=tri.get("source_context"),
            literature_id=literature_id,
        )
        db.add(triple)
        written += 1

    if written:
        await db.flush()
    return written
