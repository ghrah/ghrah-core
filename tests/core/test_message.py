# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""Message 核心数据类测试"""

from ghrah.core.message import Message, MessageType


class TestMessage:
    def test_create_basic_message(self):
        msg = Message(
            sender="user",
            recipient="agent",
            content="你好",
        )
        assert msg.sender == "user"
        assert msg.recipient == "agent"
        assert msg.content == "你好"
        assert msg.type == MessageType.CHAT
        assert msg.id is not None
        assert msg.timestamp > 0
        assert msg.reply_to is None
        assert msg.content_blocks is None

    def test_create_reply(self):
        original = Message(
            sender="user",
            recipient="agent",
            content="请帮我写代码",
            type=MessageType.COMMAND,
        )
        reply = Message.create_reply(original, "好的，我来帮你写")

        assert reply.sender == "agent"
        assert reply.recipient == "user"
        assert reply.content == "好的，我来帮你写"
        assert reply.type == MessageType.RESULT
        assert reply.reply_to == original.id
        assert reply.content_blocks is None

    def test_create_reply_with_content_blocks(self):
        original = Message(
            sender="user",
            recipient="agent",
            content="请帮我写代码",
            type=MessageType.COMMAND,
        )
        blocks = [
            {"type": "reasoning", "reasoning": "让我想想..."},
            {"type": "text", "text": "好的代码如下"},
        ]
        reply = Message.create_reply(
            original, "好的代码如下", content_blocks=blocks
        )
        assert reply.content == "好的代码如下"
        assert reply.content_blocks == blocks
        assert reply.content_blocks[0]["type"] == "reasoning"
        assert reply.content_blocks[1]["type"] == "text"

    def test_to_chat_message(self):
        msg = Message(
            sender="user",
            recipient="agent",
            content="测试消息",
            type=MessageType.CHAT,
        )
        chat_msg = msg.to_chat_message()
        assert chat_msg.role == "user"
        assert chat_msg.text == "测试消息"

    def test_to_chat_message_with_content_blocks(self):
        blocks = [
            {"type": "reasoning", "reasoning": "思考过程", "incomplete": False},
            {"type": "text", "text": "最终回复"},
        ]
        msg = Message(
            sender="agent",
            recipient="user",
            content="最终回复",
            type=MessageType.RESULT,
            content_blocks=blocks,
        )
        chat_msg = msg.to_chat_message()
        assert chat_msg.role == "ai"
        assert len(chat_msg.content_blocks) == 2
        assert chat_msg.content_blocks[0].type == "reasoning"
        assert chat_msg.content_blocks[1].type == "text"
        assert chat_msg.text == "最终回复"

    def test_to_chat_message_fallback_no_content_blocks(self):
        msg = Message(
            sender="user",
            recipient="agent",
            content="纯文本",
            type=MessageType.CHAT,
        )
        chat_msg = msg.to_chat_message()
        assert len(chat_msg.content_blocks) == 1
        assert chat_msg.content_blocks[0].type == "text"

    def test_message_types(self):
        assert MessageType.CHAT.value == "chat"
        assert MessageType.COMMAND.value == "command"
        assert MessageType.TOOL_CALL.value == "tool_call"
        assert MessageType.TOOL_RESULT.value == "tool_result"
        assert MessageType.RESULT.value == "result"
        assert MessageType.ERROR.value == "error"
        assert MessageType.BROADCAST.value == "broadcast"
