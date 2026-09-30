"""题录文件解析：支持 7 种格式 — RIS、EndNote(.enw)、PubMed 文本、PubMed RIS、WoS 纯文本、WoS CSV/Excel、读秀/超星(duxiu)。

统一输出每条记录包含：
- title: 标题（字符串，缺失为空串）
- authors: 作者（多个用分号连接，缺失为空串）
- journal: 期刊名（缺失为空串）
- year: 年份（整数字符串，缺失为空串）
- pub_date: 发表日期（RIS/ENW 为 PY/%D 原文，PubMed 为 "年份 月份" 形式，缺失为空串）
- doi: DOI（缺失为空串）
- pmid: PMID / WoS 唯一标识（缺失为空串）
- pmcid: PubMed Central 编号（缺失为空串）
- abstract: 摘要（缺失为空串）
- keywords: 关键词（多个用分号连接，缺失为空串）
- url: 文献链接（缺失为空串）
- issn: ISSN（缺失为空串）
- institution: 机构/单位（缺失为空串）
- source: 来源库（pubmed / cnki / wos / duxiu）

解析原则：每条记录独立 try/except 容错，某条失败跳过，不影响其他条。
"""
import csv
import io
import logging
import re

logger = logging.getLogger("uvicorn")


def _empty_record(source: str) -> dict:
    """构造统一结构的空记录。"""
    return {
        "title": "",
        "authors": "",
        "journal": "",
        "year": "",
        "pub_date": "",
        "doi": "",
        "pmid": "",
        "pmcid": "",
        "abstract": "",
        "keywords": "",
        "source": source,
        "url": "",
        "issn": "",
        "institution": "",
    }


def _clean_year(content: str) -> str:
    """从年份字段提取纯数字年份（取前 4 位数字）。"""
    return "".join(c for c in content[:4] if c.isdigit())


# ===== RIS =====

def _parse_ris(text: str) -> list[dict]:
    """解析 RIS 格式题录（RefWorks / NoteExpress 导出常见此格式）。

    RIS 格式约定：
    - 每条记录以 "TY  -" 开头，以 "ER  -" 结束
    - 字段名两位 + 空格 + 减号 + 空格 + 内容（如 "TY  - JOUR"）
    - AU 字段每行一个作者，多个作者多行
    - 标题 TI / 期刊 JO、JF / 年份 PY / DOI DO / 摘要 AB
    """
    records = []
    current = _empty_record("cnki")
    in_record = False
    current_field = None  # 最近识别的字段标签，用于续行追加

    for line in text.splitlines():
        line = line.rstrip("\n\r")
        if not line.strip():
            continue
        # 标准 RIS 字段行："TAG  - content"（也兼容 "TAG - content" / "TAG- content"）
        m = re.match(r"^([A-Za-z]{2})\s*-\s*(.*)$", line)
        if m:
            tag = m.group(1).upper()
            content = m.group(2).strip()
            current_field = tag
        elif in_record and current_field:
            # 续行（无标签）：追加到当前字段，摘要 AB / 标题 TI 等常跨多行
            tag = current_field
            content = line.strip()
        else:
            continue

        if tag == "TY":
            if in_record and current["title"]:
                records.append(current)
            in_record = True
            current = _empty_record("cnki")
            current_field = None
        elif tag == "ER":
            if in_record and current["title"]:
                records.append(current)
            in_record = False
            current = _empty_record("cnki")
            current_field = None
        elif in_record:
            if tag == "TI":
                current["title"] = (current["title"] + " " + content).strip() if current["title"] else content
            elif tag == "AU":
                if content:
                    current["authors"] = "; ".join(x for x in [current["authors"], content] if x)
            elif tag in ("JO", "JF"):
                current["journal"] = (current["journal"] + " " + content).strip() if current["journal"] else content
            elif tag == "PY":
                current["year"] = _clean_year(content)
                current["pub_date"] = content
            elif tag == "DO":
                current["doi"] = content
            elif tag == "AB":
                current["abstract"] = (current["abstract"] + " " + content).strip() if current["abstract"] else content
            elif tag == "KW":
                current["keywords"] = "; ".join(x for x in [current["keywords"], content] if x)
            elif tag == "UR":
                current["url"] = content
            elif tag == "SN":
                current["issn"] = content
            elif tag == "AD":
                current["institution"] = (current["institution"] + " " + content).strip() if current["institution"] else content
            # 忽略其他标签（DA、VL、SP 等，暂时不需要）

    if in_record and current["title"]:
        records.append(current)

    return records


