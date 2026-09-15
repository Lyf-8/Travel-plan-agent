"""LLM 抽象基类 + 统一调用封装 + 使用记录

设计要点：
    1. 所有 LLM 调用必须走 LLMClient.acall()，统一重试/限流/降级/日志
    2. 支持多 Provider 多模型（OpenAI 兼容协议 + 千问 DashScope 兼容协议）
    3. 记录每次调用的 token / 耗时 / 成本
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

from loguru import logger
from openai import AsyncOpenAI
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ..core.config import get_settings
from ..core.exceptions import (
    ConfigError,
    LLMCallError,
    LLMRateLimitError,
    LLMTimeoutError,
)

try:
    # 可选依赖：仅在启用了结构化输出时需要
    from openai.types.chat import ChatCompletionMessageParam
except Exception:  # pragma: no cover
    ChatCompletionMessageParam = Any  # type: ignore


# ============================================================
# 数据结构
# ============================================================
@dataclass
class LLMUsage:
    """单次 LLM 调用的资源统计"""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_cny: float = 0.0  # 估算成本（元）
    latency_ms: int = 0

    @classmethod
    def from_openai_usage(cls, usage: Any, model: str, cost_per_1k_in: float = 0.0, cost_per_1k_out: float = 0.0) -> "LLMUsage":
        prompt = getattr(usage, "prompt_tokens", 0) or 0
        completion = getattr(usage, "completion_tokens", 0) or 0
        total = getattr(usage, "total_tokens", 0) or (prompt + completion)
        cost = (prompt / 1000.0) * cost_per_1k_in + (completion / 1000.0) * cost_per_1k_out
        return cls(
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=total,
            cost_cny=round(cost, 6),
        )


@dataclass
class LLMResponse:
    """LLM 返回值封装"""
    content: str
    model: str
    provider: str
    usage: LLMUsage
    raw: Any = field(default=None, repr=False)  # 原始响应对象（可选）
    finish_reason: Optional[str] = None


# ============================================================
# 模型成本表（元 / 1000 tokens）- 2026 年参考价，更新时同步
# ============================================================
MODEL_COST_TABLE: dict[str, tuple[float, float]] = {
    # (输入每1k元, 输出每1k元)
    "gpt-4o-mini": (0.00015, 0.0006),
    "gpt-4o": (0.00375, 0.015),
    "gpt-4-turbo": (0.0075, 0.03),
    "gpt-3.5-turbo": (0.0005, 0.0015),
    "qwen-plus": (0.0004, 0.0012),
    "qwen-max": (0.008, 0.02),
    "qwen-turbo": (0.00015, 0.00045),
    "deepseek-chat": (0.0007, 0.0028),
}


def _estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    if model in MODEL_COST_TABLE:
        ci, co = MODEL_COST_TABLE[model]
    else:
        ci, co = 0.0, 0.0
    return round((prompt_tokens / 1000.0) * ci + (completion_tokens / 1000.0) * co, 6)


# ============================================================
# Provider 抽象基类
# ============================================================
class BaseLLMProvider(ABC):
    """Provider 基类 - 每个具体实现（OpenAI / DashScope）负责:
        1. 初始化 AsyncOpenAI 兼容 client
        2. 提供 provider_name / default_model
        3. 实现 _acompletion 单步调用
    """

    provider_name: str = "base"

    def __init__(self, api_key: Optional[str], base_url: Optional[str], default_model: str) -> None:
        if not api_key:
            raise ConfigError(f"{self.provider_name} API Key 未配置")
        self.default_model = default_model
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=60,
        )

    @abstractmethod
    async def _acompletion(
        self,
        messages: Sequence[ChatCompletionMessageParam],
        model: Optional[str],
        temperature: Optional[float],
        max_tokens: Optional[int],
        response_format: Optional[Any],
        **extra_kwargs,
    ) -> Any:
        """单步请求，返回 OpenAI 兼容的 ChatCompletion 对象"""
        ...

    # ---------- 公开方法：带重试 + 统计 ----------
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((LLMTimeoutError, LLMRateLimitError, LLMCallError)),
        reraise=True,
    )
    async def acall(
        self,
        messages: Sequence[ChatCompletionMessageParam],
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        response_format: Optional[Any] = None,
        **extra_kwargs,
    ) -> LLMResponse:
        """对外暴露的异步调用入口，统一重试与记录"""
        t0 = time.perf_counter()
        use_model = model or self.default_model
        settings = get_settings()
        use_temp = settings.OPENAI_TEMPERATURE if temperature is None else temperature
        use_max_tokens = settings.OPENAI_MAX_TOKENS if max_tokens is None else max_tokens

        try:
            raw = await self._acompletion(
                messages=messages,
                model=use_model,
                temperature=use_temp,
                max_tokens=use_max_tokens,
                response_format=response_format,
                **extra_kwargs,
            )
        except TimeoutError as e:
            raise LLMTimeoutError(str(e)) from e
        except Exception as e:  # noqa: BLE001 - 底层 SDK 错误都包一层
            msg = str(e).lower()
            if "rate limit" in msg or "429" in msg:
                raise LLMRateLimitError(str(e)) from e
            if "timeout" in msg or "timed out" in msg:
                raise LLMTimeoutError(str(e)) from e
            raise LLMCallError(f"{self.provider_name}: {e}") from e

        latency_ms = int((time.perf_counter() - t0) * 1000)

        # 解析 response
        try:
            choice = raw.choices[0]
            content = choice.message.content or ""
            finish_reason = getattr(choice, "finish_reason", None)
        except Exception as e:  # pragma: no cover
            raise LLMCallError(f"无法解析 LLM 返回: {e}") from e

        # usage
        usage_obj = getattr(raw, "usage", None)
        prompt_tok = int(getattr(usage_obj, "prompt_tokens", 0) or 0)
        comp_tok = int(getattr(usage_obj, "completion_tokens", 0) or 0)
        total_tok = int(getattr(usage_obj, "total_tokens", 0) or (prompt_tok + comp_tok))
        cost = _estimate_cost(use_model, prompt_tok, comp_tok)

        usage = LLMUsage(
            prompt_tokens=prompt_tok,
            completion_tokens=comp_tok,
            total_tokens=total_tok,
            cost_cny=cost,
            latency_ms=latency_ms,
        )

        resp = LLMResponse(
            content=content,
            model=use_model,
            provider=self.provider_name,
            usage=usage,
            raw=raw,
            finish_reason=finish_reason,
        )

        logger.info(
            f"[LLM] {self.provider_name}:{use_model} | "
            f"t={prompt_tok}+{comp_tok}={total_tok} | "
            f"cost={cost:.5f}元 | latency={latency_ms}ms"
        )
        return resp


# ============================================================
# 具体 Provider 实现（OpenAI 协议兼容的都用同一套即可）
# ============================================================
class OpenAIProvider(BaseLLMProvider):
    provider_name = "openai"

    async def _acompletion(
        self,
        messages: Sequence[ChatCompletionMessageParam],
        model: Optional[str],
        temperature: Optional[float],
        max_tokens: Optional[int],
        response_format: Optional[Any],
        **extra_kwargs,
    ) -> Any:
        kwargs: dict[str, Any] = {
            "model": model or self.default_model,
            "messages": list(messages),
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format is not None:
            kwargs["response_format"] = response_format
        kwargs.update(extra_kwargs)
        return await self.client.chat.completions.create(**kwargs)


class DashScopeProvider(BaseLLMProvider):
    """阿里千问 DashScope - 其 compatible-mode 支持 OpenAI 协议，所以实现和 OpenAI 一样"""
    provider_name = "dashscope"

    async def _acompletion(
        self,
        messages: Sequence[ChatCompletionMessageParam],
        model: Optional[str],
        temperature: Optional[float],
        max_tokens: Optional[int],
        response_format: Optional[Any],
        **extra_kwargs,
    ) -> Any:
        kwargs: dict[str, Any] = {
            "model": model or self.default_model,
            "messages": list(messages),
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format is not None:
            kwargs["response_format"] = response_format
        kwargs.update(extra_kwargs)
        return await self.client.chat.completions.create(**kwargs)
