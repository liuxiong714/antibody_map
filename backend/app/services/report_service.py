import logging
from datetime import date, datetime, timezone
from typing import Optional
from uuid import UUID

from openai import AsyncOpenAI
from sqlalchemy import select, func, distinct
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.methodology import build_methodology_note
from app.models.api_model_config import ApiModelConfig
from app.models.data_point import DataPoint
from app.models.report import Report
from app.models.report_template import ReportTemplate

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

VACCINATION_STRATEGY_PROMPT_ZH = """你是一位流行病学和疫苗学专家。请根据以下任务信息和任务地点传染病流行情况，综合研判并制定参加任务人员的疫苗接种策略。

任务信息：
- 任务类型：{task_type}
- 任务时间：{task_time}
- 任务地点：{task_location}
- 人员人数：{personnel_count}人
- 人员性别分布：{personnel_gender}
- 人员年龄范围：{personnel_age}
- 人员疫苗接种史：{personnel_vaccination_history}

任务地点传染病流行情况：
{epidemic_data}

请按以下结构输出疫苗接种策略报告（Markdown 格式）：
## 1. 任务概况与传染病风险评估
- 结合任务类型、时间、地点分析可能面临的传染病风险
- 评估任务地点的传染病流行威胁
## 2. 任务地点传染病流行现状分析
- 基于现有流行病学数据分析当地主要传染病的流行水平和免疫屏障状况
- 识别高风险传染病
## 3. 人员免疫状态评估
- 结合人员年龄、性别、疫苗接种史评估群体免疫水平
- 识别免疫缺口
## 4. 推荐疫苗接种方案
- 按优先级排列推荐接种的疫苗种类
- 说明每项疫苗的推荐理由（结合当地流行情况和人员特点）
- 给出建议接种率目标
## 5. 接种时间安排建议
- 根据任务时间倒推接种窗口
- 多剂次疫苗的接种排程
## 6. 其他防护措施建议
- 除疫苗接种外的健康防护建议

请基于数据给出专业的疫苗接种策略建议，确保建议具有可操作性。不要编造不存在的数据。"""


def _calc_weighted_rate(rows: list[DataPoint]) -> tuple[float, int]:
    """计算加权阳性率"""
    sp_rows = [r for r in rows if r.data_type == "seroprevalence" and r.sample_size and r.value is not None]
    if not sp_rows:
        return 0.0, 0
    total_sample = sum(r.sample_size for r in sp_rows)
    weighted_sum = sum(r.value * r.sample_size for r in sp_rows)
    return round(weighted_sum / total_sample, 2), total_sample


async def _resolve_model_name(db: AsyncSession, model: Optional[str] = None) -> str:
    """解析模型显示名称"""
    if not model:
        return settings.LLM_MODEL
    try:
        uid = UUID(model)
        result = await db.execute(select(ApiModelConfig).where(ApiModelConfig.id == uid))
        config = result.scalar_one_or_none()
        if config:
            return f"{config.name} ({config.model_name})"
    except (ValueError, AttributeError):
        pass
    return model


DEFAULT_TEMPLATES = [
    {
        "name": "抗体水平分析报告（默认）",
        "report_type": "antibody_analysis",
        "is_default": True,
        "desc": "含数据概况、时间/地区/年龄分析、总体概况与免疫学建议的标准抗体分析报告。",
        "sections": [
            {"title": "数据概览", "type": "kpi", "order": 0, "kpi": ["literature_count", "point_count", "province_count", "total_samples", "weighted_rate"]},
            {"title": "总体概况", "type": "text", "order": 1, "content_template": "请基于数据概况与分省/分年/分年龄摘要，撰写报告《总体概况》章节，给出整体抗体水平的判断与解读。"},
            {"title": "时间趋势分析", "type": "chart", "order": 2, "analysis": "trend"},
            {"title": "地区分布分析", "type": "chart", "order": 3, "analysis": "region"},
            {"title": "年龄分布特征", "type": "chart", "order": 4, "analysis": "age_curve"},
            {"title": "免疫学参考意见", "type": "text", "order": 5, "content_template": "请基于以上数据撰写《免疫学参考意见》章节，给出专业的免疫学分析与防控/接种建议，不要编造不存在的数据。"},
        ],
    },
    {
        "name": "疫苗接种策略报告（默认）",
        "report_type": "vaccination_strategy",
        "is_default": True,
        "desc": "含任务概况、疾病流行现状、年龄分布与接种方案建议的策略研判报告。",
        "sections": [
            {"title": "任务与数据概况", "type": "kpi", "order": 0, "kpi": ["literature_count", "point_count", "province_count", "weighted_rate"]},
            {"title": "传染病风险评估", "type": "text", "order": 1, "content_template": "请结合任务类型、时间、地点与当地传染病流行数据，撰写《传染病风险评估》章节，识别高风险传染病。"},
            {"title": "疾病流行现状分析", "type": "chart", "order": 2, "analysis": "disease"},
            {"title": "人群年龄分布特征", "type": "chart", "order": 3, "analysis": "age_curve"},
            {"title": "推荐疫苗接种方案", "type": "text", "order": 4, "content_template": "请基于当地流行情况与人员特点，撰写《推荐疫苗接种方案》章节，按优先级给出可操作性建议。"},
        ],
    },
]


