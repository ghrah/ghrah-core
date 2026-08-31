# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""窗口管理和上下文消息的协议定义。

通过 Protocol（structural subtyping）定义 context 子系统对外部类型的依赖接口，
使 context 不再直接 import chat 的具体类型（ChatMessage, TextBlock 等）。

设计原则：
- WindowableBlock 只要求 type 属性（discriminated union key），
  其余字段通过 getattr 按 type 分支访问（duck typing）
- 不使用 @runtime_checkable：Protocol 属性是全量并集，
  实际 block 只实现子集，isinstance 检查必然失败

协议层次：
- WindowableBlock: content block 的最小接口
- WindowableMessage: 窗口管理中消息的最小接口
- MessageFactory: 消息和 block 的构造接口（用于策略需要构造新消息时）
- SummaryLLMProtocol: LLM 摘要策略对 LLM 的最小依赖接口
- ContextManagerProtocol: AbilityExecutionContext 对 ContextManager 的最小依赖接口
"""

from __future__ import annotations

from typing import Any, Protocol

__all__ = [
    "WindowableBlock",
    "WindowableMessage",
    "MessageFactory",
    "SummaryLLMProtocol",
    "SummaryResponseProtocol",
    "ContextManagerProtocol",
]


class WindowableBlock(Protocol):
    """Content block 的最小接口 — context 窗口管理只依赖此协议。

    只要求 type 属性作为 dispatch key，其余字段通过 getattr(block, field, default)
    按 block.type 分支访问。这是 duck typing 而非 structural subtyping：
    不同 block 类型只实现各自子集的属性。

    属性参考（按 block.type 分支）：
    - text:        .text
    - tool_call:   .arguments, .name, .id
    - tool_result: .content, .name, .tool_call_id, .success, .error
    - image/file:  .base64, .url
    - audio:       .data
    """

    @property
    def type(self) -> str: ...


class WindowableMessage(Protocol):
    """窗口管理中消息的最小接口 — context 子系统只依赖此协议。

    ChatMessage 天然满足此协议，无需显式继承。
    """

    @property
    def role(self) -> str: ...

    @property
    def content_blocks(self) -> list[Any]: ...

    @property
    def text(self) -> str: ...

    @property
    def has_tool_calls(self) -> bool: ...

    @property
    def tool_results(self) -> list[Any]: ...

    @property
    def source(self) -> str | None: ...

    @property
    def metadata(self) -> dict[str, Any]: ...

    def to_dict(self) -> dict[str, Any]: ...


class MessageFactory(Protocol):
    """消息和 block 的构造接口。

    用于策略需要构造新消息时（如 ToolCallFoldStrategy, LLMSummaryStrategy），
    避免直接 import ChatMessage / ToolResultBlock 等具体类型。

    默认实现 ChatMessageFactory 在 ghrah.chat.factory 中。
    """

    def create_message(
        self,
        role: str,
        content_blocks: list[Any] | None = None,
        *,
        text: str | None = None,
        source: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Any: ...

    def create_tool_result_block(
        self,
        tool_call_id: str,
        name: str | None = None,
        content: str = "",
        success: bool = True,
        error: str | None = None,
    ) -> Any: ...


class SummaryResponseProtocol(Protocol):
    """LLM 响应的最小接口 — 仅用于摘要策略。"""

    @property
    def text(self) -> str: ...


class SummaryLLMProtocol(Protocol):
    """LLM 摘要策略对 LLM 的最小依赖接口。

    LLMSummaryStrategy 只需要调用 generate() 获取摘要文本，
    不需要知道 ChatFormat 的完整接口。
    """

    async def generate(
        self,
        messages: list[Any],
        tools: list[dict[str, Any]] | None = None,
    ) -> SummaryResponseProtocol: ...


class ContextManagerProtocol(Protocol):
    """AbilityExecutionContext 对 ContextManager 的最小依赖接口。

    解除 abilities → context 的循环依赖。
    """

    def apply_state_changes(self, changes: dict[str, Any]) -> dict[str, Any]: ...
