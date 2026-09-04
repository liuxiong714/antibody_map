"""知识图谱咨询问答引擎。

混合方案（方案 C）：
1. 模板匹配：6 类高频问题用正则解析 → 结构化查询 → 模板化答案
2. LLM 降级：未匹配问题调用 LLM，结合 KG 上下文生成自然语言答案
"""

import contextlib
import logging
import re
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.data_point import DataPoint
from app.models.kg_entity import KGEntity
from app.models.kg_triple import KGTriple
from app.models.literature import Literature
from app.ontology import ENTITY_LABELS, EntityType

logger = logging.getLogger("kg_qa")

# ===== 问句模板定义 =====

class QATemplate:
    """单条问答模板：匹配模式 → 查询逻辑 → 答案格式化"""

    def __init__(self, name: str, patterns: list[str], priority: int = 0):
        self.name = name
        self.patterns = [re.compile(p, re.IGNORECASE) for p in patterns]
        self.priority = priority

    def match(self, question: str) -> dict[str, str] | None:
        for pat in self.patterns:
            m = pat.search(question)
            if m:
                return m.groupdict()
        return None


# 已知省级行政区名称，用于 province 槽位精确匹配，避免贪婪正则吞掉疾病名
PROVINCES = (
    "北京", "上海", "天津", "重庆", "河北", "山西", "辽宁", "吉林", "黑龙江",
    "江苏", "浙江", "安徽", "福建", "江西", "山东", "河南", "湖北", "湖南",
    "广东", "海南", "四川", "贵州", "云南", "陕西", "甘肃", "青海", "台湾",
    "内蒙古", "广西", "西藏", "宁夏", "新疆", "香港", "澳门",
)
_PROV = "(?:" + "|".join(PROVINCES) + ")"
# 前缀省级行政区（用于剥离“北京市丰台”→“丰台”这类复合地点）
_PROV_RE = "(?:" + "|".join(PROVINCES) + ")"


def _disease_non_greedy() -> str:
    """疾病槽位：非贪婪匹配串，避免吞掉后置的阳性率等词。"""
    return r"[^\s,，。？?!]+?"


# 疫苗名称 → 病原体（疾病代码）：用于疫苗类问题回退到抗体阳性率数据
VACCINE_DISEASE = {
    "麻疹疫苗": "measles",
    "麻腮风": "measles",
    "麻风疫苗": "measles",
    "麻疹": "measles",
    "风疹疫苗": "rubella",
    "风疹": "rubella",
    "乙脑疫苗": "乙型脑炎",
    "乙脑": "乙型脑炎",
    "流脑疫苗": "meningitis",
    "乙肝疫苗": "hepatitis_b",
    "乙肝": "hepatitis_b",
    "流感疫苗": "influenza",
    "新冠疫苗": "covid19",
    "甲肝疫苗": "hepatitis_a",
    "百白破": "pertussis",
}


# 疾病中英文别名映射：库内 disease 存英文代码，提问常用中文，查询前需归一化
DISEASE_ALIASES = {
    "麻疹": "measles",
    "风疹": "rubella",
    "水痘": "varicella",
    "腮腺炎": "mumps",
    "乙型肝炎": "hepatitis_b",
    "乙肝": "hepatitis_b",
    "甲型肝炎": "hepatitis_a",
    "甲肝": "hepatitis_a",
    "丙型肝炎": "hepatitis_c",
    "丙肝": "hepatitis_c",
    "破伤风": "tetanus",
    "白喉": "diphtheria",
    "百日咳": "pertussis",
    "小儿麻痹": "polio",
    "脊髓灰质炎": "polio",
    "脊灰": "polio",
    "新冠": "covid19",
    "流感": "influenza",
    "脑膜炎": "meningitis",
    "手足口": "hfmd",
    "乙型脑炎": "乙型脑炎",
    "乙脑": "乙型脑炎",
}

# 已知疾病中文名（最长优先），用于“地区+疾病+阳性率”等模板识别疾病槽位
DISEASE_TERMS = "|".join(sorted(set(DISEASE_ALIASES.keys()), key=len, reverse=True))

# 常见人群/对象词（最长优先），避免“儿童麻疹抗体阳性率”被误判为地点=儿童
_POP_TERMS = (
    "儿童", "成人", "老年人", "青少年", "中小学生", "流动人口", "流动儿童",
    "医务人员", "医护人员", "婴幼儿", "新生儿", "学生", "孕妇", "老人",
    "青年", "中年", "幼儿", "婴儿", "产妇", "患者", "病例", "人群",
    "居民", "志愿者", "对象", "新兵", "流动",
)
_POP = "(?:" + "|".join(sorted(set(_POP_TERMS), key=len, reverse=True)) + ")"

# 地点槽位：省级行政区 或 非人群词的中文地名（市/区/县，2~6字）或 拉丁地名（支持“Bari”“Olmsted County”等）
_LOC = "(?:" + _PROV + "|(?!" + _POP + r")[\u4e00-\u9fa5]{2,6}?|[A-Za-z][A-Za-z .'\-]{1,40}?)"