# ===================== 报告模板相关 =====================


async def list_templates(db: AsyncSession, report_type: Optional[str] = None) -> list[dict]:
    """列出报告模板"""
    query = select(ReportTemplate)
    if report_type:
        query = query.where(ReportTemplate.report_type == report_type)
    templates = (await db.execute(query)).scalars().all()
    return [
        {
            "id": str(t.id),
            "name": t.name,
            "report_type": t.report_type,
            "sections": t.sections or [],
            "is_default": t.is_default,
            "desc": t.desc,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "updated_at": t.updated_at.isoformat() if t.updated_at else None,
        }
        for t in templates
    ]


async def get_template_by_id(db: AsyncSession, template_id: str) -> Optional[ReportTemplate]:
    from uuid import UUID
    try:
        uid = UUID(template_id)
    except (ValueError, AttributeError):
        return None
    return (await db.execute(select(ReportTemplate).where(ReportTemplate.id == uid))).scalar_one_or_none()


async def get_default_template(db: AsyncSession, report_type: str) -> Optional[ReportTemplate]:
    """获取指定类型的默认模板（优先 is_default，否则取首个）"""
    t = (await db.execute(
        select(ReportTemplate)
        .where(ReportTemplate.report_type == report_type, ReportTemplate.is_default.is_(True))
        .limit(1)
    )).scalar_one_or_none()
    if t:
        return t
    return (await db.execute(
        select(ReportTemplate).where(ReportTemplate.report_type == report_type).limit(1)
    )).scalar_one_or_none()


async def seed_default_templates(db: AsyncSession) -> int:
    """若库中无任何模板，写入内置默认模板。返回写入数量。"""
    existing = (await db.execute(select(ReportTemplate).limit(1))).scalar_one_or_none()
    if existing:
        return 0
    count = 0
    for data in DEFAULT_TEMPLATES:
        db.add(ReportTemplate(**data))
        count += 1
    await db.commit()
    return count


async def create_template(
    db: AsyncSession,
    name: str,
    report_type: str,
    sections: list,
    is_default: bool = False,
    desc: Optional[str] = None,
) -> dict:
    if report_type not in ("antibody_analysis", "vaccination_strategy"):
        raise ValueError("report_type 必须是 antibody_analysis 或 vaccination_strategy")
    # 确保 sections 有序且含必要字段
    for i, s in enumerate(sections):
        if "title" not in s or "type" not in s:
            raise ValueError("每个章节必须包含 title 和 type")
        s.setdefault("order", i)
        s.setdefault("content_template", "")
    if is_default:
        # 同类型取消原默认标记
        await db.execute(
            _update_defaults_stmt(report_type)
        )
    t = ReportTemplate(name=name, report_type=report_type, sections=sections, is_default=is_default, desc=desc)
    db.add(t)
    await db.commit()
    await db.refresh(t)
    return _template_to_dict(t)


async def update_template(
    db: AsyncSession,
    template_id: str,
    name: Optional[str] = None,
    sections: Optional[list] = None,
    is_default: Optional[bool] = None,
    desc: Optional[str] = None,
) -> Optional[dict]:
    t = await get_template_by_id(db, template_id)
    if not t:
        return None
    if name is not None:
        t.name = name
    if sections is not None:
        for i, s in enumerate(sections):
            s.setdefault("order", i)
            s.setdefault("content_template", "")
        t.sections = sections
    if desc is not None:
        t.desc = desc
    if is_default is not None:
        if is_default:
            await db.execute(_update_defaults_stmt(t.report_type))
        t.is_default = is_default
    t.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(t)
    return _template_to_dict(t)


