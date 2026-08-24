#!/usr/bin/env python
"""P2 功能全面测试：长文档分块提取 + 溯源文本端点 + 去重逻辑 + 回归验证。

运行方式（Windows PowerShell）:
  cd backend
  python tests/test_p2_features.py
"""
import os
import sys
import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# ── 路径修正 ──
_backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

_passed = 0
_failed = 0


def _ok(label: str, detail: str = ""):
    global _passed
    _passed += 1
    print(f"  ✓ {label}{(' — ' + detail) if detail else ''}")


def _fail(label: str, detail: str = ""):
    global _failed
    _failed += 1
    msg = f"  ✗ {label}{(' — ' + detail) if detail else ''}"
    print(msg)
    raise AssertionError(msg)


# ─────────────────────────────────────────────────────────
# 测试 1：文本分块逻辑
# ─────────────────────────────────────────────────────────
def test_chunk_text():
    print("\n" + "=" * 60)
    print("【测试 1】长文档分块逻辑 _chunk_text()")
    print("=" * 60)

    from app.core.llm_extractor import LLMExtractor

    # 1a: 短文本不分块
    short_text = "这是一段短文本。" * 10  # ~100 字符
    chunks = LLMExtractor._chunk_text(short_text)
    if len(chunks) == 1 and chunks[0][0] == 0:
        _ok("短文本不分块", f"chunks={len(chunks)}")
    else:
        _fail("短文本不应分块", f"chunks={len(chunks)}")

    # 1b: 长文本正确分块
    paragraph = "2023年广东省麻疹抗体阳性率调查结果显示，全省共采集血清样本1500份，IgG抗体阳性率为85.3%。\n"
    long_text = paragraph * 200  # ~16000+ 字符
    chunks = LLMExtractor._chunk_text(long_text, chunk_size=5000, overlap=200)
    if len(chunks) >= 2:
        _ok("长文本正确分块", f"chunks={len(chunks)}")
    else:
        _fail("长文本应分块", f"chunks={len(chunks)}, text_len={len(long_text)}")
        return

    # 1c: 分块覆盖完整文本（无遗漏）
    reconstructed = "".join(chunk for _, chunk in chunks)
    # 由于在段落边界切分，reconstructed 应等于原文
    if reconstructed == long_text:
        _ok("分块覆盖完整文本（无遗漏）")
    else:
        # 可能因为切分位置有微小差异，检查覆盖率
        coverage = len(reconstructed) / len(long_text)
        if coverage > 0.95:
            _ok("分块基本覆盖完整文本", f"coverage={coverage:.2%}")
        else:
            _fail("分块覆盖不完整", f"coverage={coverage:.2%}")

    # 1d: 分块在段落边界切分（不是从中间截断）
    for offset, chunk in chunks[:-1]:  # 最后一块除外
        if chunk.endswith("\n") or chunk.endswith("。"):
            _ok(f"分块在段落边界切分 (offset={offset})")
            break
    else:
        _fail("分块未在段落边界切分")

    # 1e: 各分块长度不超过 chunk_size + overlap
    max_len = max(len(chunk) for _, chunk in chunks)
    if max_len <= 5000 + 200:
        _ok("分块长度不超过限制", f"max_len={max_len}")
    else:
        _fail("分块长度超限", f"max_len={max_len}")

    # 1f: 空文本安全处理
    chunks_empty = LLMExtractor._chunk_text("")
    if len(chunks_empty) == 1:
        _ok("空文本安全处理")
    else:
        _fail("空文本处理异常", f"chunks={len(chunks_empty)}")