# 预定义 6+ 类问答模板
TEMPLATES = [
    QATemplate(
        name="seroprevalence_query",
        patterns=[
            # 优先：地点（省/市/区县）+ 已知疾病名 + 阳性率，支持“丰台麻疹阳性率是什么”
            # “北京市丰台区麻疹阳性率”等复合地点也能正确解析出区县
            r"(?P<province>" + _LOC + r")(?:省|市|区|县|自治区|地区|州)?\s*(?P<year>\d{4})?\s*年?\s*(?P<disease>" + DISEASE_TERMS + r")\s*(?:抗体|IgG|IgM|表面抗原)?\s*(?:阳性率|seroprevalence)\s*(?:是多少|如何|怎样|什么水平|是什么|为多少|多少)?",
            r"(?P<province>" + _PROV + r")(?:省|市|区|自治区)?\s*(?P<year>\d{4})?\s*年?\s*(?P<disease>" + _disease_non_greedy() + r")\s*(?:抗体|IgG|IgM)?\s*(?:阳性率|seroprevalence)\s*(?:是多少|如何|怎样|什么水平)?",
            r"(?P<disease>" + _disease_non_greedy() + r")\s*(?:抗体)?\s*阳性率\s*(?:在|于)?\s*(?P<year>\d{4})?\s*年?\s*(?P<province>" + _PROV + r")(?:省|市|区|自治区)?",
            r"(?P<province>" + _PROV + r")(?:省|市|区|自治区)?\s*(?P<disease>" + _disease_non_greedy() + r")\s*(?:抗体|IgG|IgM)\s*阳性率",
            r"(?P<disease>" + _disease_non_greedy() + r")\s*(?:的|人群)?抗体\s*(?:阳性率|水平)\s*(?:如何|怎样|是多少)\??",
        ],
        priority=10,
    ),
    QATemplate(
        name="author_query",
        patterns=[
            # 地区+疾病+研究/调查/论文/文献(可多个连写)+作者：如“北京麻疹研究的作者都有谁”“丰台麻疹研究论文的作者是谁”
            r"(?P<province>" + _LOC + r")(?:省|市|区|县|自治区|地区|州)?\s*(?P<year>\d{4})?\s*年?\s*(?P<disease>" + DISEASE_TERMS + r")\s*(?:抗体|IgG|IgM)?\s*(?:(?:研究|调查|论文|文献|报告)\s*)+(?:的)?\s*(?:作者|作者都有谁|作者都是谁|有哪些作者|都有哪些作者|都有什么作者|作者是谁|作者是|主要作者|研究人员|研究者|通讯作者|都是谁|都有谁)",
            # 疾病+研究+在/于+地区+作者：如“麻疹研究在北京的作者都有谁”（“在/于”必须出现，防止把“论文”误当地点）
            r"(?P<disease>" + DISEASE_TERMS + r")\s*(?:抗体|IgG|IgM)?\s*(?:(?:研究|调查|论文|文献|报告)\s*)+(?:在|于)\s*(?P<province>" + _LOC + r")(?:省|市|区|县|自治区|地区|州)?\s*(?:的)?\s*(?:作者|作者都有谁|作者都是谁|有哪些作者|都有哪些作者|都有什么作者|作者是谁|作者是|主要作者|研究人员|研究者|通讯作者|都是谁|都有谁)",
            # 纯疾病+研究作者：如“麻疹研究的作者都有谁”
            r"(?P<disease>" + DISEASE_TERMS + r")\s*(?:抗体|IgG|IgM)?\s*(?:(?:研究|调查|论文|文献|报告)\s*)+(?:的)?\s*(?:作者|作者都有谁|作者都是谁|有哪些作者|都有哪些作者|都有什么作者|作者是谁|作者是|主要作者|研究人员|研究者|通讯作者|都是谁|都有谁)",
        ],
        priority=11,
    ),
    QATemplate(
        name="gmc_query",
        patterns=[
            r"(?P<province>" + _PROV + r")?(?:省|市|区|自治区)?\s*(?P<year>\d{4})?\s*年?\s*(?P<disease>" + _disease_non_greedy() + r")\s*(?:抗体\s*)?(?:GMC|几何平均滴度|GMT|几何平均)\s*(?:是多少|如何|怎样)?",
            r"(?P<disease>" + _disease_non_greedy() + r")\s*(?:GMC|几何平均滴度|GMT)\s*(?:在|于)?\s*(?P<province>" + _PROV + r")?(?:省|市|区|自治区)?",
        ],
        priority=10,
    ),
    QATemplate(
        name="comparison_query",
        patterns=[
            r"(?P<province1>" + _PROV + r")(?:省|市|区|自治区)?(?:和|与|、|,|，)(?P<province2>" + _PROV + r")(?:省|市|区|自治区)?\s*(?P<disease>" + _disease_non_greedy() + r")\s*(?:抗体|IgG|IgM)?\s*(?:阳性率|seroprevalence)\s*(?:对比|比较|谁高|哪个高)?",
            r"(?P<province1>" + _PROV + r")(?:省|市|区|自治区)?(?:与|和)(?P<province2>" + _PROV + r")(?:省|市|区|自治区)?\s*(?:的)?\s*(?P<disease>" + _disease_non_greedy() + r")\s*(?:抗体|阳性率|GMC)\s*(?:对比|比较|差异)",
        ],
        priority=8,
    ),
    QATemplate(
        name="institution_query",
        patterns=[
            r"(?P<institution>[^调查研]+)(?:大学|医院|研究所|疾控中心|CDC|中心)\s*(?:做过|进行|开展|完成)过?\s*(?:哪些|什么)\s*(?:调查|研究|监测)",
            r"(?P<institution>[^调查研]+)\s*(?:调查|研究|监测)了\s*(?:哪些|什么)\s*(?:疾病|病原体|项目)",
        ],
        priority=7,
    ),
    QATemplate(
        name="population_query",
        patterns=[
            r"(?P<population>儿童|成人|青少年|老年人|学生|孕妇|婴幼儿|新生儿|流动人口|医务|接种)\s*(?:的)?\s*(?P<disease>[^\s,，，]+)\s*(?:抗体\s*)?(?:阳性率|水平|GMC)",
            r"(?P<disease>[^\s,，，]+)\s*(?:抗体\s*)?(?:阳性率|水平)\s*(?:在|于)?\s*(?P<population>[^中]+)中",
            r"(?P<population>儿童|成人|青少年|老年人|孕妇|婴幼儿|中小学生)\s*(?:麻疹|乙肝|新冠|流感|腮腺炎)\s*(?:抗体\s*)?阳性率",
        ],
        priority=7,
    ),
    QATemplate(
        name="vaccine_query",
        patterns=[
            r"(?P<province>" + _PROV + r")?(?:省|市|区|自治区)?\s*(?P<vaccine>[^\s,，。]+疫苗)\s*(?:的|后|之后)?\s*(?:抗体\s*)?(?:保护效果|效果|保护率|免疫原性|阳性率|抗体水平)\s*(?:如何|怎样|是多少|高低)?",
            r"接种\s*(?P<vaccine>[^\s,，。]+疫苗)\s*(?:后|之后)?\s*(?:抗体|阳性率|保护效果|效果|保护率)(?:如何|怎样|是多少)?",
        ],
        priority=9,
    ),
    QATemplate(
        name="trend_query",
        patterns=[
            r"(?P<disease>" + _disease_non_greedy() + r")\s*(?:抗体\s*)?(?:阳性率|水平)\s*(?:变化|趋势|走势)\s*(?:在|于)?\s*(?P<province>" + _PROV + r")?",
            r"(?P<province>" + _PROV + r")(?:省|市|区|自治区)?\s*(?P<disease>" + _disease_non_greedy() + r")\s*(?:阳性率|抗体)\s*变化趋势",
            r"(?P<disease>" + _disease_non_greedy() + r")\s*(?:抗体\s*)?阳性率\s*(?:随时间|逐年)?\s*(?:变化|趋势)",
        ],
        priority=5,
    ),
    QATemplate(
        name="overview_query",
        patterns=[
            r"(?:关于|针对|涉及)?\s*(?P<disease>[^\s,，。]+)\s*(?:有哪些|什么)\s*(?:研究|调查|文献|数据)",
            r"(?P<disease>[^\s,，。]+)\s*(?:研究|调查)\s*(?:情况|概况|数据)如何?",
        ],
        priority=6,
    ),
    QATemplate(
        name="pathogen_query",
        patterns=[
            r"(?P<disease>[^\s,，，]+)\s*(?:关联|相关|有关)\s*(?:的)?\s*(?:哪些|什么)\s*(?:病原体|疾病|病毒|细菌)",
            r"哪些\s*(?:病原体|疾病|病毒|细菌)\s*(?:与|和)\s*(?P<disease>[^\s,，，]+)\s*(?:相关|关联|有关)",
        ],
        priority=5,
    ),
]


