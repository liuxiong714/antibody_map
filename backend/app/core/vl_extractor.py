"""视觉多模态提取器骨架：让本地视觉模型（如 Qwen3.8:27b）直接读 PDF 页面图片提取数据。

本模块仅负责把页面图片 + JSON Schema 组装成多模态请求发给本地 Ollama 视觉模型，
返回模型输出的原始文本（JSON 字符串）。后处理、grounding、字段归一化属于后续步骤，
不在本文件实现。

长文档分批：一次塞入过多扫描页图片会超过 Ollama 上下文窗（默认 32768 token）。
因此按 VL_BATCH_SIZE（默认 6）页一批分批发送，把每批返回的结构化 JSON 合并成一个
同构结果返回，从而在上下文窗口内完成整篇文献提取。
"""
import base64
import json
import logging

from openai import AsyncOpenAI

from app.config import settings

logger = logging.getLogger("uvicorn")

# 默认视觉模型名。settings 中没有 VL_MODEL 字段时使用该写死默认值；
# 若后续在 config.py 增加 VL_MODEL 配置，这里会自动优先读取配置值。
DEFAULT_VL_MODEL = "qwen3.8:27b"

# 无 VL_BATCH_SIZE 配置时的兜底分页大小（页/批）
DEFAULT_VL_BATCH_SIZE = 6


def _get_vl_model() -> str:
    """读取视觉模型名：优先 settings.VL_MODEL，缺失时回退到写死默认值。"""
    return getattr(settings, "VL_MODEL", None) or DEFAULT_VL_MODEL


def _get_vl_batch_size() -> int:
    """读取单批页数：优先 settings.VL_BATCH_SIZE，缺失时回退到写死默认值。"""
    return max(1, int(getattr(settings, "VL_BATCH_SIZE", None) or DEFAULT_VL_BATCH_SIZE))


def _build_vision_prompt(json_schema: dict) -> str:
    """构造多模态提示词：要求模型严格按传入的 json_schema 输出 JSON。"""
    return (
        "你是一位专业的流行病学文献信息提取专家。请仔细阅读提供的文献页面图片，"
        "提取其中所有抗体血清学数据点（阳性率 / GMC / 样本量 / 省份 / 年龄等）。\n"
        "要求：\n"
        "1. 严格按给定的 JSON Schema 输出 JSON，字段名与结构必须完全一致；\n"
        "2. 一篇文献可能包含多个数据点（不同地区、不同人群、不同时间、不同检测指标），请全部提取；\n"
        "3. 数值保留原始形式（如阳性率 87.3 表示 87.3%）；确实无法确定的字段填 null；\n"
        "4. 仅输出 JSON，不要包含任何解释性文字或 markdown 代码块标记。\n"
        f"JSON Schema：\n{json_schema}\n"
    )


async def _call_single_batch(
    client: AsyncOpenAI, batch_images: list[bytes], json_schema: dict
) -> str:
    """向视觉模型发起一次请求（一批页），返回原始 JSON 字符串；异常返回 ""。"""
    content: list[dict] = []
    for image_bytes in batch_images:
        b64 = base64.b64encode(image_bytes).decode("ascii")
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{b64}"},
            }
        )
    content.append({"type": "text", "text": _build_vision_prompt(json_schema)})

    response = await client.chat.completions.create(
        model=_get_vl_model(),
        messages=[
            {
                "role": "user",
                "content": content,
            }
        ],
        temperature=0.1,
        max_tokens=16384,
    )
    text: str | None = response.choices[0].message.content
    if not text:
        logger.warning("[VL] 模型返回内容为空")
        return ""
    return text


def _merge_vision_results(parsed_results: list[dict]) -> dict:
    """合并多批结构化 JSON 为一个同构 dict。

    合并规则（对齐 EXTRACTION_JSON_SCHEMA 顶层结构）：
    - article：取首个非空；为空时保持空 dict
    - data_points / titer_tables：逐批 extend
    - 其余顶层字段：取首个非空
    """
    merged: dict = {}
    lists_key = {"data_points", "titer_tables"}

    for obj in parsed_results:
        if not isinstance(obj, dict):
            continue
        for key, value in obj.items():
            if isinstance(value, list) and key in lists_key:
                if key not in merged or not isinstance(merged.get(key), list):
                    merged[key] = []
                merged[key].extend(value)
            elif key == "article" and value is not None:
                if not merged.get("article"):
                    merged["article"] = value
            elif key not in merged and value is not None:
                merged[key] = value
    return merged


async def extract_with_vision(page_images: list[bytes], json_schema: dict) -> str:
    """使用本地视觉模型直接从 PDF 页面图片提取数据。

    长文档分批：按 VL_BATCH_SIZE 把 page_images 分批发送，每批独立提取成结构化 JSON，
    再合并为一个同构 JSON 字符串返回，避免整份图片一次性塞入导致上下文超限。

    Parameters
    ----------
    page_images : list[bytes]
        每页渲染出的图片字节列表（PNG）。
    json_schema : dict
        结构化输出约束用的 JSON Schema。

    Returns
    -------
    str
        合并后的 JSON 字符串；任何异常或全部批次失败都返回 ""（不抛异常）。
    """
    if not page_images:
        logger.warning("[VL] page_images 为空，跳过视觉提取")
        return ""

    try:
        client = AsyncOpenAI(
            base_url=settings.OLLAMA_BASE_URL,
            api_key=settings.OLLAMA_API_KEY,
        )

        batch_size = _get_vl_batch_size()
        batch_count = (len(page_images) + batch_size - 1) // batch_size
        parsed_results: list[dict] = []
        for i in range(batch_count):
            batch = page_images[i * batch_size : (i + 1) * batch_size]
            try:
                raw = await _call_single_batch(client, batch, json_schema)
            except Exception as e:
                logger.warning(f"[VL] 第 {i + 1}/{batch_count} 批请求失败，跳过: {e}")
                continue
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except (ValueError, TypeError):
                logger.warning(f"[VL] 第 {i + 1}/{batch_count} 批输出非合法 JSON，忽略")
                continue
            parsed_results.append(obj)

        if not parsed_results:
            logger.warning("[VL] 所有批次均未得到有效 JSON，返回空串")
            return ""

        merged = _merge_vision_results(parsed_results)
        logger.info(
            f"[VL] 分批视觉提取完成: {batch_count} 批，合并后 data_points="
            f"{len(merged.get('data_points') or [])}, titer_tables="
            f"{len(merged.get('titer_tables') or [])}"
        )
        return json.dumps(merged, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"[VL] 视觉提取失败，返回空串: {e}")
        return ""