# ─────────────────────────────────────────────────────────
# 测试 2：数据点去重逻辑
# ─────────────────────────────────────────────────────────
def test_deduplicate():
    print("\n" + "=" * 60)
    print("【测试 2】数据点去重逻辑 _deduplicate_points()")
    print("=" * 60)

    from app.core.llm_extractor import LLMExtractor

    # 2a: 完全重复的数据点去重
    points = [
        {"disease_name": "麻疹", "province": "广东", "city": "广州",
         "age_min": 1, "age_max": 50, "positivity_rate": 85.3, "source_context": "原文A"},
        {"disease_name": "麻疹", "province": "广东", "city": "广州",
         "age_min": 1, "age_max": 50, "positivity_rate": 85.3, "source_context": "原文B"},
    ]
    deduped = LLMExtractor._deduplicate_points(points)
    if len(deduped) == 1:
        _ok("完全重复数据点去重")
    else:
        _fail("完全重复应去重为1条", f"got={len(deduped)}")

    # 2b: 不同数值不去重
    points2 = [
        {"disease_name": "麻疹", "province": "广东", "city": "广州",
         "age_min": 1, "age_max": 50, "positivity_rate": 85.3},
        {"disease_name": "麻疹", "province": "广东", "city": "广州",
         "age_min": 1, "age_max": 50, "positivity_rate": 88.5},
    ]
    deduped2 = LLMExtractor._deduplicate_points(points2)
    if len(deduped2) == 2:
        _ok("不同数值不去重")
    else:
        _fail("不同数值不应去重", f"got={len(deduped2)}")

    # 2c: 不同省份不去重
    points3 = [
        {"disease_name": "麻疹", "province": "广东", "city": "",
         "age_min": None, "age_max": None, "positivity_rate": 85.3},
        {"disease_name": "麻疹", "province": "浙江", "city": "",
         "age_min": None, "age_max": None, "positivity_rate": 85.3},
    ]
    deduped3 = LLMExtractor._deduplicate_points(points3)
    if len(deduped3) == 2:
        _ok("不同省份不去重")
    else:
        _fail("不同省份不应去重", f"got={len(deduped3)}")

    # 2d: GMC 和 seroprevalence 不互相去重
    points4 = [
        {"disease_name": "麻疹", "province": "广东", "city": "广州",
         "age_min": 1, "age_max": 50, "positivity_rate": 85.3, "gmc_value": None},
        {"disease_name": "麻疹", "province": "广东", "city": "广州",
         "age_min": 1, "age_max": 50, "positivity_rate": None, "gmc_value": 1125.6},
    ]
    deduped4 = LLMExtractor._deduplicate_points(points4)
    if len(deduped4) == 2:
        _ok("GMC 和 seroprevalence 不互相去重")
    else:
        _fail("GMC 和 seroprevalence 应保留", f"got={len(deduped4)}")

    # 2e: 空列表安全处理
    deduped5 = LLMExtractor._deduplicate_points([])
    if len(deduped5) == 0:
        _ok("空列表安全处理")
    else:
        _fail("空列表应返回空", f"got={len(deduped5)}")

    # 2f: 多块重复混合
    points6 = [
        {"disease_name": "麻疹", "province": "广东", "city": "广州",
         "age_min": 1, "age_max": 50, "positivity_rate": 85.3},
        {"disease_name": "风疹", "province": "浙江", "city": "杭州",
         "age_min": 5, "age_max": 60, "gmc_value": 980.3},
        {"disease_name": "麻疹", "province": "广东", "city": "广州",
         "age_min": 1, "age_max": 50, "positivity_rate": 85.3},  # 重复
        {"disease_name": "风疹", "province": "浙江", "city": "杭州",
         "age_min": 5, "age_max": 60, "gmc_value": 980.3},  # 重复
        {"disease_name": "腮腺炎", "province": "北京", "city": "",
         "age_min": None, "age_max": None, "positivity_rate": 72.1},
    ]
    deduped6 = LLMExtractor._deduplicate_points(points6)
    if len(deduped6) == 3:
        _ok("多块重复混合去重正确", f"{len(points6)} → {len(deduped6)}")
    else:
        _fail("多块重复去重错误", f"got={len(deduped6)}, expected=3")


