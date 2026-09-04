import logging
import re

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



# 说明：为不丢失可能含有效数据的行，预处理阶段不再做关键词行级过滤
# （原 focus_relevant_sections 按行打分丢弃约 1/3 低分行，系统性降低召回）。
# 长文档由 orchestrator 按 LLM_CHUNK_THRESHOLD/SIZE/OVERLAP 全量切块、逐块交给 LLM
# （见 extraction/orchestrator.py），故此处直接使用全文。



def detect_language(text: str) -> str:
    """检测文本主要语言：zh / en"""
    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    english_chars = len(re.findall(r"[a-zA-Z]", text))
    if chinese_chars > english_chars:
        return "zh"
    return "en"


def truncate(text: str, max_chars: int | None = None) -> str:
    """截断文本到指定字符数以内。

    默认使用 settings.TEXT_PREPROCESS_MAX_CHARS（600000），仅作极长文本的安全兜底；
    分块的主导参数是 LLM_CHUNK_THRESHOLD/SIZE/OVERLAP，长文本由 orchestrator 分块逐块交给 LLM。
    """
    if max_chars is None:
        max_chars = getattr(settings, "TEXT_PREPROCESS_MAX_CHARS", 600000)
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
