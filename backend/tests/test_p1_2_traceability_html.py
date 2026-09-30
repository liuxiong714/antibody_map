"""P1-2 交互式溯源 HTML 导出测试

测试目标：
1. 基础生成：HTML 包含文献标题、全文、数据点列表
2. 高亮区间：source_char_start/end 正确插入 <mark> 标签
3. 置信度配色：high/medium/low 三档对应不同颜色
4. 未 grounded 标识：虚线边框
5. 重叠区间处理：截断不越界
6. XSS 安全：特殊字符被转义
7. 空数据点：返回"暂无数据点"
8. 字典/ORM 转换器
9. 端到端：HTML 可被 str 解析，结构完整
"""
from __future__ import annotations

import html
import re
import sys
import uuid
from pathlib import Path

# 让 tests 目录能 import app
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.traceability_html import (
    TracePoint,
    generate_traceability_html,
    datapoint_dict_to_trace,
    datapoint_orm_to_trace,
    _build_highlighted_text,
    _confidence_color,
)


def _make_trace(
    dp_id: str = "dp-001",
    *,
    disease: str = "麻疹",
    province: str = "北京市",
    value: float = 85.5,
    unit: str = "%",
    confidence: str = "medium",
    is_grounded: bool = True,
    source_char_start: int | None = 0,
    source_char_end: int | None = 10,
    source_context: str = "北京市麻疹阳性率 85.5%",
    estimate_type: str = "primary",
    review_status: str = "approved",
    source_page: int = 1,
) -> TracePoint:
    return TracePoint(
        dp_id=dp_id,
        disease=disease,
        province=province,
        city=None,
        data_type="seroprevalence",
        value=value,
        unit=unit,
        sample_size=100,
        age_min=None,
        age_max=None,
        collection_year=2020,
        confidence=confidence,
        review_status=review_status,
        source_page=source_page,
        source_context=source_context,
        source_char_start=source_char_start,
        source_char_end=source_char_end,
        is_grounded=is_grounded,
        estimate_type=estimate_type,
    )


# ── 测试 1: 基础生成 ─────────────────────────────────────
def test_basic_generation():
    """HTML 包含标题、全文、数据点列表"""
    text = "这是一段测试文本，用于验证溯源 HTML 生成功能。"
    points = [_make_trace(source_char_start=2, source_char_end=8)]
    out = generate_traceability_html("测试文献", text, points, generated_at="2026-01-01 00:00:00")

    assert "<!DOCTYPE html>" in out
    assert "测试文献" in out
    assert "2026-01-01 00:00:00" in out
    assert "数据点溯源 (1)" in out
    assert "已匹配原文: <b>1</b> / 1" in out
    # 全文被高亮 mark 分隔，但各片段应都在
    assert "这是" in out  # 高亮前
    assert "，用于验证溯源 HTML 生成功能。" in out  # 高亮后（高亮覆盖"一段测试文本"）
    print("✓ test_basic_generation")


# ── 测试 2: 高亮区间插入 <mark> ─────────────────────────
def test_highlight_interval():
    """source_char_start/end 正确插入 <mark> 标签"""
    text = "0123456789ABCDEFGHIJ"
    points = [_make_trace(dp_id="dp-a", source_char_start=5, source_char_end=10)]
    out = generate_traceability_html("T", text, points)

    # 应该有一个 mark 标签，data-dp-id=dp-a
    assert 'id="hl-dp-a"' in out
    assert 'data-dp-id="dp-a"' in out
    # mark 内文本是 "56789"
    assert ">56789<" in out
    # mark 之前的文本 "01234" 和之后的 "ABCDEFGHIJ" 都在
    assert "01234" in out
    assert "ABCDEFGHIJ" in out
    print("✓ test_highlight_interval")


# ── 测试 3: 置信度配色 ─────────────────────────────────
def test_confidence_color():
    """high/medium/low 三档对应不同颜色"""
    assert _confidence_color("high") == "#16a34a"
    assert _confidence_color("medium") == "#ca8a04"
    assert _confidence_color("low") == "#dc2626"
    # None 默认 medium
    assert _confidence_color(None) == "#ca8a04"
    # 大小写不敏感
    assert _confidence_color("HIGH") == "#16a34a"

    # 在 HTML 中验证
    text = "0123456789"
    p_high = _make_trace(dp_id="h", confidence="high", source_char_start=0, source_char_end=3)
    p_low = _make_trace(dp_id="l", confidence="low", source_char_start=4, source_char_end=7)
    out = generate_traceability_html("T", text, [p_high, p_low])
    assert "#16a34a" in out  # high
    assert "#dc2626" in out  # low
    print("✓ test_confidence_color")