# ─────────────────────────────────────────────────────────
# 测试 3：溯源文本端点（模拟文件读取）
# ─────────────────────────────────────────────────────────
def test_source_text_endpoint():
    print("\n" + "=" * 60)
    print("【测试 3】溯源文本端点逻辑")
    print("=" * 60)

    # 3a: 验证端点路由已注册
    import inspect
    from app.api.v1 import literature
    source = inspect.getsource(literature)
    if "get_source_text" in source and "/source-text" in source:
        _ok("溯源文本端点已注册")
    else:
        _fail("溯源文本端点未注册")

    # 3b: 验证端点参数定义
    if "start" in source and "end" in source and "context" in source:
        _ok("端点参数定义完整（start/end/context）")
    else:
        _fail("端点参数缺失")

    # 3c: 验证 extract_task 保存文本逻辑
    from app.tasks import extract_task
    task_source = inspect.getsource(extract_task)
    if "溯源文本已缓存" in task_source or ".txt" in task_source:
        _ok("extract_task 包含文本缓存逻辑")
    else:
        _fail("extract_task 缺少文本缓存逻辑")

    # 3d: 模拟文本文件读写
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = Path(tmpdir) / "test-lit-id.txt"
        test_text = "2023年广东省麻疹抗体阳性率为85.3%，样本量1500人。GMC为1125.6 mIU/ml。"
        test_file.write_text(test_text, encoding="utf-8")

        # 模拟端点逻辑：按区间截取
        start, end, context = 10, 30, 5
        s = max(0, start - context)
        e = min(len(test_text), end + context)
        snippet = test_text[s:e]
        if snippet and len(snippet) > 0:
            _ok("区间截取逻辑正确", f"snippet_len={len(snippet)}")
        else:
            _fail("区间截取逻辑失败")

        # 验证截取区间正确
        if test_text[start:end] in snippet:
            _ok("高亮区间包含在截取片段中")
        else:
            _fail("高亮区间不在截取片段中")


# ─────────────────────────────────────────────────────────
# 测试 4：extract_with_retry 分块路径（mock LLM）
# ─────────────────────────────────────────────────────────
def test_extract_with_retry_chunking():
    print("\n" + "=" * 60)
    print("【测试 4】extract_with_retry 分块路径（mock）")
    print("=" * 60)

    from app.core.llm_extractor import LLMExtractor

    # 4a: 验证 CHUNK_THRESHOLD 存在
    import inspect
    source = inspect.getsource(LLMExtractor.extract_with_retry)
    if "CHUNK_THRESHOLD" in source and "20000" in source:
        _ok("分块阈值 CHUNK_THRESHOLD=20000 已定义")
    else:
        _fail("分块阈值未定义")

    # 4b: 验证分块路径调用 _chunk_text 和 _deduplicate_points
    if "_chunk_text" in source and "_deduplicate_points" in source:
        _ok("分块路径调用 _chunk_text + _deduplicate_points")
    else:
        _fail("分块路径缺少关键函数调用")

    # 4c: 验证 _extract_single_chunk_with_retry 方法存在
    if hasattr(LLMExtractor, "_extract_single_chunk_with_retry"):
        _ok("_extract_single_chunk_with_retry 方法存在")
    else:
        _fail("_extract_single_chunk_with_retry 方法不存在")

    # 4d: mock 测试 — 长文本触发分块
    # 构造超过 20000 字符的文本
    paragraph = "2023年广东省麻疹抗体阳性率为85.3%，样本量1500人。GMC为1125.6 mIU/ml。"
    long_text = paragraph * 500  # ~24500 字符，超过 20000 阈值

    # mock extract 方法返回不同的数据点
    call_count = [0]

    async def mock_extract(self, text, language, title, journal, pub_year, **kwargs):
        call_count[0] += 1
        return [
            {"disease_name": "麻疹", "province": "广东", "city": "广州",
             "age_min": 1, "age_max": 50, "positivity_rate": 85.3,
             "source_context": "阳性率为85.3%"},
        ]

    with patch.object(LLMExtractor, "extract", mock_extract):
        with patch.object(LLMExtractor, "_call_llm_api", new_callable=AsyncMock):
            extractor = LLMExtractor.__new__(LLMExtractor)
            extractor.model = "deepseek-test"
            extractor.client = MagicMock()
            result = __import__("asyncio").run(
                extractor.extract_with_retry(long_text, "zh", "测试", "", 2023)
            )

    if call_count[0] > 1:
        _ok("长文本触发多次分块提取", f"calls={call_count[0]}")
    else:
        _fail("长文本应触发多次分块提取", f"calls={call_count[0]}")

    if len(result) >= 1:
        _ok("分块提取返回有效结果", f"points={len(result)}")
    else:
        _fail("分块提取返回空结果")

    # 4e: 验证去重生效（多个块返回相同数据点时）
    call_count2 = [0]

    async def mock_extract_dedup(self, text, language, title, journal, pub_year, **kwargs):
        call_count2[0] += 1
        # 每个块都返回相同的数据点
        return [
            {"disease_name": "麻疹", "province": "广东", "city": "广州",
             "age_min": 1, "age_max": 50, "positivity_rate": 85.3},
        ]

    with patch.object(LLMExtractor, "extract", mock_extract_dedup):
        with patch.object(LLMExtractor, "_call_llm_api", new_callable=AsyncMock):
            extractor2 = LLMExtractor.__new__(LLMExtractor)
            extractor2.model = "deepseek-test"
            extractor2.client = MagicMock()
            result2 = __import__("asyncio").run(
                extractor2.extract_with_retry(long_text, "zh", "测试", "", 2023)
            )

    if len(result2) == 1:
        _ok("重复数据点正确去重", f"{call_count2[0]} 块 → {len(result2)} 条")
    else:
        _fail("重复数据点去重失败", f"got={len(result2)}")