async def delete_template(db: AsyncSession, template_id: str) -> bool:
    from sqlalchemy import delete
    result = await db.execute(delete(ReportTemplate).where(ReportTemplate.id == UUID(template_id)))
    await db.commit()
    return result.rowcount > 0


def _update_defaults_stmt(report_type: str):
    from sqlalchemy import update
    return update(ReportTemplate).where(
        ReportTemplate.report_type == report_type, ReportTemplate.is_default.is_(True)
    ).values(is_default=False)


def _template_to_dict(t: ReportTemplate) -> dict:
    return {
        "id": str(t.id),
        "name": t.name,
        "report_type": t.report_type,
        "sections": t.sections or [],
        "is_default": t.is_default,
        "desc": t.desc,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
    }


# ===================== 模板章节渲染 =====================


def _build_context(rows: list, disease: Optional[str] = None, language: str = "zh") -> dict:
    """从审核通过数据点构建统一上下文，供各类型章节渲染使用。"""
    import ast

    lit_ids = set(str(r.literature_id) for r in rows if r.literature_id)
    provinces_set = set()
    for r in rows:
        for p in (r.province or "").split(";"):
            p = p.strip()
            if p:
                provinces_set.add(p)
    total_sample = sum(r.sample_size or 0 for r in rows)
    overall_rate = _calc_weighted_rate(rows)[0]

    # 分省
    province_map: dict = {}
    for r in rows:
        for p in (r.province or "").split(";"):
            p = p.strip() or "未知"
            province_map.setdefault(p, []).append(r)
    province_rows = []
    for p, group in sorted(province_map.items()):
        wpr, ps = _calc_weighted_rate(group)
        province_rows.append((p, wpr, ps, len(group)))
    province_rows.sort(key=lambda x: -x[1])

    # 分年
    year_map: dict = {}
    for r in rows:
        if r.collection_year is not None:
            year_map.setdefault(r.collection_year, []).append(r)
    year_rows = []
    for y in sorted(year_map.keys()):
        group = year_map[y]
        wpr, ps = _calc_weighted_rate(group)
        year_rows.append((y, wpr, ps, len(group)))

    # 分年龄
    age_labels = AGE_GROUPS if language == "zh" else AGE_GROUPS_EN
    age_map: dict = {}
    for r in rows:
        matched = False
        for label, lo, hi in age_labels:
            if r.age_min is not None and r.age_max is not None and r.age_min >= lo and r.age_max <= hi:
                age_map.setdefault(label, []).append(r)
                matched = True
                break
        if not matched:
            other_label = "其他" if language == "zh" else "Other"
            age_map.setdefault(other_label, []).append(r)
    age_rows = []
    for label, _lo, _hi in age_labels:
        group = age_map.get(label, [])
        if group:
            wpr, ps = _calc_weighted_rate(group)
            age_rows.append((label, wpr, ps))
    other_label = "其他" if language == "zh" else "Other"
    if age_map.get(other_label):
        group = age_map[other_label]
        wpr, ps = _calc_weighted_rate(group)
        age_rows.append((other_label, wpr, ps))

    # 分疾病（疫苗接种策略场景）
    disease_map: dict = {}
    for r in rows:
        key = r.disease or "未知"
        disease_map.setdefault(key, []).append(r)
    disease_rows = []
    for key, group in disease_map.items():
        wpr, ps = _calc_weighted_rate(group)
        gmc_rows = [r for r in group if r.data_type == "gmc" and r.value is not None]
        avg_gmc = round(sum(r.value for r in gmc_rows) / len(gmc_rows), 2) if gmc_rows else None
        disease_rows.append((DISEASE_NAMES.get(key, key), wpr, ps, len(group), avg_gmc))
    disease_rows.sort(key=lambda x: -x[1])

    disease_name = ""
    if disease:
        disease_name = DISEASE_NAMES.get(disease, disease)
    else:
        top = disease_rows[0][0] if disease_rows else "未知疾病"

    return {
        "disease_name": disease,
        "language": language,
        "literature_count": len(lit_ids),
        "point_count": len(rows),
        "province_count": len(provinces_set),
        "total_samples": total_sample,
        "weighted_rate": overall_rate,
        "province_rows": province_rows,
        "year_rows": year_rows,
        "age_rows": age_rows,
        "disease_rows": disease_rows,
    }


def _fmt_rate(v) -> str:
    return f"{v}%" if v is not None else "-"


