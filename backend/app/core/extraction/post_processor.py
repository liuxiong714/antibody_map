"""后处理（从原 app.core.llm_extractor 拆分）。

包含：
- 模块级 _parse_titer_cell（滴度单元格归一化）
- PostProcessorMixin：字段别名归一化、数值解析、数据点后处理、滴度矩阵校验
"""

import logging
import re
from typing import Any

from app.core.term_normalizer import (
    normalize_antibody_type,
    normalize_disease,
    normalize_method,
    normalize_province,
)

logger = logging.getLogger("uvicorn")


def _parse_titer_cell(cell: Any) -> float | None:
    """把滴度矩阵单元格归一化为数值。

    - 数字直接返回（float）
    - "<10"、"<20" 等低于检出限 → 0
    - "-"、""、"·"、None、无法解析 → None（缺失）
    """
    if cell is None:
        return None
    if isinstance(cell, bool):
        return None
    if isinstance(cell, (int, float)):
        return float(cell)
    s = str(cell).strip().replace("，", ",").replace("：", ":")
    if s == "" or s in ("-", "—", "–", "/", "·", "NA", "n/a", "N/A", "null", "None", "nan"):
        return None
    # "<10" / "<20" / "≤10" 等低于检出限表达
    m = re.match(r"^[<≤]\s*([0-9.]+)$", s)
    if m:
        return 0.0
    try:
        return float(s)
    except ValueError:
        return None


