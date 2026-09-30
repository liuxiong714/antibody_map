"""quality_service.py 单元测试：数据点质量分级（0-100 分 + A/B/C 三级）。

覆盖：
- 验收案例 A：n=3000 + 随机抽样 + ELISA + 全人群 + 高置信 → 应得 A
- 验收案例 C：n=50 + 便利抽样 + 无方法 + 门诊 + 低置信 → 应得 C
- 六个信号的单函数用例（已知得分 + 边界）
- estimate_grade（national / provincial / local）
- 分级边界（A≥75；B 50–74；C<50）
"""

import pytest

from app.services.quality_service import (
    CONFIDENCE_MAX,
    DETECTION_METHOD_MAX,
    ESTIMATE_GRADE_MAX,
    POPULATION_MAX,
    SAMPLE_SIZE_MAX,
    SAMPLING_MAX,
    grade_for_score,
    score_confidence,
    score_data_point,
    score_detection_method,
    score_estimate_grade,
    score_population,
    score_sample_size,
    score_sampling,
)


# ── 验收案例：A 级（n=3000 + 随机抽样 + ELISA + 全人群 + 高置信）────
def _a_case_dp() -> dict:
    return {
        "sample_size": 3000,
        "method": "ELISA",
        "population": "全人群",
        "province": "广东省",
        "city": None,
        "confidence": "high",
    }


def test_acceptance_case_a_scores_a():
    """验收 A：应得 A 级（总分 ≥75）。"""
    result = score_data_point(_a_case_dp(), literature_text="采用随机抽样方法开展调查")
    assert result["quality_score"] >= 75
    assert result["quality_grade"] == "A"


def test_acceptance_case_a_breakdown():
    """验收 A：六项得分明细与预期一致。"""
    result = score_data_point(_a_case_dp(), literature_text="采用多阶段随机抽样方法开展调查")
    bd = result["breakdown"]
    assert bd["sample_size"]["score"] == 30          # n=3000 → 30
    assert bd["sampling"]["score"] == 25              # 随机/多阶段 → 25
    assert bd["detection_method"]["score"] == 15      # ELISA → 15
    assert bd["population"]["score"] == 15            # 全人群 → 15
    assert bd["confidence"]["score"] == 5             # high → 5
    # 调查级别：单省大样本(n=3000≥2000) → provincial(8)；总分 = 30+25+15+15+8+5 = 98
    assert bd["estimate_grade"]["score"] == 8
    assert result["estimate_grade"] == "provincial"
    assert result["quality_score"] == 98


# ── 验收案例：C 级（n=50 + 便利抽样 + 无方法 + 门诊 + 低置信）────
def _c_case_dp() -> dict:
    return {
        "sample_size": 50,
        "method": None,
        "population": "门诊就诊患者",
        "province": None,
        "city": None,
        "confidence": "low",
    }


def test_acceptance_case_c_scores_c():
    """验收 C：应得 C 级（总分 <50）。"""
    result = score_data_point(_c_case_dp(), literature_text="采用便利抽样招募受试者")
    assert result["quality_score"] < 50
    assert result["quality_grade"] == "C"


def test_acceptance_case_c_breakdown():
    """验收 C：六项得分明细与预期一致。"""
    result = score_data_point(_c_case_dp(), literature_text="采用便利抽样招募受试者")
    bd = result["breakdown"]
    assert bd["sample_size"]["score"] == 8            # n=50 → 8
    assert bd["sampling"]["score"] == 6               # 便利 → 6
    assert bd["detection_method"]["score"] == 0       # 无方法 → 0
    assert bd["population"]["score"] == 5             # 门诊/患者 → 5
    assert bd["confidence"]["score"] == 1             # low → 1
    # 调查级别 local(5)；总分 = 8+6+0+5+5+1 = 25
    assert result["quality_score"] == 25


# ── 信号 1：样本量 ─────────────────────────────
class TestSampleSize:
    def test_above_2000(self):
        assert score_sample_size(2001)["score"] == 30

    def test_exactly_2000(self):
        assert score_sample_size(2000)["score"] == 24

    def test_mid_band(self):
        assert score_sample_size(500)["score"] == 24
        assert score_sample_size(100)["score"] == 16

    def test_small(self):
        assert score_sample_size(99)["score"] == 8
        assert score_sample_size(1)["score"] == 8

    def test_missing_or_zero(self):
        assert score_sample_size(None)["score"] == 0
        assert score_sample_size(0)["score"] == 0


