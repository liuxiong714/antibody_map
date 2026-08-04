import json
import logging
import re
import hashlib
from typing import Any, Optional

import httpx
from openai import AsyncOpenAI

from app.config import settings
from app.core.term_normalizer import (
    normalize_disease,
    normalize_method,
    normalize_antibody_type,
    normalize_province,
    PROVINCE_NAMES_ZH,
)

logger = logging.getLogger("uvicorn")

# ==================== Prompt 模板 ====================

PROVINCE_LIST_TIP = f"""中国省份标准名称列表（必须从这里选择，不要使用简称或拼音）：
{PROVINCE_NAMES_ZH}"""

PROMPT_ZH = """你是一位专业的流行病学文献信息提取专家。请仔细阅读以下文献文本，提取所有抗体血清学数据点。一篇文献可能包含多个数据点（不同地区、不同人群、不同时间、不同检测指标），请全部提取。

**【重要】每条数据必须标注原文出处**：包括来源页码（如能判断）和原文片段（20-50字），方便后续人工核对。

{province_list_tip}

## 提取步骤
1. **定位数据区域**：在文中找到"结果"、"表"、"图"、"阳性率"、"抗体水平"、"GMC"、"GMT"等关键词附近的内容
2. **逐一提取每个数据点**：如果一个研究包含多个省份、城市、年龄组或检测指标，分别为每个创建独立的数据点
3. **核对数值**：阳性率通常以百分比给出（如87.3%、87.3％），GMC通常以IU/ml或μg/ml为单位
4. **标注来源**：找到提取数据所在的原文片段和页码（如能判断）

## JSON 输出格式
{{
  "data_points": [
    {{
      "disease_name": "从文中提取的疾病名称（中文）",
      "province": "省份名称（必须从上述标准列表中选）",
      "city": "城市名称（如：广州市、深圳市）",
      "study_start_year": 研究起始年,
      "study_end_year": 研究结束年,
      "sample_year": 采样年份,
      "population_type": "人群描述（如：健康儿童、18-45岁成人、孕妇、军人等）",
      "age_min": 最小年龄（整数），如0,
      "age_max": 最大年龄（整数），如14,
      "sample_size": 样本量（整数），如1234,
      "detection_method": "检测方法（如：ELISA、化学发光法、中和试验等）",
      "antibody_type": "抗体类型（如：IgG、IgM、Total Ab、中和抗体等）",
      "positivity_rate": 阳性率数值（去掉%号，如87.3表示87.3%）,
      "positivity_ci_lower": 阳性率95%置信区间下限,
      "positivity_ci_upper": 阳性率95%置信区间上限,
      "gmc_value": 几何平均浓度（GMC）数值,
      "gmc_unit": "GMC单位（如：IU/ml、mIU/ml、μg/ml）",
      "gmc_ci_lower": GMC 95%置信区间下限,
      "gmc_ci_upper": GMC 95%置信区间上限,
      "journal": "发表杂志名称",
      "authors": "作者（多个用分号分隔）",
      "author_affiliations": "作者单位",
      "source_page": 来源页码（整数，如无法判断填null）,
      "source_context": "包含该数据的原文片段（20-50字，保留关键数字）",
      "estimate_type": "估计类型：primary（主估计/总体汇总）或 subgroup（子组/分层估计）",
      "parent_group": "子估计所属主估计的分组标识（如：广东全省、0-14岁组的主估计 id）。主估计填null"
    }}
  ]
}}

## 重要规则
- **省份必须匹配**：从上述标准列表中选取最匹配的省份名称。如文中"鲁"→"山东"，"广东省"→"广东"，"上海"→"上海"
- **百分比处理**：87.3% → 填87.3（去掉%符号）；如果多个年份/组别有%数据，全部提取为多个数据点
- **GMC注意**：GMC和阳性率是不同的指标。GMC通常以IU/ml、μg/ml等单位给出。文中同时有阳性率和GMC时，两者都要提取
- **年龄拆分**："0-14岁儿童" → age_min=0, age_max=14
- **多省份多城市**：如研究覆盖多个地区，每个地区作为一个独立数据点
- **无法确定填null**：确实无法从文中确定的字段填null
- **仅输出JSON**：不要包含任何解释性文字或markdown代码块标记
- **【重要】标注来源**：每个数据点必须填写source_context，摘录包含关键数据的原文片段（如："阳性者215例，阳性率84.3%"）
- **【P1-1 主估计/子估计】**：
  - 如果一个研究既有"总体/全省汇总"数据，又有"按年龄/地区/免疫史分组"的细分数据，则：
    - 总体汇总数据 → estimate_type="primary"，parent_group=null
    - 分组细分数据 → estimate_type="subgroup"，parent_group 填该分组所属的主估计标识（如"广东全省"或"广东-0-14岁组的主估计"）
  - 判断主估计 vs 子估计的方法：主估计通常样本量更大、覆盖范围更全（如"全省"vs"某市"）、年龄段更宽（如"0-14岁"vs"0-5岁"）
  - 如果文献只有单一数据点（无总体vs分组关系），统一标记为 estimate_type="primary"
  - parent_group 用简短中文描述即可，后端会自动归并同组子估计到对应主估计

文献文本：
{text}"""

