"""P2-1: 公开数据集快照导出（CSV + 数据字典 zip）

生成一个可公开分享的数据集快照 ZIP 包，包含：
1. data_points.csv — 审核通过的数据点（匿名化，脱敏内部 ID）
2. data_dictionary.csv — 字段说明（名称/类型/描述/取值范围）
3. README.txt — 数据集元信息（生成时间/筛选条件/引用建议）
4. LICENSE.txt — 数据使用许可（CC BY 4.0 默认）

设计原则：
- 脱敏：不导出 source_context 原文片段（可能含敏感信息），不导出内部 UUID
- 可复现：README 记录筛选条件和数据点数量
- 自描述：数据字典让外部研究者无需查阅代码即可理解字段
"""
from __future__ import annotations

import csv
import io
import logging
import zipfile
from datetime import datetime
from typing import Iterable, Optional

logger = logging.getLogger(__name__)


# ── 数据字典定义 ────────────────────────────────────────
# (字段名, 类型, 描述, 取值范围/示例)
DATA_DICTIONARY = [
    ("dp_id", "string", "数据点唯一标识（匿名化哈希，非系统 UUID）", "如 dp_0001"),
    ("disease", "string", "疾病名称（标准化中文）", "如 麻疹、风疹、新冠"),
    ("province", "string", "省份名称（中国标准行政区划，不含'省/市'后缀）", "如 广东、北京、上海"),
    ("city", "string", "城市名称（如文献中提及）", "如 广州市、深圳市；可能为空"),
    ("data_type", "enum", "数据类型", "seroprevalence(血清阳性率) | gmc(几何平均浓度)"),
    ("value", "float", "数值", "阳性率: 0-100(百分比); GMC: 正数(单位见 unit 字段)"),
    ("unit", "string", "数值单位", "阳性率: %; GMC: IU/ml, mIU/ml, μg/ml 等"),
    ("ci_lower", "float", "95% 置信区间下限", "可能为空"),
    ("ci_upper", "float", "95% 置信区间上限", "可能为空"),
    ("sample_size", "integer", "样本量", "正整数；可能为空"),
    ("age_min", "integer", "年龄下限", "0-200；可能为空"),
    ("age_max", "integer", "年龄上限", "0-200；可能为空"),
    ("population", "string", "人群描述", "如 健康儿童、孕妇、军人"),
    ("collection_year", "integer", "采样年份", "如 2020；可能为空"),
    ("method", "string", "检测方法", "如 ELISA、化学发光法、中和试验"),
    ("assay", "string", "抗体类型", "如 IgG、IgM、Total Ab"),
    ("estimate_type", "enum", "估计类型", "primary(主估计/总体汇总) | subgroup(子组/分层估计)"),
    ("confidence", "enum", "置信度评级", "high | medium | low"),
    ("source_page", "integer", "来源页码", "正整数；可能为空"),
    ("is_grounded", "boolean", "是否在原文中成功匹配溯源片段", "true | false"),
    ("literature_title", "string", "来源文献标题", "已脱敏，不含作者信息"),
    ("literature_year", "integer", "文献发表年份", "如 2021；可能为空"),
    ("literature_journal", "string", "发表期刊", "可能为空"),
    # P1-3：导出新增作者/DOI/引用列
    ("literature_authors", "string", "来源文献作者", "多个作者以分号分隔；可能为空"),
    ("literature_doi", "string", "来源文献 DOI", "如 10.xxxx/xxxx；可能为空"),
    ("literature_pmid", "string", "来源文献 PubMed ID", "可能为空"),
    ("literature_citation", "string", "来源文献引用格式（作者. 标题. 期刊. 年份. DOI）", "供外部直接引用"),
]

# 导出的 CSV 列顺序（与数据字典对应）
EXPORT_COLUMNS = [row[0] for row in DATA_DICTIONARY]

LICENSE_TEXT = """Creative Commons Attribution 4.0 International License (CC BY 4.0)

You are free to:
- Share — copy and redistribute the material in any medium or format
- Adapt — remix, transform, and build upon the material for any purpose

Under the following terms:
- Attribution — You must give appropriate credit, provide a link to the license,
  and indicate if changes were made. You may do so in any reasonable manner,
  but not in any way that suggests the licensor endorses you or your use.

Full license: https://creativecommons.org/licenses/by/4.0/legalcode

数据来源：antibody_map01 抗体血清学文献数据提取系统
"""


def _anonymize_id(index: int) -> str:
    """生成匿名化的数据点 ID（dp_0001 格式）"""
    return f"dp_{index:04d}"


def _build_citation(r: dict) -> str:
    """P1-3：构建文献引用字符串（作者. 标题. 期刊. 年份. DOI）。"""
    parts = []
    authors = (r.get("literature_authors") or "").strip()
    if authors:
        parts.append(authors)
    title = (r.get("literature_title") or "").strip()
    if title:
        parts.append(title)
    journal = (r.get("literature_journal") or "").strip()
    if journal:
        parts.append(journal)
    year = r.get("literature_year")
    if year:
        parts.append(str(year))
    doi = (r.get("literature_doi") or "").strip()
    if doi:
        parts.append(f"doi: {doi}")
    return ". ".join(parts)


