import logging

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
    # ---- 流脑 (meningitis)：所有脑膜炎奈瑟菌血清群合并 ----
    "流脑": "meningitis", "流行性脑脊髓膜炎": "meningitis", "脑膜炎球菌": "meningitis",
    "meningitis": "meningitis", "Meningitis": "meningitis",
    "Meningococcal Disease": "meningitis", "N. meningitidis": "meningitis",
    "脑膜炎奈瑟菌": "meningitis", "脑膜炎奈瑟菌（A群）": "meningitis",
    "脑膜炎奈瑟菌（C群）": "meningitis", "脑膜炎奈瑟菌（Y群）": "meningitis",
    "脑膜炎奈瑟菌（W135群）": "meningitis", "A群脑膜炎奈瑟菌": "meningitis",
    "C群脑膜炎奈瑟菌": "meningitis", "Y群脑膜炎奈瑟菌": "meningitis",
    "W135群脑膜炎奈瑟菌": "meningitis",
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

    # ---- 麻腮风（MMR 联合疫苗）→ 麻疹 (measles) ----
    # 麻腮风是三联疫苗，针对麻疹、腮腺炎、风疹。
    # 血清流行病学数据中"麻腮风"通常指麻疹抗体（MMR 中首个且最主要疾病），
    # 同时支持腮腺炎和风疹的模糊匹配（见下方对应条目）。
    "麻腮风": "measles", "麻腮风疫苗": "measles", "麻腮": "measles",
    "MMR": "measles", "MMR vaccine": "measles", "mmr": "measles",
    "MMR疫苗": "measles", "MMR 疫苗": "measles",

    # ============ 非标准疾病：别名 → 中文标准名 ============
    # ---- 丙肝 ----
    "丙肝": "丙肝", "丙型肝炎": "丙肝", "丙型病毒性肝炎": "丙肝",
    "丙肝病毒": "丙肝", "HCV": "丙肝", "hcv": "丙肝", "Hepatitis C": "丙肝",
    # ---- 丁肝 ----
    "丁肝": "丁型肝炎", "丁型肝炎": "丁型肝炎", "丁型病毒性肝炎": "丁型肝炎",
    "丁肝病毒": "丁型肝炎", "HDV": "丁型肝炎", "hdv": "丁型肝炎", "Hepatitis D": "丁型肝炎",
    "hepatitis d": "丁型肝炎",
    # ---- 戊肝 ----
    "戊肝": "戊肝", "戊型肝炎": "戊肝", "戊型病毒性肝炎": "戊肝",
    "戊肝病毒": "戊肝", "HEV": "戊肝", "hev": "戊肝", "Hepatitis E": "戊肝",
    # ---- 乙型脑炎 ----
    "乙型脑炎": "乙型脑炎", "流行性乙型脑炎": "乙型脑炎", "乙脑": "乙型脑炎",
    "日本脑炎": "乙型脑炎", "Japanese Encephalitis": "乙型脑炎", "JEV": "乙型脑炎",
    # ---- 结核病（所有结核相关 → 结核病）----
    "结核病": "结核病", "结核分枝杆菌": "结核病", "结核菌": "结核病",
    "Mycobacterium tuberculosis": "结核病", "TB": "结核病",
    "结核": "结核病", "儿童结核": "结核病", "肺结核": "结核病",
    "肺结核（自身免疫抗体）": "结核病", "淋巴结结核": "结核病",
    "潜伏性肺结核": "结核病", "淋巴结核": "结核病",
    "肺外结核": "结核病", "骨结核": "结核病",
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

    # ---- 肾综合征出血热 ----
    "肾综合征出血热": "肾综合征出血热", "流行性出血热": "肾综合征出血热",
    "出血热": "肾综合征出血热", "汉坦病毒": "肾综合征出血热",
    "汉坦病毒抗体": "肾综合征出血热", "Hantavirus": "肾综合征出血热",
    "HFRS": "肾综合征出血热", "hfrs": "肾综合征出血热",
    # ---- 登革热 ----
    "登革热": "登革热", "登革病毒": "登革热",
    "Dengue": "登革热", "Dengue Virus": "登革热", "DENV": "登革热",
    # ---- 寨卡病毒 ----
    "寨卡病毒": "寨卡病毒", "寨卡": "寨卡病毒",
    "Zika": "寨卡病毒", "Zika Virus": "寨卡病毒", "ZIKV": "寨卡病毒",
    # ---- 黄热病毒 ----
    "黄热病毒": "黄热病毒", "黄热病": "黄热病毒",
    "Yellow Fever": "黄热病毒", "YFV": "黄热病毒",
    # ---- 乙脑（乙型脑炎，已在上文） ----
    # ---- 马尔尼菲篮状菌 ----
    "马尔尼菲篮状菌": "马尔尼菲篮状菌", "马尔尼菲青霉菌": "马尔尼菲篮状菌",
    "Penicillium marneffei": "马尔尼菲篮状菌", "Talaromyces marneffei": "马尔尼菲篮状菌",
    # ---- 李斯特菌 ----
    "李斯特菌": "李斯特菌", "单核细胞增生李斯特菌": "李斯特菌",
    "Listeria monocytogenes": "李斯特菌", "Listeria": "李斯特菌",
    # ---- 弓形虫（已在上文） ----
    # ---- 疟疾 ----
    "疟疾": "疟疾", "疟原虫": "疟疾",
    "Plasmodium": "疟疾", "Malaria": "疟疾",
    # ---- 血吸虫 ----
    "血吸虫": "血吸虫", "血吸虫病": "血吸虫",
    "Schistosoma": "血吸虫", "Schistosomiasis": "血吸虫",
    # ---- 华支睾吸虫 ----
    "华支睾吸虫": "华支睾吸虫", "肝吸虫": "华支睾吸虫",
    "Clonorchis sinensis": "华支睾吸虫",
    # ---- 蛔虫 ----
    "蛔虫": "蛔虫", "蛔虫病": "蛔虫",
    "Ascaris lumbricoides": "蛔虫",
    # ---- 钩虫 ----
    "钩虫": "钩虫", "钩虫病": "钩虫",
    "Ancylostoma": "钩虫", "Necator": "钩虫",
    # ---- 丝虫 ----
    "丝虫": "丝虫", "丝虫病": "丝虫",
    "Filariasis": "丝虫", "Brugia": "丝虫", "Wuchereria": "丝虫",
    # ---- 包虫 ----
    "包虫": "包虫", "包虫病": "包虫", "棘球蚴病": "包虫",
    "Echinococcus": "包虫", "Hydatid": "包虫",
    # ---- 囊虫 ----
    "囊虫": "囊虫", "囊虫病": "囊虫", "猪带绦虫": "囊虫",
    "Taenia solium": "囊虫", "Cysticercosis": "囊虫",

    # ============ 2026-09-22 扩充：合并同义疾病 + 补充缺失别名 ============
    # ---- 肺炎支原体 ----
    "肺炎支原体": "肺炎支原体", "肺炎支原体肺炎": "肺炎支原体",
    "Mycoplasma pneumoniae": "肺炎支原体",
    # ---- 布鲁氏菌病（人兽共患，牛/羊/猪型合并）----
    "布鲁氏菌病": "布鲁氏菌病", "布鲁氏菌": "布鲁氏菌病",
    "布病": "布鲁氏菌病", "Brucellosis": "布鲁氏菌病",
    "牛布鲁氏菌病": "布鲁氏菌病", "羊布鲁氏菌病": "布鲁氏菌病",
    "猪布鲁氏菌病": "布鲁氏菌病",
    # ---- 森林脑炎 ----
    "森林脑炎": "森林脑炎", "蜱传脑炎": "森林脑炎",
    "Tick-borne Encephalitis": "森林脑炎", "TBE": "森林脑炎",
    # ---- 口蹄疫（兽医，含不同型别）----
    "口蹄疫": "口蹄疫", "口蹄疫病毒": "口蹄疫",
    "O型口蹄疫": "口蹄疫", "A型口蹄疫": "口蹄疫",
    "Asia1型口蹄疫": "口蹄疫", "FMDV": "口蹄疫",
    # ---- 肺炎（合并肺炎球菌感染等）----
    "肺炎": "肺炎", "肺炎球菌": "肺炎", "肺炎球菌（1型）": "肺炎",
    "肺炎链球菌": "肺炎",
    # ---- 腺病毒感染（合并各型别）----
    "腺病毒": "腺病毒感染", "腺病毒（Adenovirus）": "腺病毒感染",
    "人腺病毒": "腺病毒感染", "人腺病毒5型": "腺病毒感染",
    "Adenovirus": "腺病毒感染", "ADV": "腺病毒感染",
    # ---- 莱姆病 ----
    "莱姆病": "莱姆病", "伯氏疏螺旋体": "莱姆病",
    "Lyme Disease": "莱姆病",
    # ---- 发热伴血小板减少综合征（SFTS）----
    "发热伴血小板减少综合征": "发热伴血小板减少综合征",
    "SFTS": "发热伴血小板减少综合征", "新布尼亚病毒": "发热伴血小板减少综合征",
    # ---- 斑点热 ----
    "斑点热": "斑点热", "斑点热立克次体病": "斑点热",
    "Rickettsialpox": "斑点热",
    # ---- 虫媒病毒（泛称）----
    "虫媒病毒": "虫媒病毒", "虫媒病毒病": "虫媒病毒",
    # ---- 呼吸道感染（泛称）----
    "呼吸道感染": "呼吸道感染", "呼吸道病原体（9种）": "呼吸道感染",
    "呼吸道病原体": "呼吸道感染",
    # ---- 病毒性肝炎（泛称）----
    "病毒性肝炎": "病毒性肝炎", "肝炎": "病毒性肝炎",
    # ---- 柯萨奇病毒（CV）→ 手足口（hfmd）----
    "柯萨奇病毒A16型": "hfmd", "柯萨奇病毒（CV）": "hfmd",
    # ---- 幽门螺旋菌感染 ----
    "幽门螺旋菌感染": "幽门螺旋菌感染", "幽门螺旋杆菌": "幽门螺旋菌感染",
    "Helicobacter pylori": "幽门螺旋菌感染", "Hp": "幽门螺旋菌感染",
    # ---- 人细小病毒B19 ----
    "人细小病毒B19": "人细小病毒B19", "细小病毒B19": "人细小病毒B19",
    "Parvovirus B19": "人细小病毒B19",
    # ---- 诺如病毒 ----
    "诺如病毒": "诺如病毒", "诺瓦克病毒": "诺如病毒", "Norovirus": "诺如病毒",
    # ---- 霍乱 ----
    "霍乱": "霍乱", "霍乱弧菌": "霍乱", "Cholera": "霍乱",
    # ---- 变应性鼻炎 / 过敏性疾病（泛称，保留）----
    "变应性鼻炎": "变应性鼻炎", "过敏性疾病": "过敏性疾病",
    # ---- SARS（保留独立，与新冠区分）----
    "SARS": "SARS", "严重急性呼吸综合征": "SARS",
    # ---- 兽医类（非人源，保留但统一拼写）----
    "犬瘟热": "犬瘟热", "犬细小病毒": "犬细小病毒",
    "猪瘟": "猪瘟", "猪霍乱": "猪瘟",
    "猪繁殖与呼吸综合征": "猪繁殖与呼吸综合征", "猪繁殖与呼吸综合征病毒": "猪繁殖与呼吸综合征",
    "猪流行性腹泻": "猪流行性腹泻", "猪流行性腹泻病毒": "猪流行性腹泻",
    "猪传染性胃肠炎病毒": "猪传染性胃肠炎病毒",
    "猪链球菌2型": "猪链球菌2型",
    "副猪嗜血杆菌病": "副猪嗜血杆菌病",
    "胸膜肺炎放线杆菌": "胸膜肺炎放线杆菌",
    "新城疫": "新城疫", "Newcastle Disease": "新城疫",
    "奶牛副结核": "奶牛副结核", "副结核杆菌": "奶牛副结核",
    "小反刍兽疫": "小反刍兽疫", "PPR": "小反刍兽疫",
    "非洲猪瘟": "非洲猪瘟", "ASF": "非洲猪瘟",
    # ---- 猴病毒类（非人源）----
    "STLV-1（猴T细胞淋巴病毒1型）": "猴T细胞淋巴病毒1型",
    "猴T细胞淋巴病毒1型（STLV-1）": "猴T细胞淋巴病毒1型",
    "猴T细胞淋巴病毒1型": "猴T细胞淋巴病毒1型",
    "猴泡沫病毒（SFV）": "猴泡沫病毒",
    "猕猴疱疹病毒1型（MaHV-1）": "猕猴疱疹病毒1型",
    "猴免疫缺陷病毒（SIV）": "猴免疫缺陷病毒",
    "猴病毒40（SV40）": "猴病毒40",
    "B病毒（BV）": "猕猴疱疹病毒1型",  # BV = 猴疱疹病毒（同物异名）
    "蜱媒传染病复合感染": "蜱媒传染病复合感染",
    # ---- 泛称/非疾病项（保留原样，后续可清理）----
    "疫苗接种覆盖率": "疫苗接种覆盖率",
    "疫苗可预防疾病": "疫苗可预防疾病",
    "计划免疫（IgG抗体，具体病种表头缺失）": "计划免疫（IgG抗体，具体病种表头缺失）",
    "中枢神经系统感染性疾病": "中枢神经系统感染性疾病",
}


