import logging
import re
from typing import Optional

logger = logging.getLogger("uvicorn")

# ==================== 疾病名称标准化映射 ====================
# 15 种标准疾病：别名 → 英文 key（与前端 DISEASES 常量的 key 一致）
# 非标准疾病：别名 → 中文标准名（前端无对应常量，直接显示中文）
DISEASE_MAP: dict[str, str] = {
    # ---- 麻疹 (measles) ----
    "麻疹": "measles", "麻诊": "measles", "measles": "measles", "Measles": "measles",
    "麻疹病毒": "measles", "Measles Virus": "measles", "MV": "measles",
    "rubeola": "measles", "Rubeola": "measles",
    # ---- 腮腺炎 (mumps) ----
    "腮腺炎": "mumps", "流行性腮腺炎": "mumps", "mumps": "mumps", "Mumps": "mumps",
    "腮腺炎病毒": "mumps", "Mumps Virus": "mumps", "MuV": "mumps",
    # ---- 风疹 (rubella) ----
    "风疹": "rubella", "rubella": "rubella", "Rubella": "rubella",
    "风疹病毒": "rubella", "Rubella Virus": "rubella", "RV": "rubella",
    "German Measles": "rubella", " german measles": "rubella",
    # ---- 百日咳 (pertussis) ----
    "百日咳": "pertussis", "pertussis": "pertussis", "Pertussis": "pertussis",
    "百日咳杆菌": "pertussis", "Bordetella pertussis": "pertussis", "PT": "pertussis",
    # ---- 白喉 (diphtheria) ----
    "白喉": "diphtheria", "diphtheria": "diphtheria", "Diphtheria": "diphtheria",
    "白喉杆菌": "diphtheria", "Corynebacterium diphtheriae": "diphtheria", "DT": "diphtheria",
    # ---- 破伤风 (tetanus) ----
    "破伤风": "tetanus", "tetanus": "tetanus", "Tetanus": "tetanus",
    "破伤风杆菌": "tetanus", "Clostridium tetani": "tetanus",
    "破伤风毒素": "tetanus", "TT": "tetanus",
    # ---- 乙肝 (hepatitis_b) ----
    "乙肝": "hepatitis_b", "乙型肝炎": "hepatitis_b", "乙型病毒性肝炎": "hepatitis_b",
    "乙肝病毒": "hepatitis_b", "hepatitis b": "hepatitis_b", "hepatitis_b": "hepatitis_b",
    "Hepatitis B": "hepatitis_b", "HBV": "hepatitis_b", "hbv": "hepatitis_b",
    # ---- 甲肝 (hepatitis_a) ----
    "甲肝": "hepatitis_a", "甲型肝炎": "hepatitis_a", "甲型病毒性肝炎": "hepatitis_a",
    "甲肝病毒": "hepatitis_a", "hepatitis a": "hepatitis_a", "hepatitis_a": "hepatitis_a",
    "Hepatitis A": "hepatitis_a", "HAV": "hepatitis_a", "hav": "hepatitis_a",
    # ---- 脊灰 (polio) ----
    "脊灰": "polio", "脊髓灰质炎": "polio", "小儿麻痹症": "polio",
    "脊髓灰质炎病毒": "polio", "polio": "polio", "Polio": "polio",
    "Polimyelitis": "polio", "Poliomyelitis": "polio", "Poliovirus": "polio", "PV": "polio",
    # ---- 流感 (influenza) ----
    "流感": "influenza", "流行性感冒": "influenza", "流感病毒": "influenza",
    "influenza": "influenza", "Influenza": "influenza", "Influenza Virus": "influenza",
    "Flu": "influenza", "flu": "influenza",
    "甲型流感": "influenza", "乙型流感": "influenza", "H1N1": "influenza", "H3N2": "influenza",
    # ---- 新冠 (covid19) ----
    "新冠": "covid19", "新冠肺炎": "covid19", "新冠病毒": "covid19",
    "新型冠状病毒": "covid19", "新型冠状病毒感染": "covid19",
    "COVID-19": "covid19", "covid-19": "covid19", "covid19": "covid19",
    "SARS-CoV-2": "covid19", "SARS-CoV2": "covid19",
    # ---- 流脑 (meningitis) ----
    "流脑": "meningitis", "流行性脑脊髓膜炎": "meningitis", "脑膜炎球菌": "meningitis",
    "meningitis": "meningitis", "Meningitis": "meningitis",
    "Meningococcal Disease": "meningitis", "N. meningitidis": "meningitis",
    # ---- 水痘 (varicella) ----
    "水痘": "varicella", "水痘病毒": "varicella", "水痘-带状疱疹病毒": "varicella",
    "varicella": "varicella", "Varicella": "varicella",
    "Varicella Zoster Virus": "varicella", "VZV": "varicella", "chickenpox": "varicella",
    # ---- 手足口 (hfmd) ----
    "手足口": "hfmd", "手足口病": "hfmd", "手足口病病毒": "hfmd",
    "hfmd": "hfmd", "HFMD": "hfmd",
    "肠道病毒71型": "hfmd", "EV71": "hfmd",
    "Coxsackievirus A16": "hfmd", "CA16": "hfmd",
    # ---- 轮状病毒 (rotavirus) ----
    "轮状病毒": "rotavirus", "轮状病毒疫苗": "rotavirus",
    "rotavirus": "rotavirus", "Rotavirus": "rotavirus", "Rotavirus Vaccine": "rotavirus",
    "RVV": "rotavirus",

    # ============ 非标准疾病：别名 → 中文标准名 ============
    # ---- 丙肝 ----
    "丙肝": "丙肝", "丙型肝炎": "丙肝", "丙型病毒性肝炎": "丙肝",
    "丙肝病毒": "丙肝", "HCV": "丙肝", "hcv": "丙肝", "Hepatitis C": "丙肝",
    # ---- 戊肝 ----
    "戊肝": "戊肝", "戊型肝炎": "戊肝", "戊型病毒性肝炎": "戊肝",
    "戊肝病毒": "戊肝", "HEV": "戊肝", "hev": "戊肝", "Hepatitis E": "戊肝",
    # ---- 乙型脑炎 ----
    "乙型脑炎": "乙型脑炎", "流行性乙型脑炎": "乙型脑炎", "乙脑": "乙型脑炎",
    "日本脑炎": "乙型脑炎", "Japanese Encephalitis": "乙型脑炎", "JEV": "乙型脑炎",
    # ---- 结核病 ----
    "结核病": "结核病", "结核分枝杆菌": "结核病", "结核菌": "结核病",
    "Mycobacterium tuberculosis": "结核病", "TB": "结核病",
    # ---- EB 病毒感染 ----
    "EB病毒感染": "EB病毒感染", "EB病毒": "EB病毒感染",
    "Epstein-Barr Virus": "EB病毒感染", "EBV": "EB病毒感染",
    # ---- 巨细胞病毒感染 ----
    "巨细胞病毒感染": "巨细胞病毒感染", "巨细胞病毒": "巨细胞病毒感染",
    "Cytomegalovirus": "巨细胞病毒感染", "CMV": "巨细胞病毒感染",
    # ---- 单纯疱疹 ----
    "单纯疱疹": "单纯疱疹", "单纯疱疹病毒": "单纯疱疹",
    "单纯疱疹病毒Ⅰ型": "单纯疱疹", "单纯疱疹病毒Ⅱ型": "单纯疱疹",
    "单纯疱疹病毒Ⅰ型感染": "单纯疱疹", "单纯疱疹病毒Ⅱ型感染": "单纯疱疹",
    "单纯疱疹病毒感染（总）": "单纯疱疹", "单纯疱疹病毒感染(总)": "单纯疱疹",
    "Herpes Simplex Virus": "单纯疱疹", "HSV": "单纯疱疹",
    # ---- 弓形虫感染 ----
    "弓形虫感染": "弓形虫感染", "弓形虫": "弓形虫感染",
    "Toxoplasma": "弓形虫感染", "Toxoplasmosis": "弓形虫感染",
    # ---- 狂犬病 ----
    "狂犬病": "狂犬病", "狂犬病毒": "狂犬病", "Rabies Virus": "狂犬病", "Rabies": "狂犬病",
    # ---- 梅毒 ----
    "梅毒": "梅毒", "梅毒螺旋体": "梅毒", "梅毒抗体": "梅毒",
    "Treponema pallidum": "梅毒", "Syphilis": "梅毒", "TP": "梅毒",
    # ---- 艾滋病 ----
    "艾滋病": "艾滋病", "获得性免疫缺陷综合征": "艾滋病", "艾滋病病毒": "艾滋病",
    "AIDS": "艾滋病", "HIV": "艾滋病", "HIV抗体": "艾滋病",
    "人类免疫缺陷病毒": "艾滋病", "Human Immunodeficiency Virus": "艾滋病",
    # ---- 混合感染（归入主要疾病） ----
    "巨细胞病毒和弓形虫混合感染": "巨细胞病毒感染",
    "单纯疱疹病毒Ⅱ型和弓形虫混合感染": "单纯疱疹",
}


def normalize_disease(name: Optional[str]) -> Optional[str]:
    """标准化疾病名称。

    匹配优先级：
      1. 精确匹配（大小写敏感）
      2. 精确匹配（大小写不敏感）
      3. 模糊匹配：name 包含某个 key（按 key 长度降序，选最长匹配）
    """
    if not name:
        return None
    name = name.strip()
    # 1. 精确匹配
    if name in DISEASE_MAP:
        return DISEASE_MAP[name]
    # 2. 大小写不敏感精确匹配
    name_lower = name.lower()
    for key, value in DISEASE_MAP.items():
        if key.lower() == name_lower:
            return value
    # 3. 模糊匹配：name 包含某个 key（按 key 长度降序，选最长匹配）
    #    只检查 name 是否包含 key（单向），避免短缩写词误匹配
    #    如 "CMV" 不会被 "MV" 误匹配为 "measles"
    best_key = None
    best_value = None
    for key, value in DISEASE_MAP.items():
        if len(key) >= 2 and key.lower() in name_lower:
            if best_key is None or len(key) > len(best_key):
                best_key = key
                best_value = value
    if best_value is not None:
        return best_value
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