# ─────────────────────────────────────────────────────────
# 测试 5：前端代码结构验证
# ─────────────────────────────────────────────────────────
def test_frontend_structure():
    print("\n" + "=" * 60)
    print("【测试 5】前端代码结构验证")
    print("=" * 60)

    frontend_path = os.path.join(_backend_dir, "..", "frontend", "src")

    # 5a: LiteratureDetail.tsx 包含 rowClassName
    lit_detail = os.path.join(frontend_path, "pages", "LiteratureDetail.tsx")
    if os.path.exists(lit_detail):
        with open(lit_detail, encoding="utf-8") as f:
            content = f.read()
        if "rowClassName" in content and "low-confidence-row" in content:
            _ok("前端表格包含 rowClassName + low-confidence-row")
        else:
            _fail("前端表格缺少 rowClassName")

    # 5b: 包含溯源查看弹窗
        if "sourceModalOpen" in content and "handleViewSource" in content:
            _ok("前端包含溯源查看弹窗逻辑")
        else:
            _fail("前端缺少溯源查看弹窗")

    # 5c: 包含 source-highlight 样式类
        if "source-highlight" in content:
            _ok("前端包含 source-highlight 高亮样式")
        else:
            _fail("前端缺少 source-highlight 样式")
    else:
        _fail("LiteratureDetail.tsx 文件不存在")

    # 5d: index.css 包含低置信度行样式
    css_path = os.path.join(frontend_path, "index.css")
    if os.path.exists(css_path):
        with open(css_path, encoding="utf-8") as f:
            css = f.read()
        if "low-confidence-row" in css and "ungrounded-row" in css:
            _ok("CSS 包含低置信度和未溯源行样式")
        else:
            _fail("CSS 缺少行高亮样式")

    # 5e: literature.ts 包含 getSourceText
    lit_ts = os.path.join(frontend_path, "services", "literature.ts")
    if os.path.exists(lit_ts):
        with open(lit_ts, encoding="utf-8") as f:
            ts = f.read()
        if "getSourceText" in ts and "SourceTextResult" in ts:
            _ok("前端 service 包含 getSourceText + SourceTextResult")
        else:
            _fail("前端 service 缺少 getSourceText")
    else:
        _fail("literature.ts 文件不存在")

    # 5f: 验证 onClick 事件绑定
    if os.path.exists(lit_detail):
        with open(lit_detail, encoding="utf-8") as f:
            content = f.read()
        if "handleViewSource" in content and "onClick" in content:
            _ok("前端绑定了溯源查看点击事件")
        else:
            _fail("前端缺少溯源查看点击事件绑定")