# ===== EndNote (.enw) =====

def _parse_enw(text: str) -> list[dict]:
    """解析 EndNote .enw 格式题录。

    EndNote 格式约定：
    - 每条记录以 "%0 " 开头
    - %A：作者（每行一个） / %T：标题 / %J：期刊 / %D：年份 / %R：DOI / %X：摘要
    """
    records = []
    current = _empty_record("cnki")
    in_record = False
    current_field = None  # 最近识别的字段标签，用于续行追加

    for line in text.splitlines():
        line = line.rstrip("\n\r")
        if not line.strip():
            continue
        if line[0] == "%":
            tag = line[1]
            content = line[2:].strip()
            current_field = tag
        elif in_record and current_field:
            # 续行（不以 % 开头）：追加到当前字段，%X 摘要常跨多行
            tag = current_field
            content = line.strip()
        else:
            continue

        if tag == "0":
            if in_record and current["title"]:
                records.append(current)
            in_record = True
            current = _empty_record("cnki")
            current_field = None
        elif in_record:
            if tag == "T":
                current["title"] = (current["title"] + " " + content).strip() if current["title"] else content
            elif tag == "A":
                if content:
                    current["authors"] = "; ".join(x for x in [current["authors"], content] if x)
            elif tag == "J":
                current["journal"] = (current["journal"] + " " + content).strip() if current["journal"] else content
            elif tag == "D":
                current["year"] = _clean_year(content)
                current["pub_date"] = content
            elif tag == "R":
                current["doi"] = content
            elif tag == "7" and not current["doi"]:
                # EndNote 某些导出中 DOI 用 %7 表示（%R 兜底）
                current["doi"] = content
            elif tag == "X":
                current["abstract"] = (current["abstract"] + " " + content).strip() if current["abstract"] else content
            elif tag == "K":
                current["keywords"] = "; ".join(x for x in [current["keywords"], content] if x)
            elif tag == "U":
                current["url"] = content
            elif tag == "@":
                current["issn"] = content
            # 忽略其他标签（%I 出版社等，暂时不需要）

    if in_record and current["title"]:
        records.append(current)

    return records


# ===== PubMed 文本 =====

def _join_block(block: str) -> str:
    """将多行段落合并为单行（折叠空白）。"""
    return re.sub(r"\s+", " ", block).strip()


def _is_tail_block(block: str) -> bool:
    """判断是否为记录尾部标记块（版权/©/DOI/PMID/PMCID/关键词/利益冲突等）。"""
    stripped = block.strip()
    up = stripped.upper()
    if stripped.startswith("©"):
        return True
    return up.startswith(("PMID:", "DOI:", "PMCID:", "COPYRIGHT", "CONFLICT OF INTEREST", "KEYWORD", "ELECTRONIC ADDRESS"))