class PostProcessorMixin:
    """后处理：字段别名归一化、数值解析、数据点标准化与滴度矩阵校验。"""

    # C-2026-09-05：方法学/判定阈值伪数据点特征词。
    # 本地模型常把检测判定标准段（如 "Measles: <50 IU/l (undetectable), 50–<200 IU/l (seronegative)..."）
    # 中的 cut-off 阈值误当作数据点提取。此类伪点特征：source_context 命中方法学判定特征词，
    # 且缺少样本量（真实研究数据点通常有样本量；方法学 cut-off 没有）。
    METHODOLOGY_MARKERS = (
        "undetectable", "seronegative", "equivocal", "seropositive",
        "cut-off", "cutoff", "detection limit", "serological testing",
        "检出限", "不可检测", "判定标准", "判定为阴性", "判定为阳性",
    )

    def _filter_methodology_pseudo_points(self, results: list[dict]) -> list[dict]:
        """清洗方法学/判定阈值类伪数据点（cut-off、检出限分级说明）。

        判定规则（保守，避免误伤真实 GMC/阳性率数据）：
        1. source_context 命中方法学判定特征词（undetectable/seronegative/cut-off/检出限等）
        2. 且样本量缺失（真实研究数据点通常带样本量，判定标准说明没有）
        同时满足才丢弃；只记录日志，不抛异常。
        """
        kept: list[dict] = []
        dropped = 0
        for dp in results:
            ctx = str(dp.get("source_context") or "").lower()
            sample = dp.get("sample_size")
            if sample in (None, "") and any(m in ctx for m in self.METHODOLOGY_MARKERS):
                dropped += 1
                logger.info(
                    f"C-方法学伪点清洗：丢弃 cut-off/判定标准类数据点 "
                    f"disease={dp.get('disease_name')} "
                    f"value={dp.get('positivity_rate') or dp.get('gmc_value')} "
                    f"ctx={ctx[:60]!r}"
                )
                continue
            kept.append(dp)
        if dropped:
            logger.info(
                f"C-方法学伪点清洗：过滤 {dropped} 个判定阈值类伪数据点，保留 {len(kept)} 个"
            )
        return kept

    @staticmethod
    def _detect_truncation(val) -> str | None:
        """F19：检测截断标记（"<"=低于检出限 / ">"=高于检出限）。

        截断值（如 >80、<10）表达的是区间而非精确值，直接入库会在统计中
        被误当精确值。此方法返回 "<"/">"，None 表示非截断。
        """
        if val is None or isinstance(val, (int, float, bool)):
            return None
        s = str(val).strip()
        if not s:
            return None
        if s.startswith(("<", "≤")):
            return "<"
        if s.startswith((">", "≥")):
            return ">"
        return None

    # F19：GMC 单位统一换算表（换算系数 = 目标 IU/ml 倍数）。
    # 1 IU = 1000 mIU，故 mIU/ml → IU/ml 需 ÷1000。
    # key 为 re.sub(r"[^a-zA-Z0-9]", "", unit).lower() 后的结果，
    # 即去掉分隔符的纯字母数字形态。
    _GMC_UNIT_CONVERSION: dict[str, float] = {  # noqa: RUF012
        "miuml": 1 / 1000.0,
        "miul": 1 / 1000.0,
        "miuperml": 1 / 1000.0,
    }

    @staticmethod
    def _normalize_gmc_unit(unit: str | None) -> str | None:
        """F19：GMC 单位统一换算，返回 (已换算值, 标准单位)。"""
        if not unit:
            return unit
        key = re.sub(r"[^a-zA-Z0-9]", "", str(unit)).lower()
        factor = PostProcessorMixin._GMC_UNIT_CONVERSION.get(key)
        if factor is None:
            return unit
        return "IU/ml"

    @staticmethod
    def _parse_float_field(val) -> float | None:
        """兼容本地模型（如 qwen2.5:14b）输出的多种数值格式。

        支持：87.3、'87.3'、'87.3%'、'87.3％'、'>80'、'<10'、'1,234'、'(87.3)' 等。
        无法解析返回 None。
        """
        if val is None:
            return None
        if isinstance(val, bool):
            return None
        if isinstance(val, (int, float)):
            return float(val)
        s = str(val).strip().replace("％", "%").replace(",", "").replace("，", "")
        # 去掉百分比与无关字符
        s = s.replace("%", "").strip()
        m = re.search(r"-?\d+(?:\.\d+)?", s)
        if m:
            return float(m.group())
        return None

    @staticmethod
    def _parse_ci_string(val) -> tuple[float | None, float | None]:
        """从 CI 字符串解析 (lower, upper)。

        F-7：优先用显式区间分隔符（- – ~ 至 到）匹配第一对数字，
        仅当失败才回退到"最后两个数字"的宽松逻辑（用于逗号分隔场景）。

        支持：'(95% CI 16.2%–19.5%)'、'95%CI: 16.2-19.5'、'[16.2, 19.5]'、
              '(95% CI 16.2-19.5, P<0.05)' 等（最后这种若用旧逻辑会吃到 "0.05"）。
        无法解析返回 (None, None)。
        """
        if val is None:
            return None, None
        t = str(val)
        # 移除置信水平前缀（95%/90%/95%CI 等）
        t = re.sub(r"9[05]\s*%?\s*(CI)?", "", t, flags=re.IGNORECASE)
        t_clean = t.replace("%", "").replace("％", "")

        # F-7 优先：显式区间分隔符（短横线 / 波浪 / 汉字 至 到）
        m = re.search(r"(-?\d+(?:\.\d+)?)\s*[-–~至到]\s*(-?\d+(?:\.\d+)?)", t_clean)
        if m:
            lo, hi = float(m.group(1)), float(m.group(2))
            return min(lo, hi), max(lo, hi)

        # 回退：宽松找所有数字取最后两个（用于逗号分隔 / 括号嵌套）
        nums = re.findall(r"-?\d+(?:\.\d+)?", t_clean)
        if len(nums) >= 2:
            vals = [float(n) for n in nums[-2:]]
            return min(vals), max(vals)
        return None, None

    @staticmethod
    def _parse_age_group_text(val) -> tuple[int | None, int | None]:
        """从 age_group 文本解析 (age_min, age_max)。

        支持格式：
          - "1-4 years" / "1-4岁" / "1-4"        → (1, 4)
          - "0–14" / "0~14" / "0至14" / "0到14"   → (0, 14)
          - "<5 years" / "<5岁" / "<5"             → (None, 4)
          - "≤5" / "<=5"                          → (None, 5)
          - "≥18" / ">=18" / "18+" / ">18"        → (18, None)
          - "Adults (18+)" / "Adults ≥18"         → (18, None)
          - "Children" / "儿童"                   → (None, None)  # 无法确定
        无法解析返回 (None, None)。
        """
        if val is None:
            return None, None
        s = str(val).strip().lower()

        # 范围格式：数字-数字 / 数字–数字 / 数字~数字 / 数字至数字 / 数字到数字
        m = re.search(r"(\d+)\s*[-–~至到]\s*(\d+)", s)
        if m:
            return int(m.group(1)), int(m.group(2))

        # 上限格式：<5 / ≤5 / <=5 / < 5 years
        m = re.search(r"[<≤]\s*(\d+)", s)
        if m:
            upper = int(m.group(1))
            # "<5 years" → max=4；"≤5" → max=5
            if "≤" in s or "<=" in s:
                return None, upper
            return None, upper - 1 if upper > 0 else None

        # 下限格式：≥18 / >=18 / 18+ / >18 / adults ≥18
        m = re.search(r"[≥>=]\s*(\d+)|(\d+)\s*\+", s)
        if m:
            num = m.group(1) or m.group(2)
            lower = int(num)
            if "≥" in s or ">=" in s or "+" in s:
                return lower, None
            return lower + 1, None

        # 单个数字（如 "5 years"）—— 当作精确年龄点，当作 min=max
        m = re.search(r"^(\d+)\s*(?:years?|岁|yrs?)?$", s)
        if m:
            n = int(m.group(1))
            return n, n

        return None, None

    @staticmethod
    def _normalize_aliases(item: dict) -> dict:
        """将本地模型常见的非标准字段名映射到标准 schema。

        背景：qwen2.5 等本地模型不支持 response_format=json_object，
        经常用自己的字段名输出（如 seroprevalence 代替 positivity_rate）。
        也处理复合字段名如 after_vaccination_positivity_rate_measles_IgG。
        """
        if not isinstance(item, dict):
            return item
        norm = dict(item)

        # 阳性率简单别名
        if norm.get("positivity_rate") is None:
            for alias in (
                # 基础别名
                "seroprevalence", "positive_rate", "positivity",
                "seropositivity", "seroprevalence_rate",
                # nemotron/gemma4 MoE 模型常用别名（带 _percent / _rate 后缀）
                "positivity_rate_percent", "positive_rate_percent",
                "seroprevalence_percent", "prevalence", "prevalence_rate",
                "percent_positive", "positive_percent",
                "infection_rate", "infection_rate_percent",
            ):
                if norm.get(alias) is not None:
                    norm["positivity_rate"] = norm[alias]
                    break

        # GMC/GMT 简单别名
        if norm.get("gmc_value") is None:
            for alias in ("gmc", "geometric_mean_concentration",
                          "geometric_mean_titer", "gmt", "gmt_value"):
                if norm.get(alias) is not None:
                    norm["gmc_value"] = norm[alias]
                    if alias in ("geometric_mean_titer", "gmt", "gmt_value"):
                        norm.setdefault("gmc_unit", "titer")
                    break

        # 疾病名称简单别名
        if not norm.get("disease_name"):
            for alias in ("virus_strain", "virus", "pathogen", "antigen"):
                if norm.get(alias):
                    norm["disease_name"] = norm[alias]
                    break

        # 置信区间字符串解析
        if norm.get("positivity_ci_lower") is None and norm.get("positivity_ci_upper") is None:
            ci = norm.get("confidence_interval") or norm.get("ci") or norm.get("positivity_ci")
            if ci:
                lo, hi = PostProcessorMixin._parse_ci_string(ci)
                if lo is not None:
                    norm["positivity_ci_lower"] = lo
                    norm["positivity_ci_upper"] = hi

        # age_group 文本 → age_min/age_max 解析（nemotron/gemma4 常用 "1-4 years" / "<5 years" 等格式）
        if (norm.get("age_min") is None and norm.get("age_max") is None
                and norm.get("age_group") is not None):
            parsed_min, parsed_max = PostProcessorMixin._parse_age_group_text(
                norm["age_group"]
            )
            if parsed_min is not None:
                norm["age_min"] = parsed_min
            if parsed_max is not None:
                norm["age_max"] = parsed_max

        # ===== 复合字段名智能匹配（宽格式数据） =====
        # 本地模型常输出宽格式：每个组一行，列名包含 disease + indicator
        # 如 after_vaccination_positivity_rate_measles_IgG
        # 如果已有 positivity_rate 则跳过（避免覆盖）
        if norm.get("positivity_rate") is not None:
            return norm

        # 扫描所有字段，找包含已知子串的复合字段名
        compound_rate_val = None
        compound_disease = None
        for key, val in list(item.items()):
            if val is None:
                continue
            if not isinstance(key, str):
                continue
            k = key.lower()
            # 复合字段名包含 positivity_rate/seroprevalence/positivity/concentration
            if (
                any(sub in k for sub in ("positivity_rate", "positivity", "seroprevalence", "seropositivity"))
                and compound_rate_val is None
                and PostProcessorMixin._parse_float_field(val) is not None
            ):
                compound_rate_val = PostProcessorMixin._parse_float_field(val)
                if not compound_disease:
                    compound_disease = PostProcessorMixin._extract_disease_from_key(key)
                    break  # 取第一个匹配

        if compound_rate_val is not None:
            norm["positivity_rate"] = compound_rate_val
            if compound_disease and not norm.get("disease_name"):
                norm["disease_name"] = compound_disease

        return norm

    @staticmethod
    def _extract_disease_from_key(key: str) -> str | None:
        """从复合字段名中提取疾病名称。

        如 after_vaccination_positivity_rate_measles_IgG → measles
           before_vaccination_concentration_rubella_IgG → rubella
        """
        known_diseases = {
            "measles": "measles",
            "rubella": "rubella", 
            "mumps": "mumps",
            "influenza": "influenza",
            "flu": "influenza",
            "covid": "covid-19",
            "sars_cov_2": "covid-19",
            "sars-cov-2": "covid-19",
            "hbv": "hepatitis b",
            "hcv": "hepatitis c",
            "hav": "hepatitis a",
            "hev": "hepatitis e",
            "hpv": "hpv",
            "hiv": "hiv",
            "tb": "tuberculosis",
            "diphtheria": "diphtheria",
            "tetanus": "tetanus",
            "pertussis": "pertussis",
            "polio": "polio",
            "japanese_encephalitis": "japanese encephalitis",
            "je": "japanese encephalitis",
            "rabies": "rabies",
            "varicella": "varicella",
            "zoster": "zoster",
            "dengue": "dengue",
            "zika": "zika",
            "yellow_fever": "yellow fever",
        }
        kl = key.lower()
        for eng, std in known_diseases.items():
            if eng in kl:
                return std
        return None

    def _post_process(self, data: dict) -> list[dict]:
        """后处理：从数组格式中提取数据点列表，并进行标准化"""
        # 新格式：data_points 数组
        points = data.get("data_points", [data] if data else [])
        if not isinstance(points, list):
            points = [data]
        if not points:
            return []

        results = []
        for item in points:
            if not isinstance(item, dict):
                continue
            # 字段别名归一化（兼容本地模型非标准字段名）
            item = self._normalize_aliases(item)
            dp = {}
            # 标准化疾病名称
            dp["disease_name"] = normalize_disease(item.get("disease_name"))
            # 标准化检测方法
            dp["detection_method"] = normalize_method(item.get("detection_method"))
            # 标准化抗体类型
            dp["antibody_type"] = normalize_antibody_type(item.get("antibody_type"))
            # 标准化省份名称
            dp["province"] = normalize_province(item.get("province"))

            # 保留其他字符串字段
            for field in ["city", "population_type", "gmc_unit",
                           "journal", "authors", "author_affiliations",
                           "source_context",
                           "parent_group"]:  # P1-1：子估计分组标识
                dp[field] = item.get(field)

            # P1-1：estimate_type 归一化（默认 primary）
            et = item.get("estimate_type")
            if et in ("primary", "subgroup"):
                dp["estimate_type"] = et
            else:
                dp["estimate_type"] = "primary"

            # 整数字段
            for field in [
                "study_start_year", "study_end_year", "sample_year",
                "age_min", "age_max", "sample_size",
                "source_page",  # 新增：来源页码
            ]:
                val = item.get(field)
                if val is not None:
                    try:
                        dp[field] = int(val)
                    except (ValueError, TypeError):
                        dp[field] = None
                else:
                    dp[field] = None

            # 浮点数字段（兼容本地模型的百分比字符串、CI 字符串等格式）
            for field in [
                "positivity_rate", "positivity_ci_lower", "positivity_ci_upper",
                "gmc_value", "gmc_ci_lower", "gmc_ci_upper",
            ]:
                dp[field] = self._parse_float_field(item.get(field))

            # F19：截断值标记（"<"=低于检出限 / ">"=高于检出限）。
            # ">80"/"<10" 表达区间而非精确值，入库仍保留数值（供审核参考），
            # 但 truncation 标记使统计/合并层识别其为截断值，不当作精确值参与计算。
            _trunc = None
            for _tf in ("positivity_rate", "gmc_value"):
                _tr = self._detect_truncation(item.get(_tf))
                if _tr is not None:
                    _trunc = _tr
                    break
            dp["truncation"] = _trunc

            # F19：GMC 单位统一换算（mIU/ml → IU/ml，÷1000）。
            # 换算后 gmc_unit 统一为 IU/ml，避免同文献/跨文献 mIU 与 IU 混用导致统计失真。
            # P0-1：换算前先保存原始值，供 grounding 回验时在原文定位 mIU 数值
            # （否则换算后 0.965 与原文 965 不匹配，grounding 必然失败）。
            if dp.get("gmc_value") is not None and dp.get("gmc_unit"):
                _key = re.sub(r"[^a-zA-Z0-9]", "", str(dp["gmc_unit"])).lower()
                _factor = self._GMC_UNIT_CONVERSION.get(_key)
                if _factor is not None:
                    dp["_gmc_value_raw"] = dp["gmc_value"]
                    dp["_gmc_unit_raw"] = dp["gmc_unit"]
                    dp["gmc_value"] = round(dp["gmc_value"] * _factor, 4)
                    dp["gmc_unit"] = "IU/ml"

            results.append(dp)

        # C-2026-09-05：清洗方法学/判定阈值类伪数据点（cut-off、检出限分级说明），
        # 避免本地模型误把检测判定标准当研究结果提取（如 "<50 IU/l 为不可检测"）。
        results = self._filter_methodology_pseudo_points(results)

        return results

    def _post_process_titer_tables(self, data: dict) -> list[dict]:
        """P2-tt 试点：从 LLM 输出中提取并校验滴度矩阵（titer_tables）。

        校验规则：
        - ref_antisera / antigens 必须为非空字符串列表
        - titers 必须是二维数值列表，且维度与 antigens×ref_antisera 一致
        - assay_type 仅接受 hi/vnt/elisa
        - confidence < 0.8 一律标记 review_status='pending' 落人工（由落库方判定）
        """
        if not isinstance(data, dict):
            return []
        raw_tables = data.get("titer_tables")
        if not isinstance(raw_tables, list) or not raw_tables:
            return []

        tables: list[dict] = []
        for i, item in enumerate(raw_tables):
            if not isinstance(item, dict):
                continue
            antigens = item.get("antigens")
            antisera = item.get("ref_antisera")
            titers = item.get("titers")
            # 基础结构校验
            if not (isinstance(antigens, list) and isinstance(antisera, list)):
                continue
            if not (antigens and antisera):
                continue
            if not isinstance(titers, list) or len(titers) != len(antigens):
                logger.warning(f"P2-tt 表格#{i+1} 行数不匹配，跳过: {len(titers)} != {len(antigens)}")
                continue

            # 逐单元格归一化数值
            n_rows = len(titers)
            n_cols = len(antisera)
            norm_titers: list[list[float | None]] = []
            valid = True
            for r in range(n_rows):
                row = titers[r]
                if not isinstance(row, list) or len(row) != n_cols:
                    logger.warning(f"P2-tt 表格#{i+1} 第{r}行列数不匹配，跳过")
                    valid = False
                    break
                norm_row: list[float | None] = []
                for cell in row:
                    norm_row.append(_parse_titer_cell(cell))
                norm_titers.append(norm_row)
            if not valid:
                continue

            # assay_type 归一化
            assay_raw = str(item.get("assay_type") or "").strip().lower()
            assay_map = {"hi": "hi", "hai": "hi", "vnt": "vnt", "nt": "vnt", "elisa": "elisa"}
            assay_type = assay_map.get(assay_raw)
            if assay_type is None:
                logger.warning(f"P2-tt 表格#{i+1} 未知 assay_type={assay_raw!r}，跳过")
                continue

            # 置信度归一化（0-1，非数值默认 0.5 落人工）
            conf_raw = item.get("confidence")
            try:
                confidence = float(conf_raw)
                if not (0 <= confidence <= 1):
                    confidence = 0.5
            except (TypeError, ValueError):
                confidence = 0.5

            tables.append({
                "assay_type": assay_type,
                "ref_antisera": [str(s).strip() for s in antisera],
                "antigens": [str(a).strip() for a in antigens],
                "titers": norm_titers,
                "unit": item.get("unit"),
                "source_page": item.get("source_page"),
                "source_context": item.get("source_context"),
                "confidence": round(confidence, 3),
                # 置信度 < 0.8 一律落人工审核
                "review_status": "pending",
                "needs_manual_review": confidence < 0.8,
                "quality_score": round(confidence * 100),
            })

        if tables:
            logger.info(f"P2-tt 试点: 提取到 {len(tables)} 张滴度矩阵表")
        return tables
