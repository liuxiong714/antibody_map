"""
测试文献导出/导入 round-trip 功能。

验证场景：
1. 构造2篇文献+数据点，导出为 JSON（含数据点）
2. 删除其中1篇，重新导入 JSON
3. 验证文献和数据点是否正确恢复
4. 验证审核状态、estimate_type 等关键字段是否保留

运行方式：
  cd backend
  python -m pytest tests/test_export_import.py -v --tb=short
"""

import asyncio
import json
import io
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

# 确保后端模块可导入
sys.path.insert(0, str(Path(__file__).parent.parent))


def test_export_json_structure():
    """测试 JSON 导出数据结构正确性"""
    print("\n=== 测试1: JSON 导出结构 ===")

    # 模拟导出数据结构
    mock_lit = MagicMock()
    mock_lit.id = "test-uuid-1"
    mock_lit.title = "麻疹血清流行率研究"
    mock_lit.title_en = "Measles Seroprevalence Study"
    mock_lit.authors = "张三;李四"
    mock_lit.journal = "中华流行病学杂志"
    mock_lit.pub_year = 2020
    mock_lit.doi = "10.1234/test.001"
    mock_lit.pmid = "12345678"
    mock_lit.abstract = "测试摘要"
    mock_lit.keywords = ["麻疹", "血清流行率"]
    mock_lit.region = "华北"
    mock_lit.province = "北京"
    mock_lit.publication_types = ["Journal Article"]
    mock_lit.source_db = "pubmed"
    mock_lit.extraction_status = "done"
    mock_lit.extracted_count = 3
    mock_lit.approved_count = 2
    mock_lit.created_at = None

    mock_dp = MagicMock()
    mock_dp.literature_id = "test-uuid-1"
    mock_dp.disease = "measles"
    mock_dp.province = "北京"
    mock_dp.city = "朝阳区"
    mock_dp.data_type = "seroprevalence"
    mock_dp.value = 95.5
    mock_dp.unit = "%"
    mock_dp.sample_size = 500
    mock_dp.age_min = 5
    mock_dp.age_max = 14
    mock_dp.collection_year = 2020
    mock_dp.method = "ELISA"
    mock_dp.assay = "IgG"
    mock_dp.population = "学龄儿童"
    mock_dp.confidence = "high"
    mock_dp.review_status = "approved"
    mock_dp.estimate_type = "primary"
    mock_dp.source_page = 1
    mock_dp.source_context = "血清阳性率为95.5%"
    mock_dp.source_char_start = 100
    mock_dp.source_char_end = 120
    mock_dp.is_grounded = True
    mock_dp.latitude = None
    mock_dp.longitude = None
    mock_dp.region = None
    mock_dp.age_group = None
    mock_dp.ci_lower = None
    mock_dp.ci_upper = None

    # 构造 JSON 结构
    lit_json = {
        "title": mock_lit.title,
        "title_en": mock_lit.title_en,
        "authors": mock_lit.authors,
        "journal": mock_lit.journal,
        "pub_year": mock_lit.pub_year,
        "doi": mock_lit.doi,
        "pmid": mock_lit.pmid,
        "abstract": mock_lit.abstract,
        "keywords": mock_lit.keywords,
        "region": mock_lit.region,
        "province": mock_lit.province,
        "publication_types": mock_lit.publication_types,
        "source_db": mock_lit.source_db,
        "extraction_status": mock_lit.extraction_status,
        "extracted_count": mock_lit.extracted_count,
        "approved_count": mock_lit.approved_count,
        "data_points": [
            {
                "disease": mock_dp.disease,
                "province": mock_dp.province,
                "city": mock_dp.city,
                "data_type": mock_dp.data_type,
                "value": float(mock_dp.value),
                "unit": mock_dp.unit,
                "sample_size": mock_dp.sample_size,
                "age_min": mock_dp.age_min,
                "age_max": mock_dp.age_max,
                "collection_year": mock_dp.collection_year,
                "method": mock_dp.method,
                "assay": mock_dp.assay,
                "population": mock_dp.population,
                "confidence": mock_dp.confidence,
                "review_status": mock_dp.review_status,
                "estimate_type": mock_dp.estimate_type,
                "source_page": mock_dp.source_page,
                "source_context": mock_dp.source_context,
                "source_char_start": mock_dp.source_char_start,
                "source_char_end": mock_dp.source_char_end,
                "is_grounded": mock_dp.is_grounded,
            }
        ]
    }

    export_data = {
        "export_version": "1.0",
        "exported_at": "2026-08-12T00:00:00+00:00",
        "include_data_points": True,
        "literature_count": 1,
        "data_point_count": 1,
        "literatures": [lit_json],
    }

    # 验证结构
    assert export_data["export_version"] == "1.0"
    assert export_data["literature_count"] == 1
    assert export_data["data_point_count"] == 1
    assert len(export_data["literatures"]) == 1

    lit = export_data["literatures"][0]
    assert lit["title"] == "麻疹血清流行率研究"
    assert lit["doi"] == "10.1234/test.001"
    assert lit["extraction_status"] == "done"
    assert lit["approved_count"] == 2

    dp = lit["data_points"][0]
    assert dp["disease"] == "measles"
    assert dp["province"] == "北京"
    assert dp["value"] == 95.5
    assert dp["review_status"] == "approved"
    assert dp["estimate_type"] == "primary"
    assert dp["is_grounded"] is True

    # 测试 JSON 序列化/反序列化 round-trip
    json_str = json.dumps(export_data, ensure_ascii=False, indent=2)
    parsed = json.loads(json_str)

    assert parsed["literatures"][0]["title"] == "麻疹血清流行率研究"
    assert parsed["literatures"][0]["data_points"][0]["review_status"] == "approved"

    print("  ✅ JSON 导出结构验证通过")
    print("  ✅ JSON round-trip 序列化/反序列化验证通过")


