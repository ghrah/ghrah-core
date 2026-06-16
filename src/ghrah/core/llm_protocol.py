# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""LLM 客户端和响应的最小接口协议定义。

通过 Protocol（structural subtyping）定义 LLM 层对外部类型的依赖接口，
使 agents 层不再直接 import chat.format 的具体类型（ChatFormat, LLMResponse）。

设计原则：
- LLMProtocol 仅包含 ActorAgent 实际调用的方法
- LLMResponseProtocol 仅包含 ActorAgent._action() 实际访问的属性
- 方法签名中使用 Any 替代 chat 层的具体类型（如 ChatMessage, ToolCallBlock），
  避免 protocol 层反向依赖 chat
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

__all__ = [
    "LLMProtocol",
    "LLMResponseProtocol",
]


@runtime_checkable
class LLMResponseProtocol(Protocol):
    """LLM 响应的最小接口 — agents 层仅依赖此协议。

    ChatFormat.LLMResponse 天然满足此协议，无需显式继承。
    """

    @property
    def text(self) -> str: ...

    @property
    def tool_calls(self) -> list[Any]: ...

    def to_chat_message(self, source: str | None = None) -> Any: ...

    @property
    def token_usage(self) -> Any | None: ...

    @property
    def response_metadata(self) -> dict[str, Any]: ...

    @property
    def reasoning(self) -> str | None: ...


@runtime_checkable
class LLMProtocol(Protocol):
    """LLM 客户端的最小接口 — agents 层仅依赖此协议。

    ChatFormat 天然满足此协议，无需显式继承。
    """

    @property
    def model(self) -> str: ...

    async def generate(
        self,
        messages: list[Any],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponseProtocol: ...

    def configure_tools(self, tools: list[dict[str, Any]]) -> None: ...

    def apply_model_overrides(self, overrides: Any) -> None: ...
