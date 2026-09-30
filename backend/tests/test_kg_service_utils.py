"""knowledge_graph_service.py 纯同步函数测试。"""
from __future__ import annotations

from app.services import knowledge_graph_service as kg
from app.services.knowledge_graph_service import EntityType


class TestKGPure:
    def test_split_provinces_none(self):
        assert kg._split_provinces(None) == []
        assert kg._split_provinces("") == []

    def test_split_provinces_delimiters(self):
        # 原函数替换 "、"/"/"/"和" 为逗号后再 split(",")
        assert kg._split_provinces("北京、上海、广东") == ["北京", "上海", "广东"]
        assert kg._split_provinces("北京/上海") == ["北京", "上海"]
        assert kg._split_provinces("北京和上海") == ["北京", "上海"]
        assert kg._split_provinces("北京,上海") == ["北京", "上海"]

    def test_split_provinces_dedupe_and_normalize(self):
        # 标准化 + 去重
        result = kg._split_provinces("北京市、北京、上海")
        assert result == ["北京", "上海"]

    def test_region_of(self):
        assert kg._region_of("北京") == "华北"
        assert kg._region_of("广东") == "华南"
        assert kg._region_of("外星省") is None
        assert kg._region_of(None) is None

    def test_make_id(self):
        eid = kg._make_id(EntityType.PATHOGEN, "新冠肺炎")
        assert eid.startswith("pathogen:")
        assert "新冠肺炎" in eid

        eid2 = kg._make_id(EntityType.GEO_AREA, "广东")
        assert eid2.startswith("geo_area:")

    def test_make_id_empty_value(self):
        eid = kg._make_id(EntityType.PATHOGEN, "")
        assert "pathogen:" in eid