def _render_kpi(section: dict, ctx: dict) -> str:
    keys = section.get("kpi") or []
    labels = {
        "literature_count": ("文献数", lambda c: str(c)),
        "point_count": ("数据点", lambda c: str(c)),
        "province_count": ("覆盖省份", lambda c: str(c)),
        "total_samples": ("样本量", lambda c: str(c)),
        "weighted_rate": ("加权阳性率", lambda c: _fmt_rate(c)),
    }
    lines = []
    for k in keys:
        if k not in labels or k not in ctx:
            continue
        label, fmt = labels[k]
        lines.append(f"  - **{label}**：{fmt(ctx[k])}")
    if not lines:
        return "暂无关键指标数据。"
    return "\n".join(lines)


def _render_table(section: dict, ctx: dict) -> str:
    data = section.get("data", "province")
    if data == "year":
        rows, headers = ctx["year_rows"], ("年份", "加权阳性率", "样本量", "数据点")
    elif data == "age":
        rows, headers = ctx["age_rows"], ("年龄段", "加权阳性率", "样本量")
    elif data == "disease":
        rows, headers = ctx["disease_rows"], ("疾病", "加权阳性率", "样本量", "数据点", "GMC")
    else:
        rows, headers = ctx["province_rows"], ("省份", "加权阳性率", "样本量", "数据点")

    if not rows:
        return "暂无该维度数据。"

    def _cell(v):
        return "-" if v is None else str(v)

    body = "\n".join(
        "| " + " | ".join(_cell(c if i == 0 else (round(c, 2) if isinstance(c, float) else c)) if i == 0 else _cell(c) for i, c in enumerate(r)) + " |"
        for r in rows
    )
    header = "| " + " | ".join(headers) + " |"
    sep = "| " + " | ".join(["---"] * len(headers)) + " |"
    return f"{header}\n{sep}\n{body}"


def _render_chart(section: dict, ctx: dict) -> str:
    analysis = section.get("analysis", "trend")
    if analysis == "region":
        rows = ctx["province_rows"]
        title = "地区分布"
        if not rows:
            return "暂无地区分布数据。"
        rates = [r[1] for r in rows if r[1] is not None]
        note = f"共覆盖 {len(rows)} 个省份/地区"
        if rates:
            note += f"，加权阳性率区间 {min(rates)}% ~ {max(rates)}%"
        note += "。"
        return f"根据地区分布数据：{note}\n\n" + _render_table({**section, "data": "province"}, ctx)
    if analysis == "age_curve":
        rows = ctx["age_rows"]
        if not rows:
            return "暂无年龄分布数据。"
        rates = [r[1] for r in rows if r[1] is not None]
        note = f"共 {len(rows)} 个年龄段"
        if rates:
            note += f"，加权阳性率区间 {min(rates)}% ~ {max(rates)}%"
        note += "。"
        return f"根据年龄分布数据：{note}\n\n" + _render_table({**section, "data": "age"}, ctx)
    if analysis == "disease":
        rows = ctx["disease_rows"]
        if not rows:
            return "暂无疾病流行数据。"
        rates = [r[1] for r in rows if r[1] is not None]
        note = f"共 {len(rows)} 类疾病"
        if rates:
            note += f"，加权阳性率区间 {min(rates)}% ~ {max(rates)}%"
        note += "。"
        return f"根据疾病流行数据：{note}\n\n" + _render_table({**section, "data": "disease"}, ctx)
    # 默认 trend
    rows = ctx["year_rows"]
    if not rows:
        return "暂无年份趋势数据。"
    rates = [r[1] for r in rows if r[1] is not None]
    note = f"共 {len(rows)} 个年份"
    if rates:
        note += f"，加权阳性率区间 {min(rates)}% ~ {max(rates)}%"
    note += "。"
    return f"根据年份趋势数据：{note}\n\n" + _render_table({**section, "data": "year"}, ctx)


def _context_text(ctx: dict) -> str:
    """把上下文汇总为纯文本，供 LLM 章节提示使用。"""
    lines = [
        f"- 数据来源：{ctx['literature_count']} 篇文献，{ctx['point_count']} 个数据点",
        f"- 覆盖省份：{ctx['province_count']} 个；总样本量：{ctx['total_samples']} 人；加权阳性率：{_fmt_rate(ctx['weighted_rate'])}",
    ]
    lines.append("\n分省：")
    lines += [f"  - {p}：阳性率 {wpr}%，样本量 {ps}，数据点 {n} 个" for p, wpr, ps, n in ctx["province_rows"]]
    if ctx["year_rows"]:
        lines.append("\n分年：")
        lines += [f"  - {y}年：阳性率 {wpr}%，样本量 {ps}" for y, wpr, ps, _ in ctx["year_rows"]]
    if ctx["age_rows"]:
        lines.append("\n分年龄：")
        lines += [f"  - {label}：阳性率 {wpr}%，样本量 {ps}" for label, wpr, ps in ctx["age_rows"]]
    if ctx["disease_rows"] and len(ctx["disease_rows"]) > 1:
        lines.append("\n分疾病：")
        lines += [f"  - {name}：阳性率 {wpr}%，样本量 {ps}，数据点 {n} 个" for name, wpr, ps, n, _ in ctx["disease_rows"]]
    return "\n".join(lines)