def _parse_pubmed_record(seg: str, rec: dict) -> None:
    """解析单条 PubMed Abstract Text 记录（以 "N. " 序号开头的段落）。"""
    blocks = [b.strip() for b in re.split(r"\n\s*\n", seg.strip()) if b.strip()]
    if not blocks:
        return

    # 全局 DOI / PMID / PMCID / 年份 / 关键词
    m_doi = re.search(r"DOI:\s*(\S+)", seg, re.I)
    if m_doi:
        rec["doi"] = m_doi.group(1).rstrip(".,;")
    m_pmid = re.search(r"PMID:\s*(\d+)", seg, re.I)
    if m_pmid:
        rec["pmid"] = m_pmid.group(1)
    m_pmcid = re.search(r"PMCID:\s*(\S+)", seg, re.I)
    if m_pmcid:
        rec["pmcid"] = m_pmcid.group(1).rstrip(".,;")
    m_year = re.search(r"(19|20)\d{2}", seg)
    if m_year:
        rec["year"] = m_year.group(0)
    m_kw = re.search(r"(?m)^Keywords?[:：]\s*(.+)$", seg, re.I)
    if m_kw:
        rec["keywords"] = _join_block(m_kw.group(1))
    # 发表日期：形如 "2020 Mar 15" / "2020 Mar"（引用行中年份+月份）
    m_pubdate = re.search(
        r"\b((19|20)\d{2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*(?:\s+\d{1,2})?)",
        seg, re.I,
    )
    if m_pubdate:
        rec["pub_date"] = _join_block(m_pubdate.group(1))
    elif m_year:
        rec["pub_date"] = m_year.group(0)
    if rec["pmid"]:
        rec["url"] = f"https://pubmed.ncbi.nlm.nih.gov/{rec['pmid']}/"

    # 无空行分隔（单块）→ 简单行式解析（旧 Summary 风格）
    if len(blocks) == 1:
        lines = [line.strip() for line in seg.splitlines() if line.strip()]
        if lines:
            rec["title"] = re.sub(r"^\d+\.\s*", "", lines[0])
        if len(lines) > 1:
            rec["authors"] = lines[1]
        if m_year:
            for line in lines:
                if m_year.group(0) in line:
                    jp = re.sub(r"^\d+\.\s*", "", line[: line.find(m_year.group(0))]).strip()
                    jp = jp.split("doi:", 1)[0].strip()
                    jp = re.sub(r"[,.;]\s*$", "", jp).strip()
                    rec["journal"] = jp
                    break
        # 摘要：PMID/DOI 行之后的剩余内容
        abstract_parts = []
        for line in lines:
            if re.search(r"^PMID:", line, re.I) or re.search(r"^DOI:", line, re.I):
                abstract_parts = []
                continue
            if abstract_parts or re.search(r"^(?:OBJECTIVE|BACKGROUND|INTRODUCTION|AIM|METHODS|RESULTS|CONCLUSION|DISCUSSION|IMPORTANCE|SUMMARY)[:：]", line, re.I):
                abstract_parts.append(line)
        rec["abstract"] = " ".join(abstract_parts).strip()
        return

    # 多块：判断首块是否为引用信息（Abstract Text 风格：含 doi: 或以 ". 年份" 结尾）
    first_block = blocks[0]
    is_citation = bool(re.search(r"doi:\s*\S+", first_block, re.I)) or bool(
        re.search(r"\.\s*(19|20)\d{2}", first_block)
    )

    if is_citation:
        # 期刊：引用信息中年份之前的文本
        mj = re.search(r"(19|20)\d{2}", first_block)
        if mj:
            journal_part = re.sub(r"^\d+\.\s*", "", first_block[: first_block.find(mj.group(0))]).strip()
            journal_part = re.sub(r"[,.;]\s*$", "", journal_part).strip()
            rec["journal"] = journal_part
        # 标题 = 第二块；作者 = 第三块
        if len(blocks) > 1:
            rec["title"] = _join_block(blocks[1])
        if len(blocks) > 2:
            rec["authors"] = _join_block(blocks[2]).rstrip(".")
        # 摘要：作者块之后，跳过 "Author information:"，遇到尾部标记结束
        abstract_parts = []
        started = False
        for block in blocks[3:]:
            up = block.upper()
            if _is_tail_block(block):
                break
            if not started:
                if up.startswith("AUTHOR INFORMATION"):
                    continue
                started = True
            abstract_parts.append(_join_block(block))
        rec["abstract"] = " ".join(abstract_parts).strip()
    else:
        # 无引用信息（简单风格）：标题 = 首块；作者 = 第二块；期刊取含年份块
        rec["title"] = re.sub(r"^\d+\.\s*", "", first_block).strip()
        if len(blocks) > 1:
            rec["authors"] = _join_block(blocks[1])
        if m_year:
            for block in blocks:
                if m_year.group(0) in block:
                    jp = re.sub(r"^\d+\.\s*", "", block[: block.find(m_year.group(0))]).strip()
                    jp = jp.split("doi:", 1)[0].strip()
                    jp = re.sub(r"[,.;]\s*$", "", jp).strip()
                    rec["journal"] = jp
                    break
        # 摘要：作者块之后、尾部标记之前
        abstract_parts = []
        for block in blocks[2:]:
            if _is_tail_block(block):
                break
            abstract_parts.append(_join_block(block))
        rec["abstract"] = " ".join(abstract_parts).strip()