PROMPT_EN = """You are a professional epidemiological literature data extraction expert. Carefully read the following literature and extract ALL antibody serological data points. A single paper may contain multiple data points (different regions, populations, time periods, or assay types) — extract ALL of them.

**【IMPORTANT】Each data point MUST include source attribution**: page number (if determinable) and original text snippet (20-50 chars) for manual verification.

Chinese Province Name Reference List:
{province_list_en}

## Extraction Steps
1. Find data regions: Look near "Results", tables, "positivity", "antibody level", "GMC", "GMT" keywords
2. Extract each data point individually: If a study covers multiple provinces, cities, age groups, or assay types, create a separate entry for each
3. Verify values: Positivity rates are usually percentages (e.g., 87.3%), GMC usually in IU/ml or μg/ml
4. Mark source: Note the page and original text snippet containing the key data

## JSON Output Format
{{
  "data_points": [
    {{
      "disease_name": "disease name from text",
      "province": "province name (from reference list above)",
      "city": "city name",
      "study_start_year": study start year (integer),
      "study_end_year": study end year (integer),
      "sample_year": sample year (integer),
      "population_type": "population description (e.g., healthy children, adults 18-45)",
      "age_min": min age (integer),
      "age_max": max age (integer),
      "sample_size": sample size (integer),
      "detection_method": "e.g., ELISA, CLIA, NT, HAI",
      "antibody_type": "e.g., IgG, IgM, Total Ab, Neutralizing Ab",
      "positivity_rate": positivity rate (remove % sign, e.g., 87.3 means 87.3%),
      "positivity_ci_lower": positivity 95% CI lower bound,
      "positivity_ci_upper": positivity 95% CI upper bound,
      "gmc_value": GMC value,
      "gmc_unit": "GMC unit (IU/ml, mIU/ml, μg/ml)",
      "gmc_ci_lower": GMC 95% CI lower,
      "gmc_ci_upper": GMC 95% CI upper,
      "journal": "journal name",
      "authors": "authors (semicolon separated)",
      "author_affiliations": "author affiliations",
      "source_page": source page number (integer, null if undeterminable),
      "source_context": "original text snippet containing key data (20-50 chars)"
    }}
  ]
}}

## Important Rules
- Province names must match the reference list exactly
- Remove % sign: 87.3% → 87.3
- GMC and positivity rate are DIFFERENT indicators. Extract both if present
- "0-14 years" → age_min=0, age_max=14
- Multiple regions → separate data point for each
- Fill null if not determinable
- Output ONLY JSON, no markdown code blocks
- **【IMPORTANT】Include source_context**: Quote the original text snippet containing key numbers (e.g., "215 positive cases, positivity rate 84.3%")

Literature text:
{text}"""

PROVINCE_LIST_EN = "Beijing, Tianjin, Shanghai, Chongqing, Hebei, Shanxi, Inner Mongolia, Liaoning, Jilin, Heilongjiang, Jiangsu, Zhejiang, Anhui, Fujian, Jiangxi, Shandong, Henan, Hubei, Hunan, Guangdong, Guangxi, Hainan, Sichuan, Guizhou, Yunnan, Tibet, Shaanxi, Gansu, Qinghai, Ningxia, Xinjiang, Taiwan, Hong Kong, Macau"


# ===== B6：系统 prompt（静态部分，供 API 端 prompt caching 缓存）=====

SYSTEM_PROMPT_ZH = f"""你是一位专业的流行病学文献信息提取专家。请仔细阅读用户提供的文献文本，提取所有抗体血清学数据点。一篇文献可能包含多个数据点（不同地区、不同人群、不同时间、不同检测指标），请全部提取。

**【重要】每条数据必须标注原文出处**：包括来源页码（如能判断）和原文片段（20-50字），方便后续人工核对。

{PROVINCE_LIST_TIP}

## 提取步骤
1. **定位数据区域**：在文中找到"结果"、"表"、"图"、"阳性率"、"抗体水平"、"GMC"、"GMT"等关键词附近的内容
2. **逐一提取每个数据点**：如果一个研究包含多个省份、城市、年龄组或检测指标，分别为每个创建独立的数据点
3. **核对数值**：阳性率通常以百分比给出（如87.3%），GMC通常以IU/ml或μg/ml为单位
4. **标注来源**：找到提取数据所在的原文片段和页码（如能判断）

## JSON 输出格式
{{
  "data_points": [
    {{
      "disease_name": "从文中提取的疾病名称（中文）",
      "province": "省份名称（必须从上述标准列表中选）",
      "city": "城市名称（如：广州市、深圳市）",
      "study_start_year": 研究起始年,
      "study_end_year": 研究结束年,
      "sample_year": 采样年份,
      "population_type": "人群描述（如：健康儿童、18-45岁成人、孕妇、军人等）",
      "age_min": 最小年龄（整数），如0,
      "age_max": 最大年龄（整数），如14,
      "sample_size": 样本量（整数），如1234,
      "detection_method": "检测方法（如：ELISA、化学发光法、中和试验等）",
      "antibody_type": "抗体类型（如：IgG、IgM、Total Ab、中和抗体等）",
      "positivity_rate": 阳性率数值（去掉%号，如87.3表示87.3%）,
      "positivity_ci_lower": 阳性率95%置信区间下限,
      "positivity_ci_upper": 阳性率95%置信区间上限,
      "gmc_value": 几何平均浓度（GMC）数值,
      "gmc_unit": "GMC单位（如：IU/ml、mIU/ml、μg/ml）",
      "gmc_ci_lower": GMC 95%置信区间下限,
      "gmc_ci_upper": GMC 95%置信区间上限,
      "journal": "发表杂志名称",
      "authors": "作者（多个用分号分隔）",
      "author_affiliations": "作者单位",
      "source_page": 来源页码（整数，如无法判断填null）,
      "source_context": "包含该数据的原文片段（20-50字，保留关键数字）",
      "estimate_type": "估计类型：primary（主估计/总体汇总）或 subgroup（子组/分层估计）",
      "parent_group": "子估计所属主估计的分组标识（如：广东全省、0-14岁组的主估计 id）。主估计填null"
    }}
  ]
}}

## 重要规则
- **省份必须匹配**：从上述标准列表中选取最匹配的省份名称。如文中"鲁"→"山东"，"广东省"→"广东"，"上海"→"上海"
- **百分比处理**：87.3% → 填87.3（去掉%符号）；如果多个年份/组别有%数据，全部提取为多个数据点
- **GMC注意**：GMC和阳性率是不同的指标。GMC通常以IU/ml、μg/ml等单位给出。文中同时有阳性率和GMC时，两者都要提取
- **年龄拆分**："0-14岁儿童" → age_min=0, age_max=14
- **多省份多城市**：如研究覆盖多个地区，每个地区作为一个独立数据点
- **无法确定填null**：确实无法从文中确定的字段填null
- **仅输出JSON**：不要包含任何解释性文字或markdown代码块标记
- **【重要】标注来源**：每个数据点必须填写source_context，摘录包含关键数据的原文片段（如："阳性者215例，阳性率84.3%"）
- **【P1-1 主估计/子估计】**：
  - 如果一个研究既有"总体/全省汇总"数据，又有"按年龄/地区/免疫史分组"的细分数据，则：
    - 总体汇总数据 → estimate_type="primary"，parent_group=null
    - 分组细分数据 → estimate_type="subgroup"，parent_group 填该分组所属的主估计标识（如"广东全省"或"广东-0-14岁组的主估计"）
  - 判断主估计 vs 子估计的方法：主估计通常样本量更大、覆盖范围更全（如"全省"vs"某市"）、年龄段更宽（如"0-14岁"vs"0-5岁"）
  - 如果文献只有单一数据点（无总体vs分组关系），统一标记为 estimate_type="primary"
  - parent_group 用简短中文描述即可，后端会自动归并同组子估计到对应主估计
  - **仅输出JSON**：不要包含任何解释性文字或markdown代码块标记"""


