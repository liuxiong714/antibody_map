from fastapi import APIRouter

from app.schemas.common import ApiResponse

router = APIRouter()

# 硬编码 11 种疾病数据
DISEASES = [
    {"key": "measles", "name_cn": "麻疹", "name_en": "Measles", "category": "疫苗可预防", "vaccine": "麻腮风疫苗(MMR)"},
    {"key": "mumps", "name_cn": "腮腺炎", "name_en": "Mumps", "category": "疫苗可预防", "vaccine": "麻腮风疫苗(MMR)"},
    {"key": "rubella", "name_cn": "风疹", "name_en": "Rubella", "category": "疫苗可预防", "vaccine": "麻腮风疫苗(MMR)"},
    {"key": "pertussis", "name_cn": "百日咳", "name_en": "Pertussis", "category": "疫苗可预防", "vaccine": "百白破疫苗(DTaP)"},
    {"key": "diphtheria", "name_cn": "白喉", "name_en": "Diphtheria", "category": "疫苗可预防", "vaccine": "百白破疫苗(DTaP)"},
    {"key": "tetanus", "name_cn": "破伤风", "name_en": "Tetanus", "category": "疫苗可预防", "vaccine": "百白破疫苗(DTaP)"},
    {"key": "hepatitis_b", "name_cn": "乙肝", "name_en": "Hepatitis B", "category": "疫苗可预防", "vaccine": "乙肝疫苗(HepB)"},
    {"key": "hepatitis_a", "name_cn": "甲肝", "name_en": "Hepatitis A", "category": "疫苗可预防", "vaccine": "甲肝疫苗(HepA)"},
    {"key": "polio", "name_cn": "脊灰", "name_en": "Polio", "category": "疫苗可预防", "vaccine": "脊灰疫苗(OPV/IPV)"},
    {"key": "influenza", "name_cn": "流感", "name_en": "Influenza", "category": "呼吸道", "vaccine": "流感疫苗"},
    {"key": "covid19", "name_cn": "新冠", "name_en": "COVID-19", "category": "呼吸道", "vaccine": "新冠疫苗"},
    {"key": "meningitis", "name_cn": "流脑", "name_en": "Meningococcal Meningitis", "category": "疫苗可预防", "vaccine": "流脑疫苗"},
    {"key": "varicella", "name_cn": "水痘", "name_en": "Varicella", "category": "疫苗可预防", "vaccine": "水痘疫苗(VZV)"},
    {"key": "hfmd", "name_cn": "手足口", "name_en": "HFMD", "category": "其他传染病", "vaccine": "EV71灭活疫苗"},
    {"key": "rotavirus", "name_cn": "轮状病毒", "name_en": "Rotavirus", "category": "疫苗可预防", "vaccine": "轮状病毒疫苗(RV)"},
]

# 34 个省级行政区
PROVINCES = [
    {"code": "110000", "name": "北京市"},
    {"code": "120000", "name": "天津市"},
    {"code": "130000", "name": "河北省"},
    {"code": "140000", "name": "山西省"},
    {"code": "150000", "name": "内蒙古自治区"},
    {"code": "210000", "name": "辽宁省"},
    {"code": "220000", "name": "吉林省"},
    {"code": "230000", "name": "黑龙江省"},
    {"code": "310000", "name": "上海市"},
    {"code": "320000", "name": "江苏省"},
    {"code": "330000", "name": "浙江省"},
    {"code": "340000", "name": "安徽省"},
    {"code": "350000", "name": "福建省"},
    {"code": "360000", "name": "江西省"},
    {"code": "370000", "name": "山东省"},
    {"code": "410000", "name": "河南省"},
    {"code": "420000", "name": "湖北省"},
    {"code": "430000", "name": "湖南省"},
    {"code": "440000", "name": "广东省"},
    {"code": "450000", "name": "广西壮族自治区"},
    {"code": "460000", "name": "海南省"},
    {"code": "500000", "name": "重庆市"},
    {"code": "510000", "name": "四川省"},
    {"code": "520000", "name": "贵州省"},
    {"code": "530000", "name": "云南省"},
    {"code": "540000", "name": "西藏自治区"},
    {"code": "610000", "name": "陕西省"},
    {"code": "620000", "name": "甘肃省"},
    {"code": "630000", "name": "青海省"},
    {"code": "640000", "name": "宁夏回族自治区"},
    {"code": "650000", "name": "新疆维吾尔自治区"},
    {"code": "710000", "name": "台湾省"},
    {"code": "810000", "name": "香港特别行政区"},
    {"code": "820000", "name": "澳门特别行政区"},
]

# 常见血清学检测方法
METHODS = [
    {"key": "elisa", "name_cn": "酶联免疫吸附试验(ELISA)", "name_en": "ELISA"},
    {"key": "clia", "name_cn": "化学发光免疫分析(CLIA)", "name_en": "CLIA"},
    {"key": "ifa", "name_cn": "间接免疫荧光(IFA)", "name_en": "IFA"},
    {"key": "nt", "name_cn": "中和试验(NT)", "name_en": "Neutralization Test"},
    {"key": "hai", "name_cn": "血凝抑制试验(HAI)", "name_en": "HAI"},
    {"key": "wb", "name_cn": "免疫印迹(WB)", "name_en": "Western Blot"},
    {"key": "ria", "name_cn": "放射免疫分析(RIA)", "name_en": "RIA"},
    {"key": "lfa", "name_cn": "侧流免疫层析(LFA)", "name_en": "LFA"},
    {"key": "multiplex", "name_cn": "多重微珠免疫分析", "name_en": "Multiplex Bead Assay"},
]


@router.get("/dictionary/diseases", response_model=ApiResponse, summary="获取疾病字典", description="获取预定义的疾病数据字典列表，包含疾病key、中文名、英文名、分类和对应疫苗")
async def get_diseases():
    return ApiResponse(data=DISEASES)


@router.get("/dictionary/provinces", response_model=ApiResponse, summary="获取省份字典", description="获取中国34个省级行政区列表，包含代码和名称，用于前端选择器")
async def get_provinces():
    return ApiResponse(data=PROVINCES)


@router.get("/dictionary/methods", response_model=ApiResponse, summary="获取检测方法字典", description="获取常见的血清学检测方法字典列表，包含key、中文名和英文名")
async def get_methods():
    return ApiResponse(data=METHODS)
