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
)

logger = logging.getLogger("uvicorn")

# ==================== Prompt 模板 ====================

PROMPT_ZH = """你是一位专业的流行病学文献信息提取专家。请从以下文献文本中提取抗体血清学数据，严格按 JSON 格式输出。

提取要求：
1. 识别文中提到的疾病名称
2. 提取研究地点（省份、城市）
3. 提取调查时间（研究起始年、结束年、采样年）
4. 提取研究对象信息（人群类型、年龄范围）
5. 提取检测方法、抗体类型
6. 提取样本量和阳性率（百分比），以及阳性率95%置信区间
7. 如有抗体几何平均浓度（GMC），也需提取
8. 提取文献元信息（发表杂志名称、作者姓名、作者单位）

JSON 输出格式：
{{
  "disease_name": "疾病名称",
  "province": "省份",
  "city": "城市",
  "study_start_year": 研究起始年(整数),
  "study_end_year": 研究结束年(整数),
  "sample_year": 采样年(整数),
  "population_type": "人群类型，如：健康人群/儿童/成人/孕妇等",
  "age_min": 最小年龄(整数),
  "age_max": 最大年龄(整数),
  "sample_size": 样本量(整数),
  "detection_method": "检测方法",
  "antibody_type": "抗体类型，如：IgG/IgM/IgA/Total Ab",
  "positivity_rate": 阳性率(小数，如87.3表示87.3%),
  "positivity_ci_lower": 阳性率95%CI下限(小数),
  "positivity_ci_upper": 阳性率95%CI上限(小数),
  "gmc_value": GMC值(小数),
  "gmc_unit": "GMC单位，如：IU/ml/mIU/ml",
  "gmc_ci_lower": GMC 95%CI下限(小数),
  "gmc_ci_upper": GMC 95%CI上限(小数),
  "journal": "发表杂志名称",
  "authors": "作者姓名，多个作者用分号分隔",
  "author_affiliations": "作者单位，如：解放军空军后勤部疾病预防控制中心"
}}

注意：
- 如果某个字段无法从文本中提取，请填写 null
- 百分比值直接写数字，例如 87.3% 写为 87.3
- 年龄如有"0-6岁"等表述，拆分为 age_min=0, age_max=6
- 仅输出 JSON，不要包含任何解释性文字

文献文本：
{text}"""

PROMPT_EN = """You are a professional epidemiological literature information extraction expert. Extract antibody serological data from the following literature text and output strictly in JSON format.

Extraction requirements:
1. Identify disease name mentioned in the text
2. Extract study location (province/state, city)
3. Extract survey time (study start year, end year, sample year)
4. Extract study subject information (population type, age range)
5. Extract detection method and antibody type
6. Extract sample size and positivity rate (percentage), with 95% confidence intervals
7. Extract antibody geometric mean concentration (GMC) if available
8. Extract literature metadata (journal name, author names, author affiliations)

JSON output format:
{{
  "disease_name": "disease name",
  "province": "province/state",
  "city": "city",
  "study_start_year": study start year (integer),
  "study_end_year": study end year (integer),
  "sample_year": sample year (integer),
  "population_type": "e.g., healthy population/children/adults/pregnant women",
  "age_min": minimum age (integer),
  "age_max": maximum age (integer),
  "sample_size": sample size (integer),
  "detection_method": "detection method",
  "antibody_type": "e.g., IgG/IgM/IgA/Total Ab",
  "positivity_rate": positivity rate (decimal, e.g., 87.3 means 87.3%),
  "positivity_ci_lower": positivity rate 95% CI lower (decimal),
  "positivity_ci_upper": positivity rate 95% CI upper (decimal),
  "gmc_value": GMC value (decimal),
  "gmc_unit": "GMC unit, e.g., IU/ml/mIU/ml",
  "gmc_ci_lower": GMC 95% CI lower (decimal),
  "gmc_ci_upper": GMC 95% CI upper (decimal),
  "journal": "journal name",
  "authors": "author names, separated by semicolons",
  "author_affiliations": "author affiliations"
}}

Notes:
- If a field cannot be extracted, fill with null
- Percentage values as direct numbers, e.g., 87.3% → 87.3
- Age range like "0-6 years" → age_min=0, age_max=6
- Output ONLY JSON, no explanatory text

Literature text:
{text}"""