# ── 信号 2：抽样方式 ─────────────────────────────
class TestSampling:
    def test_random_zh(self):
        assert score_sampling("按随机抽样方法抽取样本")["score"] == 25

    def test_multistage(self):
        assert score_sampling("采用多阶段抽样")["score"] == 25

    def test_probability_sampling_en(self):
        assert score_sampling("probability sampling was used")["score"] == 25

    def test_convenience_zh(self):
        assert score_sampling("采用便利抽样")["score"] == 6

    def test_convenience_en(self):
        assert score_sampling("convenience sample of volunteers")["score"] == 6

    def test_unspecified(self):
        assert score_sampling("本研究于2020年开展")["score"] == 12

    def test_no_text(self):
        assert score_sampling(None)["score"] == 12


# ── 信号 3：检测方法 ─────────────────────────────
class TestDetectionMethod:
    def test_known_elisa(self):
        assert score_detection_method("ELISA")["score"] == 15

    def test_known_chinese(self):
        assert score_detection_method("酶联免疫吸附试验")["score"] == 15

    def test_known_nt(self):
        assert score_detection_method("中和试验")["score"] == 15

    def test_unknown(self):
        assert score_detection_method("自研胶体金卡")["score"] == 8

    def test_empty(self):
        assert score_detection_method(None)["score"] == 0
        assert score_detection_method("")["score"] == 0


# ── 信号 4：人群代表性 ─────────────────────────────
class TestPopulation:
    def test_general(self):
        assert score_population("一般人群")["score"] == 15

    def test_school_based(self):
        assert score_population("school-based students")["score"] == 15

    def test_community(self):
        assert score_population("社区居民")["score"] == 15

    def test_hospital(self):
        assert score_population("门诊患者")["score"] == 5

    def test_patients(self):
        assert score_population("乙肝患者")["score"] == 5

    def test_other(self):
        assert score_population("献血员")["score"] == 8

    def test_empty(self):
        assert score_population(None)["score"] == 8


# ── 信号 5：调查级别 + estimate_grade ─────────────
class TestEstimateGrade:
    def test_national_many_provinces(self):
        r = score_estimate_grade("北京;天津;河北;山西;内蒙古;辽宁;吉林;黑龙江;上海;江苏;浙江", None, 5000)
        assert r["score"] == 10
        assert r["estimate_grade"] == "national"

    def test_provincial_multi_city(self):
        r = score_estimate_grade("广东省", "广州;深圳;东莞;佛山", 800)
        assert r["score"] == 8
        assert r["estimate_grade"] == "provincial"

    def test_provincial_large_sample(self):
        r = score_estimate_grade("广东省", None, 3000)
        assert r["score"] == 8
        assert r["estimate_grade"] == "provincial"

    def test_local_single_point(self):
        r = score_estimate_grade("广东省", "广州市", 200)
        assert r["score"] == 5
        assert r["estimate_grade"] == "local"

    def test_local_no_location(self):
        r = score_estimate_grade(None, None, 100)
        assert r["score"] == 5
        assert r["estimate_grade"] == "local"


# ── 信号 6：溯源置信度 ─────────────────────────────
class TestConfidence:
    def test_high(self):
        assert score_confidence("high")["score"] == 5

    def test_medium(self):
        assert score_confidence("medium")["score"] == 3

    def test_low(self):
        assert score_confidence("low")["score"] == 1

    def test_case_insensitive(self):
        assert score_confidence("HIGH")["score"] == 5

    def test_unknown_defaults_low(self):
        assert score_confidence("unknown")["score"] == 1


# ── 分级边界 ─────────────────────────────────────
class TestGradeForScore:
    def test_a_ge_75(self):
        assert grade_for_score(75) == "A"
        assert grade_for_score(100) == "A"

    def test_b_50_74(self):
        assert grade_for_score(74) == "B"
        assert grade_for_score(50) == "B"

    def test_c_lt_50(self):
        assert grade_for_score(49) == "C"
        assert grade_for_score(0) == "C"