# ===== 查询执行器 =====

class QAQueryExecutor:
    """执行模板解析后的查询"""

    def __init__(self, db: AsyncSession):
        self.db = db
        # 是否纳入未审核数据点（来源标注由格式化器/答案处理）
        self.include_unreviewed = getattr(settings, "KG_QA_INCLUDE_UNREVIEWED", True)

    def _disease_terms(self, disease: str | None) -> list[str]:
        """将疾病槽位归一化为候选匹配串（中文→英文代码，去掉干扰后缀）。"""
        if not disease:
            return []
        d = disease.strip()
        terms = [d]
        # 去掉被贪婪正则误吞的“抗体”等后缀，如“麻疹抗体”→“麻疹”
        for suf in ("抗体", "免疫球蛋白", "igg", "igm"):
            if d.lower().endswith(suf) and len(d) > len(suf):
                terms.append(d[: -len(suf)])
        for zh, code in DISEASE_ALIASES.items():
            if zh in d:
                terms.append(code)
        # 去重保序
        return list(dict.fromkeys(terms))

    def _disease_cond(self, disease: str | None):
        terms = self._disease_terms(disease)
        if not terms:
            return None
        return or_(*[func.lower(DataPoint.disease).contains(t.lower()) for t in terms])

    def _review_cond(self):
        """审核过滤条件。纳入未审核时不加限制（数据更多，但结果标注来源）。"""
        if self.include_unreviewed:
            return None
        return DataPoint.review_status == "approved"

    def _province_cond(self, province: str | None):
        """地区匹配：同时匹配 province/city/region 三字段，兼容省/市/区尾缀与部分匹配，
        使“丰台”“丰台区”能命中 city 字段存储的区县数据；“全国”不限地区。"""
        if not province or not province.strip():
            return None
        p = province.strip()
        if p in ("全国", "中国", "全国范围"):
            return None
        base = re.sub(r"(省|市|自治区|特别行政区|地区|州|区|县)$", "", p).strip()
        # 剥离前缀省级行政区：处理“北京市丰台(区)”这类复合地点 → “丰台”
        stripped = re.sub(r"^" + _PROV_RE + r"(省|市|自治区|特别行政区)?", "", base).strip()
        if stripped:
            base = stripped
        conds = []
        for field in (DataPoint.province, DataPoint.city, DataPoint.region):
            if base:
                conds.append(field == base)
            conds.append(field == p)
            conds.append(func.lower(field).like(f"%{p.lower()}%"))
            if base and base != p:
                conds.append(func.lower(field).like(f"%{base.lower()}%"))
        return or_(*conds)

    def _year_cond(self, year: str | None):
        if not year:
            return None
        try:
            y = int(year)
        except (TypeError, ValueError):
            return None
        return DataPoint.collection_year == y

    async def query_seroprevalence(
        self, disease: str, province: str | None = None,
        population: str | None = None, year: str | None = None,
    ) -> list[dict]:
        """查询抗体阳性率数据"""
        stmt = select(
            DataPoint.disease, DataPoint.province, DataPoint.city,
            DataPoint.population,
            DataPoint.value, DataPoint.ci_lower, DataPoint.ci_upper,
            DataPoint.sample_size, DataPoint.collection_year,
            DataPoint.unit, DataPoint.data_type, DataPoint.method,
            DataPoint.age_group, DataPoint.literature_id, DataPoint.review_status,
        ).where(
            DataPoint.data_type == "seroprevalence",
            self._disease_cond(disease),
        )
        rc = self._review_cond()
        if rc is not None:
            stmt = stmt.where(rc)
        pc = self._province_cond(province)
        if pc is not None:
            stmt = stmt.where(pc)
        yc = self._year_cond(year)
        if yc is not None:
            stmt = stmt.where(yc)
        if population:
            stmt = stmt.where(
                or_(
                    func.lower(DataPoint.population).contains(population.lower()),
                    func.lower(DataPoint.age_group).contains(population.lower()),
                )
            )
        stmt = stmt.limit(50)
        rows = await self.db.execute(stmt)
        results = []
        for row in rows:
            results.append({
                "disease": row.disease, "province": row.province,
                "city": row.city,
                "population": row.population, "value": float(row.value) if row.value else None,
                "ci_lower": float(row.ci_lower) if row.ci_lower else None,
                "ci_upper": float(row.ci_upper) if row.ci_upper else None,
                "sample_size": row.sample_size,
                "collection_year": row.collection_year,
                "data_type": row.data_type, "method": row.method,
                "age_group": row.age_group, "literature_id": str(row.literature_id) if row.literature_id else None,
                "review_status": row.review_status,
            })
        return results

    async def query_gmc(
        self, disease: str, province: str | None = None,
        year: str | None = None,
    ) -> list[dict]:
        """查询 GMC 数据"""
        stmt = select(
            DataPoint.disease, DataPoint.province, DataPoint.city,
            DataPoint.population,
            DataPoint.value, DataPoint.ci_lower, DataPoint.ci_upper,
            DataPoint.sample_size, DataPoint.collection_year, DataPoint.unit,
            DataPoint.literature_id, DataPoint.review_status,
        ).where(
            DataPoint.data_type == "gmc",
            self._disease_cond(disease),
        )
        rc = self._review_cond()
        if rc is not None:
            stmt = stmt.where(rc)
        pc = self._province_cond(province)
        if pc is not None:
            stmt = stmt.where(pc)
        yc = self._year_cond(year)
        if yc is not None:
            stmt = stmt.where(yc)
        stmt = stmt.limit(50)
        rows = await self.db.execute(stmt)
        results = []
        for row in rows:
            results.append({
                "disease": row.disease, "province": row.province,
                "city": row.city,
                "population": row.population, "value": float(row.value) if row.value else None,
                "ci_lower": float(row.ci_lower) if row.ci_lower else None,
                "ci_upper": float(row.ci_upper) if row.ci_upper else None,
                "sample_size": row.sample_size,
                "collection_year": row.collection_year,
                "unit": row.unit,
                "literature_id": str(row.literature_id) if row.literature_id else None,
                "review_status": row.review_status,
            })
        return results

    async def query_by_institution(self, institution: str) -> list[dict]:
        """查询某机构相关的调查"""
        # 先查 KG 实体
        ent_stmt = select(KGEntity).where(
            KGEntity.merged_into.is_(None),
            KGEntity.entity_type == EntityType.INSTITUTION,
            KGEntity.name.ilike(f"%{institution}%"),
        )
        ent_rows = await self.db.execute(ent_stmt)
        institutions = ent_rows.scalars().all()

        results = []
        for inst in institutions:
            # 查询该机构关联的三元组
            tri_stmt = select(KGTriple).where(
                or_(
                    and_(KGTriple.subject_id == inst.id, KGTriple.predicate == "conducted_by"),
                    and_(KGTriple.object_id == inst.id, KGTriple.predicate == "conducted_by"),
                )
            )
            tri_rows = await self.db.execute(tri_stmt)
            for tri in tri_rows.scalars():
                survey_id = tri.subject_id if str(tri.object_id) == str(inst.id) else tri.object_id
                survey_stmt = select(KGEntity).where(KGEntity.id == survey_id)
                survey_row = await self.db.execute(survey_stmt)
                survey = survey_row.scalar_one_or_none()
                results.append({
                    "institution": inst.name,
                    "survey": survey.name if survey else None,
                    "relation": tri.predicate,
                    "source_context": tri.source_context,
                })

        # 也查数据点（通过 literature 的 author_affiliations）
        if not results:
            dp_stmt = select(
                DataPoint.disease, DataPoint.province, DataPoint.population,
                DataPoint.collection_year, DataPoint.literature_id,
            )
            rc = self._review_cond()
            if rc is not None:
                dp_stmt = dp_stmt.where(rc)
            dp_stmt = dp_stmt.distinct().limit(30)
            dp_rows = await self.db.execute(dp_stmt)
            for row in dp_rows:
                if row.literature_id:
                    lit_stmt = select(Literature.author_affiliations).where(
                        Literature.id == row.literature_id
                    )
                    lit_row = await self.db.execute(lit_stmt)
                    aff = lit_row.scalar()
                    if aff and institution in aff:
                        results.append({
                            "institution": institution,
                            "disease": row.disease,
                            "province": row.province,
                            "population": row.population,
                            "collection_year": row.collection_year,
                        })
        return results

    async def query_by_author(self, disease: str, province: str | None = None) -> list[dict]:
        """查询某地区某疾病相关研究的作者（通过 DataPoint 关联定位地区，作者取 Literature.authors）"""
        stmt = select(
            Literature.id, Literature.title, Literature.authors,
            Literature.author_affiliations, Literature.pub_year,
        ).join(
            DataPoint, Literature.id == DataPoint.literature_id
        ).where(
            self._disease_cond(disease),
        )
        rc = self._review_cond()
        if rc is not None:
            stmt = stmt.where(rc)
        pc = self._province_cond(province)
        if pc is not None:
            stmt = stmt.where(pc)
        stmt = stmt.distinct().limit(100)
        rows = await self.db.execute(stmt)
        results = []
        for row in rows:
            authors = [a.strip() for a in (row.authors or "").split(";") if a.strip()]
            results.append({
                "title": row.title,
                "authors": authors,
                "author_affiliations": row.author_affiliations,
                "pub_year": row.pub_year,
                "literature_id": str(row.id),
            })
        return results

    async def query_by_population(
        self, population: str, disease: str | None = None,
    ) -> list[dict]:
        """按人群查询"""
        stmt = select(
            DataPoint.disease, DataPoint.province, DataPoint.population,
            DataPoint.value, DataPoint.ci_lower, DataPoint.ci_upper,
            DataPoint.sample_size, DataPoint.collection_year,
            DataPoint.data_type, DataPoint.unit, DataPoint.review_status,
        ).where(
            or_(
                func.lower(DataPoint.population).contains(population.lower()),
                func.lower(DataPoint.age_group).contains(population.lower()),
            ),
        )
        rc = self._review_cond()
        if rc is not None:
            stmt = stmt.where(rc)
        dc = self._disease_cond(disease)
        if dc is not None:
            stmt = stmt.where(dc)
        stmt = stmt.limit(50)
        rows = await self.db.execute(stmt)
        results = []
        for row in rows:
            results.append({
                "disease": row.disease, "province": row.province,
                "population": row.population,
                "value": float(row.value) if row.value else None,
                "ci_lower": float(row.ci_lower) if row.ci_lower else None,
                "ci_upper": float(row.ci_upper) if row.ci_upper else None,
                "sample_size": row.sample_size,
                "collection_year": row.collection_year,
                "data_type": row.data_type, "unit": row.unit,
                "review_status": row.review_status,
            })
        return results

    async def query_comparison(
        self, province1: str, province2: str, disease: str,
    ) -> dict:
        """对比两个地区的指标"""
        results1 = await self.query_seroprevalence(disease, province1)
        results2 = await self.query_seroprevalence(disease, province2)
        return {
            "province1": province1, "province2": province2,
            "disease": disease,
            "data1": results1, "data2": results2,
        }

    async def query_trend(
        self, disease: str, province: str | None = None,
    ) -> list[dict]:
        """查询年度趋势"""
        dc = self._disease_cond(disease) if disease else None
        stmt = select(
            DataPoint.collection_year,
            func.avg(DataPoint.value).label("avg_value"),
            func.count().label("n"),
            func.min(DataPoint.value).label("min_val"),
            func.max(DataPoint.value).label("max_val"),
        ).where(
            DataPoint.data_type == "seroprevalence",
            DataPoint.collection_year.isnot(None),
        )
        if dc is not None:
            stmt = stmt.where(dc)
        rc = self._review_cond()
        if rc is not None:
            stmt = stmt.where(rc)
        pc = self._province_cond(province)
        if pc is not None:
            stmt = stmt.where(pc)
        stmt = stmt.group_by(DataPoint.collection_year).order_by(DataPoint.collection_year)
        rows = await self.db.execute(stmt)
        results = []
        for row in rows:
            results.append({
                "year": row.collection_year,
                "avg_value": round(float(row.avg_value), 2) if row.avg_value else None,
                "count": row.n,
                "min_value": float(row.min_val) if row.min_val else None,
                "max_value": float(row.max_val) if row.max_val else None,
            })
        return results

    async def query_vaccine(
        self, vaccine: str, province: str | None = None,
    ) -> dict:
        """按疫苗名称查询对应病原体的抗体阳性率数据。"""
        # 从疫苗名中识别病原体（去"接种/接种后"前缀、去"疫苗"后缀再匹配）
        vaccine = re.sub(r"^(已|未)?接种(后|之后)?", "", vaccine).strip()
        disease = None
        for name, code in VACCINE_DISEASE.items():
            if name in vaccine or vaccine in name:
                disease = code
                break
        if not disease:
            # 退化为：直接以疫苗名做疾病归一化
            disease = vaccine.replace("疫苗", "")
        srow = await self.query_seroprevalence(disease, province)
        return {"vaccine": vaccine, "disease": disease, "province": province,
                "seroprevalence": srow}

    async def query_kg_entity(self, keyword: str, entity_type: str | None = None) -> list[dict]:
        """查询 KG 实体"""
        stmt = select(KGEntity).where(
            KGEntity.merged_into.is_(None),
            KGEntity.name.ilike(f"%{keyword}%"),
        )
        if entity_type:
            stmt = stmt.where(KGEntity.entity_type == entity_type)
        stmt = stmt.limit(20)
        rows = await self.db.execute(stmt)
        results = []
        for ent in rows.scalars():
            results.append({
                "id": str(ent.id), "name": ent.name,
                "entity_type": ent.entity_type,
                "attributes": ent.attributes or {},
            })
        return results


