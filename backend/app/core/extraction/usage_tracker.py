"""Token 用量统计（从原 app.core.llm_extractor 拆分）。

包含 _accumulate_usage / get_usage_summary / _MODEL_PRICING_OVERRIDES / _get_model_pricing。
"""

import logging
from typing import Optional

logger = logging.getLogger("uvicorn")


class UsageTrackerMixin:
    """Token 用量统计与费用估算。"""

    def _accumulate_usage(self, model: str, usage: Optional[dict]) -> None:
        """将单次 LLM 调用的 usage 累加到实例累加器，按模型分别统计。

        usage 结构: {"prompt_tokens": int, "completion_tokens": int, "total_tokens": int}
        """
        if not usage:
            return
        model_key = model or self.model or "unknown"
        entry = self._usage_accumulator.setdefault(
            model_key,
            {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "call_count": 0},
        )
        entry["prompt_tokens"] += int(usage.get("prompt_tokens", 0) or 0)
        entry["completion_tokens"] += int(usage.get("completion_tokens", 0) or 0)
        entry["total_tokens"] += int(usage.get("total_tokens", 0) or 0)
        entry["call_count"] += 1
        logger.info(
            f"[TokenUsage] 本次调用 model={model_key}, "
            f"prompt={usage.get('prompt_tokens', 0)}, "
            f"completion={usage.get('completion_tokens', 0)}, "
            f"total={usage.get('total_tokens', 0)}; "
            f"累计 call_count={entry['call_count']}, "
            f"total_tokens={entry['total_tokens']}"
        )

    def get_usage_summary(self) -> dict:
        """获取本次 extractor 实例的累计 token 用量摘要。

        返回结构:
        {
          "models": {model_name: {prompt_tokens, completion_tokens, total_tokens, call_count}},
          "total_prompt_tokens": int,
          "total_completion_tokens": int,
          "total_tokens": int,
          "total_call_count": int,
          "estimated_cost_usd": float,   # 基于 Provider get_pricing() 估算
          "primary_model": str,          # 调用次数最多的模型
        }
        """
        models = self._usage_accumulator
        total_prompt = sum(m["prompt_tokens"] for m in models.values())
        total_completion = sum(m["completion_tokens"] for m in models.values())
        total_tokens = sum(m["total_tokens"] for m in models.values())
        total_calls = sum(m["call_count"] for m in models.values())

        # 估算费用：按模型查 Provider 单价
        estimated_cost = 0.0
        for model_name, m in models.items():
            pricing = self._get_model_pricing(model_name)
            if pricing:
                # pricing: (input_per_1m, output_per_1m) 美元/百万 token
                cost_in = m["prompt_tokens"] / 1_000_000 * pricing[0]
                cost_out = m["completion_tokens"] / 1_000_000 * pricing[1]
                estimated_cost += cost_in + cost_out

        # 主模型：调用次数最多
        primary_model = max(models.items(), key=lambda x: x[1]["call_count"])[0] if models else None

        return {
            "models": dict(models),
            "total_prompt_tokens": total_prompt,
            "total_completion_tokens": total_completion,
            "total_tokens": total_tokens,
            "total_call_count": total_calls,
            "estimated_cost_usd": round(estimated_cost, 6),
            "primary_model": primary_model,
        }

    # 模型级单价覆盖表（model_substring_lower -> (input_per_1m, output_per_1m) 美元/百万 token）
    # 优先于 Provider.get_pricing() 的默认值，用于区分同一 Provider 下不同模型的单价。
    # 价格来源：各厂商官网公开定价（2026 年初参考值），可能随厂商调整而变化。
    _MODEL_PRICING_OVERRIDES: dict[str, tuple[float, float]] = {
        # DeepSeek（reasoner 在 chat 之前，避免误匹配）
        "deepseek-reasoner": (0.55, 2.19),
        "deepseek-chat":     (0.14, 0.28),
        # OpenAI（mini 变体在基础模型之前，避免 gpt-4o 误匹配 gpt-4o-mini）
        "gpt-4o-mini":       (0.15, 0.60),
        "gpt-4o":            (2.50, 10.00),
        "o1-mini":           (1.10, 4.40),
        "o3-mini":           (1.10, 4.40),
        "o1":                (15.00, 60.00),
        # Qwen (DashScope)
        "qwen-turbo":        (0.05, 0.20),
        "qwen-plus":         (0.40, 1.20),
        "qwen-max":          (2.50, 10.00),
        "qwen2.5-7b":        (0.05, 0.20),
        # Ollama 本地部署：无 API 费用
        "ollama":            (0.0, 0.0),
        "llama":             (0.0, 0.0),
        "mistral":           (0.0, 0.0),
    }

    @classmethod
    def _get_model_pricing(cls, model: str) -> Optional[tuple[float, float]]:
        """查询模型单价 (input_per_1m, output_per_1m) 美元/百万 token。

        查找顺序：
          1. _MODEL_PRICING_OVERRIDES 按模型名小写子串匹配（最精确）
          2. Provider.get_pricing() 默认值（同一 Provider 下所有模型统一价）
          3. 返回 None（无法计价，费用记为 0）
        """
        if not model:
            return None
        model_lower = model.lower()
        # 1. 精确子串匹配覆盖表
        for key, pricing in cls._MODEL_PRICING_OVERRIDES.items():
            if key in model_lower:
                return pricing
        # 2. Provider 默认值
        try:
            from app.core.providers.base import get_provider_for_model
            provider_cls = get_provider_for_model(model)
            if provider_cls is not None:
                pricing = provider_cls.get_pricing()
                if pricing:
                    return pricing
        except (ImportError, AttributeError):
            pass
        return None