def _parse_pubmed(text: str) -> list[dict]:
    r"""解析 PubMed Abstract Text / Summary 文本格式题录（每条以 "N. " 序号行开头）。

    每条记录结构（按空行分段）：
    - 引用信息：杂志、年份、卷期、DOI（可能跨行）
    - 标题（可能跨行）
    - 作者（可能跨行）
    - Author information: 单位信息（跳过）
    - 摘要（可能跨行，遇到 Copyright / © / DOI: / PMID: / 利益冲突 结束）
    - DOI: / PMCID: / PMID: 等尾部字段

    记录头识别：以 "^\d{1,4}\. " 开头的行，且序号须从 1 起连续递增，
    避免摘要正文中形如 "26."（引用行续行）或 "2. In addition, ..."（摘要句子）
    被误判为记录头。
    """
    records = []
    text = text.strip()
    if not text:
        return records

    header_re = re.compile(r"(?m)^(\d{1,4}\.\s+)")
    starts = []      # 记录头起始位置
    expected = None  # 期望的下一条记录序号（从 1 起连续）
    for m in header_re.finditer(text):
        num = int(m.group(1).strip().rstrip("."))
        if expected is not None and num != expected:
            continue
        starts.append(m.start())
        expected = num + 1

    starts.append(len(text))
    for idx in range(len(starts) - 1):
        seg = text[starts[idx]:starts[idx + 1]]
        rec = _empty_record("pubmed")
        try:
            _parse_pubmed_record(seg, rec)
        except Exception as e:
            logger.warning(f"[reference_parser] PubMed 记录解析失败跳过: {e}")
            continue
        if rec["title"]:
            records.append(rec)

    return records


# ===== PubMed RIS（Save → RIS 导出） =====

def _parse_pubmed_ris_record(seg: str, rec: dict) -> None:
    """解析单条 PubMed RIS 记录（以 "PMID- 编号" 开头的段落）。

    PubMed RIS 标签为不定长（PMID/OWN/STAT/DA/TI/AB/FAU/AU/TA/JT/DP/SO/LID/AID/PMC/AD/LA...），
    以 "- " 分隔；与标准 RIS（TY/ER 两字母标签）不同，需按标签名匹配。
    """
    current_field = None
    for line in seg.splitlines():
        line = line.rstrip("\n\r")
        if not line.strip():
            continue
        m = re.match(r"^([A-Za-z0-9]{2,})\s*-\s*(.*)$", line)
        if m:
            tag = m.group(1).upper()
            content = m.group(2).strip()
            current_field = tag
        elif current_field:
            # 续行（无标签）：追加到当前字段
            tag = current_field
            content = line.strip()
        else:
            continue

        if tag == "PMID":
            rec["pmid"] = content
            rec["url"] = f"https://pubmed.ncbi.nlm.nih.gov/{content}/"
        elif tag == "TI":
            rec["title"] = (rec["title"] + " " + content).strip() if rec["title"] else content
        elif tag in ("FAU", "AU"):
            if content:
                rec["authors"] = "; ".join(x for x in [rec["authors"], content] if x)
        elif tag == "TA" and not rec["journal"]:
            rec["journal"] = content
        elif tag == "JT":
            # JT 为完整期刊名，覆盖 TA 缩写，避免重复拼接
            rec["journal"] = content
        elif tag == "DP":
            rec["pub_date"] = content
            ym = re.search(r"(19|20)\d{2}", content)
            if ym:
                rec["year"] = ym.group(0)
        elif tag in ("LID", "AID"):
            c = re.sub(r"\s*\[doi\]", "", content, flags=re.I).strip()
            if c.lower().startswith("10."):
                rec["doi"] = c
        elif tag == "AB":
            rec["abstract"] = (rec["abstract"] + " " + content).strip() if rec["abstract"] else content
        elif tag == "AD":
            rec["institution"] = (rec["institution"] + " " + content).strip() if rec["institution"] else content
        elif tag == "PMC":
            rec["pmcid"] = content
        elif tag == "SO" and not rec["journal"]:
            # 来源行 "期刊. 年份;卷(期)..."：取年份前的期刊名作兜底
            ym = re.search(r"(19|20)\d{2}", content)
            if ym:
                jp = content[: content.find(ym.group(0))].strip().rstrip(".")
                rec["journal"] = jp
        # 忽略其余标签（OWN/STAT/DA/DCOM/LR/IS/VI/IP/PG/LA/PT/DEP/JID 等）