class LLMExtractor:
    """LLM 数据提取引擎"""

    def __init__(self, model: Optional[str] = None):
        self.model = model or settings.LLM_MODEL
        self.client = AsyncOpenAI(
            api_key=settings.LLM_API_KEY,
            base_url=settings.LLM_BASE_URL,
        )

    async def _call_llm_api(self, prompt: str) -> str:
        """调用 LLM API 获取响应"""
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                timeout=120,
            )
            content = response.choices[0].message.content
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
        # 尝试直接解析
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass

        # 尝试提取 JSON 块
        json_match = re.search(r"\{[\s\S]*\}", content)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass

        logger.error(f"无法解析 LLM 响应为 JSON: {content[:200]}")
        return {}

    def _post_process(self, data: dict) -> dict:
        """后处理：标准化术语和类型转换"""
        result = {}

        # 标准化疾病名称
        result["disease_name"] = normalize_disease(data.get("disease_name"))

        # 标准化检测方法
        result["detection_method"] = normalize_method(data.get("detection_method"))

        # 标准化抗体类型
        result["antibody_type"] = normalize_antibody_type(data.get("antibody_type"))

        # 保留其他字符串字段
        for field in ["province", "city", "population_type", "gmc_unit",
                       "journal", "authors", "author_affiliations"]:
            result[field] = data.get(field)

        # 整数字段
        for field in [
            "study_start_year", "study_end_year", "sample_year",
            "age_min", "age_max", "sample_size",
        ]:
            val = data.get(field)
            if val is not None:
                try:
                    result[field] = int(val)
                except (ValueError, TypeError):
                    result[field] = None
            else:
                result[field] = None

        # 浮点数字段
        for field in [
            "positivity_rate", "positivity_ci_lower", "positivity_ci_upper",
            "gmc_value", "gmc_ci_lower", "gmc_ci_upper",
        ]:
            val = data.get(field)
            if val is not None:
                try:
                    result[field] = float(val)
                except (ValueError, TypeError):
                    result[field] = None
            else:
                result[field] = None

        return result

    def _has_key_fields(self, data: dict) -> bool:
        """检查是否包含关键字段"""
        return data.get("positivity_rate") is not None or data.get("gmc_value") is not None

    async def extract(
        self,
        text: str,
        language: str = "zh",
        title: str = "",
        journal: str = "",
        pub_year: Optional[int] = None,
    ) -> dict:
        """从文本中提取结构化数据"""
        prompt_template = PROMPT_ZH if language == "zh" else PROMPT_EN

        # 构造 prompt，加入文献元信息
        meta = ""
        if title:
            meta += f"文献标题：{title}\n"
        if journal:
            meta += f"发表杂志：{journal}\n"
        if pub_year:
            meta += f"发表年份：{pub_year}\n"

        prompt = prompt_template.format(text=meta + text)

        # 调用 LLM
        content = await self._call_llm_api(prompt)
        data = self._parse_json(content)
        result = self._post_process(data)

        # 补充元信息（如果 LLM 未提取到则用传入的覆盖）
        if title and not result.get("_title"):
            result["_title"] = title
        if journal and not result.get("journal"):
            result["journal"] = journal
        if pub_year and not result.get("_pub_year"):
            result["_pub_year"] = pub_year

        return result

    async def extract_with_retry(
        self,
        text: str,
        language: str = "zh",
        title: str = "",
        journal: str = "",
        pub_year: Optional[int] = None,
        max_retries: int = 3,
    ) -> dict:
        """带重试的提取，如果缺少关键字段则重试"""
        last_result = {}
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
