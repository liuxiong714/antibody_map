import logging
import re
from typing import Optional

logger = logging.getLogger("uvicorn")

# ==================== 疾病名称标准化映射 ====================
DISEASE_MAP: dict[str, str] = {
    # 麻疹
    "麻疹": "measles", "麻诊": "measles", "measles": "measles", "Measles": "measles",
    # 腮腺炎
    "腮腺炎": "mumps", "流行性腮腺炎": "mumps", "mumps": "mumps", "Mumps": "mumps",
    # 风疹
    "风疹": "rubella", "rubella": "rubella", "Rubella": "rubella",
    # 百日咳
    "百日咳": "pertussis", "pertussis": "pertussis", "Pertussis": "pertussis",
    # 白喉
    "白喉": "diphtheria", "diphtheria": "diphtheria", "Diphtheria": "diphtheria",
    # 破伤风
    "破伤风": "tetanus", "tetanus": "tetanus", "Tetanus": "tetanus",
    # 乙肝
    "乙肝": "hepatitis_b", "乙型肝炎": "hepatitis_b", "hepatitis b": "hepatitis_b",
    "Hepatitis B": "hepatitis_b", "HBV": "hepatitis_b", "hbv": "hepatitis_b",
    # 甲肝
    "甲肝": "hepatitis_a", "甲型肝炎": "hepatitis_a", "hepatitis a": "hepatitis_a",
    "Hepatitis A": "hepatitis_a", "HAV": "hepatitis_a", "hav": "hepatitis_a",
    # 脊灰
    "脊灰": "polio", "脊髓灰质炎": "polio", "polio": "polio", "Polio": "polio",
    "Polimyelitis": "polio",
    # 流感
    "流感": "influenza", "流行性感冒": "influenza", "influenza": "influenza",
    "Influenza": "influenza", "Flu": "influenza", "flu": "influenza",
    # 新冠
    "新冠": "covid19", "新型冠状病毒": "covid19", "COVID-19": "covid19",
    "covid-19": "covid19", "covid19": "covid19", "SARS-CoV-2": "covid19",
    "新冠肺炎": "covid19",
    # 水痘
    "水痘": "varicella", "varicella": "varicella", "Varicella": "varicella",
    "chickenpox": "varicella",
    # 手足口
    "手足口": "hfmd", "手足口病": "hfmd", "HFMD": "hfmd",
    # 轮状病毒
    "轮状病毒": "rotavirus", "rotavirus": "rotavirus", "Rotavirus": "rotavirus",
    # 流脑
    "流脑": "meningitis", "流行性脑脊髓膜炎": "meningitis",
    "meningitis": "meningitis",
}


def normalize_disease(name: Optional[str]) -> Optional[str]:
    """标准化疾病名称"""
    if not name:
        return None
    name = name.strip()
    # 精确匹配
    if name in DISEASE_MAP:
        return DISEASE_MAP[name]
    # 模糊匹配：尝试在 key 中查找包含关系
    name_lower = name.lower()
    for key, value in DISEASE_MAP.items():
        if key.lower() in name_lower or name_lower in key.lower():
            return value
    # 保留原文
    return name


# ==================== 检测方法标准化映射 ====================
METHOD_MAP: dict[str, str] = {
    "elisa": "ELISA", "ELISA": "ELISA",
    "酶联免疫吸附试验": "ELISA", "酶联免疫吸附实验": "ELISA",
    "酶联免疫": "ELISA", "酶联": "ELISA",
    "clia": "CLIA", "CLIA": "CLIA",
    "化学发光免疫分析": "CLIA", "化学发光免疫分析法": "CLIA",
    "化学发光": "CLIA", "化学发光法": "CLIA",
    "ifa": "IFA", "IFA": "IFA",
    "间接免疫荧光": "IFA", "间接免疫荧光法": "IFA",
    "nt": "NT", "NT": "NT",
    "中和试验": "NT", "中和实验": "NT", "中和抗体试验": "NT",
    "hai": "HAI", "HAI": "HAI",
    "血凝抑制试验": "HAI", "血凝抑制实验": "HAI", "血凝抑制": "HAI",
    "wb": "WB", "WB": "WB",
    "免疫印迹": "WB", "免疫印迹法": "WB", "western blot": "WB",
    "ria": "RIA", "RIA": "RIA",
    "放射免疫分析": "RIA", "放射免疫": "RIA",
    "lfa": "LFA", "LFA": "LFA",
    "侧流免疫层析": "LFA", "侧流免疫": "LFA", "胶体金": "LFA",
    "multiplex": "Multiplex", "Multiplex": "Multiplex",
    "多重微珠免疫分析": "Multiplex", "多重微珠": "Multiplex",
    "pcr": "PCR", "PCR": "PCR",
    "rt-pcr": "RT-PCR", "RT-PCR": "RT-PCR",
}


def normalize_method(method: Optional[str]) -> Optional[str]:
    """标准化检测方法名称"""
    if not method:
        return None
    method = method.strip()
    if method in METHOD_MAP:
        return METHOD_MAP[method]
    # 模糊匹配
    method_lower = method.lower()
    for key, value in METHOD_MAP.items():
        if key.lower() in method_lower or method_lower in key.lower():
            return value
    return method


# ==================== 抗体类型标准化映射 ====================
ANTIBODY_TYPE_MAP: dict[str, str] = {
    "igg": "IgG", "IgG": "IgG", "IGG": "IgG",
    "immunoglobulin g": "IgG", "Immunoglobulin G": "IgG",
    "igm": "IgM", "IgM": "IgM", "IGM": "IgM",
    "immunoglobulin m": "IgM", "Immunoglobulin M": "IgM",
    "iga": "IgA", "IgA": "IgA", "IGA": "IgA",
    "immunoglobulin a": "IgA", "Immunoglobulin A": "IgA",
    "ige": "IgE", "IgE": "IgE", "IGE": "IgE",
    "总抗体": "Total Ab", "total antibody": "Total Ab",
    "中和抗体": "Neutralizing Ab", "neutralizing": "Neutralizing Ab",
}


