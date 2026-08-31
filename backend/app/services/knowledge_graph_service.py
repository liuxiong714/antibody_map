"""知识图谱服务：基于本体（ontology.py）从 approved 数据点构建实体-关系图。

数据推导规则（仅从数据点推导）：
- 每个 approved primary 数据点 = 一个 SURVEY 实体，向 6 个维度建立基础关系边；
- disease → pathogen、province → geo_area、collection_year → time_period、
  population → host_group、method/assay → lab_assay、data_type → indicator；
- BELONGS_TO：省份 geo_area → 大区 geo_area（基于固定七大区映射）；
- HIGHER_THAN：同（疾病+指标类型+单位）分组内，高值指标指向低值指标（统计对比动态生成）；
- INFLUENCES：高于组均值+1σ 的"异常高值"调查，其宿主/地区/时期/方法因子指向该指标（动态生成）。
"""

import logging
import statistics
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.data_point import DataPoint
from app.models.literature import Literature
from app.core.term_normalizer import normalize_disease, normalize_province, normalize_method
from app.services.map_service import _normalize_population, _normalize_seroprevalence
from app.ontology import EntityType, RelationType

logger = logging.getLogger("uvicorn")

# ===== 省份 → 大区 映射（BELONGS_TO 层级）=====
REGION_MAP: dict[str, str] = {
    "北京": "华北", "天津": "华北", "河北": "华北", "山西": "华北", "内蒙古": "华北",
    "辽宁": "东北", "吉林": "东北", "黑龙江": "东北",
    "上海": "华东", "江苏": "华东", "浙江": "华东", "安徽": "华东",
    "福建": "华东", "江西": "华东", "山东": "华东",
    "河南": "华中", "湖北": "华中", "湖南": "华中",
    "广东": "华南", "广西": "华南", "海南": "华南",
    "重庆": "西南", "四川": "西南", "贵州": "西南", "云南": "西南", "西藏": "西南",
    "陕西": "西北", "甘肃": "西北", "青海": "西北", "宁夏": "西北", "新疆": "西北",
    "香港": "港澳台", "澳门": "港澳台", "台湾": "港澳台",
}

DATA_TYPE_LABEL = {"seroprevalence": "阳性率", "gmc": "几何平均滴度"}

RELATION_LABEL = {
    RelationType.SURVEYED_AT: "调查于",
    RelationType.COVERED_TIME: "覆盖时期",
    RelationType.TARGETS_HOST: "目标人群",
    RelationType.DETECTS_PATHOGEN: "检测病原体",
    RelationType.USES_ASSAY: "使用检测",
    RelationType.REPORTS_INDICATOR: "报告指标",
    RelationType.HIGHER_THAN: "高于",
    RelationType.BELONGS_TO: "隶属于",
    RelationType.INFLUENCES: "影响",
}

# 控制边数量上限，避免图谱过密
_MAX_HIGHER_THAN_PER_GROUP = 8
_MAX_HIGHER_THAN_TOTAL = 200
_MAX_INFLUENCES_PER_SURVEY = 3
_MAX_INFLUENCES_TOTAL = 150


def _split_provinces(raw: Optional[str]) -> list[str]:
    """将可能含分隔符的省份字段拆分为多个省份名并标准化。"""
    if not raw:
        return []
    out: list[str] = []
    for part in raw.replace("、", ",").replace("/", ",").replace("和", ",").split(","):
        p = normalize_province(part.strip())
        if p and p not in out:
            out.append(p)
    return out


def _region_of(province: str) -> Optional[str]:
    return REGION_MAP.get(province)


def _make_id(etype: EntityType, value: str) -> str:
    return f"{etype.value}:{value}"