# ── 兼容 dict 与模型对象两种数据点表示 ─────────────
class FakeModelDP:
    """模拟 SQLAlchemy DataPoint 模型实例。"""

    def __init__(self, **kwargs):
        self.sample_size = kwargs.get("sample_size")
        self.method = kwargs.get("method")
        self.population = kwargs.get("population")
        self.province = kwargs.get("province")
        self.city = kwargs.get("city")
        self.confidence = kwargs.get("confidence")
        self.title = kwargs.get("title")
        self.journal = kwargs.get("journal")


def test_dict_and_model_equivalence():
    a_dict = _a_case_dp()
    a_model = FakeModelDP(**a_dict)
    r1 = score_data_point(a_dict, literature_text="随机抽样")
    r2 = score_data_point(a_model, literature_text="随机抽样")
    assert r1 == r2


# ── 单项满分上界一致性 ─────────────────────────────
def test_max_scores_consistency():
    assert SAMPLE_SIZE_MAX + SAMPLING_MAX + DETECTION_METHOD_MAX + POPULATION_MAX + ESTIMATE_GRADE_MAX + CONFIDENCE_MAX == 100


# ── _build_base_query 质量等级过滤 ─────────────────
def test_build_base_query_quality_grades_filter():
    """quality_grades 参数：默认 None 不过滤；传 {"A","B"} 时 WHERE 含 quality_grade IN ('A','B')"""
    from app.services.analysis_service import _build_base_query

    def _where(sql: str) -> str:
        return sql.split("WHERE")[-1] if "WHERE" in sql else ""

    q_none = _build_base_query(
        disease=None, province=None, year_start=None, year_end=None,
        age_min=None, age_max=None, quality_grades=None,
    )
    where_none = _where(str(q_none.compile(compile_kwargs={"literal_binds": True})))
    assert "quality_grade" not in where_none.lower(), "quality_grades=None 的 WHERE 不应过滤质量等级"

    q_ab = _build_base_query(
        disease=None, province=None, year_start=None, year_end=None,
        age_min=None, age_max=None, quality_grades={"A", "B"},
    )
    where_ab = _where(str(q_ab.compile(compile_kwargs={"literal_binds": True})))
    assert "quality_grade" in where_ab.lower(), "quality_grades 非空时 WHERE 应含 quality_grade"
    assert "A" in where_ab and "B" in where_ab


def test_meta_merge_defaults_to_ab_quality():
    """get_meta_merge 默认仅纳入 A+B 级（include_low_quality=False 时 quality_grades 为 {"A","B"}）"""
    from app.services import analysis_service as svc

    class FakeDB:
        _call_count = 0
        async def execute(self, query):
            FakeDB._call_count += 1
            sql = str(query.compile(compile_kwargs={"literal_binds": True}))

            # 第一次调用：数据点查询，验证 quality_grade 过滤
            if FakeDB._call_count == 1:
                assert "quality_grade" in sql.lower(), "meta 合并默认应过滤 quality_grade"
                assert "'A'" in sql and "'B'" in sql

            # 返回空结果（无需真实 DB）
            class _Result:
                def scalars(self):
                    return self
                def all(self):
                    return []
            return _Result()

    import asyncio
    res = asyncio.run(svc.get_meta_merge(FakeDB(), disease="measles"))
    assert isinstance(res, dict)  # 空数据不崩溃即可（quality_grade 过滤已在上方断言）
    print("✓ meta 合并默认 A+B 过滤")


# ── 异步打分任务（审核通过后落库）─────────────────
def test_quality_task_persists_score(monkeypatch):
    """审核通过的数据点执行异步打分后质量字段落库（幂等）。"""
    import uuid

    import app.tasks.quality_task as quality_task

    dp_id = str(uuid.uuid4())

    class FakeDP:
        review_status = "approved"
        literature_id = None
        sample_size = 3000
        method = "ELISA"
        population = "全人群"
        confidence = "high"
        province = "广东省"
        city = None
        title = None
        journal = None
        quality_score = None
        quality_grade = None
        estimate_grade = None

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, model, pk):
            assert str(pk) == dp_id
            return FakeDP()

        async def commit(self):
            pass

    class FakeAsyncSession:
        def __call__(self):
            return FakeSession()

    monkeypatch.setattr(quality_task, "async_session", FakeAsyncSession())

    result = quality_task.score_data_point_task.run(dp_id)
    assert result["status"] == "scored"
    assert result["quality_score"] >= 75
    assert result["quality_grade"] == "A"