class LLMExtractor:
    """LLM 数据提取引擎"""

    # P2-2：旧的前缀映射表保留用于向后兼容（_resolve_api_config_legacy），
    # 新代码通过 providers 注册中心自动匹配。
    _MODEL_CONFIG_MAP = {
        "deepseek": "DEEPSEEK",
        "gpt-": "OPENAI",
        "o1-": "OPENAI",
        "o3-": "OPENAI",
        "qwen": "QWEN",
        "ollama/": "OLLAMA",
        "llama": "OLLAMA",
        "mistral": "OLLAMA",
        "gemma": "OLLAMA",
        "glm4": "OLLAMA",
        "phi": "OLLAMA",
    }

    @staticmethod
    def _resolve_api_config(model: str):
        """根据模型名解析对应的 API key 和 base_url。

        P2-2：优先使用 providers 注册中心，无匹配时回退到旧的前缀映射表。
        """
        # P2-2：优先使用 provider 注册中心
        try:
            from app.core.providers import get_provider_for_model
            provider_cls = get_provider_for_model(model)
            if provider_cls is not None:
                api_key, base_url = provider_cls.get_config()
                return api_key, base_url
        except ImportError:
            pass  # providers 包未安装时回退到旧逻辑

        # 回退：旧的前缀映射表逻辑（向后兼容）
        api_key = settings.LLM_API_KEY
        base_url = settings.LLM_BASE_URL

        model_lower = model.lower()
        for prefix, config_key in LLMExtractor._MODEL_CONFIG_MAP.items():
            if model_lower.startswith(prefix):
                vendor_key = getattr(settings, f"{config_key}_API_KEY", "")
                vendor_url = getattr(settings, f"{config_key}_BASE_URL", "")
                if vendor_key:
                    api_key = vendor_key
                if vendor_url:
                    base_url = vendor_url
                break

        return api_key, base_url

    @staticmethod
    def _supports_response_format(model: str) -> bool:
        """检查模型是否支持 response_format 参数。

        P2-2：优先查询 provider 注册中心，无匹配时回退到旧逻辑。
        """
        try:
            from app.core.providers import get_provider_for_model
            provider_cls = get_provider_for_model(model)
            if provider_cls is not None:
                return provider_cls.supports_response_format()
        except ImportError:
            pass

        # 回退：旧逻辑
        model_lower = model.lower()
        return "deepseek" in model_lower or "gpt-" in model_lower

    def __init__(
        self,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        self.model = model or settings.LLM_MODEL
        resolved_key, resolved_url = self._resolve_api_config(self.model)
        self._resolved_key = api_key or resolved_key
        self._resolved_url = base_url or resolved_url
        self.client = AsyncOpenAI(
            api_key=self._resolved_key,
            base_url=self._resolved_url,
        )
        # B6：表格 Markdown 哈希缓存（进程级，避免同一文献重抽时重复提取）
        self._table_cache: dict[str, str] = {}
        # B9：审核反馈 few-shot 示例
        self._feedback_examples: list[str] = []

    # ===== B5：分级模型策略 =====

    def _pick_model(self, text_len: int, has_tables: bool) -> str:
        """B5：根据文本长度和表格复杂度选择模型。

        - 短文本(<5000) + 无表格 → LLM_MODEL_LIGHT（便宜快速）
        - 长文本(>15000) + 有表格 → LLM_MODEL_STRONG（更强理解力）
        - 其他 → 默认 self.model
        """
        light = getattr(settings, "LLM_MODEL_LIGHT", "") or ""
        strong = getattr(settings, "LLM_MODEL_STRONG", "") or ""
        if light and text_len < 5000 and not has_tables:
            logger.info(f"B5 分级模型: text_len={text_len} → LIGHT({light})")
            return light
        if strong and (text_len > 15000 or (has_tables and text_len > 10000)):
            logger.info(f"B5 分级模型: text_len={text_len} has_tables={has_tables} → STRONG({strong})")
            return strong
        return self.model

    # ===== B9：审核反馈闭环 =====

    def set_feedback_examples(self, examples: list[str]) -> None:
        """B9：设置审核反馈示例（rejected 数据点的错误描述），注入 prompt 提升准确度。"""
        self._feedback_examples = examples[:getattr(settings, "LLM_FEEDBACK_FEW_SHOT_COUNT", 5)]
        if self._feedback_examples:
            logger.info(f"B9 已加载 {len(self._feedback_examples)} 条审核反馈示例")

    def _build_feedback_section(self) -> str:
        """B9：构建 few-shot 注入段落。"""
        if not self._feedback_examples:
            return ""
        examples_text = "\n".join(f"  {i+1}. {ex}" for i, ex in enumerate(self._feedback_examples))
        return (
            "\n\n===== 历史审核纠错记录（请避免类似错误）=====\n"
            + examples_text
            + "\n===== 纠错记录结束 =====\n"
        )

    async def _call_llm_api(self, prompt: str, system_prompt: str = "") -> str:
        """调用 LLM API 获取响应。B6：支持 system prompt 分离，启用 prompt caching。"""
        try:
            # 构建消息列表
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            # 构建请求参数
            kwargs = dict(
                model=self.model,
                messages=messages,
                temperature=0.1,
                max_tokens=16384,
                timeout=120,
            )
            # P2-2：通过 provider 注册中心查询是否支持 response_format
            if self._supports_response_format(self.model):
                kwargs["response_format"] = {"type": "json_object"}

            response = await self.client.chat.completions.create(**kwargs)
            content = response.choices[0].message.content
            if content:
                logger.info(f"LLM 返回内容长度: {len(content)}")
            return content or ""
        except Exception as e:
            logger.warning(f"LLM API 调用失败: {e}，尝试 HTTP 兜底...")
            return await self._fallback_http_call(prompt, system_prompt)

    async def _fallback_http_call(self, prompt: str, system_prompt: str = "") -> str:
        """HTTP 兜底调用（不依赖 OpenAI SDK）。B6：支持 system prompt。"""
        try:
            # P1-3：使用实例解析出的 base_url 和 api_key，而非全局默认
            base_url = self._resolved_url or settings.LLM_BASE_URL
            api_key = self._resolved_key or settings.LLM_API_KEY
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})
            payload = {
                "model": self.model,
                "messages": messages,
                "temperature": 0.1,
                "max_tokens": 16384,
            }
            # P2-2：通过 provider 注册中心查询是否支持 response_format
            if self._supports_response_format(self.model):
                payload["response_format"] = {"type": "json_object"}

            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(
                    f"{base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
                return data["choices"][0]["message"]["content"]
        except Exception as e:
            logger.error(f"HTTP 兜底调用失败: {e}")
            raise

    def _parse_json(self, content: str) -> dict:
        """解析 LLM 返回的 JSON"""
        if not content:
            return {}

        content_clean = content.strip()
        if content_clean.startswith("```json"):
            content_clean = content_clean[7:]
        if content_clean.startswith("```"):
            content_clean = content_clean[3:]
        if content_clean.endswith("```"):
            content_clean = content_clean[:-3]
        content_clean = content_clean.strip()

        # 尝试直接解析
        try:
            return json.loads(content_clean)
        except json.JSONDecodeError as e:
            logger.warning(f"直接解析失败: {e}")

        # 尝试提取 JSON 块
        json_match = re.search(r"\{[\s\S]*\}", content_clean)
        if json_match:
            match_str = json_match.group()
            try:
                return json.loads(match_str)
            except json.JSONDecodeError as e:
                logger.warning(f"提取 JSON 块解析失败: {e}")

        # 尝试修复常见的 JSON 格式问题
        try:
            fixed = content_clean.replace("'", "\"")
            return json.loads(fixed)
        except json.JSONDecodeError as e:
            logger.warning(f"修复单引号解析失败: {e}")

        # 尝试修复未闭合的 JSON（找到最后一个 }）
        try:
            last_brace = content_clean.rfind("}")
            if last_brace != -1:
                fixed_json = content_clean[:last_brace + 1]
                return json.loads(fixed_json)
        except json.JSONDecodeError as e:
            logger.warning(f"修复未闭合 JSON 失败: {e}")

        # 尝试使用 json.JSONDecoder 宽松模式
        try:
            import json as json_module
            decoder = json_module.JSONDecoder()
            result, _ = decoder.raw_decode(content_clean)
            return result
        except Exception as e:
            logger.warning(f"宽松模式解析失败: {e}")

        # 尝试逐字符检查问题
        try:
            import json as json_module
            import traceback
            for i in range(len(content_clean)):
                try:
                    json_module.loads(content_clean[:i+1])
                except json_module.JSONDecodeError:
                    continue
                else:
                    partial = content_clean[:i+1]
                    try:
                        return json_module.loads(partial)
                    except Exception:
                        logger.warning("JSON 逐字符解析失败，尝试下一个字符")
        except Exception:
            logger.warning("JSON 逐字符外层解析失败")

        logger.error(f"无法解析 LLM 响应为 JSON: {content[:500]}")
        logger.error(f"响应长度: {len(content)}")
        return {}

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

            # 浮点数字段
            for field in [
                "positivity_rate", "positivity_ci_lower", "positivity_ci_upper",
                "gmc_value", "gmc_ci_lower", "gmc_ci_upper",
            ]:
                val = item.get(field)
                if val is not None:
                    try:
                        dp[field] = float(val)
                    except (ValueError, TypeError):
                        dp[field] = None
                else:
                    dp[field] = None

            results.append(dp)

        return results

    def _has_key_fields(self, points: list[dict]) -> bool:
        """检查是否包含关键字段"""
        return any(
            p.get("positivity_rate") is not None or p.get("gmc_value") is not None
            for p in points
        )

    # ===== A3：grounding 失败时 LLM 重抽 source_context =====

    async def reground_source_context(
        self,
        full_text: str,
        extract_item: dict,
    ) -> Optional[str]:
        """A3：当 grounding 失败时，让 LLM 从全文中重新定位包含该数据点的原文片段。

        给 LLM 一个精简 prompt：只包含数据点关键字段 + 全文片段搜索范围，
        要求返回 20-50 字原文片段。成本极低（单次调用，短 prompt）。
        """
        # 构造精简的搜索线索
        clues = []
        for k in ("disease_name", "province", "city", "population_type",
                   "positivity_rate", "gmc_value", "sample_size", "age_min", "age_max",
                   "sample_year", "detection_method", "antibody_type"):
            v = extract_item.get(k)
            if v is not None:
                clues.append(f"{k}={v}")
        clue_str = ", ".join(clues[:8])  # 最多 8 个线索

        # 只取全文前 8000 字符搜索（避免 prompt 过长）
        search_text = full_text[:8000] if len(full_text) > 8000 else full_text

        prompt = (
            "请从以下文献原文中找到包含这些数据的关键句子，"
            "摘录20-50字的原文片段（保留关键数字），只输出片段本身，不要解释：\n\n"
            f"数据线索：{clue_str}\n\n"
            f"文献原文：\n{search_text}"
        )

        try:
            content = await self._call_llm_api(prompt)
            if content:
                snippet = content.strip().strip('"').strip("'").strip('""').strip("''")
                if 10 <= len(snippet) <= 200:
                    logger.info(f"A3 LLM 重抽 source_context 成功: {snippet[:40]!r}")
                    return snippet
        except Exception as e:
            logger.warning(f"A3 LLM 重抽 source_context 失败: {e}")
        return None

    @staticmethod
    def _chunk_text(
        text: str,
        chunk_size: int = 15000,
        overlap: int = 500,
        table_boundaries: Optional[list[tuple[int, int]]] = None,
    ) -> list[tuple[int, str]]:
        """P2+B7：将长文本按段落边界分块，返回 [(chunk_start_char, chunk_text), ...]。

        B7 改进：
        - table_boundaries: 表格在 text 中的 (start, end) 区间列表，切分时避免在表格中间断开
        - overlap 根据内容动态调整：表格区域附近 overlap 更大
        """
        if len(text) <= chunk_size:
            return [(0, text)]

        def _in_table(pos: int) -> bool:
            """检查位置 pos 是否在某个表格区间内"""
            if not table_boundaries:
                return False
            for ts, te in table_boundaries:
                if ts <= pos < te:
                    return True
            return False

        def _find_table_end(pos: int) -> Optional[int]:
            """如果 pos 在表格内，返回表格结束位置"""
            if not table_boundaries:
                return None
            for ts, te in table_boundaries:
                if ts <= pos < te:
                    return te
            return None

        chunks: list[tuple[int, str]] = []
        pos = 0
        while pos < len(text):
            end = min(pos + chunk_size, len(text))
            # 如果不是最后一块，尝试在段落/句子边界切分
            if end < len(text):
                # B7：如果 end 落在表格内部，扩展到表格结束位置
                if _in_table(end):
                    tbl_end = _find_table_end(end)
                    if tbl_end and tbl_end - pos < chunk_size * 1.5:
                        # 表格不大，扩展到包含整个表格
                        end = tbl_end
                    else:
                        # 表格太大，在表格开始前切分
                        for ts, te in (table_boundaries or []):
                            if ts < end < te:
                                end = ts
                                break

                # 优先在换行符处切分
                for sep in ["\n\n", "\n", "。", "；", ". ", "; "]:
                    last_sep = text.rfind(sep, pos + chunk_size - overlap, end)
                    if last_sep != -1:
                        end = last_sep + len(sep)
                        break
            chunk = text[pos:end]
            if chunk.strip():
                chunks.append((pos, chunk))
            pos = end

        logger.info(f"长文本分块: {len(text)} 字符 → {len(chunks)} 块 (chunk_size={chunk_size}, overlap={overlap}, tables={len(table_boundaries or [])})")
        return chunks

    @staticmethod
    def _deduplicate_points(points: list[dict]) -> list[dict]:
        """P2：合并去重 — 基于 disease+province+data_type+value 的组合去重"""
        seen: set[str] = set()
        unique: list[dict] = []
        for p in points:
            # 构造去重 key：疾病+省份+数据类型+数值
            disease = (p.get("disease_name") or "").strip()
            province = (p.get("province") or "").strip()
            city = (p.get("city") or "").strip()
            age_min = p.get("age_min")
            age_max = p.get("age_max")
            if p.get("positivity_rate") is not None:
                key_val = f"sero:{p.get('positivity_rate')}"
            elif p.get("gmc_value") is not None:
                key_val = f"gmc:{p.get('gmc_value')}"
            else:
                key_val = f"other:{p.get('detection_method', '')}"

            key = f"{disease}|{province}|{city}|{age_min}|{age_max}|{key_val}"
            if key not in seen:
                seen.add(key)
                unique.append(p)
            else:
                logger.info(f"去重: 移除重复数据点 {key}")

        if len(unique) < len(points):
            logger.info(f"合并去重: {len(points)} → {len(unique)} 个数据点 (移除 {len(points) - len(unique)} 个重复)")
        return unique

    async def extract(
        self,
        text: str,
        language: str = "zh",
        title: str = "",
        journal: str = "",
        pub_year: Optional[int] = None,
        tables_md: str = "",
        complement_mode: bool = False,
        table_only: bool = False,
    ) -> list[dict]:
        """从文本中提取结构化数据（返回数据点列表）

        参数：
            tables_md: P0-1 表格结构化 Markdown，注入 prompt 帮助 LLM 理解表格行列关系
            complement_mode: P0-2 查漏补缺模式，多趟提取的第 2+ 趟用，
                             prompt 追加指令要求重点检查遗漏的年龄组/地区/检测方法
            table_only: A1 表格优先模式，仅从表格 Markdown 提取，不注入全文
        """
        # B6：使用 system prompt（静态部分分离，启用 API 端 prompt caching）
        system_prompt = SYSTEM_PROMPT_ZH if language == "zh" else PROMPT_EN.format(
            province_list_en=PROVINCE_LIST_EN, text=""
        ).replace("Literature text:\n", "").strip()

        # 加入文献元信息
        meta = ""
        if title:
            meta += f"文献标题：{title}\n" if language == "zh" else f"Title: {title}\n"
        if journal:
            meta += f"发表杂志：{journal}\n" if language == "zh" else f"Journal: {journal}\n"
        if pub_year:
            meta += f"发表年份：{pub_year}\n" if language == "zh" else f"Publication year: {pub_year}\n"

        # P0-1：若有结构化表格 Markdown，注入到文本前部
        tables_section = ""
        if tables_md and tables_md.strip():
            if language == "zh":
                tables_section = (
                    "\n\n===== 文档中的结构化表格（已转为 Markdown，请重点参考表格中的行列对应关系）=====\n"
                    + tables_md
                    + "\n===== 表格结束 =====\n\n"
                )
            else:
                tables_section = (
                    "\n\n===== Structured tables in this document (converted to Markdown, pay attention to row/column correspondence) =====\n"
                    + tables_md
                    + "\n===== End of tables =====\n\n"
                )
            logger.info(f"P0-1 注入表格 Markdown: {len(tables_md)} 字符")

        # P0-2：查漏补缺模式 prompt 前缀
        complement_prefix = ""
        if complement_mode:
            if language == "zh":
                complement_prefix = (
                    "【查漏补缺模式】这是对该文献的第二次提取。请重点检查前一次可能遗漏的数据点，"
                    "特别是：\n"
                    "1. 表格中按年龄组、地区、免疫史分组的各行数据是否都已提取\n"
                    "2. 不同检测方法（ELISA/CLIA/中和试验等）的结果是否都分别提取\n"
                    "3. 不同抗体类型（IgG/IgM/中和抗体）是否都分别提取\n"
                    "4. 多年份的纵向数据是否都提取\n"
                    "5. 子地区（省下属市、县）的数据是否都提取\n"
                    "请输出你发现的所有数据点（包括与第一次可能重复的），系统会自动去重。\n\n"
                )
            else:
                complement_prefix = (
                    "[COMPLEMENT MODE] This is the second extraction pass. Focus on data points "
                    "that may have been missed in the first pass, especially:\n"
                    "1. Each row in tables grouped by age/region/immunization history\n"
                    "2. Results from different assay methods (ELISA/CLIA/NT)\n"
                    "3. Different antibody types (IgG/IgM/neutralizing)\n"
                    "4. Multi-year longitudinal data\n"
                    "5. Sub-region data (cities/counties within a province)\n"
                    "Output ALL data points you find (duplicates will be auto-merged).\n\n"
                )
            logger.info("P0-2 查漏补缺模式 prompt 已注入")

        # B9：审核反馈 few-shot 注入
        feedback_section = self._build_feedback_section()

        # A1：表格优先模式只注入表格，不注入全文
        if table_only:
            user_content = meta + complement_prefix + tables_section + feedback_section + "（仅从上述表格中提取数据点）"
        else:
            user_content = meta + tables_section + complement_prefix + feedback_section + text

        # 调用 LLM（B6：system prompt 分离）
        content = await self._call_llm_api(user_content, system_prompt=system_prompt)
        data = self._parse_json(content)
        points = self._post_process(data)

        # 补充元信息
        for p in points:
            if title and not p.get("_title"):
                p["_title"] = title
            if journal and not p.get("journal"):
                p["journal"] = journal
            if pub_year and not p.get("_pub_year"):
                p["_pub_year"] = pub_year

        return points

    # ===== B8：表格行数估算 =====

    @staticmethod
    def _count_table_rows(tables_md: str) -> int:
        """B8：估算表格 Markdown 中的数据行数（用于覆盖率评估）。

        每个 Markdown 表格由：1 行表头 + 1 行分隔（|---|---|）+ N 行数据组成。
        因此：数据行数 = (所有 | 开头的行) - 2 × (分隔行数)
        """
        if not tables_md:
            return 0
        rows = tables_md.split("\n")
        sep_re = re.compile(r"^\|[\s\-:|]+\|?\s*$")
        separator_count = sum(
            1 for r in rows if r.strip().startswith("|") and sep_re.match(r.strip())
        )
        pipe_rows = sum(1 for r in rows if r.strip().startswith("|"))
        # 每个表格有 1 个分隔行 + 1 个表头行需要扣除
        return max(0, pipe_rows - separator_count * 2)

    @staticmethod
    def _find_table_boundaries(text: str, tables_md: str) -> list[tuple[int, int]]:
        """B7：在全文中定位表格的大致位置区间，供分块时避让。

        通过搜索表格 Markdown 中的特征行（| 开头的数据行）在全文中的位置。
        """
        if not tables_md:
            return []
        boundaries: list[tuple[int, int]] = []
        # 取表格中几个特征行搜索
        lines = [l.strip() for l in tables_md.split("\n") if l.strip().startswith("|") and len(l.strip()) > 10]
        for line in lines[:20]:  # 最多搜索 20 行
            # 取行的前 20 字符作为搜索特征
            snippet = line[:20].strip("|").strip()
            if len(snippet) < 4:
                continue
            pos = text.find(snippet)
            if pos != -1:
                boundaries.append((pos, pos + len(line)))
        # 合并重叠区间
        if not boundaries:
            return []
        boundaries.sort()
        merged = [boundaries[0]]
        for s, e in boundaries[1:]:
            if s <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], e))
            else:
                merged.append((s, e))
        return merged

    async def extract_with_retry(
        self,
        text: str,
        language: str = "zh",
        title: str = "",
        journal: str = "",
        pub_year: Optional[int] = None,
        max_retries: int = 3,
        tables_md: str = "",
        extraction_passes: int = 1,
    ) -> list[dict]:
        """带重试的提取。P2：长文档（>20000字符）自动分块并行提取+合并去重。

        优化集成：
        - A1：表格优先提取（有表格时先单独从表格提取一轮）
        - B5：分级模型策略（短文本用轻量模型，长文本用强模型）
        - B7：表格边界感知分块
        - B8：多趟提取智能调度（覆盖率>90%跳过后续趟）
        """
        has_tables = bool(tables_md and tables_md.strip())

        # A1：表格优先提取 — 先从表格单独提取一轮
        all_points: list[dict] = []
        if has_tables and getattr(settings, "LLM_TABLE_FIRST_EXTRACTION", True):
            logger.info("A1 表格优先提取：先从表格 Markdown 单独提取一轮")
            try:
                table_points = await self._single_pass_with_retry(
                    "", language, title, journal, pub_year, max_retries,
                    tables_md=tables_md,
                )
                # 标记表格来源
                for p in table_points:
                    p["_from_table_pass"] = True
                all_points.extend(table_points)
                logger.info(f"A1 表格优先提取: {len(table_points)} 个数据点")
            except Exception as e:
                logger.warning(f"A1 表格优先提取失败（不影响全文提取）: {e}")

        # B5：分级模型选择
        original_model = self.model
        picked_model = self._pick_model(len(text), has_tables)
        if picked_model != self.model:
            self.model = picked_model
            # 重新初始化 client 以匹配新模型
            resolved_key, resolved_url = self._resolve_api_config(self.model)
            self._resolved_key = self._resolved_key or resolved_key
            self._resolved_url = self._resolved_url or resolved_url
            self.client = AsyncOpenAI(api_key=self._resolved_key, base_url=self._resolved_url)

        try:
            # A2：两阶段提取（默认关闭，开启时替代常规流程）
            if getattr(settings, "LLM_TWO_PHASE_EXTRACTION", False) and not has_tables:
                logger.info("A2 两阶段提取模式已启用")
                try:
                    phase_result = await self._two_phase_extract(
                        text, language, title, journal, pub_year, tables_md,
                    )
                    all_points.extend(phase_result)
                    deduped = self._deduplicate_points(all_points)
                    logger.info(f"A2 两阶段提取完成: {len(deduped)} 个数据点")
                    return deduped
                except Exception as e:
                    logger.warning(f"A2 两阶段提取失败，回退到常规模式: {e}")
            # B7：表格边界感知分块
            table_boundaries = self._find_table_boundaries(text, tables_md) if has_tables else None

            # P2：长文档分块判断
            CHUNK_THRESHOLD = 20000
            if len(text) > CHUNK_THRESHOLD:
                logger.info(f"P2 长文档分块提取: 文本长度={len(text)} > 阈值={CHUNK_THRESHOLD}")
                chunks = self._chunk_text(text, table_boundaries=table_boundaries)

                for idx, (chunk_offset, chunk_text) in enumerate(chunks):
                    logger.info(f"分块 {idx + 1}/{len(chunks)}: offset={chunk_offset}, len={len(chunk_text)}")
                    # B5：每个分块也可以按复杂度选模型
                    chunk_model = self._pick_model(len(chunk_text), has_tables)
                    if chunk_model != self.model:
                        self.model = chunk_model
                    chunk_result = await self._extract_single_chunk_with_retry(
                        chunk_text, language, title, journal, pub_year, max_retries,
                        tables_md=tables_md if idx == 0 else "",  # 表格只在第一块注入
                        extraction_passes=extraction_passes,
                    )
                    all_points.extend(chunk_result)

                logger.info(f"所有分块提取完成，共 {len(all_points)} 个数据点，开始去重...")
                deduped = self._deduplicate_points(all_points)
                return deduped

            # 短文档：P0-2 多趟提取（B8 智能调度）
            if extraction_passes >= 2:
                full_result = await self._multi_pass_extract(
                    text, language, title, journal, pub_year, max_retries,
                    tables_md=tables_md, passes=extraction_passes,
                )
                all_points.extend(full_result)
                # 合并表格优先 + 全文提取结果并去重
                if len(all_points) > len(full_result):
                    deduped = self._deduplicate_points(all_points)
                    logger.info(f"A1 合并表格+全文提取: {len(all_points)} → {len(deduped)} 个数据点")
                    return deduped
                return full_result

            # 短文档单趟
            last_result: list[dict] = []
            for attempt in range(max_retries):
                try:
                    result = await self.extract(text, language, title, journal, pub_year, tables_md=tables_md)
                    last_result = result
                    if self._has_key_fields(result):
                        break
                    logger.warning(
                        f"提取结果缺少关键字段（positivity_rate/gmc_value），"
                        f"第 {attempt + 1}/{max_retries} 次重试..."
                    )
                except Exception as e:
                    logger.error(f"提取失败（第 {attempt + 1} 次）: {e}")
                    if attempt == max_retries - 1:
                        raise

            all_points.extend(last_result)
            if len(all_points) > len(last_result):
                return self._deduplicate_points(all_points)
            return last_result
        finally:
            # 恢复原始模型
            self.model = original_model

    async def _multi_pass_extract(
        self,
        text: str,
        language: str,
        title: str,
        journal: str,
        pub_year: Optional[int],
        max_retries: int,
        tables_md: str,
        passes: int,
    ) -> list[dict]:
        """P0-2：多趟提取，每趟用不同 prompt 措辞，结果合并去重提升召回率。

        B8 智能调度：第 1 趟后评估表格行数 vs 提取数据点数，
        若覆盖率 > 90% 则跳过后续趟，节省 API 成本。
        """
        all_points: list[dict] = []
        for pass_idx in range(passes):
            logger.info(f"P0-2 多趟提取: 第 {pass_idx + 1}/{passes} 趟")
            try:
                if pass_idx == 0:
                    # 第一趟：标准 prompt
                    pass_result = await self._single_pass_with_retry(
                        text, language, title, journal, pub_year, max_retries, tables_md,
                    )
                else:
                    # 后续趟：查漏补缺 prompt
                    pass_result = await self._single_pass_with_retry(
                        text, language, title, journal, pub_year, max_retries, tables_md,
                        complement_mode=True,
                    )
                all_points.extend(pass_result)
                logger.info(f"P0-2 第 {pass_idx + 1} 趟提取 {len(pass_result)} 个数据点")

                # B8：智能调度 — 第 1 趟后评估覆盖率
                if pass_idx == 0 and getattr(settings, "LLM_ADAPTIVE_PASSES", True) and passes >= 2:
                    table_rows = self._count_table_rows(tables_md)
                    if table_rows > 0:
                        # 覆盖率 = 提取的数据点数 / 表格行数
                        coverage = len(pass_result) / table_rows
                        logger.info(f"B8 覆盖率评估: {len(pass_result)} 数据点 / {table_rows} 表格行 = {coverage:.1%}")
                        if coverage >= 0.9:
                            logger.info(f"B8 覆盖率 {coverage:.1%} >= 90%，跳过后续 {passes - 1} 趟（节省成本）")
                            break
            except Exception as e:
                logger.error(f"P0-2 第 {pass_idx + 1} 趟提取失败（不阻塞其他趟）: {e}")

        logger.info(f"P0-2 多趟提取完成: 共 {len(all_points)} 个数据点，开始去重...")
        deduped = self._deduplicate_points(all_points)
        logger.info(f"P0-2 去重后: {len(deduped)} 个数据点")
        return deduped

    async def _single_pass_with_retry(
        self,
        text: str,
        language: str,
        title: str,
        journal: str,
        pub_year: Optional[int],
        max_retries: int,
        tables_md: str,
        complement_mode: bool = False,
    ) -> list[dict]:
        """单趟带重试提取。complement_mode=True 时在 prompt 中追加查漏补缺指令。"""
        last_result: list[dict] = []
        for attempt in range(max_retries):
            try:
                result = await self.extract(
                    text, language, title, journal, pub_year,
                    tables_md=tables_md, complement_mode=complement_mode,
                )
                last_result = result
                if self._has_key_fields(result) or attempt == max_retries - 1:
                    return result
                logger.warning(
                    f"单趟提取结果缺少关键字段，第 {attempt + 1}/{max_retries} 次重试..."
                )
            except Exception as e:
                logger.error(f"单趟提取失败（第 {attempt + 1} 次）: {e}")
                if attempt == max_retries - 1:
                    return last_result
        return last_result

    async def _extract_single_chunk_with_retry(
        self,
        chunk_text: str,
        language: str,
        title: str,
        journal: str,
        pub_year: Optional[int],
        max_retries: int,
        tables_md: str = "",
        extraction_passes: int = 1,
    ) -> list[dict]:
        """单个文本块的带重试提取。P0-2：支持多趟提取。"""
        # P0-2：多趟提取（块级别）
        if extraction_passes >= 2:
            all_points: list[dict] = []
            for pass_idx in range(extraction_passes):
                logger.info(f"P0-2 分块多趟提取: 第 {pass_idx + 1}/{extraction_passes} 趟")
                try:
                    pass_result = await self._single_pass_with_retry(
                        chunk_text, language, title, journal, pub_year, max_retries,
                        tables_md=tables_md,
                        complement_mode=(pass_idx > 0),
                    )
                    all_points.extend(pass_result)
                except Exception as e:
                    logger.error(f"P0-2 分块第 {pass_idx + 1} 趟失败（不阻塞）: {e}")
            return all_points

        # 单趟：原有逻辑
        last_result: list[dict] = []
        for attempt in range(max_retries):
            try:
                result = await self.extract(chunk_text, language, title, journal, pub_year, tables_md=tables_md)
                last_result = result
                if self._has_key_fields(result) or attempt == max_retries - 1:
                    return result
                logger.warning(
                    f"分块提取结果缺少关键字段，第 {attempt + 1}/{max_retries} 次重试..."
                )
            except Exception as e:
                logger.error(f"分块提取失败（第 {attempt + 1} 次）: {e}")
                if attempt == max_retries - 1:
                    return last_result  # 单块失败不阻塞其他块
        return last_result

    # ===== A2：两阶段提取（先抽骨架再填数值）=====

    SKELETON_PROMPT_ZH = """请从以下文献中提取所有血清学数据点的"骨架信息"（不含具体数值）。
    对于每个数据点，只提取以下字段：
    - disease_name, province, city, sample_year, population_type
    - age_min, age_max, sample_size, detection_method, antibody_type
    - estimate_type, parent_group, source_page, source_context

    输出 JSON 格式：{"data_points": [{...}]}
    仅输出 JSON，不要解释。

    文献文本：
    {text}"""

    async def _two_phase_extract(
        self,
        text: str,
        language: str,
        title: str,
        journal: str,
        pub_year: Optional[int],
        tables_md: str,
    ) -> list[dict]:
        """A2：两阶段提取。

        第 1 阶段：用精简 prompt 只抽骨架（省份/年份/人群/方法），token 少。
        第 2 阶段：对每个骨架数据点，用聚焦 prompt 让 LLM 补充数值、CI、样本量。
        好处：第 2 阶段 context 短、聚焦，数值准确率提升。
        """
        # --- 第 1 阶段：骨架提取 ---
        logger.info("A2 两阶段提取 - 第1阶段：骨架提取")
        meta = ""
        if title:
            meta += f"文献标题：{title}\n"
        if journal:
            meta += f"发表杂志：{journal}\n"
        if pub_year:
            meta += f"发表年份：{pub_year}\n"

        tables_section = ""
        if tables_md and tables_md.strip():
            tables_section = f"\n\n===== 结构化表格 =====\n{tables_md}\n===== 表格结束 =====\n\n"

        skeleton_prompt = self.SKELETON_PROMPT_ZH.replace("{text}", meta + tables_section + text)
        content = await self._call_llm_api(skeleton_prompt, system_prompt=SYSTEM_PROMPT_ZH)
        skeleton_data = self._parse_json(content)
        skeleton_points = self._post_process(skeleton_data)

        logger.info(f"A2 第1阶段骨架提取: {len(skeleton_points)} 个数据点")

        if not skeleton_points:
            return []

        # --- 第 2 阶段：数值填充 ---
        # 将所有骨架合并成一次调用，让 LLM 为每个补充数值
        logger.info("A2 两阶段提取 - 第2阶段：数值填充")
        skeleton_summary = json.dumps(
            [{"idx": i, **{k: v for k, v in p.items() if k != "source_context"}}
             for i, p in enumerate(skeleton_points)],
            ensure_ascii=False, indent=2,
        )

        value_fill_prompt = (
            "请根据以下文献原文，为每个骨架数据点补充具体的数值字段。\n"
            "需要补充的字段：positivity_rate, positivity_ci_lower, positivity_ci_upper, "
            "gmc_value, gmc_unit, gmc_ci_lower, gmc_ci_upper, sample_size, source_context。\n\n"
            f"骨架数据点列表：\n{skeleton_summary}\n\n"
            "输出 JSON 格式：{\"data_points\": [{\"idx\": 0, \"positivity_rate\": ..., \"source_context\": \"...\"}, ...]}\n"
            "仅输出 JSON。无法确定的数值填 null。\n\n"
            f"文献原文：\n{text[:10000]}"
        )

        content2 = await self._call_llm_api(value_fill_prompt, system_prompt=SYSTEM_PROMPT_ZH)
        fill_data = self._parse_json(content2)
        fill_points = fill_data.get("data_points", []) if fill_data else []

        # 合并骨架 + 数值
        for fill_item in fill_points:
            if not isinstance(fill_item, dict):
                continue
            idx = fill_item.get("idx")
            if idx is not None and 0 <= idx < len(skeleton_points):
                for k in ("positivity_rate", "positivity_ci_lower", "positivity_ci_upper",
                          "gmc_value", "gmc_unit", "gmc_ci_lower", "gmc_ci_upper",
                          "sample_size", "source_context"):
                    v = fill_item.get(k)
                    if v is not None:
                        skeleton_points[idx][k] = v

        logger.info(f"A2 两阶段提取完成: {len(skeleton_points)} 个数据点（数值已填充）")
        return skeleton_points
