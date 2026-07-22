import logging
from datetime import datetime, timezone
from typing import Optional

from openai import AsyncOpenAI
from sqlalchemy import select, func, distinct
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.data_point import DataPoint
from app.models.report import Report

logger = logging.getLogger("uvicorn")

DISEASE_NAMES = {
    "measles": "麻疹", "mumps": "腮腺炎", "rubella": "风疹",
    "pertussis": "百日咳", "diphtheria": "白喉", "tetanus": "破伤风",
    "hepatitis_b": "乙肝", "hepatitis_a": "甲肝", "polio": "脊灰",
    "influenza": "流感", "covid19": "新冠", "meningitis": "流脑",
    "varicella": "水痘", "hfmd": "手足口病", "rotavirus": "轮状病毒",
}

AGE_GROUPS = [
    ("<1岁", 0, 0),
    ("1-4岁", 1, 4),
    ("5-14岁", 5, 14),
    ("15-59岁", 15, 59),
    (">=60岁", 60, 200),
]

AGE_GROUPS_EN = [
    ("<1y", 0, 0),
    ("1-4y", 1, 4),
    ("5-14y", 5, 14),
    ("15-59y", 15, 59),
    (">=60y", 60, 200),
]

REPORT_PROMPT_ZH = """你是一位流行病学专家，请根据以下数据生成一份{title}的抗体水平分析报告。

数据概况：
- 数据来源：{literature_count} 篇文献
- 数据点数：{point_count} 个
- 覆盖省份：{province_count} 个
- 总样本量：{total_samples} 人

各省数据：
{province_table}

年份趋势：
{year_trend}

年龄分布：
{age_distribution}

请按以下结构输出报告（Markdown 格式）：
## 1. 总体概况
## 2. 地区分布
## 3. 时间趋势分析
## 4. 年龄分布特征
## 5. 免疫学参考意见

请基于数据给出专业的免疫学分析和建议，不要编造不存在的数据。"""

REPORT_PROMPT_EN = """You are an epidemiological expert. Please generate an antibody level analysis report based on the following data for {title_en}.

Data Overview:
- Data Sources: {literature_count} papers
- Data Points: {point_count}
- Provinces Covered: {province_count}
- Total Sample Size: {total_samples}

Province Data:
{province_table}

Yearly Trend:
{year_trend}

Age Distribution:
{age_distribution}

Please structure the report in Markdown format:
## 1. Overall Summary
## 2. Regional Distribution
## 3. Temporal Trend Analysis
## 4. Age Distribution Characteristics
## 5. Immunological Recommendations

Base your analysis strictly on the provided data. Do not fabricate any data."""


def _calc_weighted_rate(rows: list[DataPoint]) -> tuple[float, int]:
    """计算加权阳性率"""
    sp_rows = [r for r in rows if r.data_type == "seroprevalence" and r.sample_size and r.value is not None]
    if not sp_rows:
        return 0.0, 0
    total_sample = sum(r.sample_size for r in sp_rows)
    weighted_sum = sum(r.value * r.sample_size for r in sp_rows)
    return round(weighted_sum / total_sample, 2), total_sample


