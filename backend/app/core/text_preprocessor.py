import logging
import re
from typing import Optional

from app.config import settings

logger = logging.getLogger("uvicorn")


def clean_text(text: str) -> str:
    """清洗文本：去除多余空白、换行、特殊控制字符"""
    # 去除控制字符（保留常用空白）
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    # 将多个空白合并为单个空格
    text = re.sub(r"[ \t]+", " ", text)
    # 将 3 个以上连续换行合并为 2 个
    text = re.sub(r"\n{3,}", "\n\n", text)
    # 去除行首行尾空白
    text = text.strip()
    return text



def focus_relevant_sections(text: str, lang: str = "zh") -> str:
    """聚焦最相关段落：结果 > 方法 > 摘要 > 全文，减少LLM输入量"""
    if len(text) <= 5000:
        return text
    keywords = {
        "zh": ["结果", "阳性率", "抗体水平", "血清", "GMC", "方法", "研究对象", "材料与方法", "摘要"],
        "en": ["results", "positivity", "antibody", "seroprevalence", "GMC", "methods", "materials", "abstract"],
    }
    kw = keywords.get(lang, keywords["en"])
    lines = text.split("\n")
    scored = []
    for i, line in enumerate(lines):
        score = sum(1 for k in kw if k.lower() in line.lower())
        if i < 20:
            score += 1
        scored.append((score, i, line))
    scored.sort(key=lambda x: x[0], reverse=True)
    keep_count = min(len(scored), max(80, len(scored) * 2 // 3))
    # 按原始行号排序保留
    kept = scored[:keep_count]
    kept.sort(key=lambda x: x[1])
    keep_lines = [line for _, _, line in kept]
    return "\n".join(keep_lines)



def detect_language(text: str) -> str:
    """检测文本主要语言：zh / en"""
    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    english_chars = len(re.findall(r"[a-zA-Z]", text))
    if chinese_chars > english_chars:
        return "zh"
    return "en"


def truncate(text: str, max_chars: Optional[int] = None) -> str:
    """截断文本到指定字符数以内。

    默认使用 settings.TEXT_PREPROCESS_MAX_CHARS（60000），须 > LLM_CHUNK_THRESHOLD(20000)，
    否则 llm_extractor 的分块并发逻辑永不触发。
    """
    if max_chars is None:
        max_chars = getattr(settings, "TEXT_PREPROCESS_MAX_CHARS", 60000)
    if len(text) <= max_chars:
        return text
    # 尽量在段落边界截断
    truncated = text[:max_chars]
    last_newline = truncated.rfind("\n")
    if last_newline > max_chars * 0.7:
        return truncated[:last_newline]
    return truncated


def extract_references(text: str) -> list[str]:
    """提取参考文献列表"""
    # 匹配参考文献常见的起始模式：[1] 1. 参考文献 (1)
    ref_pattern = re.compile(
        r"(?:^|\n)\s*(?:\[\d+\]|\d+[\.\)]\s*|参考文献\s*)",
        re.MULTILINE,
    )
    refs = []
    # 先找"参考文献"标记位置
    ref_section_match = re.search(
        r"(?:参考文献|References|REFERENCES)\s*\n",
        text,
        re.IGNORECASE,
    )
    if ref_section_match:
        ref_text = text[ref_section_match.end() :]
        lines = ref_text.strip().split("\n")
        for line in lines:
            line = line.strip()
            if line and re.match(r"\s*[\[\(]?\d+[\]\)\.]", line):
                refs.append(line)
    return refs


def preprocess(text: str, file_type: str = "text") -> str:
    """文本预处理主入口"""
    text = clean_text(text)
    lang = detect_language(text)
    text = focus_relevant_sections(text, lang)
    text = truncate(text)

    # 尝试移除参考文献部分，减少噪音
    refs = extract_references(text)
    if refs and lang == "zh":
        ref_start = text.find("参考文献")
        if ref_start > 0:
            text = text[:ref_start]
    elif refs:
        ref_start = re.search(r"\nReferences\s*\n", text, re.IGNORECASE)
        if ref_start:
            text = text[: ref_start.start()]

    return text.strip()