async def _render_template_report(
    db: AsyncSession,
    ctx: dict,
    template: ReportTemplate,
    model: Optional[str],
    language: str,
) -> str:
    """按模板 sections 顺序渲染报告 Markdown。"""
    blocks = []
    context_text = _context_text(ctx)
    sections = sorted(template.sections or [], key=lambda s: s.get("order", 0))
    for s in sections:
        stype = s.get("type", "text")
        title = s.get("title", "章节")
        if stype == "kpi":
            body = _render_kpi(s, ctx)
        elif stype == "table":
            body = _render_table(s, ctx)
        elif stype == "chart":
            body = _render_chart(s, ctx)
        else:  # text
            instruction = s.get("content_template") or "请基于以下数据撰写本章节的分析内容。"
            prompt = (
                f"你是一位流行病学专家。请撰写报告章节《{title}》。\n"
                f"章节要求：{instruction}\n\n"
                f"可用数据：\n{context_text}\n\n"
                f"请直接输出该章节的正文内容（Markdown），不要输出章节标题，不要编造不存在的数据。"
            )
            body = await _call_llm(db, prompt, model=model)
        blocks.append(f"## {title}\n\n{body.strip()}")
    return "\n\n".join(blocks)


def _build_legacy_inline_text(rows: list, language: str = "zh") -> tuple[str, str, str]:
    """按内置 Prompt 所需的文本格式，构建分省/分年/分年龄摘要（兜底路径）。"""
    province_lines = []
    province_map: dict[str, list[DataPoint]] = {}
    for r in rows:
        for p in (r.province or "").split(";"):
            p = p.strip() or "未知"
            province_map.setdefault(p, []).append(r)
    for prov, group in sorted(province_map.items()):
        wpr, ps = _calc_weighted_rate(group)
        province_lines.append(f"- {prov}：阳性率 {wpr}%，样本量 {ps}，数据点 {len(group)} 个")
    province_table = "\n".join(province_lines) if province_lines else "暂无数据"

    year_map: dict[int, list[DataPoint]] = {}
    for r in rows:
        y = r.collection_year
        if y is None:
            continue
        year_map.setdefault(y, []).append(r)
    year_lines = []
    for year in sorted(year_map.keys()):
        group = year_map[year]
        wpr, ps = _calc_weighted_rate(group)
        year_lines.append(f"- {year}年：阳性率 {wpr}%，样本量 {ps}，数据点 {len(group)} 个")
    year_trend = "\n".join(year_lines) if year_lines else "暂无数据"

    age_labels = AGE_GROUPS if language == "zh" else AGE_GROUPS_EN
    age_map: dict[str, list[DataPoint]] = {label: [] for label, _, _ in age_labels}
    other_label = "其他" if language == "zh" else "Other"
    age_map.setdefault(other_label, [])
    for r in rows:
        matched = False
        for label, lo, hi in age_labels:
            if r.age_min is not None and r.age_max is not None and r.age_min >= lo and r.age_max <= hi:
                age_map[label].append(r)
                matched = True
                break
        if not matched:
            age_map[other_label].append(r)
    age_lines = []
    for label, _lo, _hi in age_labels:
        group = age_map.get(label, [])
        if group:
            wpr, ps = _calc_weighted_rate(group)
            age_lines.append(f"- {label}：阳性率 {wpr}%，样本量 {ps}")
    if age_map.get(other_label):
        group = age_map[other_label]
        wpr, ps = _calc_weighted_rate(group)
        age_lines.append(f"- {other_label}：阳性率 {wpr}%，样本量 {ps}")
    age_distribution = "\n".join(age_lines) if age_lines else "暂无数据"

    return province_table, year_trend, age_distribution