# ── 测试 4: 未 grounded 虚线边框 ────────────────────────
def test_ungrounded_dashed_border():
    """未 grounded 的数据点高亮使用虚线边框"""
    text = "0123456789"
    p_grounded = _make_trace(dp_id="g", is_grounded=True, source_char_start=0, source_char_end=3)
    p_ungrounded = _make_trace(dp_id="u", is_grounded=False, source_char_start=4, source_char_end=7)
    out = generate_traceability_html("T", text, [p_grounded, p_ungrounded])

    # 虚线标识
    assert "border:1px dashed" in out
    # 实线标识
    assert "border:1px solid" in out
    # 侧边栏统计：1/2 已匹配
    assert "已匹配原文: <b>1</b> / 2" in out
    print("✓ test_ungrounded_dashed_border")


# ── 测试 5: 重叠区间处理 ────────────────────────────────
def test_overlapping_intervals():
    """重叠区间被截断，不越界"""
    text = "0123456789"
    # 区间 [2,7) 和 [4,9) 重叠
    p1 = _make_trace(dp_id="p1", source_char_start=2, source_char_end=7)
    p2 = _make_trace(dp_id="p2", source_char_start=4, source_char_end=9)
    out = _build_highlighted_text(text, [p1, p2])

    # 不应抛异常，且所有字符 0-9 都应出现（要么在 mark 内，要么在外）
    for ch in "0123456789":
        assert ch in out, f"字符 {ch} 丢失"
    # p1 高亮 "23456"（text[2:7]），p2 被截断为 "78"（text[7:9]，因为 p1 占到 7）
    assert ">23456<" in out
    assert ">78<" in out
    print("✓ test_overlapping_intervals")


# ── 测试 6: XSS 安全 ────────────────────────────────────
def test_xss_safety():
    """特殊字符（<, >, &, ", '）被正确转义"""
    # 标题包含脚本注入尝试
    text = "正常文本<script>alert(1)</script>结束"
    points = [_make_trace(
        dp_id="xss';--",
        disease="<img src=x onerror=alert(1)>",
        source_context="恶意'\"上下文",
        source_char_start=0,
        source_char_end=4,
    )]
    out = generate_traceability_html("标题<script>", text, points)

    # 原始脚本标签不应出现（应被转义为 &lt;script&gt;）
    assert "<script>alert(1)</script>" not in out
    assert "&lt;script&gt;" in out
    # 原始 <img 标签不应出现（应被转义为 &lt;img）
    assert "<img src=x onerror" not in out
    assert "&lt;img" in out
    # dp_id 中的引号也应被转义
    assert "xss&#x27;;--" in out or "xss';--" not in out or "&#x27;" in out
    print("✓ test_xss_safety")


# ── 测试 7: 空数据点 ────────────────────────────────────
def test_empty_data_points():
    """无数据点时显示 暂无数据点 占位"""
    out = generate_traceability_html("T", "全文", [], generated_at="2026-01-01")
    assert "暂无数据点" in out
    assert "数据点溯源 (0)" in out
    assert "已匹配原文: <b>0</b> / 0" in out
    # 全文仍正常显示
    assert "全文" in out
    print("✓ test_empty_data_points")


# ── 测试 8: 无效区间被跳过 ──────────────────────────────
def test_invalid_intervals_skipped():
    """source_char_start/end 为 None 或越界的区间被跳过，不报错"""
    text = "0123456789"
    p_none = _make_trace(dp_id="n", source_char_start=None, source_char_end=None)
    p_neg = _make_trace(dp_id="neg", source_char_start=-5, source_char_end=3)
    p_oob = _make_trace(dp_id="oob", source_char_start=100, source_char_end=200)
    p_inv = _make_trace(dp_id="inv", source_char_start=5, source_char_end=5)  # e<=s

    out = _build_highlighted_text(text, [p_none, p_neg, p_oob, p_inv])
    # 全文原样返回（无 mark）
    assert "<mark" not in out
    assert "0123456789" in out
    print("✓ test_invalid_intervals_skipped")


