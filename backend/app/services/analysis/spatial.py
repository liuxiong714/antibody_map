"""Submodule of app.services.analysis (split from analysis_service.py)."""



from sqlalchemy.ext.asyncio import AsyncSession

from app.core.stats_engine import (
    classify_hotspot_cluster,
    g_star,
    morans_i,
)
from app.core.term_normalizer import normalize_province
from app.services.analysis._common import (
    _build_province_weights,
    _load_province_adjacency,
)
from app.services.analysis.basic import get_region_compare


async def get_spatial_hotspots(
    db: AsyncSession,
    disease: str,
    year_start: int | None = None,
    year_end: int | None = None,
    level: str = "province",
) -> dict:
    """省级空间热点/冷点分析（Moran's I 全局自相关 + Getis-Ord Gi* 局部热点）。

    - 率口径：复用 ``get_region_compare`` 的省级加权阳性率（avg_positivity）。
    - 权重口径：binary queen 邻接 → 对称化 → 行标准化；缺数省份不参与且不纳入邻接。
    - 有数据省份 < 8 → 返回 n_valid，由路由层转 422 中文提示。
    """
    region = await get_region_compare(
        db=db,
        disease=disease,
        province=None,
        year_start=year_start,
        year_end=year_end,
        age_min=None,
        age_max=None,
        data_type=None,
    )
    regions = region.get("regions", [])

    adj = _load_province_adjacency()
    adjacency = adj["binary"]

    # 省份名归一化到标准键，仅保留有阳性率的省
    prov_map: dict[str, dict] = {}
    for r in regions:
        rate = r.get("avg_positivity")
        if rate is None:
            continue
        std = normalize_province(r["province"])
        if not std or std not in adjacency or std in prov_map:
            continue
        prov_map[std] = {"name": std, "rate": float(rate)}

    if len(prov_map) < 8:
        return {
            "disease": disease,
            "level": level,
            "year_start": year_start,
            "year_end": year_end,
            "n_valid": len(prov_map),
            "adjacency_version": adj.get("version"),
            "global_moran": None,
            "provinces": [],
        }

    data_provinces = sorted(prov_map.keys())
    rates = [prov_map[p]["rate"] for p in data_provinces]

    # 权重阵 W（对称化 + 行标准化，缺数省份已删行列）
    w = _build_province_weights(adjacency, data_provinces)

    global_moran = morans_i(rates, w)
    gi_list = g_star(rates, w) or []

    provinces = []
    for i, p in enumerate(data_provinces):
        g = gi_list[i] if i < len(gi_list) else None
        gi_z = g["gi_z"] if g else None
        provinces.append({
            "name": p,
            "rate": round(prov_map[p]["rate"], 4),
            "gi_z": gi_z,
            "p": g["p"] if g else None,
            "cluster": classify_hotspot_cluster(gi_z),
        })

    return {
        "disease": disease,
        "level": level,
        "year_start": year_start,
        "year_end": year_end,
        "n_valid": len(data_provinces),
        "adjacency_version": adj.get("version"),
        "global_moran": global_moran,
        "provinces": provinces,
    }



