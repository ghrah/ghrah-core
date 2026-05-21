# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""LLM 交互格式适配器。

封装不同 SDK 的消息格式和 API 差异，统一转换为项目内部的 ChatMessage + LLMResponse。

包含：
- ChatFormat: 格式适配器抽象基类
- LLMResponse: 统一的 LLM 响应
- TokenUsage: token 用量
- create_format: 工厂函数
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ghrah.chat.content import ContentBlock, ReasoningBlock, TextBlock, ToolCallBlock
from ghrah.chat.message import ChatMessage

if TYPE_CHECKING:
    from ghrah.core.config import ModelOverrides


@dataclass
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TokenUsage:
        return cls(
            input_tokens=data.get("input_tokens", 0),
            output_tokens=data.get("output_tokens", 0),
            total_tokens=data.get("total_tokens", 0),
        )


@dataclass
class LLMResponse:
    content_blocks: list[ContentBlock] = field(default_factory=list)
    token_usage: TokenUsage | None = None
    response_metadata: dict[str, Any] = field(default_factory=dict)
    raw: Any = None

    @property
    def text(self) -> str:
        return "".join(b.text for b in self.content_blocks if isinstance(b, TextBlock))

    @property
    def tool_calls(self) -> list[ToolCallBlock]:
        return [b for b in self.content_blocks if isinstance(b, ToolCallBlock)]

    @property
    def reasoning(self) -> str | None:
        for b in self.content_blocks:
            if isinstance(b, ReasoningBlock):
                return b.reasoning
        return None

    def to_chat_message(self, source: str | None = None) -> ChatMessage:
        return ChatMessage(
            role="ai",
            content_blocks=list(self.content_blocks),
            source=source,
            metadata=self.response_metadata,
        )


class ChatFormat(ABC):
    _tools: list[dict[str, Any]]

    def __init__(self) -> None:
        self._tools: list[dict[str, Any]] = []

    @property
    @abstractmethod
    def model(self) -> str: ...

    @abstractmethod
    async def generate(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        ...

    # 预留流式接口（当前不实现）
    # async def stream(
    #     self, messages: list[ChatMessage], tools: list[dict[str, Any]] | None = None
    # ) -> AsyncIterator[TextBlock | ToolCallChunkBlock]:
    #     ...

    def configure_tools(self, tools: list[dict[str, Any]]) -> None:
        self._tools = tools

    def apply_model_overrides(self, overrides: ModelOverrides) -> None:
        """将 Manifest 模型覆盖值应用到当前实例。

        由 ActorAgent._ensure_llm() 在创建 ChatFormat 后调用，
        Manifest 的 model_overrides 优先级高于 agentconf 解析结果。
        子类应重写此方法以处理子类特有的属性（如 top_k），
        并调用 super().apply_model_overrides(overrides) 处理共享属性。

        Args:
            overrides: 来自 AgentManifest.model 的覆盖值，非 None 字段覆盖当前值
        """
        if overrides.temperature is not None:
            self._temperature = overrides.temperature
        if overrides.max_tokens is not None:
            self._max_tokens = overrides.max_tokens
        if overrides.top_p is not None:
            self._top_p = overrides.top_p


__all__ = ["ChatFormat", "LLMResponse", "TokenUsage", "create_format"]


def create_format(provider_type: str, **kwargs: object) -> ChatFormat:
    if provider_type == "openai":
        from ghrah.chat.format.openai import OpenAIFormat

        return OpenAIFormat(**kwargs)  # type: ignore[arg-type]
    elif provider_type == "anthropic":
        from ghrah.chat.format.anthropic import AnthropicFormat

        return AnthropicFormat(**kwargs)  # type: ignore[arg-type]
    elif provider_type == "deepseek":
        from ghrah.chat.format.deepseek import DeepSeekFormat

        return DeepSeekFormat(**kwargs)  # type: ignore[arg-type]
    else:
        raise ValueError(f"Unsupported provider type: {provider_type!r}")