# ===== 答案格式化器 =====

class QAAnswerFormatter:
    """将查询结果格式化为自然语言答案"""

    @staticmethod
    def _unreviewed_note(results: list[dict]) -> str:
        """若结果包含未审核数据点，返回来源提示（不阻断答案）。"""
        if any(r.get("review_status") and r["review_status"] != "approved" for r in results):
            return "\n> ⚠️ 以上结果含**未审核**数据点，仅供参考，请以审核通过的正式数据为准。"
        return ""

    @staticmethod
    def format_seroprevalence_answer(
        disease: str, province: str | None, results: list[dict],
    ) -> str:
        if not results:
            loc = f"{province}" if province else "全国"
            return f"暂未找到「{loc}{disease}抗体阳性率」的相关数据。请检查疾病名称或地区是否正确。"
        note = QAAnswerFormatter._unreviewed_note(results)
        loc = province or "全国"
        values = [r["value"] for r in results if r["value"] is not None]
        if not values:
            return f"已找到 {loc} {disease} 抗体阳性率数据，但数值为空。"
        avg_val = sum(values) / len(values)
        years = [r["collection_year"] for r in results if r["collection_year"]]
        year_range = f"{min(years)}-{max(years)}" if years else "未知年份"
        samples = [r["sample_size"] for r in results if r["sample_size"]]
        total_samples = sum(samples) if samples else 0
        lines = [
            f"## {loc}{disease} 抗体阳性率",
            f"**数据来源**：{len(results)} 项调查（{year_range}，累计样本量 {total_samples:,}）",
            f"**综合阳性率**：约 {avg_val:.1f}%",
        ]
        # 按年份列出
        by_year = {}
        for r in results:
            y = r["collection_year"] or "未知"
            by_year.setdefault(y, []).append(r)
        lines.append("\n**按年份分布**：")
        for year in sorted(by_year.keys(), key=lambda x: str(x)):
            items = by_year[year]
            vals = [i["value"] for i in items if i["value"] is not None]
            if vals:
                avg = sum(vals) / len(vals)
                pop = items[0]["population"] or "一般人群"
                city = (items[0].get("city") or "").strip()
                where = f" {city}" if city else ""
                lines.append(f"- {year}年{where}：{avg:.1f}%（{len(items)} 项调查，{pop}，样本量 {items[0]['sample_size'] or '未知'}）")
        if note:
            lines.append(note)
        return "\n".join(lines)

    @staticmethod
    def format_gmc_answer(
        disease: str, province: str | None, results: list[dict],
    ) -> str:
        if not results:
            loc = province or ""
            return f"暂未找到「{loc}{disease}几何平均滴度(GMC)」的相关数据。"
        note = QAAnswerFormatter._unreviewed_note(results)
        loc = province or "全国"
        values = [r["value"] for r in results if r["value"] is not None]
        if not values:
            return f"已找到 {loc} {disease} GMC 数据，但数值为空。"
        avg_val = sum(values) / len(values)
        units = results[0].get("unit") or "U/mL"
        lines = [
            f"## {loc}{disease} 几何平均滴度 (GMC)",
            f"**数据来源**：{len(results)} 项调查",
            f"**综合 GMC**：约 {avg_val:.2f} {units}",
        ]
        for r in results[:10]:
            pop = r["population"] or "一般人群"
            year = r["collection_year"] or "未知"
            val = f"{r['value']:.2f}" if r["value"] else "无"
            city = (r.get("city") or "").strip()
            where = f" {city}" if city else ""
            lines.append(f"- {year}年{where} {pop}：{val} {units}")
        if note:
            lines.append(note)
        return "\n".join(lines)

    @staticmethod
    def format_comparison_answer(data: dict) -> str:
        p1, p2 = data["province1"], data["province2"]
        disease = data["disease"]
        d1, d2 = data["data1"], data["data2"]
        v1 = [r["value"] for r in d1 if r["value"] is not None]
        v2 = [r["value"] for r in d2 if r["value"] is not None]
        lines = [f"## {p1} vs {p2} {disease} 抗体阳性率对比"]
        if v1:
            lines.append(f"- **{p1}**：{sum(v1)/len(v1):.1f}%（{len(d1)} 项调查）")
        else:
            lines.append(f"- **{p1}**：暂无数据")
        if v2:
            lines.append(f"- **{p2}**：{sum(v2)/len(v2):.1f}%（{len(d2)} 项调查）")
        else:
            lines.append(f"- **{p2}**：暂无数据")
        if v1 and v2:
            diff = sum(v1)/len(v1) - sum(v2)/len(v2)
            who = p1 if diff > 0 else p2
            lines.append(f"\n**结论**：{who}的{disease}抗体阳性率{'高' if diff > 0 else '低'}约 {abs(diff):.1f} 个百分点")
        return "\n".join(lines)

    @staticmethod
    def format_institution_answer(results: list[dict]) -> str:
        if not results:
            return "暂未找到相关机构调查数据。"
        lines = [f"## 机构调查结果（{len(results)} 条）"]
        for r in results[:15]:
            if r.get("survey"):
                lines.append(f"- {r.get('institution','')}：{r['survey']}")
            else:
                lines.append(f"- {r.get('institution','')}：{r.get('disease','')}（{r.get('province','')}，{r.get('collection_year','')}年）")
        return "\n".join(lines)

    @staticmethod
    def format_population_answer(
        population: str, disease: str | None, results: list[dict],
    ) -> str:
        if not results:
            dis = disease or ""
            return f"暂未找到「{population}{dis}抗体水平」的相关数据。"
        note = QAAnswerFormatter._unreviewed_note(results)
        dis = disease or "多种疾病"
        lines = [f"## {population} {dis} 抗体水平"]
        for r in results[:15]:
            val = f"{r['value']:.1f}" if r["value"] else "无"
            unit = r.get("unit") or "%"
            year = r["collection_year"] or "未知"
            prov = r["province"] or "未知地区"
            lines.append(f"- {prov} {year}年：{val} {unit}（样本量 {r['sample_size'] or '未知'}）")
        if note:
            lines.append(note)
        return "\n".join(lines)

    @staticmethod
    def format_vaccine_answer(data: dict) -> str:
        """疫苗类问题答案：疫苗 → 对应病原体的抗体阳性率。"""
        vaccine = data["vaccine"]
        province = data["province"]
        results = data["seroprevalence"]
        loc = province or "全国"
        if not results:
            return f"暂未找到「{loc} {vaccine}」相关抗体数据。可尝试查询对应疾病如「{vaccine.replace('疫苗','')}抗体阳性率」。"
        note = QAAnswerFormatter._unreviewed_note(results)
        values = [r["value"] for r in results if r["value"] is not None]
        avg = f"{sum(values)/len(values):.1f}%" if values else "无"
        years = [r["collection_year"] for r in results if r["collection_year"]]
        yr = f"{min(years)}-{max(years)}" if years else "未知年份"
        lines = [
            f"## {loc} {vaccine}免疫相关抗体",
            f"**数据来源**：{len(results)} 项调查（{yr}）",
            f"**综合抗体阳性率**：约 {avg}",
        ]
        for r in results[:10]:
            val = f"{r['value']:.1f}" if r["value"] is not None else "无"
            year = r["collection_year"] or "未知"
            pop = r["population"] or "一般人群"
            lines.append(f"- {year}年 {pop}：{val}%（样本量 {r['sample_size'] or '未知'}）")
        if note:
            lines.append(note)
        return "\n".join(lines)

    @staticmethod
    def format_overview_answer(disease: str, results: list[dict]) -> str:
        """研究/调查概况汇总"""
        if not results:
            return f"暂未找到与「{disease}」相关的调查数据。"
        note = QAAnswerFormatter._unreviewed_note(results)
        provs = sorted({r["province"] for r in results if r["province"]})
        values = [r["value"] for r in results if r["value"] is not None]
        lines = [f"## 「{disease}」相关研究概况"]
        lines.append(f"共找到 **{len(results)}** 项调查数据，覆盖地区：{'、'.join(provs[:20]) if provs else '未知'}。")
        if values:
            lines.append(f"阳性率范围：{min(values):.1f}% - {max(values):.1f}%（综合平均约 {sum(values)/len(values):.1f}%）")
        if note:
            lines.append(note)
        return "\n".join(lines)

    @staticmethod
    def format_author_answer(
        disease: str, province: str | None, results: list[dict],
    ) -> str:
        """汇总某地区某疾病研究的相关作者"""
        if not results:
            loc = province or "全国"
            return f"暂未找到「{loc}{disease}研究」的作者信息。请确认疾病名称或地区是否正确。"
        loc = province or "全国"
        # 汇总所有作者（去重保序）
        author_set: list[str] = []
        seen: set[str] = set()
        for r in results:
            for a in r.get("authors") or []:
                key = a.lower()
                if key not in seen:
                    seen.add(key)
                    author_set.append(a)
        lines = [
            f"## {loc}{disease}研究的作者",
            f"共找到 **{len(results)}** 篇相关文献，涉及 **{len(author_set)}** 位作者：",
        ]
        lines.append("、".join(author_set[:50]) + ("…" if len(author_set) > 50 else ""))
        if len(results) <= 15:
            lines.append("\n**相关文献**：")
            for r in results:
                authors = "、".join((r.get("authors") or [])[:5])
                lines.append(f"- {r.get('pub_year') or '未知'}年《{r['title']}》（{authors}）")
        return "\n".join(lines)

    @staticmethod
    def format_trend_answer(results: list[dict]) -> str:
        if not results:
            return "暂未找到相关趋势数据。"
        years = [r["year"] for r in results if r["year"]]
        lines = [f"## 年度趋势（{min(years)}-{max(years)}）"]
        for r in results:
            lines.append(f"- {r.get('year','')}年：平均 {r['avg_value']}%（{r['count']} 项调查，{r['min_value']}-{r['max_value']}%）")
        # 趋势方向
        vals = [r["avg_value"] for r in results if r["avg_value"]]
        if len(vals) >= 2:
            direction = "上升" if vals[-1] > vals[0] else "下降"
            lines.append(f"\n**趋势方向**：整体{direction}（{results[0]['year']}年 {vals[0]}% → {results[-1]['year']}年 {vals[-1]}%）")
        return "\n".join(lines)

    @staticmethod
    def format_kg_answer(results: list[dict]) -> str:
        if not results:
            return "暂未找到相关实体信息。"
        lines = [f"## 知识图谱实体（{len(results)} 条）"]
        for r in results:
            etype = ENTITY_LABELS.get(r["entity_type"]) or r["entity_type"]
            attrs = r.get("attributes", {})
            extra = ""
            if attrs.get("disease"):
                extra += f" 疾病：{attrs['disease']}"
            if attrs.get("province"):
                extra += f" 地区：{attrs['province']}"
            lines.append(f"- [{etype}] {r['name']}{extra}")
        return "\n".join(lines)