async def get_approved_dps(
    db: AsyncSession,
    disease: Optional[str] = None,
    province: Optional[str] = None,
    data_type: Optional[str] = None,
    year_start: Optional[int] = None,
    year_end: Optional[int] = None,
) -> list:
    """查询 approved + primary 数据点（不含已删除文献），仅投影所需列。"""
    base = select(
        DataPoint.id, DataPoint.literature_id, DataPoint.disease, DataPoint.province,
        DataPoint.collection_year, DataPoint.population, DataPoint.method, DataPoint.assay,
        DataPoint.data_type, DataPoint.value, DataPoint.unit, DataPoint.sample_size,
        DataPoint.estimate_type,
    ).where(
        DataPoint.review_status == "approved",
        DataPoint.estimate_type == "primary",
    )
    base = base.outerjoin(Literature, DataPoint.literature_id == Literature.id)
    base = base.where(Literature.deleted_at.is_(None))
    if disease:
        base = base.where(DataPoint.disease == disease)
    if province:
        base = base.where(DataPoint.province.ilike(f"%{province}%"))
    if data_type:
        base = base.where(DataPoint.data_type == data_type)
    if year_start:
        base = base.where(DataPoint.collection_year >= year_start)
    if year_end:
        base = base.where(DataPoint.collection_year <= year_end)
    result = await db.execute(base)
    return result.all()


