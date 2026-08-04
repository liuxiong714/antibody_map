"""P1-1 主估计/子估计层级测试。

验证：
1. DataPoint 模型新增 estimate_type / parent_id 字段
2. LLM prompt 包含 estimate_type / parent_group 字段
3. _post_process 正确归一化 estimate_type
4. _link_subgroup_parents 子估计归并逻辑（mock）
5. _build_base_query 默认过滤 primary
6. 回归：无 estimate_type 字段时默认 primary，不丢失数据
"""
import asyncio
import json
import sys
import uuid
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.models.data_point import DataPoint
from app.core.llm_extractor import LLMExtractor, PROMPT_ZH
from app.services.analysis_service import _build_base_query


# ========== 1. DataPoint 模型字段验证 ==========

def test_datapoint_has_estimate_type_field():
    """DataPoint 模型包含 estimate_type 字段"""
    col = DataPoint.__table__.columns.get("estimate_type")
    assert col is not None, "DataPoint 应有 estimate_type 列"
    print("✓ test_datapoint_has_estimate_type_field")


def test_datapoint_has_parent_id_field():
    """DataPoint 模型包含 parent_id 字段"""
    col = DataPoint.__table__.columns.get("parent_id")
    assert col is not None, "DataPoint 应有 parent_id 列"
    print("✓ test_datapoint_has_parent_id_field")


def test_datapoint_estimate_type_check_constraint():
    """estimate_type 有 CHECK 约束：只能 primary / subgroup"""
    constraints = [c for c in DataPoint.__table_args__ if hasattr(c, "sqltext")]
    estimate_constraints = [
        c for c in constraints
        if "estimate_type" in str(c.sqltext)
    ]
    assert len(estimate_constraints) == 1, "应有 1 个 estimate_type CHECK 约束"
    print("✓ test_datapoint_estimate_type_check_constraint")


# ========== 2. LLM prompt 包含新字段 ==========

def test_prompt_contains_estimate_type():
    """PROMPT_ZH 包含 estimate_type 字段说明"""
    assert "estimate_type" in PROMPT_ZH
    assert "primary" in PROMPT_ZH
    assert "subgroup" in PROMPT_ZH
    print("✓ test_prompt_contains_estimate_type")


def test_prompt_contains_parent_group():
    """PROMPT_ZH 包含 parent_group 字段说明"""
    assert "parent_group" in PROMPT_ZH
    print("✓ test_prompt_contains_parent_group")


# ========== 3. _post_process 归一化 estimate_type ==========

def test_post_process_estimate_type_primary():
    """LLM 返回 estimate_type='primary' 时正确保留"""
    extractor = LLMExtractor(model="deepseek-chat")
    data = {
        "data_points": [{
            "disease_name": "麻疹",
            "province": "广东",
            "positivity_rate": 87.3,
            "estimate_type": "primary",
        }]
    }
    points = extractor._post_process(data)
    assert len(points) == 1
    assert points[0]["estimate_type"] == "primary"
    print("✓ test_post_process_estimate_type_primary")


def test_post_process_estimate_type_subgroup():
    """LLM 返回 estimate_type='subgroup' 时正确保留"""
    extractor = LLMExtractor(model="deepseek-chat")
    data = {
        "data_points": [{
            "disease_name": "麻疹",
            "province": "广东",
            "positivity_rate": 85.0,
            "estimate_type": "subgroup",
            "parent_group": "广东全省",
        }]
    }
    points = extractor._post_process(data)
    assert len(points) == 1
    assert points[0]["estimate_type"] == "subgroup"
    assert points[0]["parent_group"] == "广东全省"
    print("✓ test_post_process_estimate_type_subgroup")


def test_post_process_estimate_type_default_primary():
    """LLM 未返回 estimate_type 时默认 primary（回归兼容）"""
    extractor = LLMExtractor(model="deepseek-chat")
    data = {
        "data_points": [{
            "disease_name": "麻疹",
            "province": "广东",
            "positivity_rate": 87.3,
            # 不传 estimate_type
        }]
    }
    points = extractor._post_process(data)
    assert len(points) == 1
    assert points[0]["estimate_type"] == "primary"
    print("✓ test_post_process_estimate_type_default_primary")


def test_post_process_estimate_type_invalid_normalized():
    """LLM 返回非法 estimate_type 时归一化为 primary"""
    extractor = LLMExtractor(model="deepseek-chat")
    data = {
        "data_points": [{
            "disease_name": "麻疹",
            "province": "广东",
            "positivity_rate": 87.3,
            "estimate_type": "invalid_value",
        }]
    }
    points = extractor._post_process(data)
    assert points[0]["estimate_type"] == "primary"
    print("✓ test_post_process_estimate_type_invalid_normalized")


# ========== 4. _link_subgroup_parents 归并逻辑（mock）==========

