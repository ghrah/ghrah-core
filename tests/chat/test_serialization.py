# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from ghrah.chat.content import ToolCallBlock
from ghrah.chat.message import ChatMessage
from ghrah.chat.serialization import (
    deserialize_messages,
    serialize_messages,
)


class TestSerializeMessages:
    def test_normal_messages(self) -> None:
        msgs = [
            ChatMessage.system(text="sys"),
            ChatMessage.user(text_or_blocks="hello"),
            ChatMessage.ai(text="hi"),
        ]
        result = serialize_messages(msgs)
        assert result is not None
        assert len(result) == 3
        assert result[0]["role"] == "system"
        assert result[1]["role"] == "user"
        assert result[2]["role"] == "ai"

    def test_none_returns_none(self) -> None:
        assert serialize_messages(None) is None

    def test_empty_list(self) -> None:
        assert serialize_messages([]) == []

    def test_preserves_tool_calls(self) -> None:
        tc = ToolCallBlock(id="c1", name="read", arguments={"path": "/tmp"})
        msgs = [ChatMessage.ai(tool_calls=[tc])]
        result = serialize_messages(msgs)
        assert result[0]["content_blocks"][0]["type"] == "tool_call"


class TestDeserializeMessagesNewFormat:
    def test_new_format(self) -> None:
        data = [
            {
                "role": "user",
                "content_blocks": [{"type": "text", "text": "hello"}],
                "source": "human",
            },
            {
                "role": "ai",
                "content_blocks": [{"type": "text", "text": "hi"}],
                "source": None,
            },
        ]
        result = deserialize_messages(data)
        assert result is not None
        assert len(result) == 2
        assert result[0].role == "user"
        assert result[1].role == "ai"

    def test_none_returns_none(self) -> None:
        assert deserialize_messages(None) is None

    def test_empty_list(self) -> None:
        result = deserialize_messages([])
        assert result == []

    def test_fallback_to_new_format(self) -> None:
        data = [{"role": "user", "content_blocks": [{"type": "text", "text": "hi"}]}]
        result = deserialize_messages(data)
        assert result is not None
        assert result[0].text == "hi"


class TestRoundTrip:
    def test_serialize_deserialize_roundtrip(self) -> None:
        msgs = [
            ChatMessage.system(text="sys"),
            ChatMessage.user(text_or_blocks="hello"),
            ChatMessage.ai(text="hi", source="agent:test"),
            ChatMessage.tool(tool_call_id="c1", content="ok", name="read"),
        ]
        serialized = serialize_messages(msgs)
        assert serialized is not None
        restored = deserialize_messages(serialized)
        assert restored is not None
        assert len(restored) == 4
        assert restored[0].role == "system"
        assert restored[1].text == "hello"
        assert restored[2].role == "ai"
        assert restored[3].role == "tool"

    def test_tool_calls_roundtrip(self) -> None:
        tc = ToolCallBlock(id="c1", name="read", arguments={"path": "/tmp"})
        msgs = [ChatMessage.ai(tool_calls=[tc])]
        serialized = serialize_messages(msgs)
        restored = deserialize_messages(serialized)
        assert restored is not None
        assert len(restored[0].tool_calls) == 1
        assert restored[0].tool_calls[0].arguments == {"path": "/tmp"}
