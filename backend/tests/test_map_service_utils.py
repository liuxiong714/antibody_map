"""map_service.py 纯同步函数单元测试 —— 零 mock，全纯数据喂入。"""
from __future__ import annotations

from app.services import map_service as ms


# ===== _normalize_population =====

class TestNormalizePopulation:
    def test_exact_match(self):
        assert ms._normalize_population("大学生") == "学生"
        assert ms._normalize_population("一线医务人员") == "医护人员"
        assert ms._normalize_population("60岁及以上老年人") == "老年人"

    def test_fuzzy_match_contains(self):
        # "18-45岁健康成人" 包含 "成人" → "成人"
        assert ms._normalize_population("18-45岁健康成人") == "成人"
        # 含 "散居儿童" 完整词
        assert ms._normalize_population("某地区散居儿童") == "儿童"

    def test_age_range_pattern(self):
        assert ms._normalize_population("0-6岁") == "儿童"
        assert ms._normalize_population("7-14岁") == "儿童"

    def test_age_single_elder(self):
        assert ms._normalize_population("60岁以上") == "老年人"
        assert ms._normalize_population("65岁及以上老年人") == "老年人"

    def test_age_single_child(self):
        assert ms._normalize_population("5岁以下儿童") == "儿童"

    def test_unknown_kept_as_is(self):
        assert ms._normalize_population("外星生物") == "外星生物"

    def test_empty_returns_empty(self):
        assert ms._normalize_population("") == ""
        assert ms._normalize_population(None) is None

    def test_whitespace_stripped(self):
        assert ms._normalize_population("  小学生  ") == "学生"


# ===== _build_occupation_filter =====

class TestBuildOccupationFilter:
    def test_none_returns_none(self):
        assert ms._build_occupation_filter(None) is None

    def test_empty_string_returns_none(self):
        assert ms._build_occupation_filter("") is None
        assert ms._build_occupation_filter("   ,  ") is None

    def test_single_returns_ilike(self):
        f = ms._build_occupation_filter("医生")
        assert f is not None
        # SQLAlchemy BinaryExpression
        assert hasattr(f, "operator")

    def test_multi_returns_or_(self):
        f = ms._build_occupation_filter("医生,护士,技师")
        assert f is not None
        s = str(f)
        # 多值 → OR 组合多个 LIKE
        assert " OR " in s
        assert "LIKE" in s


# ===== _get_city_coords =====

class TestGetCityCoords:
    def test_exact_match(self):
        lat, lng = ms._get_city_coords("北京", "北京市")
        assert lat == 39.9042
        assert lng == 116.4074

    def test_fuzzy_match(self):
        # "海" 包含 "海淀区" → 命中模糊
        lat, lng = ms._get_city_coords("北京", "海淀")
        assert lat == 39.9592
        assert lng == 116.2992

    def test_fallback_to_province_center(self):
        # 新疆的一个非标准县级市 → 回退到新疆中心 PROVINCE_CENTERS: (87.6, 43.8)
        lat, lng = ms._get_city_coords("新疆", "呼喇喇市")
        assert (lat, lng) == (43.8, 87.6)

    def test_unknown_province_returns_none(self):
        lat, lng = ms._get_city_coords("火星省", "奥林帕斯山")
        assert lat is None
        assert lng is None

    def test_lru_cache_hit(self):
        # 第二次调用应走缓存（内部 lru_cache）
        lat1, lng1 = ms._get_city_coords("广东", "深圳市")
        lat2, lng2 = ms._get_city_coords("广东", "深圳市")
        assert (lat1, lng1) == (lat2, lng2) == (22.5431, 114.0579)


# ===== _parse_provinces =====