# ── 测试 9: 字典转换器 ──────────────────────────────────
def test_datapoint_dict_to_trace():
    """datapoint_dict_to_trace 正确转换字典"""
    dpo = {
        "id": "abc-123",
        "disease": "麻疹",
        "province": "北京市",
        "city": "海淀区",
        "data_type": "seroprevalence",
        "value": 92.3,
        "unit": "%",
        "sample_size": 500,
        "age_min": 1,
        "age_max": 14,
        "collection_year": 2021,
        "confidence": "high",
        "review_status": "approved",
        "source_page": 3,
        "source_context": "海淀区阳性率 92.3%",
        "source_char_start": 10,
        "source_char_end": 30,
        "is_grounded": True,
        "estimate_type": "subgroup",
    }
    t = datapoint_dict_to_trace(dpo)
    assert t.dp_id == "abc-123"
    assert t.disease == "麻疹"
    assert t.value == 92.3
    assert t.is_grounded is True
    assert t.estimate_type == "subgroup"
    assert t.source_char_start == 10
    print("✓ test_datapoint_dict_to_trace")


# ── 测试 10: ORM 转换器 ─────────────────────────────────
def test_datapoint_orm_to_trace():
    """datapoint_orm_to_trace 正确转换 ORM 对象"""
    class FakeDP:
        id = uuid.UUID("12345678-1234-5678-1234-567812345678")
        disease = "新冠"
        province = "上海市"
        city = None
        data_type = "gmc"
        value = 50.5
        unit = "IU/mL"
        sample_size = None
        age_min = None
        age_max = None
        collection_year = 2022
        confidence = "medium"
        review_status = "pending"
        source_page = 2
        source_context = "GMC 50.5"
        source_char_start = 0
        source_char_end = 10
        is_grounded = False
        estimate_type = "primary"

    t = datapoint_orm_to_trace(FakeDP())
    assert t.dp_id == "12345678-1234-5678-1234-567812345678"
    assert t.disease == "新冠"
    assert t.value == 50.5
    assert t.is_grounded is False
    assert t.estimate_type == "primary"
    print("✓ test_datapoint_orm_to_trace")


# ── 测试 11: 端到端 HTML 结构完整 ───────────────────────
def test_html_structure_complete():
    """生成的 HTML 结构完整：DOCTYPE/html/head/body 齐全"""
    out = generate_traceability_html("T", "全文", [_make_trace()])
    assert out.startswith("<!DOCTYPE html>")
    assert "</html>" in out
    assert "<head>" in out and "</head>" in out
    assert "<body>" in out and "</body>" in out
    # 关键交互脚本存在
    assert "function focusHl" in out
    assert "function focusCard" in out
    assert "scrollIntoView" in out
    # 侧边栏和数据点卡片
    assert 'class="sidebar"' in out
    assert 'class="dp-card"' in out
    print("✓ test_html_structure_complete")


# ── 测试 12: 子估计徽章 ─────────────────────────────────
def test_estimate_type_badge():
    """主估计/子估计徽章正确渲染"""
    text = "0123456789"
    p_pri = _make_trace(dp_id="pri", estimate_type="primary", source_char_start=0, source_char_end=3)
    p_sub = _make_trace(dp_id="sub", estimate_type="subgroup", source_char_start=4, source_char_end=7)
    out = generate_traceability_html("T", text, [p_pri, p_sub])

    assert "主估计" in out
    assert "子估计" in out
    print("✓ test_estimate_type_badge")


def run_all():
    tests = [
        test_basic_generation,
        test_highlight_interval,
        test_confidence_color,
        test_ungrounded_dashed_border,
        test_overlapping_intervals,
        test_xss_safety,
        test_empty_data_points,
        test_invalid_intervals_skipped,
        test_datapoint_dict_to_trace,
        test_datapoint_orm_to_trace,
        test_html_structure_complete,
        test_estimate_type_badge,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except AssertionError as e:
            print(f"✗ {t.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"✗ {t.__name__}: 异常 {type(e).__name__}: {e}")
            failed += 1
    print(f"\n{'='*50}")
    print(f"P1-2 溯源 HTML 测试: {passed}/{len(tests)} 通过, {failed} 失败")
    return failed == 0


if __name__ == "__main__":
    ok = run_all()
    sys.exit(0 if ok else 1)
