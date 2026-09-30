"""知识图谱本体定义：实体类型与关系类型。

实体（EntityType）与关系（RelationType）用于描述血清抗体流行病学
调查数据的多维语义网络。

图谱数据有两个来源：
1. 计算式推导：从 approved 数据点自动生成基础节点与边（knowledge_graph_service.py）。
2. LLM 抽取：从文献全文中抽取持久化三元组（kg_llm_integration.py → kg_entity/kg_triple 表）。

两者共存互补：计算式保证数据始终最新，持久化支持实体搜索与路径推理。
"""

from enum import Enum


class EntityType(str, Enum):
    SURVEY = "survey"
    PATHOGEN = "pathogen"
    GEO_AREA = "geo_area"
    TIME_PERIOD = "time_period"
    HOST_GROUP = "host_group"
    LAB_ASSAY = "lab_assay"
    INDICATOR = "indicator"
    INSTITUTION = "institution"
    AUTHOR = "author"
    SAMPLE = "sample"
    VACCINE = "vaccine"
    DATA_QUALITY = "data_quality"
    PUBLICATION = "publication"


class RelationType(str, Enum):
    # 基础维度关系（计算式 + LLM 抽取均可生成）
    SURVEYED_AT = "surveyed_at"
    COVERED_TIME = "covered_time"
    TARGETS_HOST = "targets_host"
    DETECTS_PATHOGEN = "detects_pathogen"
    USES_ASSAY = "uses_assay"
    REPORTS_INDICATOR = "reports_indicator"

    # LLM 抽取扩展关系（仅从文献全文抽取）
    CONDUCTED_BY = "conducted_by"
    AUTHORED_BY = "authored_by"
    AFFILIATED_WITH = "affiliated_with"
    HAS_SAMPLE = "has_sample"
    VACCINATED_WITH = "vaccinated_with"
    HAS_QUALITY = "has_quality"
    CONTAINS_SURVEY = "contains_survey"
    SAME_COHORT = "same_cohort"
    ADJUSTED_FOR = "adjusted_for"

    # 计算式统计对比关系（仅由 knowledge_graph_service 动态生成，不入库）
    HIGHER_THAN = "higher_than"
    BELONGS_TO = "belongs_to"
    INFLUENCES = "influences"


# 各实体类型的中文标签（供前端/日志使用）
ENTITY_LABELS = {
    EntityType.SURVEY: "调查",
    EntityType.PATHOGEN: "病原体",
    EntityType.GEO_AREA: "地理区域",
    EntityType.TIME_PERIOD: "时间时期",
    EntityType.HOST_GROUP: "人群",
    EntityType.LAB_ASSAY: "检测方法",
    EntityType.INDICATOR: "指标结果",
    EntityType.INSTITUTION: "实施单位",
    EntityType.AUTHOR: "作者",
    EntityType.SAMPLE: "样本",
    EntityType.VACCINE: "疫苗",
    EntityType.DATA_QUALITY: "数据质量",
    EntityType.PUBLICATION: "出版物",
}

# 各关系类型的中文标签
RELATION_LABELS = {
    RelationType.SURVEYED_AT: "调查于",
    RelationType.COVERED_TIME: "覆盖时期",
    RelationType.TARGETS_HOST: "目标人群",
    RelationType.DETECTS_PATHOGEN: "检测病原体",
    RelationType.USES_ASSAY: "使用检测",
    RelationType.REPORTS_INDICATOR: "报告指标",
    RelationType.CONDUCTED_BY: "实施单位",
    RelationType.AUTHORED_BY: "作者",
    RelationType.AFFILIATED_WITH: "隶属于",
    RelationType.HAS_SAMPLE: "使用样本",
    RelationType.VACCINATED_WITH: "接种疫苗",
    RelationType.HAS_QUALITY: "数据质量",
    RelationType.CONTAINS_SURVEY: "包含调查",
    RelationType.SAME_COHORT: "同一队列",
    RelationType.ADJUSTED_FOR: "校正因素",
    RelationType.HIGHER_THAN: "高于",
    RelationType.BELONGS_TO: "隶属于",
    RelationType.INFLUENCES: "影响",
}