class TestParseProvinces:
    def test_none_returns_unknown(self):
        assert ms._parse_provinces(None) == ["unknown"]
        assert ms._parse_provinces("") == ["unknown"]

    def test_semicolon_split(self):
        result = ms._parse_provinces("北京; 上海; 广东")
        assert result == ["北京", "上海", "广东"]

    def test_chinese_semicolon(self):
        result = ms._parse_provinces("北京；上海；广东")
        assert result == ["北京", "上海", "广东"]

    def test_long_text_extracts_provinces(self):
        # "在北京、上海、广东三地开展研究" → 提取出 ["北京", "上海", "广东"]
        result = ms._parse_provinces("在北京上海广东三地开展研究")
        assert "北京" in result
        assert "上海" in result
        assert "广东" in result

    def test_unknown_part_kept_raw(self):
        result = ms._parse_provinces("外星省")
        assert result == ["外星省"]


# ===== _normalize_seroprevalence =====

class TestNormalizeSeroprevalence:
    def test_decimal_converted(self):
        assert ms._normalize_seroprevalence(0.5) == 50.0
        assert ms._normalize_seroprevalence(0.12345) == 12.345  # round(4)

    def test_percentage_passthrough(self):
        assert ms._normalize_seroprevalence(50) == 50.0
        assert ms._normalize_seroprevalence(99.12345) == 99.1235

    def test_greater_than_100_returns_none(self):
        assert ms._normalize_seroprevalence(100.01) is None
        assert ms._normalize_seroprevalence(150) is None

    def test_negative_returns_none(self):
        assert ms._normalize_seroprevalence(-1) is None

    def test_zero_passthrough(self):
        assert ms._normalize_seroprevalence(0) == 0.0

    def test_none_returns_none(self):
        assert ms._normalize_seroprevalence(None) is None


# ===== _calc_weighted_rate =====

class TestCalcWeightedRate:

    class _FakeDP:
        def __init__(self, value, sample_size, data_type="seroprevalence"):
            self.value = value
            self.sample_size = sample_size
            self.data_type = data_type

    def test_empty_returns_none_zero(self):
        rate, n = ms._calc_weighted_rate([])
        assert rate is None and n == 0

    def test_no_valid_samples(self):
        # sample_size=0 的被跳过
        dps = [self._FakeDP(0.5, 0)]
        rate, n = ms._calc_weighted_rate(dps)
        assert rate is None and n == 0

    def test_seroprevalence_weighted(self):
        # dp1: 0.5*100=50% weight 100  → 5000
        # dp2: 0.3*100=30% weight 200  → 6000
        # rate = 11000/300 ≈ 36.67
        dps = [self._FakeDP(0.5, 100), self._FakeDP(0.3, 200)]
        rate, n = ms._calc_weighted_rate(dps)
        assert abs(rate - 36.6667) < 0.01
        assert n == 300

    def test_seroprevalence_out_of_range_excluded(self):
        # dp2 越界 → 排除
        dps = [self._FakeDP(0.5, 100), self._FakeDP(150, 200)]
        rate, n = ms._calc_weighted_rate(dps)
        assert rate == 50.0
        assert n == 100

    def test_gmc_weighted_uses_raw_value(self):
        # GMC 不做 *100
        dps = [self._FakeDP(100, 100, data_type="gmc"), self._FakeDP(200, 200, data_type="gmc")]
        rate, n = ms._calc_weighted_rate(dps, target_data_type="gmc")
        expected = (100*100 + 200*200) / 300  # = 50000/300 = 166.67
        assert abs(rate - expected) < 0.01
        assert n == 300

    def test_seroprevalence_skips_gmc_by_default(self):
        # 默认只算 seroprevalence，GMC 被过滤
        dps = [
            self._FakeDP(50, 100, data_type="seroprevalence"),
            self._FakeDP(200, 200, data_type="gmc"),
        ]
        rate, n = ms._calc_weighted_rate(dps)
        assert rate == 50.0 and n == 100

    def test_mixed_target_ignores_other_type(self):
        dps = [
            self._FakeDP(100, 100, data_type="gmc"),
            self._FakeDP(0.5, 200, data_type="seroprevalence"),
        ]
        rate, n = ms._calc_weighted_rate(dps, target_data_type="gmc")
        assert rate == 100.0 and n == 100  # 只取 GMC
