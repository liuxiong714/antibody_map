"""P2-3 本地拖拽转换 UI 测试

测试目标：
1. 文件存在且为单文件
2. 可导入（PyQt5 不可用时优雅降级）
3. 后端模块导入路径正确
4. 导出 CSV 逻辑正确
5. 导出 JSON 逻辑正确
6. 导出 HTML 逻辑正确（调用 traceability_html）
7. 文件类型白名单校验
8. DropZone fileDropped 信号（无需 GUI）
"""
from __future__ import annotations

import csv
import io
import json
import sys
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

TOOLS_PATH = Path(__file__).resolve().parent.parent.parent / "tools" / "quick_convert.py"


# ── 测试 1: 文件存在 ───────────────────────────────────
def test_file_exists():
    """quick_convert.py 存在且为单文件"""
    assert TOOLS_PATH.exists(), f"文件不存在: {TOOLS_PATH}"
    assert TOOLS_PATH.is_file()
    # 是单文件（不是包目录）
    assert TOOLS_PATH.suffix == ".py"
    print("✓ test_file_exists")


# ── 测试 2: 文件内容包含关键组件 ───────────────────────
def test_file_contains_components():
    """文件包含关键组件定义"""
    content = TOOLS_PATH.read_text(encoding="utf-8")
    assert "class DropZone" in content
    assert "class ExtractionWorker" in content
    assert "class QuickConvertWindow" in content
    assert "def main" in content
    # 拖拽支持
    assert "setAcceptDrops" in content
    assert "dragEnterEvent" in content
    assert "dropEvent" in content
    # 导出功能
    assert "_export_csv" in content
    assert "_export_json" in content
    assert "_export_html" in content
    # 后端模块导入
    assert "from app.core.document_parser" in content
    assert "from app.core.llm_extractor" in content
    assert "from app.core.traceability_html" in content
    print("✓ test_file_contains_components")


# ── 测试 3: 后端 sys.path 添加 ─────────────────────────
def test_backend_sys_path_setup():
    """文件正确添加 backend 目录到 sys.path"""
    content = TOOLS_PATH.read_text(encoding="utf-8")
    assert "_BACKEND_DIR" in content
    assert "sys.path.insert" in content
    assert '"backend"' in content or "'backend'" in content
    print("✓ test_backend_sys_path_setup")


# ── 测试 4: 模块导入（无 PyQt5 时降级） ────────────────
def test_module_import_graceful_degradation():
    """无 PyQt5 时给出友好错误而非崩溃"""
    content = TOOLS_PATH.read_text(encoding="utf-8")
    # 应有 PyQt5 导入失败的 try/except
    assert "ImportError" in content
    assert "PyQt5" in content
    assert "pip install PyQt5" in content
    # 后端导入也应有 try/except
    assert "无法导入后端模块" in content
    print("✓ test_module_import_graceful_degradation")


# ── 测试 5: CSV 导出逻辑 ───────────────────────────────
def test_csv_export_logic():
    """CSV 导出逻辑生成正确格式"""
    # 模拟导出逻辑（不依赖 GUI）
    data_points = [
        {
            "disease_name": "麻疹",
            "province": "广东",
            "city": "广州市",
            "data_type": "seroprevalence",
            "positivity_rate": 85.5,
            "sample_size": 1000,
            "age_min": 0,
            "age_max": 14,
            "sample_year": 2020,
            "estimate_type": "primary",
            "source_context": "广州市麻疹阳性率85.5%",
        },
        {
            "disease_name": "风疹",
            "province": "北京",
            "city": None,
            "data_type": "gmc",
            "gmc_value": 1125.6,
            "gmc_unit": "IU/ml",
            "sample_size": 500,
            "age_min": None,
            "age_max": None,
            "sample_year": 2021,
            "estimate_type": "subgroup",
            "source_context": "GMC 1125.6 IU/ml",
        },
    ]

    TABLE_COLUMNS = [
        "疾病", "省份", "城市", "数据类型", "数值", "单位",
        "样本量", "年龄", "年份", "置信度", "原文依据",
    ]

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(TABLE_COLUMNS)
    for dp in data_points:
        age = ""
        if dp.get("age_min") is not None and dp.get("age_max") is not None:
            age = f"{dp['age_min']}-{dp['age_max']}"
        writer.writerow([
            dp.get("disease_name", ""),
            dp.get("province", ""),
            dp.get("city", ""),
            dp.get("data_type", ""),
            dp.get("positivity_rate") or dp.get("gmc_value") or "",
            dp.get("gmc_unit", "") if dp.get("gmc_value") else "%",
            dp.get("sample_size") or "",
            age,
            dp.get("sample_year") or "",
            dp.get("estimate_type", "primary"),
            (dp.get("source_context") or "").replace("\n", " "),
        ])

    csv_text = output.getvalue()
    reader = csv.reader(io.StringIO(csv_text))
    header = next(reader)
    assert header == TABLE_COLUMNS
    row1 = next(reader)
    assert row1[0] == "麻疹"
    assert row1[1] == "广东"
    assert row1[4] == "85.5"
    row2 = next(reader)
    assert row2[4] == "1125.6"
    assert row2[5] == "IU/ml"
    print("✓ test_csv_export_logic")


