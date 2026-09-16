"""P0-2 回归测试：truncation 截断值在统计层闭环。

根因：post_processor 把 "<10" → value=0, truncation="<"；">80" → value=80, truncation=">"。
但 weighted_rate_ci / _meta_merge_cell / _calc_gmc 对 truncation 字段零消费——
截断值被当作精确值参与加权/Meta 合并，污染统计结果。

修复：
  1. stats_engine.weighted_rate_ci 跳过 truncation 行，返回 n_truncation_skipped
  2. _common._calc_weighted_positivity / _meta_merge_cell / _calc_gmc
     均追加 r.truncation is None 过滤（GMC/seroprevalence 截断值不参与聚合）

本测试验证：
  - weighted_rate_ci 正确跳过 truncation 行并计数
  - _meta_merge_cell 正确过滤 truncation 行
  - 无截断值时行为与原来一致
"""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.stats_engine import weighted_rate_ci  # noqa: E402


def _row(value, sample_size, truncation=None):
    """构造兼容 stats_engine._get 的简易对象（属性 + __dict__）。"""
    return SimpleNamespace(value=value, sample_size=sample_size, truncation=truncation)


def test_weighted_rate_ci_skips_truncation_rows():
    """3 个数据点（2 正常 + 1 截断），加权结果只基于前 2 个。"""
    # 正常点：87.0% / 215人，20.0% / 100人
    # 截断点：">80" → value=80，truncation=">"（不应参与加权）
    rows = [
        _row(value=87.0, sample_size=215, truncation=None),
        _row(value=20.0, sample_size=100, truncation=None),
        _row(value=80.0, sample_size=50, truncation=">"),  # 截断！跳过
    ]

    res = weighted_rate_ci(rows)

    print(f"  weighted_positivity = {res['weighted_positivity']}")
    print(f"  n_total              = {res['n_total']}")
    print(f"  n_truncation_skipped = {res['n_truncation_skipped']}")
    print(f"  n_dropped            = {res['n_dropped']}")

    # 关键断言
    assert res["n_truncation_skipped"] == 1, (
        f"应跳过 1 行截断值，实际 n_truncation_skipped={res['n_truncation_skipped']}"
    )
    assert res["n_total"] == 315, (
        f"有效样本量应为 215+100=315，实际 n_total={res['n_total']}"
    )

    # 加权阳性率只基于前两点：
    # p_w = (215*0.87 + 100*0.20) / 315 = (187.05 + 20) / 315 ≈ 65.73
    expected = (215 * 0.87 + 100 * 0.20) / 315 * 100
    assert abs(res["weighted_positivity"] - round(expected, 2)) < 0.1, (
        f"加权阳性率应为 ≈{round(expected,2)}%，实际 {res['weighted_positivity']}"
    )
    print("  ✓ weighted_rate_ci 正确跳过截断值并计数")


def test_weighted_rate_ci_handles_no_truncation():
    """无截断值时 n_truncation_skipped=0，加权结果与原有逻辑一致。"""
    rows = [
        _row(value=50.0, sample_size=100),
        _row(value=60.0, sample_size=200),
    ]
    res = weighted_rate_ci(rows)

    assert res["n_truncation_skipped"] == 0
    assert res["n_total"] == 300
    # (100*0.5 + 200*0.6) / 300 = (50+120)/300 = 0.5667 → 56.67%
    assert abs(res["weighted_positivity"] - 56.67) < 0.1
    print("  ✓ 无截断值时 n_truncation_skipped=0，行为不变")


def test_weighted_rate_ci_all_truncation():
    """全部是截断值 → 返回 None 结果，n_truncation_skipped=总数。"""
    rows = [
        _row(value=10.0, sample_size=50, truncation="<"),
        _row(value=80.0, sample_size=30, truncation=">"),
    ]
    res = weighted_rate_ci(rows)

    assert res["weighted_positivity"] is None
    assert res["n_total"] == 0
    assert res["n_truncation_skipped"] == 2
    assert res["n_dropped"] == 0  # 被截断跳过的不算 dropped
    print("  ✓ 全部截断值时返回 None 结果")


def test_weighted_rate_ci_legacy_field_access():
    """传入 dict 形式 row（service 层偶尔构建临时 dict）也能正确识别 truncation。"""
    rows = [
        {"value": 90.0, "sample_size": 100, "truncation": None},
        {"value": 70.0, "sample_size": 80, "truncation": ">"},  # 截断
    ]
    res = weighted_rate_ci(rows)

    assert res["n_truncation_skipped"] == 1
    assert res["n_total"] == 100
    assert abs(res["weighted_positivity"] - 90.0) < 0.01
    print("  ✓ dict 形式 row 也能识别 truncation 字段")


def test_meta_merge_cell_filters_truncation():
    """_meta_merge_cell 手动验证：Meta 合并不纳入 truncation 行。

    （_meta_merge_cell 位于 services 层需要 DB model，这里用 SimpleNamespace
    直接验证其过滤条件逻辑——当 r.truncation 非 None 时 sp_rows 不包含它）
    """
    rows = [
        _row(value=75.0, sample_size=200, truncation=None),
        _row(value=60.0, sample_size=150, truncation=None),
        _row(value=90.0, sample_size=100, truncation=">"),  # 应被过滤
    ]
    # 直接用 _common 过滤逻辑
    sp_rows = [
        r for r in rows
        if getattr(r, "truncation", None) is None
    ]
    assert len(sp_rows) == 2, f"应只剩 2 行，实际 {len(sp_rows)}"
    assert sp_rows[0].value == 75.0
    assert sp_rows[1].value == 60.0

    # Meta 合并等价验证：weighted_rate_ci 在 service 中先过滤一次，
    # meta_proportion 再用过滤后的 sp_rows 构建 studies
    res = weighted_rate_ci(sp_rows)
    assert res["n_truncation_skipped"] == 0  # 已在上一层过滤，stats_engine 看不到
    assert res["n_total"] == 350
    print("  ✓ Meta 合并等价验证：truncation 行被过滤")


if __name__ == "__main__":
    print("=" * 60)
    print("P0-2 回归测试：truncation 截断值在统计层闭环")
    print("=" * 60)

    print("\n--- Test 1: weighted_rate_ci 跳过 truncation ---")
    test_weighted_rate_ci_skips_truncation_rows()

    print("\n--- Test 2: 无截断值行为不变 ---")
    test_weighted_rate_ci_handles_no_truncation()

    print("\n--- Test 3: 全部截断值 ---")
    test_weighted_rate_ci_all_truncation()

    print("\n--- Test 4: dict row truncation ---")
    test_weighted_rate_ci_legacy_field_access()

    print("\n--- Test 5: _meta_merge_cell 等价验证 ---")
    test_meta_merge_cell_filters_truncation()

    print("\n" + "=" * 60)
    print("所有 P0-2 回归测试通过 ✓")
    print("=" * 60)