def test_link_subgroup_parents_basic():
    """子估计的 parent_id 被正确指向匹配的主估计"""
    from app.tasks.extract_task import _link_subgroup_parents

    # 构造 mock DataPoint 对象
    primary_dp = MagicMock()
    primary_dp.id = uuid.uuid4()
    primary_dp.estimate_type = "primary"
    primary_dp.disease = "麻疹"
    primary_dp.data_type = "seroprevalence"
    primary_dp.province = "广东"
    primary_dp.city = None

    subgroup_dp = MagicMock()
    subgroup_dp.id = uuid.uuid4()
    subgroup_dp.estimate_type = "subgroup"
    subgroup_dp.disease = "麻疹"
    subgroup_dp.data_type = "seroprevalence"
    subgroup_dp.province = "广东"
    subgroup_dp.city = "广州市"
    subgroup_dp._parent_group = "广东全省"
    subgroup_dp.parent_id = None

    all_dps = [primary_dp, subgroup_dp]

    # mock db.flush
    db = AsyncMock()
    asyncio.run(_link_subgroup_parents(db, all_dps))

    assert subgroup_dp.parent_id == primary_dp.id, "子估计 parent_id 应指向主估计 id"
    print("✓ test_link_subgroup_parents_basic")


def test_link_subgroup_parents_no_match():
    """无匹配主估计时子估计 parent_id 保持 None"""
    from app.tasks.extract_task import _link_subgroup_parents

    primary_dp = MagicMock()
    primary_dp.id = uuid.uuid4()
    primary_dp.estimate_type = "primary"
    primary_dp.disease = "麻疹"
    primary_dp.data_type = "seroprevalence"
    primary_dp.province = "广东"

    subgroup_dp = MagicMock()
    subgroup_dp.id = uuid.uuid4()
    subgroup_dp.estimate_type = "subgroup"
    subgroup_dp.disease = "腮腺炎"  # 不同疾病，不匹配
    subgroup_dp.data_type = "seroprevalence"
    subgroup_dp.province = "广东"
    subgroup_dp._parent_group = "广东全省"
    subgroup_dp.parent_id = None

    all_dps = [primary_dp, subgroup_dp]
    db = AsyncMock()
    asyncio.run(_link_subgroup_parents(db, all_dps))

    assert subgroup_dp.parent_id is None, "无匹配时 parent_id 应保持 None"
    print("✓ test_link_subgroup_parents_no_match")


def test_link_subgroup_parents_no_subgroups():
    """无子估计时函数正常返回"""
    from app.tasks.extract_task import _link_subgroup_parents

    primary_dp = MagicMock()
    primary_dp.estimate_type = "primary"
    db = AsyncMock()
    asyncio.run(_link_subgroup_parents(db, [primary_dp]))  # 不应抛异常
    print("✓ test_link_subgroup_parents_no_subgroups")


# ========== 5. _build_base_query 默认过滤 primary ==========

def test_build_base_query_filters_primary_by_default():
    """默认查询只返回主估计"""
    from sqlalchemy import select
    from app.models.data_point import DataPoint

    query = _build_base_query(
        disease="麻疹", province=None, year_start=None, year_end=None,
        age_min=None, age_max=None,
    )
    # 检查 WHERE 子句包含 estimate_type = 'primary' 条件
    sql_str = str(query.compile(compile_kwargs={"literal_binds": True}))
    where_clause = sql_str.split("WHERE")[-1] if "WHERE" in sql_str else ""
    assert "estimate_type" in where_clause.lower(), "WHERE 子句应包含 estimate_type 过滤"
    assert "primary" in where_clause.lower(), "WHERE 子句应包含 primary 值"
    print("✓ test_build_base_query_filters_primary_by_default")


def test_build_base_query_includes_subgroups_when_requested():
    """传 include_subgroups=True 时 WHERE 子句不过滤 estimate_type"""
    query = _build_base_query(
        disease="麻疹", province=None, year_start=None, year_end=None,
        age_min=None, age_max=None,
        include_subgroups=True,
    )
    sql_str = str(query.compile(compile_kwargs={"literal_binds": True}))
    where_clause = sql_str.split("WHERE")[-1] if "WHERE" in sql_str else ""
    assert "estimate_type" not in where_clause.lower(), "include_subgroups=True 时 WHERE 不应过滤 estimate_type"
    print("✓ test_build_base_query_includes_subgroups_when_requested")


# ========== 6. 回归：现有数据（无 estimate_type）兼容 ==========

def test_regression_default_estimate_type_is_primary():
    """DataPoint 列定义含 default='primary'（向后兼容现有数据）"""
    col = DataPoint.__table__.columns.get("estimate_type")
    assert col is not None
    # 检查列有 Python 端 default 或 server_default
    has_python_default = col.default is not None
    has_server_default = col.server_default is not None
    assert has_python_default or has_server_default, \
        "estimate_type 列应有 default 或 server_default 保证向后兼容"
    print("✓ test_regression_default_estimate_type_is_primary")


if __name__ == "__main__":
    print("=" * 60)
    print("P1-1 主估计/子估计层级测试")
    print("=" * 60)
    test_datapoint_has_estimate_type_field()
    test_datapoint_has_parent_id_field()
    test_datapoint_estimate_type_check_constraint()
    test_prompt_contains_estimate_type()
    test_prompt_contains_parent_group()
    test_post_process_estimate_type_primary()
    test_post_process_estimate_type_subgroup()
    test_post_process_estimate_type_default_primary()
    test_post_process_estimate_type_invalid_normalized()
    test_link_subgroup_parents_basic()
    test_link_subgroup_parents_no_match()
    test_link_subgroup_parents_no_subgroups()
    test_build_base_query_filters_primary_by_default()
    test_build_base_query_includes_subgroups_when_requested()
    test_regression_default_estimate_type_is_primary()
    print("=" * 60)
    print("P1-1 全部测试通过 ✓")