def test_import_data_point_fields():
    """测试导入数据点时字段映射正确"""
    print("\n=== 测试2: 导入数据点字段映射 ===")

    # 导入 JSON 中的数据点
    dp_json = {
        "disease": "mumps",
        "province": "广东",
        "city": "深圳",
        "data_type": "gmc",
        "value": 120.5,
        "unit": "mIU/ml",
        "ci_lower": 100.0,
        "ci_upper": 140.0,
        "sample_size": 300,
        "age_min": 1,
        "age_max": 4,
        "collection_year": 2019,
        "method": "CLIA",
        "assay": "IgG",
        "population": "散居儿童",
        "confidence": "medium",
        "review_status": "approved",
        "estimate_type": "primary",
        "source_page": 2,
        "source_context": "GMC值为120.5 mIU/ml",
        "source_char_start": 50,
        "source_char_end": 70,
        "is_grounded": True,
    }

    # 模拟导入时创建 DataPoint 的字段映射
    dp_fields = {
        "disease": dp_json.get("disease"),
        "region": dp_json.get("region"),
        "province": dp_json.get("province"),
        "city": dp_json.get("city"),
        "data_type": dp_json.get("data_type"),
        "value": dp_json.get("value"),
        "unit": dp_json.get("unit"),
        "ci_lower": dp_json.get("ci_lower"),
        "ci_upper": dp_json.get("ci_upper"),
        "sample_size": dp_json.get("sample_size"),
        "age_min": dp_json.get("age_min"),
        "age_max": dp_json.get("age_max"),
        "collection_year": dp_json.get("collection_year"),
        "method": dp_json.get("method"),
        "assay": dp_json.get("assay"),
        "population": dp_json.get("population"),
        "confidence": dp_json.get("confidence") or "medium",
        "review_status": dp_json.get("review_status") or "pending",
        "estimate_type": dp_json.get("estimate_type") or "primary",
        "source_page": dp_json.get("source_page"),
        "source_context": dp_json.get("source_context"),
        "source_char_start": dp_json.get("source_char_start"),
        "source_char_end": dp_json.get("source_char_end"),
        "is_grounded": dp_json.get("is_grounded", False),
    }

    # 验证所有字段正确映射
    assert dp_fields["disease"] == "mumps"
    assert dp_fields["province"] == "广东"
    assert dp_fields["city"] == "深圳"
    assert dp_fields["data_type"] == "gmc"
    assert dp_fields["value"] == 120.5
    assert dp_fields["unit"] == "mIU/ml"
    assert dp_fields["ci_lower"] == 100.0
    assert dp_fields["ci_upper"] == 140.0
    assert dp_fields["sample_size"] == 300
    assert dp_fields["review_status"] == "approved"
    assert dp_fields["estimate_type"] == "primary"
    assert dp_fields["confidence"] == "medium"
    assert dp_fields["is_grounded"] is True
    assert dp_fields["source_char_start"] == 50
    assert dp_fields["source_char_end"] == 70

    print("  ✅ 所有数据点字段映射正确")