def _build_data_points_csv(rows: list[dict]) -> str:
    """构建数据点 CSV 字符串（UTF-8 with BOM）"""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(EXPORT_COLUMNS)

    for idx, r in enumerate(rows, start=1):
        # 从关联的文献信息中提取标题/年份/期刊/作者/DOI/PMID/引用
        lit_title = r.get("literature_title") or ""
        lit_year = r.get("literature_year")
        lit_journal = r.get("literature_journal") or ""
        lit_authors = r.get("literature_authors") or ""
        lit_doi = r.get("literature_doi") or ""
        lit_pmid = r.get("literature_pmid") or ""
        lit_citation = _build_citation(r)

        writer.writerow([
            _anonymize_id(idx),
            r.get("disease", ""),
            r.get("province", ""),
            r.get("city", ""),
            r.get("data_type", ""),
            r.get("value"),
            r.get("unit", ""),
            r.get("ci_lower"),
            r.get("ci_upper"),
            r.get("sample_size"),
            r.get("age_min"),
            r.get("age_max"),
            r.get("population", ""),
            r.get("collection_year"),
            r.get("method", ""),
            r.get("assay", ""),
            r.get("estimate_type", "primary"),
            r.get("confidence", ""),
            r.get("source_page", ""),
            "true" if r.get("is_grounded") else "false",
            lit_title,
            lit_year,
            lit_journal,
            lit_authors,
            lit_doi,
            lit_pmid,
            lit_citation,
        ])

    return output.getvalue()


def _build_data_dictionary_csv() -> str:
    """构建数据字典 CSV 字符串"""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["field_name", "data_type", "description", "value_range"])
    for name, dtype, desc, vrange in DATA_DICTIONARY:
        writer.writerow([name, dtype, desc, vrange])
    return output.getvalue()


def _build_readme(
    total_count: int,
    filters: dict,
    generated_at: Optional[str] = "",
) -> str:
    """构建 README.txt 内容"""
    if not generated_at:
        generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    filter_lines = []
    for k, v in filters.items():
        if v is not None and v != "":
            filter_lines.append(f"  - {k}: {v}")
    filter_str = "\n".join(filter_lines) if filter_lines else "  (无筛选，导出全部审核通过数据)"

    return f"""antibody_map01 公开数据集快照
================================

生成时间: {generated_at}
数据点总数: {total_count}
数据来源: antibody_map01 抗体血清学文献数据提取系统

筛选条件:
{filter_str}

文件说明:
  - data_points.csv    数据点主表（审核通过的数据）
  - data_dictionary.csv 字段说明（每个字段的名称/类型/描述/取值范围）
  - README.txt         本文件
  - LICENSE.txt        数据使用许可（CC BY 4.0）

字段说明:
  详细字段描述请参见 data_dictionary.csv。
  关键字段：
  - dp_id: 匿名化数据点 ID（非系统内部 UUID，可安全公开）
  - data_type: seroprevalence(阳性率) 或 gmc(几何平均浓度)
  - value: 数值（阳性率为 0-100 百分比，GMC 为原始值）
  - estimate_type: primary(主估计) 或 subgroup(子组估计)
  - is_grounded: 是否在原文中成功匹配溯源片段

使用建议:
  1. 引用本数据集时，请注明来源：antibody_map01 抗体血清学文献数据提取系统
  2. 进行汇总统计时，建议默认使用 estimate_type='primary' 的主估计数据点，
     避免主估计与子组估计重复计算
  3. 阳性率(value)已标准化为 0-100 百分比格式
  4. 如需追溯单个数据点的原文出处，请联系数据管理员获取完整溯源信息

免责声明:
  本数据集由 AI 辅助提取 + 人工审核产生，虽经多轮校验但仍可能存在误差。
  使用者应自行核实关键数据，作者不对数据准确性作绝对保证。
"""


def generate_dataset_snapshot_zip(
    data_points: list[dict],
    filters: Optional[dict] = None,
    generated_at: Optional[str] = "",
) -> bytes:
    """生成公开数据集快照 ZIP 包。

    Args:
        data_points: 数据点列表（dict 格式，包含 literature_title/year/journal 等关联字段）
        filters: 筛选条件字典（用于 README 记录）
        generated_at: 生成时间字符串

    Returns:
        ZIP 文件的字节内容
    """
    filters = filters or {}
    if not generated_at:
        generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 构建 CSV 内容
    dp_csv = _build_data_points_csv(data_points)
    dict_csv = _build_data_dictionary_csv()
    readme = _build_readme(len(data_points), filters, generated_at)

    # 打包 ZIP
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("data_points.csv", dp_csv.encode("utf-8-sig"))
        zf.writestr("data_dictionary.csv", dict_csv.encode("utf-8-sig"))
        zf.writestr("README.txt", readme.encode("utf-8"))
        zf.writestr("LICENSE.txt", LICENSE_TEXT.encode("utf-8"))

    zip_bytes = zip_buffer.getvalue()
    logger.info(
        f"[P2-1] 生成数据集快照: dp_count={len(data_points)}, "
        f"zip_size={len(zip_bytes)} bytes, filters={filters}"
    )
    return zip_bytes