async def generate_report(
    db: AsyncSession,
    disease: Optional[str] = None,
    province: Optional[str] = None,
    data_type: Optional[str] = None,
    language: str = "zh",
    title: Optional[str] = None,
    model: Optional[str] = None,
    template_id: Optional[str] = None,
) -> dict:
    """生成报告。

    若提供 template_id，则按模板的 sections 顺序渲染（支持 text/chart/table/kpi 章节）；
    否则使用内置默认 Prompt 结构生成。
    """
    # 0. 解析模板（template_id 缺省时使用抗体分析默认模板）
    template = None
    if template_id:
        template = await get_template_by_id(db, template_id)
        if not template:
            raise ValueError("指定的报告模板不存在")
    else:
        template = await get_default_template(db, "antibody_analysis")

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

    # 2. 生成疾病名称与报告标题
    disease_name = DISEASE_NAMES.get(disease or "", disease or "未知疾病")

    if title:
        report_title = title
        report_title_en = title
    else:
        report_title = f"{disease_name}抗体水平分析报告"
        report_title_en = f"{disease_name} Antibody Level Analysis Report"

    # 8. 生成正文：template_id 走模板渲染，否则走内置 Prompt
    if template:
        ctx = _build_context(rows, disease=disease, language=language)
        content = await _render_template_report(db, ctx, template, model=model, language=language)
    else:
        content = None

    if content is None:
        # 使用内置 Prompt（无可用模板时的兜底路径）
        lit_ids = set(str(r.literature_id) for r in rows if r.literature_id)
        provinces_set = set()
        for r in rows:
            for p in (r.province or "").split(";"):
                p = p.strip()
                if p:
                    provinces_set.add(p)
        total_sample = sum(r.sample_size or 0 for r in rows)
        province_table, year_trend, age_distribution = _build_legacy_inline_text(rows, language)
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
        content = await _call_llm(db, prompt, model=model)

    # 8.5 方法学小节：统一脚注（复用 build_methodology_note），拼接进报告正文
    lit_ids = set(str(r.literature_id) for r in rows if r.literature_id)
    methodology_note = build_methodology_note(
        "report",
        {"disease": disease, "province": province, "data_type": data_type},
        {"n_estimates": len(rows), "n_literatures": len(lit_ids), "quality_grades": True},
    )
    content = (content or "").rstrip()
    if language == "zh":
        content += f"\n\n## 方法学\n\n{methodology_note}"
        content += (
            f"\n\n## 引用\n\n"
            f"抗体地图数据库分析报告[EB/OL]. 抗体地图数据库（版本 v1.0）. "
            f"数据截至：{date.today().isoformat()}；[引用日期 {date.today().isoformat()}]. "
            f"报告编号：{disease_name}_{province or '全国'}_{date.today().isoformat()}。"
        )
    else:
        content += f"\n\n## Methodology\n\n{methodology_note}"
        content += (
            f"\n\n## Citation\n\n"
            f"Antibody Map Database Analysis Report[EB/OL]. Antibody Map Database (Version v1.0). "
            f"Data as of: {date.today().isoformat()}; [Accessed {date.today().isoformat()}]. "
            f"Report ID: {disease_name}_{province or 'National'}_{date.today().isoformat()}."
        )

    # 解析模型显示名称
    llm_model_name = await _resolve_model_name(db, model)

    # 9. Save to database
    try:
        report = Report(
            title=report_title,
            content=content,
            report_type="antibody_analysis",
            disease=disease,
            province=province,
            data_type=data_type,
            language=language,
            literature_count=len(lit_ids),
            data_point_count=len(rows),
            llm_model=llm_model_name,
        )
        db.add(report)
        await db.commit()
    except Exception as e:
        logger.error(f"保存抗体分析报告失败: {e}；内容摘要: {content[:300]}")
        raise RuntimeError(f"报告生成成功但保存失败: {e}") from e

    return {
        "id": str(report.id),
        "title": report_title,
        "content": content,
        "report_type": "antibody_analysis",
        "literature_count": len(lit_ids),
        "data_point_count": len(rows),
        "language": language,
        "llm_model": report.llm_model,
        "generated_at": report.generated_at.isoformat(),
    }


