# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from dataclasses import fields

import pytest

from ghrah.chat.content import (
    AudioBlock,
    ContentBlock,
    ErrorBlock,
    FileBlock,
    ImageBlock,
    ReasoningBlock,
    StreamingBlock,
    TextBlock,
    ToolCallBlock,
    ToolCallChunkBlock,
    ToolResultBlock,
    block_from_dict,
    block_to_dict,
)


class TestContentBlockDefaults:
    def test_text_block(self) -> None:
        b = TextBlock()
        assert b.type == "text"
        assert b.text == ""

    def test_reasoning_block(self) -> None:
        b = ReasoningBlock()
        assert b.type == "reasoning"
        assert b.reasoning == ""
        assert b.incomplete is False

    def test_image_block(self) -> None:
        b = ImageBlock()
        assert b.type == "image"
        assert b.url is None
        assert b.base64 is None

    def test_audio_block(self) -> None:
        b = AudioBlock()
        assert b.type == "audio"
        assert b.data == ""

    def test_file_block(self) -> None:
        b = FileBlock()
        assert b.type == "file"
        assert b.url is None
        assert b.filename is None

    def test_tool_call_block(self) -> None:
        b = ToolCallBlock()
        assert b.type == "tool_call"
        assert b.id == ""
        assert b.name == ""
        assert b.arguments == {}

    def test_tool_result_block(self) -> None:
        b = ToolResultBlock()
        assert b.type == "tool_result"
        assert b.tool_call_id == ""
        assert b.success is True

    def test_error_block(self) -> None:
        b = ErrorBlock()
        assert b.type == "error"
        assert b.error_type == ""

    def test_tool_call_chunk_block(self) -> None:
        b = ToolCallChunkBlock()
        assert b.type == "tool_call_chunk"
        assert b.index == 0


class TestBlockToDict:
    def test_text_block(self) -> None:
        d = block_to_dict(TextBlock(text="hello"))
        assert d == {"type": "text", "text": "hello"}

    def test_reasoning_block(self) -> None:
        d = block_to_dict(ReasoningBlock(reasoning="think", incomplete=True))
        assert d["type"] == "reasoning"
        assert d["reasoning"] == "think"
        assert d["incomplete"] is True

    def test_image_block_url(self) -> None:
        d = block_to_dict(ImageBlock(url="https://example.com/img.png"))
        assert d == {"type": "image", "url": "https://example.com/img.png"}

    def test_image_block_base64(self) -> None:
        d = block_to_dict(ImageBlock(base64="abc123", mime_type="image/png"))
        assert d["type"] == "image"
        assert d["base64"] == "abc123"
        assert d["mime_type"] == "image/png"

    def test_tool_call_block_with_arguments(self) -> None:
        d = block_to_dict(ToolCallBlock(id="c1", name="read", arguments={"path": "/tmp"}))
        assert d["type"] == "tool_call"
        assert d["id"] == "c1"
        assert d["name"] == "read"
        assert d["arguments"] == {"path": "/tmp"}

    def test_tool_call_block_empty_arguments(self) -> None:
        d = block_to_dict(ToolCallBlock(id="c1", name="read", arguments={}))
        assert d["type"] == "tool_call"
        assert "arguments" not in d

    def test_tool_result_block(self) -> None:
        d = block_to_dict(ToolResultBlock(tool_call_id="tc1", content="ok"))
        assert d["type"] == "tool_result"
        assert d["tool_call_id"] == "tc1"
        assert d["content"] == "ok"

    def test_error_block(self) -> None:
        d = block_to_dict(ErrorBlock(error_type="ValueError", message="bad"))
        assert d["type"] == "error"
        assert d["error_type"] == "ValueError"
        assert d["message"] == "bad"


class TestBlockFromDict:
    def test_text_block(self) -> None:
        b = block_from_dict({"type": "text", "text": "hello"})
        assert isinstance(b, TextBlock)
        assert b.text == "hello"

    def test_tool_call_block(self) -> None:
        b = block_from_dict({"type": "tool_call", "id": "c1", "name": "read", "arguments": {}})
        assert isinstance(b, ToolCallBlock)
        assert b.id == "c1"

    def test_unknown_type_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown block type"):
            block_from_dict({"type": "nonexistent"})

    def test_extra_fields_ignored(self) -> None:
        b = block_from_dict({"type": "text", "text": "hi", "extra_key": "ignored"})
        assert isinstance(b, TextBlock)
        assert b.text == "hi"

    def test_extra_fields_on_tool_call(self) -> None:
        b = block_from_dict({
            "type": "tool_call",
            "id": "c1",
            "name": "read",
            "arguments": {"path": "/tmp"},
            "legacy_field": 42,
        })
        assert isinstance(b, ToolCallBlock)
        assert b.name == "read"
        assert b.arguments == {"path": "/tmp"}


class TestBlockRoundTrip:
    @pytest.mark.parametrize(
        "block",
        [
            TextBlock(text="hello"),
            ReasoningBlock(reasoning="thinking...", incomplete=True),
            ImageBlock(url="https://example.com/img.png"),
            ImageBlock(base64="abc", mime_type="image/png"),
            AudioBlock(data="base64audio", mime_type="audio/wav"),
            FileBlock(base64="filedata", mime_type="application/pdf", filename="doc.pdf"),
            ToolCallBlock(id="c1", name="read", arguments={"path": "/tmp"}),
            ToolResultBlock(
                tool_call_id="tc1", name="read", content="file content", success=True
            ),
            ErrorBlock(error_type="RuntimeError", message="crashed"),
        ],
    )
    def test_round_trip(self, block: ContentBlock) -> None:
        d = block_to_dict(block)
        restored = block_from_dict(d)
        for f in fields(block):
            assert getattr(restored, f.name) == getattr(block, f.name), f"Field {f.name} mismatch"


class TestContentBlockUnion:
    def test_content_block_includes_core_types(self) -> None:
        assert TextBlock in ContentBlock.__args__
        assert ReasoningBlock in ContentBlock.__args__
        assert ToolCallBlock in ContentBlock.__args__
        assert ToolResultBlock in ContentBlock.__args__
        assert ErrorBlock in ContentBlock.__args__

    def test_streaming_block_includes_chunk(self) -> None:
        assert TextBlock in StreamingBlock.__args__
        assert ToolCallChunkBlock in StreamingBlock.__args__