def _parse_pubmed_ris(text: str) -> list[dict]:
    """解析 PubMed「Save → RIS」导出格式题录。

    - 每条记录以 "PMID- 编号" 行开头，按此切分记录
    - 不定长标签 + "- " 分隔（PMID- / TI- / AB- / FAU- 等）
    - 期刊取 JT/TA，年份取 DP 中的数字
    """
    records = []
    starts = [m.start() for m in re.finditer(r"(?m)^PMID\s*-\s*\d+", text)]
    starts.append(len(text))
    for idx in range(len(starts) - 1):
        seg = text[starts[idx]:starts[idx + 1]]
        rec = _empty_record("pubmed")
        try:
            _parse_pubmed_ris_record(seg, rec)
        except Exception as e:
            logger.warning(f"[reference_parser] PubMed RIS 记录解析失败跳过: {e}")
            continue
        if rec["title"]:
            records.append(rec)

    return records


# ===== WoS 纯文本 =====

_WOS_TAGS = {
    "TI": "title",
    "AU": "authors",
    "SO": "journal",
    "PY": "year",
    "DI": "doi",
    "AB": "abstract",
    "DE": "keywords",
    "UT": "pmid",
    "SN": "issn",
}


def _append_wos_field(rec: dict, tag: str, content: str) -> None:
    """将 WoS 两字母标签内容写入记录，多行字段（AU/AB）自动续接。"""
    if not content:
        return
    if tag == "AU":
        rec["authors"] = "; ".join(x for x in [rec["authors"], content] if x)
    elif tag == "AB":
        rec["abstract"] = (rec["abstract"] + " " + content).strip() if rec["abstract"] else content
    elif tag == "TI":
        rec["title"] = (rec["title"] + " " + content).strip() if rec["title"] else content
    elif tag == "SO":
        rec["journal"] = (rec["journal"] + " " + content).strip() if rec["journal"] else content
    elif tag == "PY":
        rec["year"] = _clean_year(content)
        rec["pub_date"] = content
    elif tag == "DI":
        rec["doi"] = content
    elif tag == "DE":
        rec["keywords"] = "; ".join(x for x in [rec["keywords"], content] if x)
    elif tag == "UT":
        rec["pmid"] = content
    elif tag == "SN":
        rec["issn"] = content