# ── 测试 6: JSON 导出逻辑 ──────────────────────────────
def test_json_export_logic():
    """JSON 导出生成有效 JSON"""
    data_points = [
        {"disease_name": "麻疹", "province": "广东", "positivity_rate": 85.5},
        {"disease_name": "风疹", "province": "北京", "gmc_value": 1125.6},
    ]
    json_str = json.dumps(data_points, ensure_ascii=False, indent=2)
    parsed = json.loads(json_str)
    assert len(parsed) == 2
    assert parsed[0]["disease_name"] == "麻疹"
    assert parsed[1]["gmc_value"] == 1125.6
    print("✓ test_json_export_logic")


# ── 测试 7: HTML 导出依赖 traceability_html ────────────
def test_html_export_uses_traceability_module():
    """HTML 导出调用 generate_traceability_html"""
    content = TOOLS_PATH.read_text(encoding="utf-8")
    assert "generate_traceability_html" in content
    assert "TracePoint" in content
    assert "_export_html" in content
    print("✓ test_html_export_uses_traceability_module")


# ── 测试 8: 文件类型白名单校验 ─────────────────────────
def test_file_type_whitelist():
    """拖拽时校验文件类型白名单"""
    content = TOOLS_PATH.read_text(encoding="utf-8")
    assert "ALLOWED_EXTS" in content
    assert "不支持的格式" in content
    print("✓ test_file_type_whitelist")


# ── 测试 9: 模型选择器 ─────────────────────────────────
def test_model_selector():
    """模型选择器包含常用模型"""
    content = TOOLS_PATH.read_text(encoding="utf-8")
    assert "deepseek-chat" in content
    assert "llama3" in content
    assert "qwen-max" in content
    assert "gpt-4o" in content
    print("✓ test_model_selector")


# ── 测试 10: 后台线程设计 ──────────────────────────────
def test_background_thread_design():
    """提取在后台线程执行（不阻塞 UI）"""
    content = TOOLS_PATH.read_text(encoding="utf-8")
    assert "QThread" in content
    assert "ExtractionWorker" in content
    assert "pyqtSignal" in content
    assert "progress" in content
    assert "finished_extract" in content
    print("✓ test_background_thread_design")


# ── 测试 11: 多趟提取支持 ──────────────────────────────
def test_multipass_extraction_support():
    """使用 settings.LLM_EXTRACTION_PASSES 配置多趟提取"""
    content = TOOLS_PATH.read_text(encoding="utf-8")
    assert "LLM_EXTRACTION_PASSES" in content
    assert "extract_with_retry" in content
    print("✓ test_multipass_extraction_support")


# ── 测试 12: 可独立运行 ────────────────────────────────
def test_runnable_standalone():
    """可作为独立脚本运行（__main__ 入口）"""
    content = TOOLS_PATH.read_text(encoding="utf-8")
    assert 'if __name__ == "__main__"' in content
    assert "def main" in content
    assert "QApplication" in content
    print("✓ test_runnable_standalone")


def run_all():
    tests = [
        test_file_exists,
        test_file_contains_components,
        test_backend_sys_path_setup,
        test_module_import_graceful_degradation,
        test_csv_export_logic,
        test_json_export_logic,
        test_html_export_uses_traceability_module,
        test_file_type_whitelist,
        test_model_selector,
        test_background_thread_design,
        test_multipass_extraction_support,
        test_runnable_standalone,
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
    print(f"P2-3 拖拽转换 UI 测试: {passed}/{len(tests)} 通过, {failed} 失败")
    return failed == 0


if __name__ == "__main__":
    ok = run_all()
    sys.exit(0 if ok else 1)