async def generate_vaccination_strategy_report(
    db: AsyncSession,
    task_type: str,
    task_time: str,
    task_location: str,
    personnel_count: int,
    personnel_gender: str = "",
    personnel_age: str = "",
    personnel_vaccination_history: str = "",
    title: Optional[str] = None,
    template_id: Optional[str] = None,
) -> dict:
    """生成疫苗接种策略研判报告。template_id 缺省时使用内置 Prompt；指定时按模板 sections 渲染。"""
    # 1. 查询任务地点的传染病流行数据
    query = select(DataPoint).where(DataPoint.review_status == "approved")
    if task_location:
        query = query.where(DataPoint.province.ilike(f"%{task_location}%"))

    result = await db.execute(query)
    rows = list(result.scalars().all())

    # 2. 构建疫情数据汇总
    epidemic_lines = []
    if rows:
        lit_ids = set(str(r.literature_id) for r in rows if r.literature_id)
        epidemic_lines.append(f"- 数据来源：{len(lit_ids)} 篇文献，{len(rows)} 个数据点")

        # 按疾病汇总
        disease_map: dict[str, list[DataPoint]] = {}
        for r in rows:
            d = r.disease or "未知"
            if d not in disease_map:
                disease_map[d] = []
            disease_map[d].append(r)

        epidemic_lines.append("\n各疾病流行情况：")
        for disease_key, group in disease_map.items():
            disease_name = DISEASE_NAMES.get(disease_key, disease_key)
            wpr, ps = _calc_weighted_rate(group)
            gmc_rows = [r for r in group if r.data_type == "gmc" and r.value is not None]
            avg_gmc = round(sum(r.value for r in gmc_rows) / len(gmc_rows), 2) if gmc_rows else None
            epidemic_lines.append(
                f"  - {disease_name}：加权阳性率 {wpr}%（样本量 {ps}）"
                + (f"，GMC {avg_gmc}" if avg_gmc else "")
                + f"，数据点 {len(group)} 个"
            )

        # 按年份汇总
        year_map: dict[int, list[DataPoint]] = {}
        for r in rows:
            y = r.collection_year
            if y is None:
                continue
            if y not in year_map:
                year_map[y] = []
            year_map[y].append(r)

        if year_map:
            epidemic_lines.append("\n年份趋势：")
            for year in sorted(year_map.keys(), reverse=True)[:5]:
                group = year_map[year]
                wpr, ps = _calc_weighted_rate(group)
                epidemic_lines.append(f"  - {year}年：阳性率 {wpr}%，样本量 {ps}，数据点 {len(group)} 个")

        # 按年龄汇总
        age_map: dict[str, list[DataPoint]] = {}
        for r in rows:
            matched = False
            for label, lo, hi in AGE_GROUPS:
                if r.age_min is not None and r.age_max is not None:
                    if r.age_min >= lo and r.age_max <= hi:
                        if label not in age_map:
                            age_map[label] = []
                        age_map[label].append(r)
                        matched = True
                        break
            if not matched:
                if "其他" not in age_map:
                    age_map["其他"] = []
                age_map["其他"].append(r)

        if age_map:
            epidemic_lines.append("\n年龄分布：")
            for label in age_map:
                group = age_map[label]
                wpr, ps = _calc_weighted_rate(group)
                epidemic_lines.append(f"  - {label}：阳性率 {wpr}%，样本量 {ps}")
    else:
        epidemic_lines.append("暂无该地区的传染病流行病学数据。")

    epidemic_data = "\n".join(epidemic_lines)

    # 3. 报告标题
    if title:
        report_title = title
    else:
        report_title = f"{task_location}任务人员疫苗接种策略研判报告"

    # 3.5 若指定模板，按模板 sections 渲染
    template = None
    if template_id:
        template = await get_template_by_id(db, template_id)
        if not template:
            raise ValueError("指定的报告模板不存在")

    # 4. 构建 Prompt 或渲染模板
    if template:
        ctx = _build_context(rows, language="zh")
        ctx["task_info"] = (
            f"任务类型：{task_type}；任务时间：{task_time}；任务地点：{task_location}；"
            f"人员人数：{personnel_count}人；年龄范围：{personnel_age or '未提供'}；"
            f"疫苗接种史：{personnel_vaccination_history or '未提供'}"
        )
        content = await _render_template_report(db, ctx, template, model=None, language="zh")
    else:
        prompt = VACCINATION_STRATEGY_PROMPT_ZH.format(
            task_type=task_type,
            task_time=task_time,
            task_location=task_location,
            personnel_count=personnel_count,
            personnel_gender=personnel_gender or "未提供",
            personnel_age=personnel_age or "未提供",
            personnel_vaccination_history=personnel_vaccination_history or "未提供",
            epidemic_data=epidemic_data,
        )
        content = await _call_llm(db, prompt)

    # 5. Save to database
    try:
        report = Report(
            title=report_title,
            content=content,
            report_type="vaccination_strategy",
            task_type=task_type,
            task_time=task_time,
            task_location=task_location,
            personnel_count=personnel_count,
            personnel_gender=personnel_gender or None,
            personnel_age=personnel_age or None,
            personnel_vaccination_history=personnel_vaccination_history or None,
            data_point_count=len(rows),
            literature_count=len(set(str(r.literature_id) for r in rows if r.literature_id)),
        )
        db.add(report)
        await db.commit()
    except Exception as e:
        logger.error(f"保存疫苗接种策略报告失败: {e}；内容摘要: {content[:300]}")
        raise RuntimeError(f"报告生成成功但保存失败: {e}") from e

    return {
        "id": str(report.id),
        "title": report_title,
        "content": content,
        "report_type": "vaccination_strategy",
        "task_type": task_type,
        "task_time": task_time,
        "task_location": task_location,
        "personnel_count": personnel_count,
        "personnel_gender": personnel_gender,
        "personnel_age": personnel_age,
        "personnel_vaccination_history": personnel_vaccination_history,
        "data_point_count": len(rows),
        "literature_count": len(set(str(r.literature_id) for r in rows if r.literature_id)),
        "language": "zh",
        "generated_at": report.generated_at.isoformat(),
    }