# ===== LLM 降级 =====

async def _retrieve_qa_evidence(
    question: str, db: AsyncSession,
) -> str:
    """RAG-lite：从问题中识别已收录的疾病/地区，真检索数据点，返回紧凑证据块。

    让 LLM 兜底回答基于真实数据库，而不是泛泛而谈。
    """
    try:
        executor = QAQueryExecutor(db)
        # 已知疾病/地区词表（去重取前 N）；疾病在库内存英文代码，需支持中文别名归一化
        dis_stmt = select(func.distinct(DataPoint.disease)).where(DataPoint.disease.isnot(None)).limit(300)
        prov_stmt = select(func.distinct(DataPoint.province)).where(
            DataPoint.province.isnot(None)).limit(400)
        city_stmt = select(func.distinct(DataPoint.city)).where(
            DataPoint.city.isnot(None)).limit(400)
        pop_stmt = select(func.distinct(DataPoint.population)).where(
            DataPoint.population.isnot(None)).limit(200)
        diseases = [r[0] for r in (await db.execute(dis_stmt)) if r[0]]
        provinces = [r[0] for r in (await db.execute(prov_stmt)) if r[0]]
        cities = [r[0] for r in (await db.execute(city_stmt)) if r[0]]
        populations = [r[0] for r in (await db.execute(pop_stmt)) if r[0]]

        ql = question.lower()
        # 疾病：先直接命中库内代码（如 "measles"），再尝试中文别名 → 英文代码
        hit_disease = next((d for d in diseases if d and d.lower() in ql), None)
        if not hit_disease:
            for zh, code in DISEASE_ALIASES.items():
                if zh in question:
                    hit_disease = code
                    break
        # 地区：省级 + 市级（区县）一起匹配，支持“丰台”命中 city 字段
        hit_province = next(
            (p for p in (provinces + cities) if p and p.lower() in ql), None)
        hit_pop = next((p for p in populations if p and p.lower() in ql), None)

        if not hit_disease and not hit_province and not hit_pop:
            return ""

        lines = []
        # 作者类问题：检索该地区该疾病相关文献的作者
        if "作者" in question and hit_disease:
            try:
                author_rows = await executor.query_by_author(hit_disease, province=hit_province)
                if author_rows:
                    author_set: list[str] = []
                    seen: set[str] = set()
                    for r in author_rows:
                        for a in r.get("authors") or []:
                            if a.lower() not in seen:
                                seen.add(a.lower())
                                author_set.append(a)
                    lines.append(f"### 已检索到的「{hit_disease}」研究作者（{len(author_rows)} 篇文献，{len(author_set)} 位作者）：")
                    lines.append("、".join(author_set[:50]) + ("…" if len(author_set) > 50 else ""))
            except Exception as e:
                logger.warning(f"RAG 作者检索失败: {e}")
        if hit_disease:
            rows = await executor.query_seroprevalence(
                hit_disease, province=hit_province, population=hit_pop)
            if rows:
                lines.append(f"### 已检索到的「{hit_disease}」数据（共 {len(rows)} 条）：")
                for r in rows[:15]:
                    loc = r.get("city") or r.get("province") or "全国"
                    val = f"{r['value']:.1f}" if r.get("value") is not None else "无"
                    year = r.get("collection_year") or "未知"
                    pop = r.get("population") or "一般人群"
                    flag = "" if r.get("review_status") == "approved" else "（未审核）"
                    lines.append(
                        f"- {loc} {year}年 {pop}：阳性率 {val}%（样本量 {r.get('sample_size') or '未知'}）{flag}")
            gmc_rows = await executor.query_gmc(hit_disease, province=hit_province)
            if gmc_rows:
                lines.append(f"### 已检索到的「{hit_disease}」GMC 数据：")
                for r in gmc_rows[:8]:
                    loc = r.get("city") or r.get("province") or "全国"
                    val = f"{r['value']:.2f}" if r.get("value") is not None else "无"
                    year = r.get("collection_year") or "未知"
                    flag = "" if r.get("review_status") == "approved" else "（未审核）"
                    lines.append(f"- {loc} {year}年：GMC {val} {r.get('unit') or 'U/mL'}{flag}")
        elif hit_province or hit_pop:
            if hit_province:
                rows = await executor.query_seroprevalence("", province=hit_province)
                if rows:
                    lines.append(f"### 已检索到的「{hit_province}」数据（共 {len(rows)} 条）：")
                    for r in rows[:12]:
                        val = f"{r['value']:.1f}" if r.get("value") is not None else "无"
                        lines.append(f"- {r.get('disease','未知疾病')} {r.get('population','')}：阳性率 {val}%")
        return "\n".join(lines)
    except Exception as e:
        logger.warning(f"RAG 检索失败: {e}")
        return ""


