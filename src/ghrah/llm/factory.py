# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""LLM 工厂：基于 agentconf SDK 创建 ChatFormat 实例。

数据流：
    agentconf SQLite DB
        └── resolve_agent(agent_name)
                ├── provider_type: ProviderType  →  决定使用哪个 ChatFormat 子类
                ├── base_url: str                →  API 端点
                ├── api_key: SecretStr           →  认证密钥（安全获取）
                ├── model_name: str              →  模型标识
                ├── temperature: float | None    →  Agent 级参数
                ├── top_p: float | None          →  Agent 级参数
                └── max_tokens: int | None       →  Agent 级参数
                        │
                        ▼
                LLMFactory.create(resolved)
                        │
                        ▼
                ChatFormat 实例（OpenAIFormat / AnthropicFormat）
"""

from __future__ import annotations

import logging
from typing import Any

from agentconf import ProviderType

from ghrah.chat.format import ChatFormat
from ghrah.core.exceptions import LLMError

logger = logging.getLogger(__name__)


def _get_secret_value(api_key: Any) -> str | None:
    """安全提取 API Key。

    agentconf 使用 Pydantic SecretStr 保护 api_key，
    需要调用 get_secret_value() 提取实际值。
    """
    if api_key is None:
        return None
    if hasattr(api_key, "get_secret_value"):
        return api_key.get_secret_value()
    return str(api_key)


class LLMFactory:
    """基于 agentconf resolved 配置创建 ChatFormat 实例。

    Usage:
        from agentconf import AgentsConfig

        config = AgentsConfig()
        resolved = config.resolve_agent("code-reviewer")
        llm = LLMFactory.create(resolved)
    """

    @classmethod
    def create(cls, resolved_agent: Any) -> ChatFormat:
        """从 agentconf resolved 配置创建 ChatFormat 实例。

        Args:
            resolved_agent: agentconf 的 resolve_agent() 返回值，
                           包含完整的 Provider → LLM → Agent 配置链。

        Returns:
            ChatFormat 实例。

        Raises:
            LLMError: 不支持的 provider 类型或创建失败。
        """
        try:
            llm_config = resolved_agent.model
            provider_type = llm_config.provider_type
            model_name = llm_config.model_name
            base_url = llm_config.base_url
            api_key = _get_secret_value(llm_config.api_key)

            temperature = getattr(resolved_agent, "temperature", None) or 0.7
            max_tokens = getattr(resolved_agent, "max_tokens", None)
            top_p = getattr(resolved_agent, "top_p", None)

            logger.info(
                f"Creating ChatFormat: provider={provider_type!r}, "
                f"model={model_name}, base_url={base_url}"
            )

            chat_format = cls._build_chat_format(
                provider_type=provider_type,
                model_name=model_name,
                base_url=base_url,
                api_key=api_key,
                temperature=temperature,
                max_tokens=max_tokens,
                top_p=top_p,
            )

            logger.info(f"ChatFormat created successfully: {type(chat_format).__name__}")
            return chat_format

        except LLMError:
            raise
        except Exception as e:
            raise LLMError(
                provider=str(
                    resolved_agent.model.provider_type
                    if hasattr(resolved_agent, "llm")
                    else "unknown"
                ),
                message=f"Failed to create ChatFormat from agentconf: {e}",
            ) from e

    @classmethod
    def _build_chat_format(
        cls,
        provider_type: ProviderType,
        model_name: str,
        base_url: str,
        api_key: str | None,
        temperature: float,
        max_tokens: int | None,
        top_p: float | None,
    ) -> ChatFormat:
        """根据 ProviderType 枚举构建对应的 ChatFormat。"""

        if provider_type in (ProviderType.OPENAI, ProviderType.CUSTOM):
            from ghrah.chat.format.openai import OpenAIFormat

            return OpenAIFormat(
                model=model_name,
                api_key=api_key,
                base_url=base_url or None,
                temperature=temperature,
                max_tokens=max_tokens,
                top_p=top_p,
            )

        if provider_type == ProviderType.ANTHROPIC:
            from ghrah.chat.format.anthropic import AnthropicFormat

            return AnthropicFormat(
                model=model_name,
                api_key=api_key,
                base_url=base_url or None,
                temperature=temperature,
                max_tokens=max_tokens or 4096,
                top_p=top_p,
            )

        if provider_type == ProviderType.DEEPSEEK:
            from ghrah.chat.format.deepseek import DeepSeekFormat

            return DeepSeekFormat(
                model=model_name,
                api_key=api_key,
                base_url=base_url or None,
                temperature=temperature,
                max_tokens=max_tokens,
                top_p=top_p,
            )

        supported = [pt.value for pt in ProviderType]
        raise LLMError(
            provider=str(provider_type),
            message=f"Unsupported provider type: {provider_type!r}. Supported types: {supported}",
        )