async def _call_llm(db: AsyncSession, prompt: str, model: Optional[str] = None) -> str:
    """调用 LLM 生成报告"""
    llm_model = model or settings.LLM_MODEL
    api_key = settings.LLM_API_KEY
    base_url = settings.LLM_BASE_URL

    # 如果 model 是远程模型配置的 UUID，查找对应的 API 配置
    if model:
        try:
            uid = UUID(model)
            result = await db.execute(select(ApiModelConfig).where(ApiModelConfig.id == uid))
            config = result.scalar_one_or_none()
            if config:
                llm_model = config.model_name
                api_key = config.api_key
                base_url = config.base_url
        except (ValueError, AttributeError):
            # 不是 UUID，当作普通模型名直接使用
            pass

    client = AsyncOpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=settings.LLM_REQUEST_TIMEOUT,
    )
    try:
        extra_kwargs = {}
        # 本地 Ollama 模型：禁用 thinking 模式
        if ":" in llm_model or llm_model.startswith("qwen"):
            extra_kwargs["extra_body"] = {"think": False}
        response = await client.chat.completions.create(
            model=llm_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            timeout=settings.LLM_REQUEST_TIMEOUT,
            **extra_kwargs,
        )
        return response.choices[0].message.content or ""
    except Exception as e:
        logger.warning(f"LLM API 调用失败 (model={llm_model}): {e}", exc_info=True)
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
            "report_type": r.report_type,
            "disease": r.disease,
            "province": r.province,
            "data_type": r.data_type,
            "language": r.language,
            "llm_model": r.llm_model,
            "literature_count": r.literature_count,
            "data_point_count": r.data_point_count,
            "task_type": r.task_type,
            "task_time": r.task_time,
            "task_location": r.task_location,
            "personnel_count": r.personnel_count,
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
        "report_type": r.report_type,
        "disease": r.disease,
        "province": r.province,
        "data_type": r.data_type,
        "language": r.language,
        "llm_model": r.llm_model,
        "literature_count": r.literature_count,
        "data_point_count": r.data_point_count,
        "task_type": r.task_type,
        "task_time": r.task_time,
        "task_location": r.task_location,
        "personnel_count": r.personnel_count,
        "personnel_gender": r.personnel_gender,
        "personnel_age": r.personnel_age,
        "personnel_vaccination_history": r.personnel_vaccination_history,
        "generated_at": r.generated_at.isoformat(),
    }


async def update_report(
    db: AsyncSession,
    report_id: str,
    title: Optional[str] = None,
    content: Optional[str] = None,
) -> Optional[dict]:
    """更新报告标题或内容"""
    from uuid import UUID
    from sqlalchemy import update
    from datetime import datetime, timezone

    uid = UUID(report_id)
    values = {}
    if title is not None:
        values["title"] = title
    if content is not None:
        values["content"] = content
    if not values:
        return await get_report_by_id(db, report_id)

    values["generated_at"] = datetime.now(timezone.utc)
    stmt = update(Report).where(Report.id == uid).values(**values)
    await db.execute(stmt)
    await db.commit()

    return await get_report_by_id(db, report_id)


async def delete_report(db: AsyncSession, report_id: str) -> bool:
    """删除报告"""
    from uuid import UUID
    from sqlalchemy import delete

    uid = UUID(report_id)
    result = await db.execute(delete(Report).where(Report.id == uid))
    await db.commit()
    return result.rowcount > 0