def _parse_wos(text: str) -> list[dict]:
    """解析 WoS（Web of Science）纯文本导出格式题录。

    - 每条记录以 "ER" 单独一行结束，按 "ER" 行分段
    - 字段为两字母标签 + 空格 + 内容（TI/SO/PY/DI/UT 等）
    - AU、AB 支持续行（行首为空白符的缩进行自动追加到上一字段）
    """
    records = []
    segments = re.split(r"(?m)^ER\s*$", text)
    for seg in segments:
        seg = seg.strip()
        if not seg:
            continue
        rec = _empty_record("wos")
        try:
            current_tag = None
            for line in seg.splitlines():
                if not line.strip():
                    continue
                if line[0].isspace():
                    # 续行：追加到当前字段
                    if current_tag:
                        _append_wos_field(rec, current_tag, line.strip())
                    continue
                m = re.match(r"^([A-Z]{2})\s+(.*)$", line)
                if m:
                    current_tag = m.group(1)
                    _append_wos_field(rec, current_tag, m.group(2).strip())
                else:
                    current_tag = None
        except Exception as e:
            logger.warning(f"[reference_parser] WoS 记录解析失败跳过: {e}")
            continue
        if rec["title"]:
            records.append(rec)

    return records


# ===== WoS CSV / Excel =====

def _parse_woscsv(text: str) -> list[dict]:
    """解析 WoS 导出的 CSV/Excel（逗号或制表符分隔）格式题录。

    - 用 csv.Sniffer 自动识别分隔符，DictReader 逐行读取
    - 列名映射：TI→title, AU→authors, SO→journal, PY→year, DI→doi, AB→abstract, UT→pmid
    """
    records = []
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",\t;")
    except Exception:
        dialect = csv.excel

    try:
        reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    except Exception as e:
        logger.warning(f"[reference_parser] WoS CSV 读取失败返回空: {e}")
        return records

    for row in reader:
        rec = _empty_record("wos")
        try:
            for col in row:
                key = (col or "").strip().upper()
                val = (row[col] or "").strip()
                if key in _WOS_TAGS:
                    _append_wos_field(rec, key, val)
        except Exception as e:
            logger.warning(f"[reference_parser] WoS CSV 记录解析失败跳过: {e}")
            continue
        if rec["title"]:
            records.append(rec)

    return records


# ===== 读秀 / 超星（中文标签） =====

def _parse_duxiu(text: str) -> list[dict]:
    """解析读秀/超星（ss.zhizhen.com）中文标签导出格式题录。

    每条记录以 "N. [" 序号行开头，标签行形如 "题名：xxx" / "作者：xxx" /
    "出处：期刊名; 年份; 卷(期)"，摘要、关键词、链接等同样以中文标签给出。
    """
    records = []
    starts = [m.start() for m in re.finditer(r"(?m)^\d+\.\s*\[", text)]
    starts.append(len(text))
    for idx in range(len(starts) - 1):
        rec_text = text[starts[idx]:starts[idx + 1]]
        rec = _empty_record("duxiu")
        try:
            def f(label_re, rec_text=rec_text):  # 绑定当前循环的 rec_text，避免闭包延迟绑定
                m = re.search(label_re, rec_text, re.M)
                return _join_block(m.group(1)) if m else ""

            rec["title"] = f(r"^题\s*名\s*[：:]\s*(.*)$")
            rec["authors"] = f(r"^作\s*者\s*[：:]\s*(.*)$")
            rec["institution"] = f(r"^作者单位\s*[：:]\s*(.*)$")
            rec["keywords"] = f(r"^关键词\s*[：:]\s*(.*)$")
            source = f(r"^出\s*处\s*[：:]\s*(.*)$")
            rec["abstract"] = f(r"^摘\s*要\s*[：:]\s*(.*)$")
            rec["url"] = f(r"^链\s*接\s*[：:]\s*(.*)$")
            rec["issn"] = f(r"^ISSN\s*[：:]\s*(.*)$")

            # 出处形如 "期刊名; 年份; 卷(期)"：第一段为期刊，其后段中提取年份
            if source:
                parts = [p.strip() for p in source.split(";") if p.strip()]
                rec["journal"] = parts[0] if parts else ""
                for p in parts[1:]:
                    m = re.search(r"(19|20)\d{2}", p)
                    if m:
                        rec["year"] = m.group(0)
                        break
        except Exception as e:
            logger.warning(f"[reference_parser] 读秀记录解析失败跳过: {e}")
            continue
        if rec["title"]:
            records.append(rec)

    return records


