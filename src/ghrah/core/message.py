# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""消息定义：Agent 间通信的统一消息协议"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

__all__ = ["AgentMessage", "MessageType", "classify_source"]


class MessageType(str, Enum):
    """消息类型枚举"""

    CHAT = "chat"  # 普通对话消息
    COMMAND = "command"  # 命令消息（要求执行操作）
    TOOL_CALL = "tool_call"  # 工具调用请求
    TOOL_RESULT = "tool_result"  # 工具调用结果
    RESULT = "result"  # 最终结果
    ERROR = "error"  # 错误消息
    BROADCAST = "broadcast"  # 广播消息


def classify_source(sender: str) -> str:
    """将 sender 归类为 {category}:{object} 格式的 source。

    当前规则（仅 human/agent，system/tool 不经此函数）：
    - sender == "user" → "human:user"
    - 其他 → f"agent:{sender}"

    扩展点：未来引入多人类/sensor/cron 时，在此增加分类规则，
    或改为从 AgentMessage.sender_type 字段取值。
    """
    if sender == "user":
        return "human:user"
    return f"agent:{sender}"


@dataclass
class AgentMessage:
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
        content_blocks: 结构化内容块列表（序列化后的字典），
            保留 reasoning/text 等类型区分。
            为 None 时表示仅有纯文本 content。

    Note:
        类名 AgentMessage 用于区别于 ghrah.protocol.types.Envelope（别名 Message）。
        本类是 Agent 间通信的领域消息，不是 WebSocket 信封。
    """

    sender: str
    recipient: str
    content: str
    type: MessageType = MessageType.CHAT
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=lambda: __import__("time").time())
    reply_to: str | None = None
    content_blocks: list[dict[str, Any]] | None = None

    def to_chat_message(self):
        """转换为 ChatMessage。

        将内部消息协议转换为 ChatMessage，用于 LLM 上下文管理。

        如果 content_blocks 存在，优先使用结构化块；
        否则回退到纯文本 TextBlock。

        Returns:
            ChatMessage 实例
        """
        from ghrah.chat.content import TextBlock, blocks_from_dicts
        from ghrah.chat.message import ChatMessage

        if self.content_blocks:
            blocks = blocks_from_dicts(self.content_blocks)
        else:
            blocks = [TextBlock(text=self.content)]

        role_map: dict[MessageType, str] = {
            MessageType.CHAT: "user",
            MessageType.COMMAND: "user",
            MessageType.TOOL_CALL: "ai",
            MessageType.TOOL_RESULT: "tool",
            MessageType.RESULT: "ai",
            MessageType.ERROR: "system",
            MessageType.BROADCAST: "user",
        }

        role = role_map.get(self.type, "user")
        source = classify_source(self.sender)
        return ChatMessage(
            role=role,
            content_blocks=blocks,
            source=source,
            metadata=self.metadata,
        )

    @staticmethod
    def create_reply(
        original: AgentMessage,
        content: str,
        msg_type: MessageType | None = None,
        content_blocks: list[dict[str, Any]] | None = None,
    ) -> AgentMessage:
        """便捷方法：基于原始消息创建回复。

        Args:
            original: 原始消息
            content: 回复内容
            msg_type: 回复消息类型（默认为 RESULT）
            content_blocks: 结构化内容块（序列化后的字典），保留 reasoning/text 等类型区分

        Returns:
            新的回复 AgentMessage
        """
        return AgentMessage(
            sender=original.recipient,
            recipient=original.sender,
            content=content,
            type=msg_type or MessageType.RESULT,
            reply_to=original.id,
            content_blocks=content_blocks,
        )

    def __repr__(self) -> str:
        return (
            f"AgentMessage(id={self.id!r}, {self.sender!r} -> {self.recipient!r}, "
            f"type={self.type.value!r}, content={self.content[:50]!r}...)"
        )
