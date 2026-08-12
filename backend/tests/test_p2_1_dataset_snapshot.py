"""P2-1 公开数据集快照导出测试

测试目标：
1. ZIP 结构完整：包含 data_points.csv, data_dictionary.csv, README.txt, LICENSE.txt
2. 数据点 CSV：列名与数据字典一致，ID 匿名化
3. 数据字典：包含所有字段定义
4. README：记录筛选条件和数据点数量
5. LICENSE：包含 CC BY 4.0
6. 空数据点：正常生成（0 条记录）
7. 字段脱敏：不导出 source_context 原文片段、不导出内部 UUID
8. 匿名 ID 格式：dp_0001, dp_0002, ...
"""
from __future__ import annotations

import csv
import io
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.dataset_snapshot import (
    generate_dataset_snapshot_zip,
    DATA_DICTIONARY,
    EXPORT_COLUMNS,
    _anonymize_id,
    _build_data_points_csv,
    _build_data_dictionary_csv,
    _build_readme,
)


def _make_dp(
    disease="麻疹",
    province="广东",
    city="广州市",
    data_type="seroprevalence",
    value=85.5,
    unit="%",
    sample_size=1000,
    collection_year=2020,
    estimate_type="primary",
    confidence="medium",
    is_grounded=True,
    source_page=3,
    literature_title="广东省麻疹抗体水平调查",
    literature_year=2021,
    literature_journal="中华流行病学杂志",
) -> dict:
    return {
        "disease": disease,
        "province": province,
        "city": city,
        "data_type": data_type,
        "value": value,
        "unit": unit,
        "ci_lower": 82.1,
        "ci_upper": 88.9,
        "sample_size": sample_size,
        "age_min": 0,
        "age_max": 14,
        "population": "健康儿童",
        "collection_year": collection_year,
        "method": "ELISA",
        "assay": "IgG",
        "estimate_type": estimate_type,
        "confidence": confidence,
        "source_page": source_page,
        "is_grounded": is_grounded,
        "literature_title": literature_title,
        "literature_year": literature_year,
        "literature_journal": literature_journal,
    }


# ── 测试 1: ZIP 结构完整 ───────────────────────────────
def test_zip_structure():
    """ZIP 包含 4 个必需文件"""
    dps = [_make_dp()]
    zip_bytes = generate_dataset_snapshot_zip(dps, filters={"disease": "麻疹"})

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = zf.namelist()
        assert "data_points.csv" in names
        assert "data_dictionary.csv" in names
        assert "README.txt" in names
        assert "LICENSE.txt" in names
    print("✓ test_zip_structure")


# ── 测试 2: 数据点 CSV 列名 ────────────────────────────
def test_data_points_csv_columns():
    """数据点 CSV 列名与数据字典一致"""
    dps = [_make_dp(), _make_dp(disease="风疹", province="北京")]
    csv_text = _build_data_points_csv(dps)

    reader = csv.reader(io.StringIO(csv_text))
    header = next(reader)
    assert header == EXPORT_COLUMNS
    # dp_id 在第一列
    assert header[0] == "dp_id"
    print("✓ test_data_points_csv_columns")


# ── 测试 3: 匿名 ID 格式 ───────────────────────────────
def test_anonymize_id():
    """ID 匿名化格式：dp_0001, dp_0002, ..."""
    assert _anonymize_id(1) == "dp_0001"
    assert _anonymize_id(2) == "dp_0002"
    assert _anonymize_id(100) == "dp_0100"
    assert _anonymize_id(9999) == "dp_9999"
    print("✓ test_anonymize_id")


# ── 测试 4: 数据点 CSV 内容 ────────────────────────────
def test_data_points_csv_content():
    """数据点 CSV 内容正确，且 ID 匿名化"""
    dps = [_make_dp(value=92.3, province="上海")]
    csv_text = _build_data_points_csv(dps)

    reader = csv.reader(io.StringIO(csv_text))
    header = next(reader)
    row = next(reader)

    # dp_id 匿名化
    assert row[0] == "dp_0001"
    # 疾病和省份
    assert row[1] == "麻疹"
    assert row[2] == "上海"
    # 数值
    assert row[5] == "92.3"
    assert row[6] == "%"
    # 文献信息
    assert "广东省麻疹抗体水平调查" in row[20]
    print("✓ test_data_points_csv_content")


# ── 测试 5: 数据字典完整 ───────────────────────────────
def test_data_dictionary_complete():
    """数据字典包含所有字段定义"""
    csv_text = _build_data_dictionary_csv()
    reader = csv.reader(io.StringIO(csv_text))
    header = next(reader)
    assert header == ["field_name", "data_type", "description", "value_range"]

    rows = list(reader)
    assert len(rows) == len(DATA_DICTIONARY)
    # 检查关键字段
    field_names = [r[0] for r in rows]
    assert "dp_id" in field_names
    assert "disease" in field_names
    assert "data_type" in field_names
    assert "value" in field_names
    assert "estimate_type" in field_names
    assert "is_grounded" in field_names
    print(f"✓ test_data_dictionary_complete ({len(rows)} 个字段)")