class _GraphBuilder:
    """从数据点集合构建节点与边，支持按样本量裁剪。"""

    def __init__(self):
        self.nodes: dict[str, dict] = {}
        self.edges: list[dict] = []
        self._edge_keys: set[tuple[str, str, str]] = set()
        self._seq = 0
        # 每个调查的构建记录：新增节点/边、指标分组信息
        self._surveys: list[dict] = []

    # ---- 节点/边 ----
    def _add_node(self, nid: str, etype: EntityType, label: str, props: Optional[dict] = None) -> bool:
        """新增节点返回 True；已存在则聚合 survey_count 并合并 props 返回 False。"""
        node = self.nodes.get(nid)
        if node is None:
            self.nodes[nid] = {
                "id": nid, "type": etype.value, "label": label, "survey_count": 0, "props": props or {},
            }
            return True
        node["survey_count"] = node.get("survey_count", 0) + 1
        if props:
            node.setdefault("props", {}).update(props)
        return False

    def _add_edge(self, source: str, target: str, rtype: RelationType, props: Optional[dict] = None) -> int:
        key = (source, target, rtype.value)
        if key in self._edge_keys:
            return -1
        self._edge_keys.add(key)
        edge = {
            "id": f"e{len(self.edges)}",
            "source": source,
            "target": target,
            "type": rtype.value,
            "label": RELATION_LABEL.get(rtype, rtype.value),
        }
        if props:
            edge["props"] = props
        self.edges.append(edge)
        return len(self.edges) - 1

    # ---- 单个调查子图 ----
    def add_survey(self, dp) -> None:
        self._seq += 1
        sid = str(dp.id)
        survey_id = _make_id(EntityType.SURVEY, sid)

        disease = normalize_disease(dp.disease)
        provinces = _split_provinces(dp.province)
        year = dp.collection_year
        host = _normalize_population(dp.population) if dp.population else None
        method = normalize_method(dp.method) or (normalize_method(dp.assay) if dp.assay else None)
        data_type = dp.data_type
        value = None
        if dp.value is not None:
            value = _normalize_seroprevalence(dp.value) if data_type == "seroprevalence" else float(dp.value)
        unit = dp.unit or ("%" if data_type == "seroprevalence" else None)
        sample_size = dp.sample_size

        survey_props = {
            "disease": disease,
            "province": "、".join(provinces) if provinces else None,
            "year": year,
            "population": host,
            "method": method,
            "data_type": data_type,
            "value": value,
            "unit": unit,
            "sample_size": sample_size,
            "literature_id": str(dp.literature_id) if dp.literature_id else None,
        }
        self._add_node(survey_id, EntityType.SURVEY, f"调查#{self._seq}", survey_props)

        # pathogen
        if disease:
            pid = _make_id(EntityType.PATHOGEN, disease)
            self._add_node(pid, EntityType.PATHOGEN, disease, {"disease": disease})
            self._add_edge(survey_id, pid, RelationType.DETECTS_PATHOGEN)

        # geo_area（省份）+ BELONGS_TO（省份→大区）
        for prov in provinces:
            gid = _make_id(EntityType.GEO_AREA, prov)
            self._add_node(gid, EntityType.GEO_AREA, prov, {"province": prov})
            self._add_edge(survey_id, gid, RelationType.SURVEYED_AT)
            region = _region_of(prov)
            if region:
                rid = _make_id(EntityType.GEO_AREA, f"region:{region}")
                self._add_node(rid, EntityType.GEO_AREA, region, {"region": region})
                self._add_edge(gid, rid, RelationType.BELONGS_TO)

        # time_period
        if year:
            tid = _make_id(EntityType.TIME_PERIOD, str(year))
            self._add_node(tid, EntityType.TIME_PERIOD, f"{year}年", {"year": year})
            self._add_edge(survey_id, tid, RelationType.COVERED_TIME)

        # host_group
        if host:
            hid = _make_id(EntityType.HOST_GROUP, host)
            self._add_node(hid, EntityType.HOST_GROUP, host, {"population": host})
            self._add_edge(survey_id, hid, RelationType.TARGETS_HOST)

        # lab_assay
        if method:
            aid = _make_id(EntityType.LAB_ASSAY, method)
            self._add_node(aid, EntityType.LAB_ASSAY, method, {"method": method})
            self._add_edge(survey_id, aid, RelationType.USES_ASSAY)

        # indicator（每调查一个指标测量节点，承载数值用于 HIGHER_THAN/INFLUENCES）
        group_member = None
        if data_type and value is not None:
            iid = _make_id(EntityType.INDICATOR, sid)
            type_label = DATA_TYPE_LABEL.get(data_type, data_type)
            base_label = f"{disease or '未知'}·{type_label}"
            self._add_node(
                iid, EntityType.INDICATOR, f"{base_label} {value}{unit or ''}",
                {
                    "disease": disease,
                    "data_type": data_type,
                    "value": value,
                    "unit": unit,
                    "sample_size": sample_size,
                    "survey_id": sid,
                },
            )
            self._add_edge(survey_id, iid, RelationType.REPORTS_INDICATOR)
            group_member = {
                "indicator_id": iid,
                "survey_id": sid,
                "value": value,
                "sample_size": sample_size or 0,
                "province": provinces,
                "year": year,
                "host": host,
                "method": method,
            }

        self._surveys.append({
            "sample_size": sample_size or 0,
            "sid": sid,
            "iid": _make_id(EntityType.INDICATOR, sid) if group_member else None,
            "group_key": (disease, data_type, unit) if group_member else None,
            "group_member": group_member,
        })

    # ---- 裁剪：按样本量从小到大移除，直到节点数不超过 max_nodes ----
    def trim_to(self, max_nodes: int) -> int:
        if len(self.nodes) <= max_nodes:
            return 0
        removed = 0
        # 按样本量升序（小样本优先移除），样本量相同则按加入顺序（后者优先）
        order = sorted(range(len(self._surveys)), key=lambda i: (self._surveys[i]["sample_size"], -i))
        for idx in order:
            if len(self.nodes) <= max_nodes:
                break
            rec = self._surveys[idx]
            survey_nid = _make_id(EntityType.SURVEY, rec["sid"])
            # 移除与该调查直接相关的边（survey 节点与指标节点上的所有边）
            edges_to_remove = [
                i for i, e in enumerate(self.edges)
                if e["source"] == survey_nid or e["target"] == survey_nid
                or (rec["iid"] and (e["source"] == rec["iid"] or e["target"] == rec["iid"]))
            ]
            drop = set(edges_to_remove)
            self.edges = [e for i, e in enumerate(self.edges) if i not in drop]
            self._edge_keys = {(e["source"], e["target"], e["type"]) for e in self.edges}
            # 移除失去所有边引用的孤立节点（survey 节点、指标节点、独占维度节点）
            referenced = {e["source"] for e in self.edges} | {e["target"] for e in self.edges}
            candidates = {survey_nid}
            if rec["iid"]:
                candidates.add(rec["iid"])
            for nid in candidates:
                if nid in self.nodes and nid not in referenced:
                    self.nodes.pop(nid, None)
                    removed += 1
            rec["removed"] = True
        # 清理已移除调查的指标分组记录
        self._surveys = [r for r in self._surveys if not r.get("removed")]
        return removed

    # ---- 统计对比边（基于保留的调查）----
    def add_comparison_edges(self) -> None:
        groups: dict[tuple, list[dict]] = {}
        for rec in self._surveys:
            if rec["group_key"] and rec["group_member"] and rec["group_member"]["indicator_id"] in self.nodes:
                groups.setdefault(rec["group_key"], []).append(rec["group_member"])

        # HIGHER_THAN：分组内高值指标 → 低值指标
        higher_total = 0
        for group in groups.values():
            if len(group) < 2:
                continue
            ordered = sorted(group, key=lambda m: m["value"], reverse=True)
            top = ordered[:3]
            bottom = ordered[-3:]
            group_count = 0
            for t in top:
                for b in bottom:
                    if t["value"] > b["value"] and higher_total < _MAX_HIGHER_THAN_TOTAL:
                        self._add_edge(
                            t["indicator_id"], b["indicator_id"], RelationType.HIGHER_THAN,
                            {"diff": round(t["value"] - b["value"], 2)},
                        )
                        higher_total += 1
                        group_count += 1
                        if group_count >= _MAX_HIGHER_THAN_PER_GROUP:
                            break
                if group_count >= _MAX_HIGHER_THAN_PER_GROUP:
                    break

        # INFLUENCES：分组内异常高值调查的因子 → 该指标
        influences_total = 0
        for group in groups.values():
            if len(group) < 3:
                continue
            vals = [m["value"] for m in group]
            mean = statistics.fmean(vals)
            std = statistics.stdev(vals) if len(vals) > 1 else 0.0
            for m in group:
                if m["value"] <= mean + std:
                    continue
                factors = []
                if m["host"]:
                    factors.append(_make_id(EntityType.HOST_GROUP, m["host"]))
                for prov in m["province"]:
                    factors.append(_make_id(EntityType.GEO_AREA, prov))
                if m["year"]:
                    factors.append(_make_id(EntityType.TIME_PERIOD, str(m["year"])))
                if m["method"]:
                    factors.append(_make_id(EntityType.LAB_ASSAY, m["method"]))
                for fid in factors[: _MAX_INFLUENCES_PER_SURVEY]:
                    if influences_total >= _MAX_INFLUENCES_TOTAL:
                        return
                    if fid in self.nodes:
                        self._add_edge(
                            fid, m["indicator_id"], RelationType.INFLUENCES,
                            {"delta": round(m["value"] - mean, 2)},
                        )
                        influences_total += 1

    def survey_count(self) -> int:
        return len(self._surveys)

    def node_list(self) -> list[dict]:
        return list(self.nodes.values())

    def edge_list(self) -> list[dict]:
        return self.edges


