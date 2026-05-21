# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import pytest

from ghrah.chat.content import (
    AudioBlock,
    ImageBlock,
    ReasoningBlock,
    TextBlock,
    ToolCallBlock,
)
from ghrah.chat.message import ChatMessage


class TestChatMessageConstructors:
    def test_system(self) -> None:
        msg = ChatMessage.system(text="You are helpful")
        assert msg.role == "system"
        assert msg.text == "You are helpful"
        assert msg.source == "system"

    def test_user_with_string(self) -> None:
        msg = ChatMessage.user(text_or_blocks="hello")
        assert msg.role == "user"
        assert msg.text == "hello"
        assert msg.source == "human"

    def test_user_with_blocks(self) -> None:
        blocks = [TextBlock(text="hello"), ImageBlock(url="https://img.png")]
        msg = ChatMessage.user(text_or_blocks=blocks)
        assert msg.role == "user"
        assert len(msg.content_blocks) == 2

    def test_user_with_none(self) -> None:
        msg = ChatMessage.user(text_or_blocks=None)
        assert msg.role == "user"
        assert len(msg.content_blocks) == 0

    def test_ai_text_only(self) -> None:
        msg = ChatMessage.ai(text="response")
        assert msg.role == "ai"
        assert msg.text == "response"

    def test_ai_with_tool_calls(self) -> None:
        tc = ToolCallBlock(id="c1", name="read", arguments={"path": "/tmp"})
        msg = ChatMessage.ai(tool_calls=[tc])
        assert msg.role == "ai"
        assert len(msg.tool_calls) == 1
        assert msg.tool_calls[0].name == "read"

    def test_ai_with_reasoning(self) -> None:
        msg = ChatMessage.ai(reasoning="let me think", text="answer")
        assert msg.role == "ai"
        assert msg.reasoning == "let me think"
        assert msg.text == "answer"

    def test_ai_mixed_content(self) -> None:
        tc = ToolCallBlock(id="c1", name="read", arguments={})
        msg = ChatMessage.ai(reasoning="think", text="doing", tool_calls=[tc])
        assert msg.reasoning == "think"
        assert msg.text == "doing"
        assert len(msg.tool_calls) == 1

    def test_tool_success(self) -> None:
        msg = ChatMessage.tool(tool_call_id="c1", content="file content", name="read")
        assert msg.role == "tool"
        assert len(msg.tool_results) == 1
        assert msg.tool_results[0].tool_call_id == "c1"
        assert msg.tool_results[0].success is True

    def test_tool_error(self) -> None:
        msg = ChatMessage.tool(
            tool_call_id="c1",
            content="Error: not found",
            success=False,
            error="not found",
        )
        assert msg.role == "tool"
        assert msg.tool_results[0].success is False
        assert msg.tool_results[0].error == "not found"


class TestChatMessageProperties:
    def test_text_concatenates_multiple_text_blocks(self) -> None:
        msg = ChatMessage(
            role="user",
            content_blocks=[TextBlock(text="hello "), TextBlock(text="world")],
        )
        assert msg.text == "hello world"

    def test_text_skips_non_text_blocks(self) -> None:
        msg = ChatMessage(
            role="ai",
            content_blocks=[ReasoningBlock(reasoning="think"), TextBlock(text="answer")],
        )
        assert msg.text == "answer"

    def test_tool_calls_extracts_tool_call_blocks(self) -> None:
        tc = ToolCallBlock(id="c1", name="read", arguments={})
        msg = ChatMessage.ai(text="ok", tool_calls=[tc])
        assert len(msg.tool_calls) == 1

    def test_has_tool_calls(self) -> None:
        msg_no = ChatMessage.ai(text="hello")
        assert msg_no.has_tool_calls is False

        tc = ToolCallBlock(id="c1", name="read", arguments={})
        msg_yes = ChatMessage.ai(tool_calls=[tc])
        assert msg_yes.has_tool_calls is True

    def test_reasoning_returns_first(self) -> None:
        msg = ChatMessage.ai(reasoning="think")
        assert msg.reasoning == "think"

    def test_reasoning_returns_none_when_absent(self) -> None:
        msg = ChatMessage.ai(text="hello")
        assert msg.reasoning is None

    def test_images(self) -> None:
        msg = ChatMessage.user(
            text_or_blocks=[ImageBlock(url="https://a.png"), TextBlock(text="see above")]
        )
        assert len(msg.images) == 1

    def test_is_multimodal(self) -> None:
        msg_text = ChatMessage.user(text_or_blocks="hello")
        assert msg_text.is_multimodal is False

        msg_img = ChatMessage.user(text_or_blocks=[ImageBlock(url="https://a.png")])
        assert msg_img.is_multimodal is True

        msg_audio = ChatMessage.user(
            text_or_blocks=[AudioBlock(data="abc", mime_type="audio/wav")]
        )
        assert msg_audio.is_multimodal is True

    def test_tool_results(self) -> None:
        msg = ChatMessage.tool(tool_call_id="c1", content="ok")
        assert len(msg.tool_results) == 1