# ── 测试 6: README 记录筛选条件 ────────────────────────
def test_readme_content():
    """README 记录筛选条件和数据点数量"""
    filters = {"disease": "麻疹", "province": "广东", "year_start": 2020}
    readme = _build_readme(total_count=42, filters=filters, generated_at="2026-01-01")

    assert "42" in readme
    assert "2026-01-01" in readme
    assert "disease: 麻疹" in readme
    assert "province: 广东" in readme
    assert "year_start: 2020" in readme
    # 包含使用建议
    assert "estimate_type" in readme
    assert "primary" in readme
    print("✓ test_readme_content")


# ── 测试 7: 空筛选条件 ─────────────────────────────────
def test_readme_no_filters():
    """无筛选条件时 README 显示 无筛选 占位"""
    readme = _build_readme(total_count=0, filters={})
    assert "(无筛选" in readme
    assert "0" in readme
    print("✓ test_readme_no_filters")


# ── 测试 8: 空数据点 ───────────────────────────────────
def test_empty_data_points():
    """空数据点列表正常生成 ZIP"""
    zip_bytes = generate_dataset_snapshot_zip([], filters={})

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        dp_csv = zf.read("data_points.csv").decode("utf-8-sig")
        # 只有表头，无数据行
        lines = dp_csv.strip().split("\n")
        assert len(lines) == 1  # 只有表头
        assert "dp_id" in lines[0]
    print("✓ test_empty_data_points")


# ── 测试 9: 脱敏 - 不导出 source_context ────────────────
def test_no_source_context_exported():
    """不导出 source_context 原文片段（可能含敏感信息）"""
    dps = [_make_dp()]
    csv_text = _build_data_points_csv(dps)

    # source_context 不应在导出列中
    assert "source_context" not in EXPORT_COLUMNS
    # CSV 表头不含 source_context
    reader = csv.reader(io.StringIO(csv_text))
    header = next(reader)
    assert "source_context" not in header
    print("✓ test_no_source_context_exported")


# ── 测试 10: 脱敏 - 不导出内部 UUID ────────────────────
def test_no_internal_uuid_exported():
    """不导出内部 UUID（id, literature_id）"""
    dps = [_make_dp()]
    csv_text = _build_data_points_csv(dps)

    reader = csv.reader(io.StringIO(csv_text))
    header = next(reader)
    # 不应包含 id 或 literature_id（原始 UUID 字段）
    assert "id" not in header
    assert "literature_id" not in header
    # 但应包含匿名化的 dp_id
    assert "dp_id" in header
    print("✓ test_no_internal_uuid_exported")


# ── 测试 11: LICENSE 包含 CC BY 4.0 ───────────────────
def test_license_content():
    """LICENSE.txt 包含 CC BY 4.0"""
    from app.core.dataset_snapshot import LICENSE_TEXT
    assert "CC BY 4.0" in LICENSE_TEXT
    assert "creativecommons.org" in LICENSE_TEXT
    print("✓ test_license_content")


# ── 测试 12: ZIP 端到端 - 解压验证 ─────────────────────
def test_zip_end_to_end():
    """端到端：解压 ZIP 并验证所有文件可读"""
    dps = [
        _make_dp(value=85.5, province="广东"),
        _make_dp(value=92.3, province="北京", disease="风疹"),
        _make_dp(value=50.5, province="上海", data_type="gmc", unit="IU/ml"),
    ]
    zip_bytes = generate_dataset_snapshot_zip(dps, filters={"disease": "麻疹"})

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        # data_points.csv
        dp_csv = zf.read("data_points.csv").decode("utf-8-sig")
        reader = csv.reader(io.StringIO(dp_csv))
        header = next(reader)
        rows = list(reader)
        assert len(rows) == 3
        assert rows[0][0] == "dp_0001"
        assert rows[1][0] == "dp_0002"
        assert rows[2][0] == "dp_0003"

        # data_dictionary.csv
        dict_csv = zf.read("data_dictionary.csv").decode("utf-8-sig")
        assert "field_name" in dict_csv

        # README.txt
        readme = zf.read("README.txt").decode("utf-8")
        assert "3" in readme  # 数据点数量
        assert "disease: 麻疹" in readme

        # LICENSE.txt
        license_text = zf.read("LICENSE.txt").decode("utf-8")
        assert "CC BY 4.0" in license_text
    print("✓ test_zip_end_to_end")


def run_all():
    tests = [
        test_zip_structure,
        test_data_points_csv_columns,
        test_anonymize_id,
        test_data_points_csv_content,
        test_data_dictionary_complete,
        test_readme_content,
        test_readme_no_filters,
        test_empty_data_points,
        test_no_source_context_exported,
        test_no_internal_uuid_exported,
        test_license_content,
        test_zip_end_to_end,
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
    print(f"P2-1 数据集快照测试: {passed}/{len(tests)} 通过, {failed} 失败")
    return failed == 0


if __name__ == "__main__":
    ok = run_all()
    sys.exit(0 if ok else 1)