async def llm_fallback_answer(
    question: str, db: AsyncSession,
) -> str:
    """模板未匹配时，用 LLM 生成问答。

    先做真实数据检索（RAG-lite），把检索结果连同 KG 概览一并喂给 LLM，
    让兜底回答有数据支撑。
    """
    try:
        # 真实数据证据（RAG）
        rag_evidence = await _retrieve_qa_evidence(question, db)

        # 获取 KG 上下文
        ent_count = await db.execute(select(func.count()).select_from(KGEntity).where(KGEntity.merged_into.is_(None)))
        tri_count = await db.execute(select(func.count()).select_from(KGTriple))
        total_entities = ent_count.scalar() or 0
        total_triples = tri_count.scalar() or 0

        # 获取疾病列表
        dis_stmt = select(DataPoint.disease).distinct().limit(10)
        dis_rows = await db.execute(dis_stmt)
        diseases = [r[0] for r in dis_rows if r[0]]

        context = (
            f"知识图谱包含 {total_entities} 个实体和 {total_triples} 条关系。"
            f"涵盖的疾病有：{', '.join(diseases)}。"
            f"实体类型包括：调查、病原体、地区、人群、检测方法、指标、实施单位、作者、样本、疫苗等。"
            f"关系类型包括：调查于、覆盖时期、目标人群、检测病原体、使用检测方法、报告指标、实施单位等。"
        )

        from app.services.kg_llm_integration import KGExtractor
        extractor = KGExtractor()

        evidence_block = f"\n\n检索到的真实数据库数据：\n{rag_evidence}" if rag_evidence else ""

        prompt = f"""你是一个血清抗体流行病学知识图谱问答助手。请根据以下信息回答用户的问题。

知识图谱上下文：
{context}
{evidence_block}

用户问题：{question}

请用中文回答。优先依据上面「检索到的真实数据库数据」作答；若该板块没有相关内容，
再结合知识图谱上下文给出可能有帮助的答复。
如果既无检索数据也无相关上下文，请如实说明当前知识图谱/数据库未覆盖该问题，并给出可尝试的查询方向。
严禁编造不存在的数值。"""

        messages = [
            {"role": "system", "content": "你是血清抗体流行病学知识图谱问答助手，基于知识图谱和真实数据库数据回答用户问题，不得编造数据。"},
            {"role": "user", "content": prompt},
        ]

        response = await extractor.client.chat.completions.create(
            model=extractor.model,
            messages=messages,
            temperature=0.3,
            max_tokens=1000,
        )
        return response.choices[0].message.content or "抱歉，暂时无法回答该问题。"

    except Exception as e:
        logger.warning(f"LLM fallback 失败: {e}")
        return (
            "抱歉，当前问题未能匹配到知识图谱中的模板，且 LLM 服务暂时不可用。\n\n"
            "请尝试以下问题类型：\n"
            '- 查询某地区某疾病的抗体阳性率（如"北京麻疹阳性率是多少"）\n'
            '- 对比两个地区（如"北京和上海麻疹阳性率对比"）\n'
            '- 查询某机构调查（如"哈尔滨医科大学做过哪些调查"）\n'
            '- 查询某人群抗体水平（如"儿童麻疹抗体阳性率"）\n'
            '- 查询年度趋势（如"麻疹阳性率变化趋势"）\n'
        )