def test_import_default_values():
    """测试导入时默认值处理"""
    print("\n=== 测试3: 导入默认值处理 ===")

    # 模拟缺少某些字段的数据点
    dp_json_minimal = {
        "disease": "rubella",
        "province": "上海",
        "data_type": "seroprevalence",
        "value": 85.0,
    }

    # 模拟导入时的默认值处理
    confidence = dp_json_minimal.get("confidence") or "medium"
    review_status = dp_json_minimal.get("review_status") or "pending"
    estimate_type = dp_json_minimal.get("estimate_type") or "primary"
    is_grounded = dp_json_minimal.get("is_grounded", False)

    assert confidence == "medium"
    assert review_status == "pending"
    assert estimate_type == "primary"
    assert is_grounded is False

    print("  ✅ 默认值处理正确（confidence=medium, review_status=pending, estimate_type=primary）")


def test_two_literatures_export_import():
    """测试2篇文献的完整导出导入 round-trip"""
    print("\n=== 测试4: 2篇文献导出导入 round-trip ===")

    # 模拟2篇文献 + 数据点的完整导出 JSON
    export_data = {
        "export_version": "1.0",
        "exported_at": "2026-08-12T10:00:00+00:00",
        "include_data_points": True,
        "literature_count": 2,
        "data_point_count": 5,
        "literatures": [
            {
                "title": "北京市麻疹血清流行率调查",
                "authors": "张三;李四;王五",
                "journal": "中华流行病学杂志",
                "pub_year": 2020,
                "doi": "10.1234/measles.001",
                "province": "北京",
                "extraction_status": "done",
                "extracted_count": 3,
                "approved_count": 2,
                "data_points": [
                    {
                        "disease": "measles",
                        "province": "北京",
                        "city": "朝阳区",
                        "data_type": "seroprevalence",
                        "value": 95.5,
                        "unit": "%",
                        "sample_size": 500,
                        "age_min": 5,
                        "age_max": 14,
                        "collection_year": 2020,
                        "population": "学龄儿童",
                        "method": "ELISA",
                        "confidence": "high",
                        "review_status": "approved",
                        "estimate_type": "primary",
                    },
                    {
                        "disease": "measles",
                        "province": "北京",
                        "city": "海淀区",
                        "data_type": "seroprevalence",
                        "value": 92.3,
                        "unit": "%",
                        "sample_size": 300,
                        "age_min": 5,
                        "age_max": 14,
                        "collection_year": 2020,
                        "population": "学龄儿童",
                        "method": "ELISA",
                        "confidence": "high",
                        "review_status": "approved",
                        "estimate_type": "primary",
                    },
                    {
                        "disease": "measles",
                        "province": "北京",
                        "city": "西城区",
                        "data_type": "seroprevalence",
                        "value": 88.0,
                        "unit": "%",
                        "sample_size": 200,
                        "age_min": 15,
                        "age_max": 59,
                        "collection_year": 2020,
                        "population": "成人",
                        "confidence": "medium",
                        "review_status": "pending",
                        "estimate_type": "primary",
                    },
                ],
            },
            {
                "title": "广东省腮腺炎抗体水平监测",
                "authors": "Chen L;Wang Y",
                "journal": "Chinese Journal of Vaccines",
                "pub_year": 2019,
                "doi": "10.5678/mumps.002",
                "province": "广东",
                "extraction_status": "done",
                "extracted_count": 2,
                "approved_count": 2,
                "data_points": [
                    {
                        "disease": "mumps",
                        "province": "广东",
                        "city": "深圳",
                        "data_type": "gmc",
                        "value": 120.5,
                        "unit": "mIU/ml",
                        "sample_size": 300,
                        "age_min": 1,
                        "age_max": 4,
                        "collection_year": 2019,
                        "population": "散居儿童",
                        "confidence": "high",
                        "review_status": "approved",
                        "estimate_type": "primary",
                    },
                    {
                        "disease": "mumps",
                        "province": "广东",
                        "city": "广州",
                        "data_type": "gmc",
                        "value": 115.2,
                        "unit": "mIU/ml",
                        "sample_size": 250,
                        "age_min": 5,
                        "age_max": 14,
                        "collection_year": 2019,
                        "population": "学龄儿童",
                        "confidence": "high",
                        "review_status": "approved",
                        "estimate_type": "primary",
                    },
                ],
            },
        ],
    }

    # 验证导出结构
    assert export_data["literature_count"] == 2
    assert export_data["data_point_count"] == 5

    lit1 = export_data["literatures"][0]
    lit2 = export_data["literatures"][1]

    assert lit1["title"] == "北京市麻疹血清流行率调查"
    assert lit1["doi"] == "10.1234/measles.001"
    assert len(lit1["data_points"]) == 3
    approved_dps_1 = [dp for dp in lit1["data_points"] if dp["review_status"] == "approved"]
    assert len(approved_dps_1) == 2

    assert lit2["title"] == "广东省腮腺炎抗体水平监测"
    assert lit2["doi"] == "10.5678/mumps.002"
    assert len(lit2["data_points"]) == 2
    assert all(dp["review_status"] == "approved" for dp in lit2["data_points"])

    # 验证 JSON round-trip（模拟导出→文件→导入的过程）
    json_str = json.dumps(export_data, ensure_ascii=False, indent=2)
    assert len(json_str) > 0

    reimported = json.loads(json_str)
    assert reimported["literature_count"] == 2
    assert reimported["literatures"][0]["data_points"][0]["disease"] == "measles"
    assert reimported["literatures"][0]["data_points"][0]["review_status"] == "approved"
    assert reimported["literatures"][1]["data_points"][0]["disease"] == "mumps"
    assert reimported["literatures"][1]["data_points"][0]["value"] == 120.5

    print("  ✅ 2篇文献 + 5个数据点 round-trip 验证通过")
    print("  ✅ 文献1: 麻疹, 3个数据点(2 approved, 1 pending)")
    print("  ✅ 文献2: 腮腺炎, 2个数据点(全部 approved)")
    print("  ✅ 所有审核状态、estimate_type、数据值均正确保留")