async def get_graph(
    db: AsyncSession,
    disease: Optional[str] = None,
    province: Optional[str] = None,
    data_type: Optional[str] = None,
    year_start: Optional[int] = None,
    year_end: Optional[int] = None,
    max_nodes: int = 600,
) -> dict:
    """构建知识图谱（按样本量优先，超出 max_nodes 时裁剪调查）。"""
    rows = await get_approved_dps(db, disease, province, data_type, year_start, year_end)
    if not rows:
        return {"survey_count": 0, "nodes": [], "edges": [], "trimmed_nodes": 0}

    # 按样本量降序加入，保证裁剪时优先保留大样本调查
    rows_sorted = sorted(rows, key=lambda r: (r.sample_size or 0), reverse=True)
    builder = _GraphBuilder()
    for row in rows_sorted:
        builder.add_survey(row)
    trimmed = builder.trim_to(max_nodes=max_nodes)
    # 节点上限过小导致全部调查被裁剪时，清空残留的共享维度节点，避免出现
    # survey_count=0 却仍有孤立节点/边的困惑展示
    if builder.survey_count() == 0:
        return {"survey_count": 0, "nodes": [], "edges": [], "trimmed_nodes": trimmed}
    builder.add_comparison_edges()
    return {
        "survey_count": builder.survey_count(),
        "nodes": builder.node_list(),
        "edges": builder.edge_list(),
        "trimmed_nodes": trimmed,
    }