# ===== 主入口 =====

async def ask_question(
    question: str, db: AsyncSession,
) -> dict[str, Any]:
    """问答主入口：模板匹配 → 查询执行 → 答案格式化 → LLM 降级"""

    # 1. 模板匹配
    matched_template = None
    matched_slots = None
    for tmpl in sorted(TEMPLATES, key=lambda t: -t.priority):
        slots = tmpl.match(question)
        if slots:
            matched_template = tmpl
            matched_slots = slots
            break

    executor = QAQueryExecutor(db)
    formatter = QAAnswerFormatter()

    # 2. 执行查询
    if matched_template:
        template_name = matched_template.name
        try:
            if template_name == "seroprevalence_query":
                disease = matched_slots.get("disease", "")
                province = matched_slots.get("province")
                year = matched_slots.get("year")
                results = await executor.query_seroprevalence(disease, province, year=year)
                answer = formatter.format_seroprevalence_answer(disease, province, results)
                return {
                    "answer": answer,
                    "template": template_name,
                    "method": "template",
                    "result_count": len(results),
                    "slots": matched_slots,
                }

            elif template_name == "gmc_query":
                disease = matched_slots.get("disease", "")
                province = matched_slots.get("province")
                year = matched_slots.get("year")
                results = await executor.query_gmc(disease, province, year=year)
                answer = formatter.format_gmc_answer(disease, province, results)
                return {
                    "answer": answer,
                    "template": template_name,
                    "method": "template",
                    "result_count": len(results),
                    "slots": matched_slots,
                }

            elif template_name == "author_query":
                disease = matched_slots.get("disease", "")
                province = matched_slots.get("province")
                results = await executor.query_by_author(disease, province)
                answer = formatter.format_author_answer(disease, province, results)
                return {
                    "answer": answer,
                    "template": template_name,
                    "method": "template",
                    "result_count": len(results),
                    "slots": matched_slots,
                }

            elif template_name == "comparison_query":
                data = await executor.query_comparison(
                    matched_slots["province1"],
                    matched_slots["province2"],
                    matched_slots.get("disease", ""),
                )
                answer = formatter.format_comparison_answer(data)
                return {
                    "answer": answer,
                    "template": template_name,
                    "method": "template",
                    "result_count": len(data["data1"]) + len(data["data2"]),
                    "slots": matched_slots,
                }

            elif template_name == "institution_query":
                institution = matched_slots.get("institution", "")
                results = await executor.query_by_institution(institution)
                answer = formatter.format_institution_answer(results)
                return {
                    "answer": answer,
                    "template": template_name,
                    "method": "template",
                    "result_count": len(results),
                    "slots": matched_slots,
                }

            elif template_name == "population_query":
                population = matched_slots.get("population", "")
                disease = matched_slots.get("disease")
                results = await executor.query_by_population(population, disease)
                answer = formatter.format_population_answer(population, disease, results)
                return {
                    "answer": answer,
                    "template": template_name,
                    "method": "template",
                    "result_count": len(results),
                    "slots": matched_slots,
                }

            elif template_name == "vaccine_query":
                vaccine = matched_slots.get("vaccine", "")
                province = matched_slots.get("province")
                data = await executor.query_vaccine(vaccine, province)
                answer = formatter.format_vaccine_answer(data)
                return {
                    "answer": answer,
                    "template": template_name,
                    "method": "template",
                    "result_count": len(data["seroprevalence"]),
                    "slots": matched_slots,
                }

            elif template_name == "trend_query":
                disease = matched_slots.get("disease", "")
                province = matched_slots.get("province")
                results = await executor.query_trend(disease, province)
                answer = formatter.format_trend_answer(results)
                return {
                    "answer": answer,
                    "template": template_name,
                    "method": "template",
                    "result_count": len(results),
                    "slots": matched_slots,
                }

            elif template_name == "overview_query":
                disease = matched_slots.get("disease", "")
                results = await executor.query_seroprevalence(disease)
                if not results:
                    # 也试 GMC，最大化命中
                    results = await executor.query_gmc(disease)
                    gmc_only = True
                else:
                    gmc_only = False
                answer = formatter.format_overview_answer(disease, results)
                if gmc_only and results:
                    note = f"\n（仅检索到「{disease}」的 GMC 数据，共 {len(results)} 条）"
                    answer = answer + note
                return {
                    "answer": answer,
                    "template": template_name,
                    "method": "template",
                    "result_count": len(results),
                    "slots": matched_slots,
                }

            elif template_name == "pathogen_query":
                disease = matched_slots.get("disease", "")
                results = await executor.query_kg_entity(disease, "pathogen")
                # 也查关联文献
                lit_results = await executor.query_seroprevalence(disease)
                if results:
                    answer = formatter.format_kg_answer(results)
                elif lit_results:
                    answer = f"关于「{disease}」共找到 {len(lit_results)} 项调查数据。"
                else:
                    answer = f"暂未找到与「{disease}」相关的知识图谱实体。"
                return {
                    "answer": answer,
                    "template": template_name,
                    "method": "template",
                    "result_count": len(results) + len(lit_results),
                    "slots": matched_slots,
                }

        except Exception as e:
            logger.error(f"模板查询执行失败: {template_name}: {e}", exc_info=True)
            # 回滚可能处于 pending 状态的事务，避免坏 session 连坐 LLM 兜底
            with contextlib.suppress(Exception):
                await db.rollback()
            # 降级到 LLM
            answer = await llm_fallback_answer(question, db)
            return {
                "answer": answer,
                "template": template_name,
                "method": "llm_fallback",
                "result_count": 0,
                "slots": matched_slots,
            }

    # 3. 未匹配 → LLM 降级
    answer = await llm_fallback_answer(question, db)
    return {
        "answer": answer,
        "template": None,
        "method": "llm",
        "result_count": 0,
        "slots": None,
    }