async def generate_report(
    db: AsyncSession,
    disease: Optional[str] = None,
    province: Optional[str] = None,
    data_type: Optional[str] = None,
    language: str = "zh",
    title: Optional[str] = None,
) -> dict:
    """生成报告"""
    # 1. 查询审核通过的数据点
    query = select(DataPoint).where(DataPoint.review_status == "approved")
    if disease:
        query = query.where(DataPoint.disease == disease)
    if province:
        query = query.where(DataPoint.province.ilike(f"%{province}%"))
    if data_type:
        query = query.where(DataPoint.data_type == data_type)

    result = await db.execute(query)
    rows = list(result.scalars().all())

    if not rows:
        raise ValueError("没有找到审核通过的数据，无法生成报告")

    # 2. 统计概况
    lit_ids = set(str(r.literature_id) for r in rows if r.literature_id)
    provinces_set = set()
    for r in rows:
        for p in (r.province or "").split(";"):
            p = p.strip()
            if p:
                provinces_set.add(p)

    total_sample = sum(r.sample_size or 0 for r in rows)

    # 3. 省份对比数据
    province_map: dict[str, list[DataPoint]] = {}
    for r in rows:
        for p in (r.province or "").split(";"):
            p = p.strip()
            if not p:
                p = "未知"
            if p not in province_map:
                province_map[p] = []
            province_map[p].append(r)

    province_lines = []
    for prov, group in sorted(province_map.items()):
        wpr, ps = _calc_weighted_rate(group)
        province_lines.append(f"- {prov}：阳性率 {wpr}%，样本量 {ps}，数据点 {len(group)} 个")

    province_table = "\n".join(province_lines) if province_lines else "暂无数据"

    # 4. 年份趋势
    year_map: dict[int, list[DataPoint]] = {}
    for r in rows:
        y = r.collection_year
        if y is None:
            continue
        if y not in year_map:
            year_map[y] = []
        year_map[y].append(r)

    year_lines = []
    for year in sorted(year_map.keys()):
        group = year_map[year]
        wpr, ps = _calc_weighted_rate(group)
        year_lines.append(f"- {year}年：阳性率 {wpr}%，样本量 {ps}，数据点 {len(group)} 个")

    year_trend = "\n".join(year_lines) if year_lines else "暂无数据"

    # 5. 年龄分布
    age_labels = AGE_GROUPS if language == "zh" else AGE_GROUPS_EN
    age_map: dict[str, list[DataPoint]] = {}
    for label, _, _ in age_labels:
        age_map[label] = []

    for r in rows:
        matched = False
        for label, lo, hi in age_labels:
            if r.age_min is not None and r.age_max is not None:
                if r.age_min >= lo and r.age_max <= hi:
                    age_map[label].append(r)
                    matched = True
                    break
        if not matched:
            if "其他" not in age_map:
                age_map["其他" if language == "zh" else "Other"] = []
            age_map["其他" if language == "zh" else "Other"].append(r)

    age_lines = []
    for label, _lo, _hi in age_labels:
        group = age_map.get(label, [])
        if group:
            wpr, ps = _calc_weighted_rate(group)
            age_lines.append(f"- {label}：阳性率 {wpr}%，样本量 {ps}")
    other_label = "其他" if language == "zh" else "Other"
    if age_map.get(other_label):
        group = age_map[other_label]
        wpr, ps = _calc_weighted_rate(group)
        age_lines.append(f"- {other_label}：阳性率 {wpr}%，样本量 {ps}")

    age_distribution = "\n".join(age_lines) if age_lines else "暂无数据"

    # 6. 生成疾病名称
    disease_name = DISEASE_NAMES.get(disease or "", disease or "未知疾病")

    # 7. 报告标题
    if title:
        report_title = title
        report_title_en = title
    else:
        report_title = f"{disease_name}抗体水平分析报告"
        report_title_en = f"{disease_name} Antibody Level Analysis Report"

    # 8. 构建 Prompt 并调用 LLM
    if language == "zh":
        prompt = REPORT_PROMPT_ZH.format(
            title=report_title,
            literature_count=len(lit_ids),
            point_count=len(rows),
            province_count=len(provinces_set),
            total_samples=total_sample,
            province_table=province_table,
            year_trend=year_trend,
            age_distribution=age_distribution,
        )
    else:
        prompt = REPORT_PROMPT_EN.format(
            title_en=report_title_en,
            literature_count=len(lit_ids),
            point_count=len(rows),
            province_count=len(provinces_set),
            total_samples=total_sample,
            province_table=province_table,
            year_trend=year_trend,
            age_distribution=age_distribution,
        )

    content = await _call_llm(prompt)


    # 9. Save to database
    try:
        report = Report(
            title=report_title,
            content=content,
            disease=disease,
            province=province,
            data_type=data_type,
            language=language,
            literature_count=len(lit_ids),
            data_point_count=len(rows),
        )
        db.add(report)
        await db.commit()
    except Exception as e:
        logger.warning(f"??????????: {e}")

    return {
        "id": str(report.id) if report else None,
        "title": report_title,
        "content": content,
        "literature_count": len(lit_ids),
        "data_point_count": len(rows),
        "language": language,
        "generated_at": report.generated_at.isoformat() if report else datetime.now(timezone.utc).isoformat(),
    }


async def _call_llm(prompt: str) -> str:
    """调用 LLM 生成报告"""
    client = AsyncOpenAI(
        api_key=settings.LLM_API_KEY,
        base_url=settings.LLM_BASE_URL,
    )
    try:
        response = await client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            timeout=120,
        )
        return response.choices[0].message.content or ""
    except Exception as e:
        logger.warning(f"LLM API 调用失败: {e}")
        raise RuntimeError(f"报告生成失败: {e}")


async def get_reports(db: AsyncSession, page: int = 1, page_size: int = 20):
    """??????"""
    from sqlalchemy import desc
    q = select(Report).order_by(desc(Report.generated_at))
    total_q = select(func.count(Report.id))
    total = (await db.execute(total_q)).scalar() or 0
    rows = (await db.execute(q.offset((page - 1) * page_size).limit(page_size))).scalars().all()
    items = []
    for r in rows:
        items.append({
            "id": str(r.id),
            "title": r.title,
            "disease": r.disease,
            "province": r.province,
            "data_type": r.data_type,
            "language": r.language,
            "literature_count": r.literature_count,
            "data_point_count": r.data_point_count,
            "generated_at": r.generated_at.isoformat(),
        })
    return {"items": items, "total": total, "page": page, "page_size": page_size}


async def get_report_by_id(db: AsyncSession, report_id):
    """????????"""
    from uuid import UUID
    uid = UUID(report_id)
    r = (await db.execute(select(Report).where(Report.id == uid))).scalar_one_or_none()
    if not r:
        return None
    return {
        "id": str(r.id),
        "title": r.title,
        "content": r.content,
        "disease": r.disease,
        "province": r.province,
        "data_type": r.data_type,
        "language": r.language,
        "literature_count": r.literature_count,
        "data_point_count": r.data_point_count,
        "generated_at": r.generated_at.isoformat(),
    }