async def get_overview(db: AsyncSession) -> dict:
    """各实体/关系类型的计数概览（基于 approved primary 数据点）。"""
    rows = await get_approved_dps(db)
    builder = _GraphBuilder()
    for row in rows:
        builder.add_survey(row)
    builder.add_comparison_edges()

    entity_counts = {e.value: 0 for e in EntityType}
    for node in builder.nodes.values():
        entity_counts[node["type"]] += 1
    relation_counts = {r.value: 0 for r in RelationType}
    for edge in builder.edges:
        relation_counts[edge["type"]] += 1

    return {
        "survey_count": builder.survey_count(),
        "entity_counts": entity_counts,
        "relation_counts": relation_counts,
    }


async def get_options(db: AsyncSession) -> dict:
    """可选筛选维度（疾病/地区/时期/人群/方法/指标类型）。"""
    diseases = set()
    provinces = set()
    years = set()
    populations = set()
    methods = set()
    data_types = set()
    rows = await get_approved_dps(db)
    for r in rows:
        d = normalize_disease(r.disease)
        if d:
            diseases.add(d)
        for p in _split_provinces(r.province):
            provinces.add(p)
        if r.collection_year:
            years.add(int(r.collection_year))
        if r.population:
            populations.add(_normalize_population(r.population))
        m = normalize_method(r.method) or (normalize_method(r.assay) if r.assay else None)
        if m:
            methods.add(m)
        if r.data_type:
            data_types.add(r.data_type)
    return {
        "diseases": sorted(diseases, key=lambda x: str(x)),
        "provinces": sorted(provinces, key=lambda x: str(x)),
        "years": sorted(years),
        "populations": sorted(populations, key=lambda x: str(x)),
        "methods": sorted(methods, key=lambda x: str(x)),
        "data_types": sorted(data_types),
    }


async def search_computed(
    db: AsyncSession,
    q: str,
    entity_type: Optional[str] = None,
    limit: int = 10,
) -> list[dict]:
    """在计算式维度中搜索实体（回退方案，当持久化表无结果时使用）。

    从 approved 数据点推导的维度值中模糊匹配关键词。
    """
    rows = await get_approved_dps(db)
    results: list[dict] = []
    seen: set[str] = set()

    for r in rows:
        # 疾病 → pathogen
        d = normalize_disease(r.disease)
        if d and q.lower() in d.lower() and (not entity_type or entity_type == "pathogen"):
            eid = _make_id(EntityType.PATHOGEN, d)
            if eid not in seen:
                seen.add(eid)
                results.append({
                    "id": eid, "entity_type": "pathogen", "name": d,
                    "attributes": {"disease": d}, "triple_count": 0, "source": "computed",
                })

        # 省份 → geo_area
        for p in _split_provinces(r.province):
            if q.lower() in p.lower() and (not entity_type or entity_type == "geo_area"):
                eid = _make_id(EntityType.GEO_AREA, p)
                if eid not in seen:
                    seen.add(eid)
                    results.append({
                        "id": eid, "entity_type": "geo_area", "name": p,
                        "attributes": {"province": p}, "triple_count": 0, "source": "computed",
                    })

        # 人群 → host_group
        if r.population:
            host = _normalize_population(r.population)
            if host and q.lower() in host.lower() and (not entity_type or entity_type == "host_group"):
                eid = _make_id(EntityType.HOST_GROUP, host)
                if eid not in seen:
                    seen.add(eid)
                    results.append({
                        "id": eid, "entity_type": "host_group", "name": host,
                        "attributes": {"population": host}, "triple_count": 0, "source": "computed",
                    })

        # 方法 → lab_assay
        m = normalize_method(r.method) or (normalize_method(r.assay) if r.assay else None)
        if m and q.lower() in m.lower() and (not entity_type or entity_type == "lab_assay"):
            eid = _make_id(EntityType.LAB_ASSAY, m)
            if eid not in seen:
                seen.add(eid)
                results.append({
                    "id": eid, "entity_type": "lab_assay", "name": m,
                    "attributes": {"method": m}, "triple_count": 0, "source": "computed",
                })

        if len(results) >= limit:
            break

    return results[:limit]