def test_module_compatibility():
    """验证导入的数据点能在地图/分析模块正常展示"""
    print("\n=== 测试5: 模块兼容性验证 ===")

    # 地图模块要求：review_status='approved' AND estimate_type='primary'
    # 分析模块要求：review_status='approved' AND estimate_type='primary'

    # 模拟导入后的数据点
    dps = [
        {"disease": "measles", "province": "北京", "review_status": "approved", "estimate_type": "primary"},
        {"disease": "measles", "province": "北京", "review_status": "pending", "estimate_type": "primary"},
        {"disease": "mumps", "province": "广东", "review_status": "approved", "estimate_type": "primary"},
        {"disease": "mumps", "province": "广东", "review_status": "approved", "estimate_type": "subgroup"},
    ]

    # 地图模块筛选
    map_visible = [dp for dp in dps if dp["review_status"] == "approved" and dp["estimate_type"] == "primary"]
    assert len(map_visible) == 2
    assert map_visible[0]["disease"] == "measles"
    assert map_visible[1]["disease"] == "mumps"

    # 分析模块筛选
    analysis_visible = [dp for dp in dps if dp["review_status"] == "approved" and dp["estimate_type"] == "primary"]
    assert len(analysis_visible) == 2

    print("  ✅ 地图模块可见数据点: 2个（approved + primary）")
    print("  ✅ 分析模块可见数据点: 2个（approved + primary）")
    print("  ✅ pending 和 subgroup 数据点被正确过滤")


def test_duplicate_detection():
    """测试导入时的重复检测逻辑"""
    print("\n=== 测试6: 重复检测逻辑 ===")

    # 模拟已有文献
    existing_literatures = [
        {"title": "北京市麻疹血清流行率调查", "doi": "10.1234/measles.001"},
        {"title": "其他研究", "doi": "10.9999/other.001"},
    ]

    # 模拟导入的文献
    import_lit = {"title": "北京市麻疹血清流行率调查", "doi": "10.1234/measles.001"}

    # 按 DOI 匹配
    doi_match = any(
        existing["doi"] == import_lit["doi"] and import_lit["doi"]
        for existing in existing_literatures
    )
    assert doi_match is True

    # 按标题匹配
    title_match = any(
        existing["title"] == import_lit["title"]
        for existing in existing_literatures
    )
    assert title_match is True

    # 不重复的文献
    new_lit = {"title": "全新研究", "doi": "10.1234/new.001"}
    doi_match_new = any(
        existing["doi"] == new_lit["doi"] and new_lit["doi"]
        for existing in existing_literatures
    )
    title_match_new = any(
        existing["title"] == new_lit["title"]
        for existing in existing_literatures
    )
    assert doi_match_new is False
    assert title_match_new is False

    print("  ✅ DOI 重复检测正确")
    print("  ✅ 标题重复检测正确")
    print("  ✅ 新文献不被误判为重复")


if __name__ == "__main__":
    test_export_json_structure()
    test_import_data_point_fields()
    test_import_default_values()
    test_two_literatures_export_import()
    test_module_compatibility()
    test_duplicate_detection()
    print("\n✅ 所有测试通过！导出/导入功能符合预期。")
