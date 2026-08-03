import json
import logging
import re
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
      "source_context": "包含该数据的原文片段（20-50字，保留关键数字）"
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


class LLMExtractor:
    """LLM 数据提取引擎"""

    # 模型前缀 → 配置前缀的映射
    _MODEL_CONFIG_MAP = {
        "deepseek": "DEEPSEEK",
        "gpt-": "OPENAI",
        "o1-": "OPENAI",
        "o3-": "OPENAI",
        "qwen": "QWEN",
    }

    @staticmethod
    def _resolve_api_config(model: str):
        """根据模型名解析对应的 API key 和 base_url"""
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

    def __init__(
        self,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        self.model = model or settings.LLM_MODEL
        resolved_key, resolved_url = self._resolve_api_config(self.model)
        self.client = AsyncOpenAI(
            api_key=api_key or resolved_key,
            base_url=base_url or resolved_url,
        )

    async def _call_llm_api(self, prompt: str) -> str:
        """调用 LLM API 获取响应"""
        try:
            # 构建请求参数，DeepSeek 支持 response_format
            kwargs = dict(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=16384,
                timeout=120,
            )
            # 仅对明确支持 json_object 的模型添加此参数
            if "deepseek" in self.model.lower() or "gpt-" in self.model.lower():
                kwargs["response_format"] = {"type": "json_object"}
            else:
                # 其他模型（如 qwen）通过 prompt 引导输出 JSON
                pass

            response = await self.client.chat.completions.create(**kwargs)
            content = response.choices[0].message.content
            if content:
                logger.info(f"LLM 返回内容长度: {len(content)}")
            return content or ""
        except Exception as e:
            logger.warning(f"LLM API 调用失败: {e}，尝试 HTTP 兜底...")
            return await self._fallback_http_call(prompt)

    async def _fallback_http_call(self, prompt: str) -> str:
        """HTTP 兜底调用（不依赖 OpenAI SDK）"""
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(
                    f"{settings.LLM_BASE_URL}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {settings.LLM_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.model,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.1,
                        "max_tokens": 16384,
                        "response_format": {"type": "json_object"},
                    },
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
                    except:
                        pass
        except:
            pass

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
                           "source_context"]:  # 新增：原文片段
                dp[field] = item.get(field)

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

    async def extract(
        self,
        text: str,
        language: str = "zh",
        title: str = "",
        journal: str = "",
        pub_year: Optional[int] = None,
    ) -> list[dict]:
        """从文本中提取结构化数据（返回数据点列表）"""
        prompt_template = PROMPT_ZH if language == "zh" else PROMPT_EN

        # 构造 prompt，注入省份列表
        province_tip = PROVINCE_LIST_TIP if language == "zh" else PROVINCE_LIST_EN
        if language == "zh":
            province_tip = PROVINCE_LIST_TIP
        else:
            province_tip = PROVINCE_LIST_EN

        # 插入省份列表到 prompt
        if language == "zh":
            prompt_template_filled = PROMPT_ZH.format(
                province_list_tip=PROVINCE_LIST_TIP,
                text="{text}"
            )
        else:
            prompt_template_filled = PROMPT_EN.format(
                province_list_en=PROVINCE_LIST_EN,
                text="{text}"
            )

        # 加入文献元信息
        meta = ""
        if title:
            meta += f"文献标题：{title}\n" if language == "zh" else f"Title: {title}\n"
        if journal:
            meta += f"发表杂志：{journal}\n" if language == "zh" else f"Journal: {journal}\n"
        if pub_year:
            meta += f"发表年份：{pub_year}\n" if language == "zh" else f"Publication year: {pub_year}\n"

        # 使用 replace 避免 PDF 文本中的 {} 被 str.format 误解析
        prompt = prompt_template_filled.replace("{text}", meta + text)

        # 调用 LLM
        content = await self._call_llm_api(prompt)
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

    async def extract_with_retry(
        self,
        text: str,
        language: str = "zh",
        title: str = "",
        journal: str = "",
        pub_year: Optional[int] = None,
        max_retries: int = 3,
    ) -> list[dict]:
        """带重试的提取"""
        last_result: list[dict] = []
        for attempt in range(max_retries):
            try:
                result = await self.extract(text, language, title, journal, pub_year)
                last_result = result
                if self._has_key_fields(result):
                    return result
                logger.warning(
                    f"提取结果缺少关键字段（positivity_rate/gmc_value），"
                    f"第 {attempt + 1}/{max_retries} 次重试..."
                )
            except Exception as e:
                logger.error(f"提取失败（第 {attempt + 1} 次）: {e}")
                if attempt == max_retries - 1:
                    raise

        return last_result