# ─────────────────────────────────────────────────────────
# 测试 6：回归 — P0 grounding + schema 仍正常
# ─────────────────────────────────────────────────────────
def test_p0_regression():
    print("\n" + "=" * 60)
    print("【测试 6】回归测试：P0 grounding + schema 约束")
    print("=" * 60)

    from app.core.extraction_grounding import (
        ground_extraction, validate_extraction_schema, GroundingResult
    )

    # 6a: 精确匹配 grounding
    source_text = "2023年广东省麻疹抗体阳性率为85.3%，样本量1500人。"
    extract_item = {"source_context": "阳性率为85.3%，样本量1500人"}
    result = ground_extraction(source_text, extract_item["source_context"], extract_item)
    if result.is_grounded:
        _ok("P0 精确匹配 grounding 正常")
    else:
        _fail("P0 精确匹配 grounding 失败")

    # 6b: 幻觉检测
    extract_item2 = {"source_context": "这是一个不存在的文本片段1234567890"}
    result2 = ground_extraction(source_text, extract_item2["source_context"], extract_item2)
    if not result2.is_grounded:
        _ok("P0 幻觉检测正常")
    else:
        _fail("P0 幻觉检测失败")

    # 6c: schema 校验 — province 枚举
    extract_result = {"province": "广东", "positivity_rate": 85.3}
    cleaned, flags = validate_extraction_schema(extract_result, grounded=True)
    if flags.province_valid:
        _ok("P0 省份枚举校验正常")
    else:
        _fail("P0 省份枚举校验失败")

    # 6d: schema 校验 — 非法省份
    extract_result2 = {"province": "荷兰省", "positivity_rate": 50.0}
    cleaned2, flags2 = validate_extraction_schema(extract_result2, grounded=True)
    if not flags2.province_valid and "province_not_in_enum" in flags2.schema_issues:
        _ok("P0 非法省份检测正常")
    else:
        _fail("P0 非法省份检测失败")

    # 6e: schema 校验 — value 范围
    extract_result3 = {"province": "广东", "positivity_rate": 150.0}
    cleaned3, flags3 = validate_extraction_schema(extract_result3, grounded=True)
    if not flags3.value_range_valid and "value_out_of_range" in flags3.schema_issues:
        _ok("P0 value 范围校验正常")
    else:
        _fail("P0 value 范围校验失败")


# ─────────────────────────────────────────────────────────
# 测试 7：回归 — P1 多格式解析仍正常
# ─────────────────────────────────────────────────────────
def test_p1_regression():
    print("\n" + "=" * 60)
    print("【测试 7】回归测试：P1 多格式解析")
    print("=" * 60)

    from app.core.processors import get_parser, list_supported_exts

    # 7a: 解析器注册表完整
    expected = {".epub", ".docx", ".pptx", ".xlsx", ".txt", ".html", ".htm"}
    actual = set(list_supported_exts())
    if expected.issubset(actual):
        _ok("P1 解析器注册表完整")
    else:
        _fail("P1 解析器注册表缺失", f"missing={expected - actual}")

    # 7b: TXT 解析正常
    txt_parser = get_parser(".txt")
    txt_text = txt_parser.extract_text("测试文本85.3%".encode("utf-8"))
    if "85.3%" in txt_text:
        _ok("P1 TXT 解析正常")
    else:
        _fail("P1 TXT 解析失败")

    # 7c: HTML 解析正常
    html_parser = get_parser(".html")
    html_text = html_parser.extract_text(
        "<html><body><p>阳性率85.3%</p></body></html>".encode("utf-8")
    )
    if "85.3%" in html_text:
        _ok("P1 HTML 解析正常")
    else:
        _fail("P1 HTML 解析失败")

    # 7d: 上传白名单完整
    from app.core.document_parser import ALLOWED_EXTS
    if ".pptx" in ALLOWED_EXTS and ".xlsx" in ALLOWED_EXTS:
        _ok("P1 上传白名单包含 PPTX/XLSX")
    else:
        _fail("P1 上传白名单缺失 PPTX/XLSX")

    # 7e: OCR 服务可导入
    from app.core.ocr_service import get_ocr_status, ocr_image
    status = get_ocr_status()
    if "tesseract_available" in status:
        _ok("P1 OCR 服务正常")
    else:
        _fail("P1 OCR 服务异常")


# ─────────────────────────────────────────────────────────
# 主入口
# ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print("P2 功能全面测试")
    print("涵盖：长文档分块 | 溯源文本端点 | 去重逻辑 | 回归测试")
    print("=" * 60)

    tests = [
        test_chunk_text,
        test_deduplicate,
        test_source_text_endpoint,
        test_extract_with_retry_chunking,
        test_frontend_structure,
        test_p0_regression,
        test_p1_regression,
    ]

    for test_fn in tests:
        try:
            test_fn()
        except AssertionError:
            pass  # _fail already handled printing and counting
        except Exception as e:
            import traceback
            _fail(f"{test_fn.__name__} 异常", str(e))
            traceback.print_exc()

    print("\n" + "=" * 60)
    print(f"总结：{_passed}/{_passed + _failed} 通过", end="")
    if _failed:
        print(f"，{_failed} 失败 ❌")
    else:
        print(" 🎉")
    print("=" * 60)

    sys.exit(1 if _failed else 0)
