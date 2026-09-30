"""中国 34 个省级行政区权威元数据：分区分类（中部/东部/西部/北部/南部）与简称。

此模块作为省份→(全称/分区/简称) 的唯一数据源，供字典 API、区域/空间聚合、
前端省份选择器等消费。所有查询函数先经 ``term_normalizer.normalize_province``
归一化为规范短名（北京、天津……）再查表，兼容全称/简称/英文等原始表述。

**只增不改**：新增字段或函数不影响既有省份标准化与聚合逻辑。
"""
from __future__ import annotations

from app.core.term_normalizer import normalize_province

# 五大地域分区（颜色/排序语义由消费端决定）
REGIONS = ["中部", "东部", "西部", "北部", "南部"]

# 规范短名 → {全称, 分区, 简称}
CHINA_PROVINCE_META: dict[str, dict[str, str]] = {
    "北京": {"full": "北京市", "region": "中部", "abbr": "京"},
    "天津": {"full": "天津市", "region": "中部", "abbr": "津"},
    "上海": {"full": "上海市", "region": "东部", "abbr": "沪"},
    "重庆": {"full": "重庆市", "region": "西部", "abbr": "渝"},
    "河北": {"full": "河北省", "region": "中部", "abbr": "冀"},
    "山西": {"full": "山西省", "region": "中部", "abbr": "晋"},
    "辽宁": {"full": "辽宁省", "region": "北部", "abbr": "辽"},
    "吉林": {"full": "吉林省", "region": "北部", "abbr": "吉"},
    "黑龙江": {"full": "黑龙江省", "region": "北部", "abbr": "黑"},
    "江苏": {"full": "江苏省", "region": "东部", "abbr": "苏"},
    "浙江": {"full": "浙江省", "region": "东部", "abbr": "浙"},
    "安徽": {"full": "安徽省", "region": "东部", "abbr": "皖"},
    "福建": {"full": "福建省", "region": "东部", "abbr": "闽"},
    "江西": {"full": "江西省", "region": "东部", "abbr": "赣"},
    "山东": {"full": "山东省", "region": "北部", "abbr": "鲁"},
    "河南": {"full": "河南省", "region": "中部", "abbr": "豫"},
    "湖北": {"full": "湖北省", "region": "中部", "abbr": "鄂"},
    "湖南": {"full": "湖南省", "region": "南部", "abbr": "湘"},
    "广东": {"full": "广东省", "region": "南部", "abbr": "粤"},
    "海南": {"full": "海南省", "region": "南部", "abbr": "琼"},
    "四川": {"full": "四川省", "region": "西部", "abbr": "川"},
    "贵州": {"full": "贵州省", "region": "南部", "abbr": "贵"},
    "云南": {"full": "云南省", "region": "南部", "abbr": "云"},
    "陕西": {"full": "陕西省", "region": "中部", "abbr": "陕"},
    "甘肃": {"full": "甘肃省", "region": "西部", "abbr": "甘"},
    "青海": {"full": "青海省", "region": "西部", "abbr": "青"},
    "台湾": {"full": "台湾省", "region": "东部", "abbr": "台"},
    "内蒙古": {"full": "内蒙古自治区", "region": "北部", "abbr": "蒙"},
    "广西": {"full": "广西壮族自治区", "region": "南部", "abbr": "桂"},
    "西藏": {"full": "西藏自治区", "region": "西部", "abbr": "藏"},
    "宁夏": {"full": "宁夏回族自治区", "region": "西部", "abbr": "宁"},
    "新疆": {"full": "新疆维吾尔自治区", "region": "西部", "abbr": "新"},
    "香港": {"full": "香港特别行政区", "region": "南部", "abbr": "港"},
    "澳门": {"full": "澳门特别行政区", "region": "南部", "abbr": "澳"},
}


def _short(name: str | None) -> str | None:
    """任意表述归一化为规范短名；无法识别返回 None。"""
    if not name:
        return None
    return normalize_province(name)


def province_meta(name: str | None) -> dict[str, str] | None:
    """返回省份元数据 {full, region, abbr}；无法识别返回 None。"""
    key = _short(name)
    if not key:
        return None
    return CHINA_PROVINCE_META.get(key)


def province_region(name: str | None) -> str | None:
    """省份所属分区（中部/东部/西部/北部/南部）。"""
    meta = province_meta(name)
    return meta["region"] if meta else None


def province_abbr(name: str | None) -> str | None:
    """省份简称（京、沪……）。"""
    meta = province_meta(name)
    return meta["abbr"] if meta else None


def province_full_name(name: str | None) -> str | None:
    """省份全称（北京市、新疆维吾尔自治区……）。"""
    meta = province_meta(name)
    return meta["full"] if meta else None


def group_provinces_by_region(short_names: list[str]) -> dict[str, list[str]]:
    """将规范短名列表按分区归组，返回 {分区: [短名...]}（跳过无法识别的）。"""
    grouped: dict[str, list[str]] = {}
    for name in short_names:
        key = _short(name)
        if not key:
            continue
        region = province_region(key)
        if not region:
            continue
        grouped.setdefault(region, []).append(key)
    return grouped