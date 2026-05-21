# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""ToolCallFoldStrategy：ToolCall 折叠策略。

压缩冗长的工具调用返回（ToolResultBlock），减少单条消息的体积。

行为：
- 识别 role="tool" 消息中的 ToolResultBlock，如果 content 超过阈值，截断并添加省略标记
- AI 消息的 tool_calls 保持不变（保留函数名和参数等关键信息）
- 不改变消息数量，只压缩单条消息体积

适用场景：工具返回大量数据（如文件内容、API 响应）时压缩。
"""

from __future__ import annotations

from ghrah.chat.content import ContentBlock, ToolResultBlock
from ghrah.chat.message import ChatMessage
from ghrah.context.window import WindowStrategy

__all__ = ["ToolCallFoldStrategy"]

# 默认截断长度
_DEFAULT_MAX_CONTENT_LENGTH = 500

# 截断后缀模板
_TRUNCATION_SUFFIX = "\n...[truncated, original: {length} chars]"


class ToolCallFoldStrategy(WindowStrategy):
    """ToolCall 折叠策略 — 压缩冗长的工具调用返回。

    行为：
    - 识别 role="tool" 消息中的 ToolResultBlock，如果 content 超过阈值，截断并添加省略标记
    - AI 消息的 tool_calls 保持不变
    - 不改变消息数量，只压缩单条消息体积

    适用场景：工具返回大量数据时压缩。

    Args:
        max_content_length: ToolResultBlock content 的最大字符长度，默认 500
    """

    def __init__(self, max_content_length: int = _DEFAULT_MAX_CONTENT_LENGTH) -> None:
        if max_content_length <= 0:
            raise ValueError(f"max_content_length must be positive, got {max_content_length}")
        self._max_content_length = max_content_length

    @property
    def max_content_length(self) -> int:
        """最大 content 长度。"""
        return self._max_content_length

    async def apply(self, messages: list[ChatMessage], token_budget: int) -> list[ChatMessage]:
        """应用 ToolCall 折叠策略。

        Args:
            messages: 输入消息列表
            token_budget: token 预算（此策略不使用此参数，仅保留接口一致）

        Returns:
            折叠后的消息列表
        """
        result: list[ChatMessage] = []
        for msg in messages:
            if msg.role == "tool":
                folded = self._fold_tool_message(msg)
                result.append(folded)
            else:
                result.append(msg)
        return result

    def _fold_tool_message(self, msg: ChatMessage) -> ChatMessage:
        """折叠 role="tool" 消息中的 ToolResultBlock。

        如果 content 超过 max_content_length，截断并添加省略标记。

        Args:
            msg: 原始 ChatMessage (role="tool")

        Returns:
            折叠后的 ChatMessage（如果需要折叠），或原始消息
        """
        needs_fold = False
        for block in msg.content_blocks:
            if isinstance(block, ToolResultBlock) and len(block.content) > self._max_content_length:
                needs_fold = True
                break

        if not needs_fold:
            return msg

        new_blocks: list[ContentBlock] = []
        for block in msg.content_blocks:
            if isinstance(block, ToolResultBlock):
                content = block.content
                if len(content) > self._max_content_length:
                    suffix = _TRUNCATION_SUFFIX.format(length=len(content))
                    truncated_content = content[: self._max_content_length] + suffix
                    new_blocks.append(
                        ToolResultBlock(
                            tool_call_id=block.tool_call_id,
                            name=block.name,
                            content=truncated_content,
                            success=block.success,
                            error=block.error,
                        )
                    )
                else:
                    new_blocks.append(block)
            else:
                new_blocks.append(block)

        return ChatMessage(
            role=msg.role,
            content_blocks=new_blocks,
            source=msg.source,
            metadata=msg.metadata,
        )

    @property
    def name(self) -> str:
        """策略名称。"""
        return "tool_call_fold"
