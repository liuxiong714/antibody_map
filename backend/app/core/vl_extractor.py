"""视觉多模态提取器骨架：让本地视觉模型（如 Qwen3.8:27b）直接读 PDF 页面图片提取数据。

本模块仅负责把页面图片 + JSON Schema 组装成多模态请求发给本地 Ollama 视觉模型，
返回模型输出的原始文本（JSON 字符串）。后处理、grounding、字段归一化属于后续步骤，
不在本文件实现。
"""
import base64
import logging
from typing import Optional

from openai import AsyncOpenAI

from app.config import settings

logger = logging.getLogger("uvicorn")

# 默认视觉模型名。settings 中没有 VL_MODEL 字段时使用该写死默认值；
# 若后续在 config.py 增加 VL_MODEL 配置，这里会自动优先读取配置值。
DEFAULT_VL_MODEL = "qwen3.8:27b"


def _get_vl_model() -> str:
    """读取视觉模型名：优先 settings.VL_MODEL，缺失时回退到写死默认值。"""
    return getattr(settings, "VL_MODEL", None) or DEFAULT_VL_MODEL


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


async def extract_with_vision(page_images: list[bytes], json_schema: dict) -> str:
    """使用本地视觉模型直接从 PDF 页面图片提取数据。

    Parameters
    ----------
    page_images : list[bytes]
        每页渲染出的图片字节列表（PNG）。
    json_schema : dict
        结构化输出约束用的 JSON Schema。

    Returns
    -------
    str
        模型输出的原始文本（JSON 字符串）；任何异常都返回 ""（不抛异常）。
    """
    if not page_images:
        logger.warning("[VL] page_images 为空，跳过视觉提取")
        return ""

    try:
        client = AsyncOpenAI(
            base_url=settings.OLLAMA_BASE_URL,
            api_key=settings.OLLAMA_API_KEY,
        )

        content: list[dict] = []
        for image_bytes in page_images:
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
        text: Optional[str] = response.choices[0].message.content
        if not text:
            logger.warning("[VL] 模型返回内容为空")
            return ""
        logger.info(f"[VL] 视觉提取返回内容长度: {len(text)}")
        return text
    except Exception as e:
        logger.warning(f"[VL] 视觉提取失败，返回空串: {e}")
        return ""
