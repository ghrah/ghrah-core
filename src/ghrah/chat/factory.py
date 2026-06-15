# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""ChatMessageFactory：MessageFactory 的 ChatMessage 默认实现。

将消息构造逻辑从 context 策略中解耦——策略通过 MessageFactory Protocol
构造新消息，而 ChatMessageFactory 使用具体的 ChatMessage / ToolResultBlock。

context 子系统不直接 import 此模块；由编排层（agents）在构造 WindowManager 时注入。
"""

from __future__ import annotations

from typing import Any

from ghrah.chat.content import ContentBlock, ToolResultBlock
from ghrah.chat.message import ChatMessage

__all__ = ["ChatMessageFactory"]


class ChatMessageFactory:
    """MessageFactory 的 ChatMessage 实现。

    提供基于 ChatMessage 和 ToolResultBlock 的消息构造方法，
    供 ToolCallFoldStrategy、LLMSummaryStrategy 等需要构造新消息的策略使用。
    """

    def create_message(
        self,
        role: str,
        content_blocks: list[Any] | None = None,
        *,
        text: str | None = None,
        source: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ChatMessage:
        """构造 ChatMessage 实例。

        Args:
            role: 消息角色（system, user, ai, tool）
            content_blocks: 内容 block 列表
            text: 文本内容（如果提供，会创建 TextBlock 并追加到 content_blocks）
            source: 消息来源
            metadata: 消息元数据

        Returns:
            ChatMessage 实例
        """
        blocks: list[ContentBlock] = list(content_blocks) if content_blocks else []
        if text is not None:
            from ghrah.chat.content import TextBlock
            blocks.append(TextBlock(text=text))
        return ChatMessage(
            role=role,
            content_blocks=blocks,
            source=source,
            metadata=metadata or {},
        )

    def create_tool_result_block(
        self,
        tool_call_id: str,
        name: str | None = None,
        content: str = "",
        success: bool = True,
        error: str | None = None,
    ) -> ToolResultBlock:
        """构造 ToolResultBlock 实例。

        Args:
            tool_call_id: 工具调用 ID
            name: 工具名称
            content: 工具返回内容
            success: 是否成功
            error: 错误信息

        Returns:
            ToolResultBlock 实例
        """
        return ToolResultBlock(
            tool_call_id=tool_call_id,
            name=name,
            content=content,
            success=success,
            error=error,
        )
