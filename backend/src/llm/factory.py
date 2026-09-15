"""多模型工厂 + 降级策略

策略说明：
    primary_only          : 只使用主模型，失败直接报错
    primary_fallback      : 主模型失败后，自动切换到备用模型（推荐）
    round_robin           : 轮询所有可用模型（分摊压力/限流）
"""
from __future__ import annotations

import asyncio
from typing import Optional, Sequence

from loguru import logger

from ..core.config import Settings, get_settings
from ..core.exceptions import ConfigError, LLMCallError
from .base import BaseLLMProvider, ChatCompletionMessageParam, DashScopeProvider, LLMResponse, OpenAIProvider


# ============================================================
# 工厂类
# ============================================================
class LLMFactory:
    """负责创建/持有所有可用 Provider，并按策略路由请求"""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.providers: list[BaseLLMProvider] = []
        self._idx = 0  # round_robin 游标

        # ---------- 按优先级初始化（顺序决定 fallback 顺序）----------
        self._init_openai()
        self._init_dashscope()

        if not self.providers:
            raise ConfigError("至少需要配置一个 LLM Provider (OPENAI_API_KEY 或 DASHSCOPE_API_KEY)")

        self.primary = self.providers[0]
        logger.info(f"LLMFactory 初始化完成: {[p.provider_name for p in self.providers]}，策略={settings.LLM_STRATEGY}")

    # ---------- 初始化 ----------
    def _init_openai(self) -> None:
        s = self.settings
        if not s.OPENAI_API_KEY:
            logger.debug("跳过 OpenAI Provider: API_KEY 未配置")
            return
        try:
            p = OpenAIProvider(
                api_key=s.OPENAI_API_KEY,
                base_url=s.OPENAI_BASE_URL,
                default_model=s.OPENAI_MODEL,
            )
            self.providers.append(p)
        except ConfigError:
            logger.warning("OpenAI Provider 初始化失败")

    def _init_dashscope(self) -> None:
        s = self.settings
        if not s.DASHSCOPE_API_KEY:
            logger.debug("跳过 DashScope Provider: API_KEY 未配置")
            return
        try:
            p = DashScopeProvider(
                api_key=s.DASHSCOPE_API_KEY,
                base_url=s.DASHSCOPE_BASE_URL,
                default_model=s.DASHSCOPE_MODEL,
            )
            self.providers.append(p)
        except ConfigError:
            logger.warning("DashScope Provider 初始化失败")

    # ---------- 策略路由 ----------
    async def acall(
        self,
        messages: Sequence[ChatCompletionMessageParam],
        **kwargs,
    ) -> LLMResponse:
        strategy = self.settings.LLM_STRATEGY

        if strategy == "primary_only":
            return await self.primary.acall(messages, **kwargs)

        if strategy == "primary_fallback":
            return await self._fallback_call(messages, **kwargs)

        if strategy == "round_robin":
            return await self._round_robin_call(messages, **kwargs)

        logger.warning(f"未知策略 {strategy}，回退到 primary_fallback")
        return await self._fallback_call(messages, **kwargs)

    async def _fallback_call(
        self,
        messages: Sequence[ChatCompletionMessageParam],
        **kwargs,
    ) -> LLMResponse:
        last_err: Optional[Exception] = None
        for i, p in enumerate(self.providers):
            try:
                return await p.acall(messages, **kwargs)
            except Exception as e:  # noqa: BLE001
                last_err = e
                if i < len(self.providers) - 1:
                    logger.warning(
                        f"[Fallback] Provider {p.provider_name} 失败: {e}，"
                        f"尝试下一个: {self.providers[i + 1].provider_name}"
                    )
                    await asyncio.sleep(0.2)
                else:
                    logger.error(f"[Fallback] 所有 Provider 都失败，最后一个错误: {e}")
        raise LLMCallError(f"所有 Provider 调用失败: {last_err}")

    async def _round_robin_call(
        self,
        messages: Sequence[ChatCompletionMessageParam],
        **kwargs,
    ) -> LLMResponse:
        p = self.providers[self._idx % len(self.providers)]
        self._idx += 1
        try:
            return await p.acall(messages, **kwargs)
        except Exception:  # noqa: BLE001
            # 轮询失败则 fallback 到所有其他
            return await self._fallback_call(messages, **kwargs)


# ============================================================
# 单例（模块级懒加载）
# ============================================================
_factory: Optional[LLMFactory] = None


def get_llm_factory() -> LLMFactory:
    global _factory
    if _factory is None:
        _factory = LLMFactory(get_settings())
    return _factory


async def llm_call(
    messages: Sequence[ChatCompletionMessageParam],
    **kwargs,
) -> LLMResponse:
    """便捷函数：直接获取工厂并调用"""
    factory = get_llm_factory()
    return await factory.acall(messages, **kwargs)
