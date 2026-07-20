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
