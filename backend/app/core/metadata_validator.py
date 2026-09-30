"""P0-5：文献元数据格式校验。

防止 LLM 编造 DOI/PMID/年份 等标识符污染文献库。
所有函数均返回 bool；调用侧（extract_task.py）在校验失败时应 warning + 跳过回填。
"""
from __future__ import annotations

import re
from datetime import datetime

# DOI 通用正则：10. + 4-9 位注册机构号 + "/" + 至少 1 字符后缀
# 参考 Crossref 官方规范：https://www.crossref.org/documentation/register-and-deposit/doi-system/
_DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$")
_MAX_DOI_LEN = 128


def is_valid_doi(s: object) -> bool:
    """校验 DOI 格式合法性。

    规则：
    1. 必须是 str（或可转 str 且非空）
    2. 去除 ``doi:`` / ``https?://doi.org/`` / ``https?://dx.doi.org/`` 前缀后再校验
    3. 正则 ``^10\\.\\d{4,9}/\\S+$`` 且总长 ≤ 128

    示例：
      ✅ "10.1234/abc"
      ✅ "doi:10.1000/xyz123"
      ✅ "https://doi.org/10.1038/nature12345"
      ❌ "11.1234/x"        (前缀不是 10)
      ❌ "10.12/abc"        (注册机构号 < 4 位)
      ❌ "" / None / 123
    """
    if s is None:
        return False
    try:
        text = str(s).strip()
    except (TypeError, ValueError):
        return False
    if not text or len(text) > _MAX_DOI_LEN + 60:  # 留前缀余量
        return False

    # 剥离常见前缀
    text_lower = text.lower()
    for prefix in ("https://dx.doi.org/", "http://dx.doi.org/",
                   "https://doi.org/", "http://doi.org/",
                   "doi:"):
        if text_lower.startswith(prefix):
            text = text[len(prefix):].strip()
            break

    # 去前后斜杠（罕见防御）
    text = text.strip("/ ")
    if not text or len(text) > _MAX_DOI_LEN:
        return False

    return bool(_DOI_RE.match(text))


def is_valid_pmid(v: object) -> bool:
    """校验 PubMed ID：纯数字 1-9 位，且 int > 0。

    示例：
      ✅ "12345678" / 12345678 / "1"
      ❌ "" / None / "abc" / "1234567890" (>9 位) / 0 / "-5"
    """
    if v is None:
        return False
    try:
        text = str(v).strip()
    except (TypeError, ValueError):
        return False
    if not text or not text.isdigit():
        return False
    if len(text) > 9:
        return False
    try:
        n = int(text)
    except (TypeError, ValueError):
        return False
    return n > 0


def is_valid_pub_year(v: object) -> bool:
    """校验出版年份：1900 ≤ v ≤ 当前年 + 1（允许预印本或年份提前标注）。

    示例（以 2026 年为例）：
      ✅ 1950 / "2023" / 2026 / 2027
      ❌ "" / None / "abc" / 1899 / 2100 / 0 / "-5"
    """
    if v is None:
        return False
    try:
        n = int(str(v).strip())
    except (TypeError, ValueError):
        return False
    current_year = datetime.now().year
    return 1900 <= n <= current_year + 1
