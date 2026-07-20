import logging
import re
from typing import Optional

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


def detect_language(text: str) -> str:
    """检测文本主要语言：zh / en"""
    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    english_chars = len(re.findall(r"[a-zA-Z]", text))
    if chinese_chars > english_chars:
        return "zh"
    return "en"


def truncate(text: str, max_chars: int = 8000) -> str:
    """截断文本到 LLM 上下文窗口以内"""
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