class TestChatMessageToDict:
    def test_simple_message(self) -> None:
        msg = ChatMessage.user(text_or_blocks="hello")
        d = msg.to_dict()
        assert d["role"] == "user"
        assert d["content_blocks"] == [{"type": "text", "text": "hello"}]
        assert d["source"] == "human"

    def test_message_with_tool_calls(self) -> None:
        tc = ToolCallBlock(id="c1", name="read", arguments={"path": "/tmp"})
        msg = ChatMessage.ai(tool_calls=[tc])
        d = msg.to_dict()
        assert d["role"] == "ai"
        assert len(d["content_blocks"]) == 1
        assert d["content_blocks"][0]["type"] == "tool_call"

    def test_preserves_metadata(self) -> None:
        msg = ChatMessage.system(text="sys", metadata={"key": "val"})
        d = msg.to_dict()
        assert d["metadata"] == {"key": "val"}


class TestChatMessageFromDict:
    def test_simple_message(self) -> None:
        d = {
            "role": "user",
            "content_blocks": [{"type": "text", "text": "hello"}],
            "source": "human",
        }
        msg = ChatMessage.from_dict(d)
        assert msg.role == "user"
        assert msg.text == "hello"

    def test_message_with_tool_calls(self) -> None:
        d = {
            "role": "ai",
            "content_blocks": [
                {"type": "tool_call", "id": "c1", "name": "read", "arguments": {"path": "/tmp"}}
            ],
        }
        msg = ChatMessage.from_dict(d)
        assert msg.role == "ai"
        assert len(msg.tool_calls) == 1
        assert msg.tool_calls[0].name == "read"

    def test_assistant_role_alias(self) -> None:
        d = {"role": "assistant", "content_blocks": [{"type": "text", "text": "hi"}]}
        msg = ChatMessage.from_dict(d)
        assert msg.role == "ai"
        assert msg.text == "hi"

    def test_invalid_role_raises(self) -> None:
        d = {"role": "invalid_role", "content_blocks": [{"type": "text", "text": "hi"}]}
        with pytest.raises(ValueError, match="Invalid role"):
            ChatMessage.from_dict(d)

    def test_invalid_content_block_entry_raises(self) -> None:
        d = {"role": "user", "content_blocks": ["not a dict"]}
        with pytest.raises(ValueError, match="Invalid content_block entry"):
            ChatMessage.from_dict(d)

    def test_missing_role_defaults_to_user(self) -> None:
        d = {"content_blocks": [{"type": "text", "text": "hi"}]}
        msg = ChatMessage.from_dict(d)
        assert msg.role == "user"

    def test_preserves_source_and_metadata(self) -> None:
        d = {
            "role": "system",
            "content_blocks": [{"type": "text", "text": "sys"}],
            "source": "config",
            "metadata": {"model": "gpt-4"},
        }
        msg = ChatMessage.from_dict(d)
        assert msg.source == "config"
        assert msg.metadata == {"model": "gpt-4"}


class TestChatMessageRoundTrip:
    def test_text_message(self) -> None:
        original = ChatMessage.user(text_or_blocks="hello")
        restored = ChatMessage.from_dict(original.to_dict())
        assert restored.role == original.role
        assert restored.text == original.text
        assert restored.source == original.source

    def test_ai_with_tool_calls(self) -> None:
        tc = ToolCallBlock(id="c1", name="read", arguments={"path": "/tmp"})
        original = ChatMessage.ai(tool_calls=[tc], source="agent:test")
        restored = ChatMessage.from_dict(original.to_dict())
        assert restored.role == "ai"
        assert len(restored.tool_calls) == 1
        assert restored.tool_calls[0].name == "read"
        assert restored.tool_calls[0].arguments == {"path": "/tmp"}

    def test_tool_result_message(self) -> None:
        original = ChatMessage.tool(tool_call_id="c1", content="ok", name="read")
        restored = ChatMessage.from_dict(original.to_dict())
        assert restored.role == "tool"
        assert len(restored.tool_results) == 1
        assert restored.tool_results[0].content == "ok"


class TestChatMessageFindBlocks:
    def test_find_text_blocks(self) -> None:
        msg = ChatMessage(
            role="ai",
            content_blocks=[
                TextBlock(text="hello"),
                ToolCallBlock(id="c1", name="r", arguments={}),
            ],
        )
        found = msg.find_blocks(TextBlock)
        assert len(found) == 1

    def test_find_tool_call_blocks(self) -> None:
        msg = ChatMessage.ai(
            tool_calls=[
                ToolCallBlock(id="c1", name="a", arguments={}),
                ToolCallBlock(id="c2", name="b", arguments={}),
            ]
        )
        found = msg.find_blocks(ToolCallBlock)
        assert len(found) == 2

    def test_find_returns_empty_when_none(self) -> None:
        msg = ChatMessage.user(text_or_blocks="hello")
        found = msg.find_blocks(ToolCallBlock)
        assert found == []
