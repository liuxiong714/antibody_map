"""快速测试：解析指定 PDF 并尝试 AI 提取"""
import sys
from app.core.pdf_parser import extract_text
from app.core.text_preprocessor import preprocess

pdf_path = "test_doc.pdf"

print("=" * 60)
print("PDF 文本提取测试")
print("=" * 60)

with open(pdf_path, "rb") as f:
    raw_text = extract_text(f.read())

print(f"\n提取文本长度: {len(raw_text)} 字符")
print(f"\n{'─' * 40}")
print("【原始提取文本（前 2000 字符）】")
print(f"{'─' * 40}")
print(raw_text[:2000])
print(f"\n{'─' * 40}")

if raw_text:
    clean = preprocess(raw_text)
    print(f"\n清洗后长度: {len(clean)} 字符")
    print(f"\n{'─' * 40}")
    print("【清洗后文本（前 500 字符）】")
    print(f"{'─' * 40}")
    print(clean[:500])

# 尝试 LLM 提取
if "--real" in sys.argv and raw_text:
    print(f"\n{'─' * 40}")
    print("【LLM 提取测试】")
    print(f"{'─' * 40}")
    import asyncio
    import json
    from app.core.llm_extractor import LLMExtractor

    async def do_extract():
        extractor = LLMExtractor()
        result = await extractor.extract(raw_text, language="zh")
        print(json.dumps(result, ensure_ascii=False, indent=2))
    asyncio.run(do_extract())
