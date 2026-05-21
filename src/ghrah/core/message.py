# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""消息定义：Agent 间通信的统一消息协议"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class MessageType(str, Enum):
    """消息类型枚举"""

    CHAT = "chat"  # 普通对话消息
    COMMAND = "command"  # 命令消息（要求执行操作）
    TOOL_CALL = "tool_call"  # 工具调用请求
    TOOL_RESULT = "tool_result"  # 工具调用结果
    RESULT = "result"  # 最终结果
    ERROR = "error"  # 错误消息
    BROADCAST = "broadcast"  # 广播消息


@dataclass
class TokenUsage:
    """LLM 调用的 token 用量。

    Attributes:
        input_tokens: 输入 token 数
        output_tokens: 输出 token 数
        total_tokens: 总 token 数
    """

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0

    def to_dict(self) -> dict[str, int]:
        """转换为 dict，便于序列化。"""
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TokenUsage:
        """从 dict 创建 TokenUsage。"""
        return cls(
            input_tokens=data.get("input_tokens", 0),
            output_tokens=data.get("output_tokens", 0),
            total_tokens=data.get("total_tokens", 0),
        )


@dataclass
class Message:
    """Agent 间通信的统一消息对象。

    Attributes:
        id: 消息唯一 ID
        sender: 发送者 Agent 名称
        recipient: 接收者 Agent 名称（"*" 表示广播）
        content: 消息文本内容
        type: 消息类型
        metadata: 扩展元数据（工具参数、错误信息等）
        timestamp: 消息创建时间戳（Unix 时间）
        reply_to: 回复的目标消息 ID（用于请求-响应关联）
    """

    sender: str
    recipient: str
    content: str
    type: MessageType = MessageType.CHAT
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=lambda: __import__("time").time())
    reply_to: str | None = None

    def to_chat_message(self):
        """转换为 ChatMessage。

        将内部消息协议转换为 ChatMessage，用于 LLM 上下文管理。

        Returns:
            ChatMessage 实例
        """
        from ghrah.chat.content import ContentBlock, TextBlock
        from ghrah.chat.message import ChatMessage

        blocks: list[ContentBlock] = [TextBlock(text=self.content)]

        role_map: dict[MessageType, tuple[str, str | None]] = {
            MessageType.CHAT: ("user", self.sender),
            MessageType.COMMAND: ("user", self.sender),
            MessageType.TOOL_CALL: ("ai", self.sender),
            MessageType.TOOL_RESULT: ("tool", self.sender),
            MessageType.RESULT: ("ai", self.sender),
            MessageType.ERROR: ("system", self.sender),
            MessageType.BROADCAST: ("user", self.sender),
        }

        role, source = role_map.get(self.type, ("user", self.sender))
        return ChatMessage(
            role=role,
            content_blocks=blocks,
            source=source,
            metadata=self.metadata,
        )

    @staticmethod
    def create_reply(
        original: Message, content: str, msg_type: MessageType | None = None
    ) -> Message:
        """便捷方法：基于原始消息创建回复。

        Args:
            original: 原始消息
            content: 回复内容
            msg_type: 回复消息类型（默认为 RESULT）

        Returns:
            新的回复 Message
        """
        return Message(
            sender=original.recipient,
            recipient=original.sender,
            content=content,
            type=msg_type or MessageType.RESULT,
            reply_to=original.id,
        )

    def __repr__(self) -> str:
        return (
            f"Message(id={self.id!r}, {self.sender!r} -> {self.recipient!r}, "
            f"type={self.type.value!r}, content={self.content[:50]!r}...)"
        )