# ===== 格式自动探测 =====

def _detect_format(text: str) -> str | None:
    """按内容特征自动判断题录格式：ris / enw / wos / pubmed / pubmed_ris / woscsv / duxiu。"""
    lines = [line for line in text.splitlines() if line.strip()]
    first_line = lines[0].strip() if lines else ""

    # a) RIS（TY/ER 两字母标签，兼容单/多空格）
    if re.search(r"(?m)^TY\s*-\s*", text) and re.search(r"(?m)^ER\s*-\s*", text):
        return "ris"
    # b) EndNote（%0 开头，兼容任意缩进/前导内容）
    if re.search(r"(?m)^%0\s*", text):
        return "enw"
    # c) WoS 纯文本（PT J/PT S 类型 + ER 单独成行）
    if ("PT J" in text or "PT S" in text) and re.search(r"(?m)^ER\s*$", text):
        return "wos"
    # d) 读秀/超星（中文标签，形如 "1. [出处]" + "题名："）
    if re.search(r"(?m)^\d+\.\s*\[", text) and re.search(r"题\s*名\s*[：:]|出\s*处\s*[：:]", text):
        return "duxiu"
    # e) PubMed RIS（Save → RIS 导出，"PMID- 编号" 不定长标签）
    if re.search(r"(?m)^PMID\s*-\s*\d+", text):
        return "pubmed_ris"
    # f) PubMed 文本（首行含 PMID: 或形如 "1. 标题"）
    if "PMID:" in first_line or re.match(r"^\d+\.\s*\S", first_line):
        return "pubmed"
    # g) WoS CSV/Excel（首行表头含 TI 列，逗号/制表符分隔）
    if first_line:
        try:
            dialect = csv.Sniffer().sniff(first_line, delimiters=",\t;")
            headers = [h.strip().upper() for h in next(csv.reader([first_line], dialect=dialect))]
            if "TI" in headers:
                return "woscsv"
        except Exception:
            pass
    return None


# ===== 统一入口 =====

def parse_references(text: str, fmt: str = "auto") -> list[dict]:
    """解析题录文本，返回统一结构的记录列表。

    Args:
        text: 题录文件的全文文本
        fmt: 格式，取值 auto / ris / enw / pubmed / pubmed_ris / wos / woscsv / duxiu；
             auto 时按内容特征自动判断。

    Returns:
        list[dict]: 每条为 {title, authors, journal, year, pub_date, doi, pmid,
                    pmcid, abstract, keywords, source, url, issn, institution}
    """
    if not text or not text.strip():
        return []

    text = text.lstrip("\ufeff")  # 去除 BOM，避免影响格式探测
    fmt = (fmt or "auto").strip().lower()
    if fmt == "auto":
        fmt = _detect_format(text) or "ris"  # 探测失败时回退按 RIS 尝试

    try:
        if fmt == "ris":
            return _parse_ris(text)
        if fmt == "enw":
            return _parse_enw(text)
        if fmt == "pubmed":
            # PubMed 文本与 PubMed RIS 二选一（显式指定 pubmed 时自动兼容）
            if re.search(r"(?m)^PMID\s*-\s*\d+", text):
                return _parse_pubmed_ris(text)
            return _parse_pubmed(text)
        if fmt == "pubmed_ris":
            return _parse_pubmed_ris(text)
        if fmt == "wos":
            return _parse_wos(text)
        if fmt == "woscsv":
            return _parse_woscsv(text)
        if fmt == "duxiu":
            return _parse_duxiu(text)
        logger.warning(f"[reference_parser] 未知格式: {fmt}")
        return []
    except Exception as e:
        logger.warning(f"[reference_parser] {fmt} 解析失败，返回空: {e}")
        return []
