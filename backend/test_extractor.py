"""
AI 提取引擎测试脚本

用法：
    python test_extractor.py                     # 使用模拟模式（不调用真实 API）
    python test_extractor.py --real               # 使用真实 LLM API

设置为真实模式前，请确保 .env 中已配置：
    LLM_API_KEY=sk-your-key
    LLM_BASE_URL=https://api.deepseek.com
    LLM_MODEL=deepseek-chat
"""
import asyncio
import json
import sys


# 模拟 LLM 响应（用于无 API 时的测试）
MOCK_RESPONSE = {
    "disease_name": "麻疹",
    "province": "广东省",
    "city": None,
    "study_start_year": 2022,
    "study_end_year": 2022,
    "sample_year": 2022,
    "population_type": "健康人群",
    "age_min": None,
    "age_max": None,
    "sample_size": 1245,
    "detection_method": "ELISA",
    "antibody_type": "IgG",
    "positivity_rate": 87.3,
    "positivity_ci_lower": 84.1,
    "positivity_ci_upper": 90.5,
    "gmc_value": None,
    "gmc_unit": None,
    "gmc_ci_lower": None,
    "gmc_ci_upper": None,
    "journal": "中华流行病学杂志",
    "authors": "张三;李四;王五",
    "author_affiliations": "广东省疾病预防控制中心",
}


async def test_mock():
    """模拟模式测试：只用 term_normalizer 验证标准化逻辑"""
    print("=" * 50)
    print("模拟模式测试（不调用 LLM API）")
    print("=" * 50)

    from app.core.term_normalizer import (
        normalize_disease,
        normalize_method,
        normalize_antibody_type,
    )

    print("\n--- 术语标准化测试 ---")

    diseases = ["麻疹", "麻诊", "Measles", "乙肝", "Hepatitis B", "新冠", "COVID-19"]
    for d in diseases:
        print(f"  {d:20s} → {normalize_disease(d)}")

    methods = ["ELISA", "酶联免疫吸附试验", "化学发光", "中和试验"]
    for m in methods:
        print(f"  {m:20s} → {normalize_method(m)}")

    abs_types = ["IgG", "Immunoglobulin G", "中和抗体", "igm"]
    for t in abs_types:
        print(f"  {t:20s} → {normalize_antibody_type(t)}")

    print("\n--- 模拟提取结果 ---")
    print(json.dumps(MOCK_RESPONSE, ensure_ascii=False, indent=2))
    print("\n模拟模式测试完成！")


async def test_real():
    """真实 LLM 提取测试"""
    print("=" * 50)
    print("真实 LLM API 提取测试")
    print("=" * 50)

    from app.core.llm_extractor import LLMExtractor

    extractor = LLMExtractor()

    test_text = (
        "2022年3月在广东省采集1245份血清样本，男性52.3%。"
        "采用ELISA法检测麻疹IgG抗体，"
        "阳性率87.3%（95%CI: 84.1%-90.5%）。"
    )

    print(f"\n输入文本:\n{test_text}\n")
    print("正在调用 LLM API...")

    result = await extractor.extract(test_text, language="zh")
    print(f"\n提取结果:\n{json.dumps(result, ensure_ascii=False, indent=2)}")

    # 验证关键字段
    print("\n--- 字段验证 ---")
    checks = [
        ("disease_name", "measles"),  # 标准化后应为 measles
        ("province", "广东省"),
        ("sample_size", 1245),
        ("positivity_rate", 87.3),
    ]
    for field, expected in checks:
        actual = result.get(field)
        status = "PASS" if actual == expected else f"FAIL (got: {actual})"
        print(f"  {field}: expected={expected}, {status}")

    print("\n真实 LLM 测试完成！")


async def test_preprocessor():
    """文本预处理测试"""
    print("=" * 50)
    print("文本预处理测试")
    print("=" * 50)

    from app.core.text_preprocessor import preprocess, detect_language, truncate

    dirty_text = "2022年3月在广东省采集1245份血清样本...\x00\n\n\n\n  参考文献\n[1] 某某.xxx\n[2] 某某.yyy"

    cleaned = preprocess(dirty_text)
    lang = detect_language(cleaned)
    print(f"\n原始长度: {len(dirty_text)}")
    print(f"清洗后长度: {len(cleaned)}")
    print(f"检测语言: {lang}")
    print(f"截断测试(50字符): {truncate(cleaned, 50)}...")

    print("\n文本预处理测试完成！")


async def test_pdf():
    """PDF 解析测试"""
    print("=" * 50)
    print("PDF 解析测试")
    print("=" * 50)

    try:
        from app.core.pdf_parser import extract_text
    except ImportError as e:
        print(f"  PyMuPDF 导入失败: {e}")
        print("  跳过 PDF 解析测试")
        return

    import os

    # 尝试找测试 PDF
    test_pdfs = []
    for root, dirs, files in os.walk("."):
        for f in files:
            if f.endswith(".pdf"):
                test_pdfs.append(os.path.join(root, f))
                if len(test_pdfs) >= 3:
                    break
        if test_pdfs:
            break

    if not test_pdfs:
        print("  未找到测试 PDF 文件，跳过 PDF 解析测试")
        return

    for pdf_path in test_pdfs[:1]:
        print(f"\n解析: {pdf_path}")
        with open(pdf_path, "rb") as f:
            text = extract_text(f.read())
        print(f"  提取字符数: {len(text)}")
        print(f"  前 200 字符: {text[:200]}...")

    print("\nPDF 解析测试完成！")


async def main():
    use_real = "--real" in sys.argv

    await test_preprocessor()
    print("\n")

    if use_real:
        await test_real()
    else:
        await test_mock()

    print("\n")
    await test_pdf()


if __name__ == "__main__":
    asyncio.run(main())