def normalize_disease(name: str | None) -> str | None:
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
        if len(key) >= 2 and key.lower() in name_lower and (best_key is None or len(key) > len(best_key)):
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


def normalize_method(method: str | None) -> str | None:
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


def normalize_antibody_type(t: str | None) -> str | None:
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
    # 全国级汇总
    "中国": "全国", "中华人民共和国": "全国", "全国": "全国",
}

CHINA_PROVINCE_NAMES = sorted(set(PROVINCE_MAP.values()))

PROVINCE_NAMES_ZH = "、".join(CHINA_PROVINCE_NAMES)

# 常见城市名排除集：命中此集合的输入不参与省份简称模糊匹配，避免"南京"含"京"误归北京等 bug
_CITY_EXCLUSION = {
    "南京", "上海", "广州", "深圳", "杭州", "郑州", "成都", "兰州", "贵阳",
    "沈阳", "长春", "哈尔滨", "福州", "南昌", "长沙", "武汉", "西安",
    "石家庄", "合肥", "太原", "呼和浩特", "南宁", "海口", "昆明", "拉萨",
    "西宁", "银川", "乌鲁木齐", "济南", "青岛", "大连", "厦门", "宁波",
    "苏州", "无锡", "佛山", "东莞", "温州", "常州", "徐州", "洛阳",
    "邯郸", "保定", "大同", "包头", "珠海", "中山", "惠州", "嘉兴",
    "绍兴", "南通", "扬州", "镇江", "台州", "金华", "宜昌", "襄阳",
    "柳州", "桂林", "遵义", "曲靖", "咸阳", "宝鸡", "绵阳",
}


def normalize_province(name: str | None) -> str | None:
    """标准化省份名称，将 LLM 提取的各种表述统一为省份名"""
    if not name:
        return None
    name = name.strip()

    # 1. 精确匹配（含全名、简称、英文名）
    if name in PROVINCE_MAP:
        return PROVINCE_MAP[name]

    # 2. 带"省"/"自治区"/"特别行政区"后缀的精确匹配
    name_clean = (
        name.replace("省", "")
        .replace("自治区", "")
        .replace("特别行政区", "")
        .strip()
    )
    if name_clean in PROVINCE_MAP:
        return PROVINCE_MAP[name_clean]

    # 3. 城市名排除：以"市"结尾或命中排除集的输入，仅尝试去掉"市"后精确匹配，不做简称模糊匹配
    if name.endswith("市") or name in _CITY_EXCLUSION:
        if name.endswith("市"):
            city_clean = name[:-1].strip()
            if city_clean in PROVINCE_MAP:
                return PROVINCE_MAP[city_clean]
        return name

    # 4. 模糊匹配：仅使用长 key（>2字符），避免单字简称误伤城市名
    for key, value in PROVINCE_MAP.items():
        if len(key) > 2 and (key in name or name in key):
            return value

    return name