def normalize_antibody_type(t: Optional[str]) -> Optional[str]:
    """标准化抗体类型"""
    if not t:
        return None
    t = t.strip()
    if t in ANTIBODY_TYPE_MAP:
        return ANTIBODY_TYPE_MAP[t]
    # 模糊匹配
    t_lower = t.lower()
    for key, value in ANTIBODY_TYPE_MAP.items():
        if key.lower() in t_lower or t_lower in key.lower():
            return value
    return t


# ==================== 省份名称标准化映射 ====================
PROVINCE_MAP: dict[str, str] = {
    "北京": "北京", "北京市": "北京", "Beijing": "北京",
    "天津": "天津", "天津市": "天津", "Tianjin": "天津",
    "上海": "上海", "上海市": "上海", "Shanghai": "上海",
    "重庆": "重庆", "重庆市": "重庆", "Chongqing": "重庆",
    "河北": "河北", "河北省": "河北", "Hebei": "河北",
    "山西": "山西", "山西省": "山西", "Shanxi": "山西",
    "内蒙古": "内蒙古", "内蒙古自治区": "内蒙古", "Inner Mongolia": "内蒙古",
    "辽宁": "辽宁", "辽宁省": "辽宁", "Liaoning": "辽宁",
    "吉林": "吉林", "吉林省": "吉林", "Jilin": "吉林",
    "黑龙江": "黑龙江", "黑龙江省": "黑龙江", "Heilongjiang": "黑龙江",
    "江苏": "江苏", "江苏省": "江苏", "Jiangsu": "江苏",
    "浙江": "浙江", "浙江省": "浙江", "Zhejiang": "浙江",
    "安徽": "安徽", "安徽省": "安徽", "Anhui": "安徽",
    "福建": "福建", "福建省": "福建", "Fujian": "福建",
    "江西": "江西", "江西省": "江西", "Jiangxi": "江西",
    "山东": "山东", "山东省": "山东", "Shandong": "山东",
    "河南": "河南", "河南省": "河南", "Henan": "河南",
    "湖北": "湖北", "湖北省": "湖北", "Hubei": "湖北",
    "湖南": "湖南", "湖南省": "湖南", "Hunan": "湖南",
    "广东": "广东", "广东省": "广东", "Guangdong": "广东",
    "广西": "广西", "广西壮族自治区": "广西", "Guangxi": "广西",
    "海南": "海南", "海南省": "海南", "Hainan": "海南",
    "四川": "四川", "四川省": "四川", "Sichuan": "四川",
    "贵州": "贵州", "贵州省": "贵州", "Guizhou": "贵州",
    "云南": "云南", "云南省": "云南", "Yunnan": "云南",
    "西藏": "西藏", "西藏自治区": "西藏", "Tibet": "西藏",
    "陕西": "陕西", "陕西省": "陕西", "Shaanxi": "陕西",
    "甘肃": "甘肃", "甘肃省": "甘肃", "Gansu": "甘肃",
    "青海": "青海", "青海省": "青海", "Qinghai": "青海",
    "宁夏": "宁夏", "宁夏回族自治区": "宁夏", "Ningxia": "宁夏",
    "新疆": "新疆", "新疆维吾尔自治区": "新疆", "Xinjiang": "新疆",
    "台湾": "台湾", "台湾省": "台湾", "Taiwan": "台湾",
    "香港": "香港", "香港特别行政区": "香港", "Hong Kong": "香港",
    "澳门": "澳门", "澳门特别行政区": "澳门", "Macau": "澳门",
    # 省份简称
    "京": "北京", "津": "天津", "沪": "上海", "渝": "重庆",
    "冀": "河北", "晋": "山西", "蒙": "内蒙古", "辽": "辽宁",
    "吉": "吉林", "黑": "黑龙江", "苏": "江苏", "浙": "浙江",
    "皖": "安徽", "闽": "福建", "赣": "江西", "鲁": "山东",
    "豫": "河南", "鄂": "湖北", "湘": "湖南", "粤": "广东",
    "桂": "广西", "琼": "海南", "川": "四川", "蜀": "四川",
    "黔": "贵州", "贵": "贵州", "滇": "云南", "云": "云南",
    "藏": "西藏", "陕": "陕西", "秦": "陕西", "甘": "甘肃",
    "陇": "甘肃", "青": "青海", "宁": "宁夏", "新": "新疆",
    "台": "台湾", "港": "香港", "澳": "澳门",
}

CHINA_PROVINCE_NAMES = sorted(set(PROVINCE_MAP.values()))

PROVINCE_NAMES_ZH = "、".join(CHINA_PROVINCE_NAMES)


def normalize_province(name: Optional[str]) -> Optional[str]:
    """标准化省份名称，将 LLM 提取的各种表述统一为省份名"""
    if not name:
        return None
    name = name.strip()
    # 精确匹配
    if name in PROVINCE_MAP:
        return PROVINCE_MAP[name]
    # 模糊匹配：key 包含在 name 中
    for key, value in PROVINCE_MAP.items():
        if key in name or name in key:
            return value
    # 带"省"/"市"/"自治区"后缀的清理
    name_clean = name.replace("省", "").replace("市", "").replace("自治区", "").replace("特别行政区", "").strip()
    if name_clean in PROVINCE_MAP:
        return PROVINCE_MAP[name_clean]
    for key, value in PROVINCE_MAP.items():
        if key in name_clean or name_clean in key:
            return value
    return name
