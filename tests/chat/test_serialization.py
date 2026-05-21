# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from ghrah.chat.content import ToolCallBlock
from ghrah.chat.message import ChatMessage
from ghrah.chat.serialization import (
    deserialize_messages,
    migrate_langchain_messages,
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


class TestDeserializeLangChainHuman:
    LC_HUMAN = {
        "type": "constructor",
        "id": ["langchain", "schema", "messages", "HumanMessage"],
        "kwargs": {"content": "hello"},
    }

    def test_migrate(self) -> None:
        result = deserialize_messages([self.LC_HUMAN])
        assert result is not None
        assert len(result) == 1
        assert result[0].role == "user"
        assert result[0].text == "hello"
        assert result[0].source == "human"


class TestDeserializeLangChainAI:
    LC_AI_TEXT = {
        "type": "constructor",
        "id": ["langchain", "schema", "messages", "AIMessage"],
        "kwargs": {"content": "response"},
    }

    LC_AI_WITH_TOOLS = {
        "type": "constructor",
        "id": ["langchain", "schema", "messages", "AIMessage"],
        "kwargs": {
            "content": "",
            "tool_calls": [{"id": "c1", "name": "read", "args": {"path": "/tmp"}}],
        },
    }

    LC_AI_WITH_REASONING = {
        "type": "constructor",
        "id": ["langchain", "schema", "messages", "AIMessage"],
        "kwargs": {
            "content": "answer",
            "additional_kwargs": {"reasoning_content": "thinking..."},
        },
    }

    def test_migrate_text_only(self) -> None:
        result = deserialize_messages([self.LC_AI_TEXT])
        assert result is not None
        assert result[0].role == "ai"
        assert result[0].text == "response"

    def test_migrate_with_tool_calls(self) -> None:
        result = deserialize_messages([self.LC_AI_WITH_TOOLS])
        assert result is not None
        assert result[0].role == "ai"
        assert len(result[0].tool_calls) == 1
        assert result[0].tool_calls[0].name == "read"

    def test_migrate_with_reasoning(self) -> None:
        result = deserialize_messages([self.LC_AI_WITH_REASONING])
        assert result is not None
        assert result[0].role == "ai"
        assert result[0].reasoning == "thinking..."


class TestDeserializeLangChainSystem:
    LC_SYSTEM = {
        "type": "constructor",
        "id": ["langchain", "schema", "messages", "SystemMessage"],
        "kwargs": {"content": "You are helpful"},
    }

    def test_migrate(self) -> None:
        result = deserialize_messages([self.LC_SYSTEM])
        assert result is not None
        assert result[0].role == "system"
        assert result[0].text == "You are helpful"
        assert result[0].source == "system"


class TestDeserializeLangChainTool:
    LC_TOOL = {
        "type": "constructor",
        "id": ["langchain", "schema", "messages", "ToolMessage"],
        "kwargs": {"content": "file content", "tool_call_id": "c1", "name": "read_file"},
    }

    def test_migrate(self) -> None:
        result = deserialize_messages([self.LC_TOOL])
        assert result is not None
        assert result[0].role == "tool"
        assert len(result[0].tool_results) == 1
        assert result[0].tool_results[0].tool_call_id == "c1"
        assert result[0].tool_results[0].name == "read_file"
        assert result[0].tool_results[0].content == "file content"


class TestDeserializeMixedFormats:
    def test_new_and_old_mixed(self) -> None:
        new_msg = {
            "role": "user",
            "content_blocks": [{"type": "text", "text": "new hello"}],
        }
        old_msg = {
            "type": "constructor",
            "id": ["langchain", "schema", "messages", "HumanMessage"],
            "kwargs": {"content": "old hello"},
        }
        result = deserialize_messages([new_msg, old_msg])
        assert result is not None
        assert len(result) == 2
        assert result[0].text == "new hello"
        assert result[1].text == "old hello"

    def test_unrecognized_constructor_returns_none_skipped(self) -> None:
        bad = {
            "type": "constructor",
            "id": ["langchain", "schema", "messages", "CustomMessage"],
            "kwargs": {"content": "custom"},
        }
        result = deserialize_messages([bad])
        assert result is not None
        assert len(result) == 0


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


class TestMigrateLangchainMessagesAlias:
    def test_is_same_function(self) -> None:
        assert migrate_langchain_messages is deserialize_messages
