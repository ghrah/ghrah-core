# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from ghrah.chat.content import (
    FileBlock,
    ImageBlock,
    ReasoningBlock,
    TextBlock,
    ToolCallBlock,
)
from ghrah.chat.format import LLMResponse
from ghrah.chat.format.anthropic import AnthropicFormat
from ghrah.chat.message import ChatMessage
from ghrah.core.config import ModelOverrides


def _make_anthropic_response(
    content_blocks: list[Any] | None = None,
    usage: Any = None,
    model: str = "claude-3-sonnet",
    stop_reason: str = "end_turn",
) -> SimpleNamespace:
    if content_blocks is None:
        content_blocks = [SimpleNamespace(type="text", text="Hello")]
    resp_usage = usage or SimpleNamespace(input_tokens=10, output_tokens=5)
    return SimpleNamespace(
        content=content_blocks, model=model, stop_reason=stop_reason, usage=resp_usage
    )


class TestAnthropicFormatInit:
    def test_default_params(self) -> None:
        fmt = AnthropicFormat(model="claude-3-sonnet")
        assert fmt.model == "claude-3-sonnet"
        assert fmt._temperature == 0.7
        assert fmt._max_tokens == 4096

    def test_custom_params(self) -> None:
        fmt = AnthropicFormat(
            model="claude-3-opus",
            api_key="sk-ant",
            temperature=0.3,
            max_tokens=2048,
            top_p=0.8,
        )
        assert fmt.model == "claude-3-opus"
        assert fmt._api_key == "sk-ant"
        assert fmt._max_tokens == 2048
        assert fmt._top_p == 0.8


class TestAnthropicFormatApplyModelOverrides:
    def test_apply_temperature(self) -> None:
        fmt = AnthropicFormat(model="claude-3-sonnet")
        fmt.apply_model_overrides(ModelOverrides(temperature=0.1))
        assert fmt._temperature == 0.1

    def test_apply_max_tokens(self) -> None:
        fmt = AnthropicFormat(model="claude-3-sonnet")
        fmt.apply_model_overrides(ModelOverrides(max_tokens=999))
        assert fmt._max_tokens == 999

    def test_apply_top_p(self) -> None:
        fmt = AnthropicFormat(model="claude-3-sonnet")
        fmt.apply_model_overrides(ModelOverrides(top_p=0.5))
        assert fmt._top_p == 0.5

    def test_apply_top_k(self) -> None:
        fmt = AnthropicFormat(model="claude-3-sonnet")
        fmt.apply_model_overrides(ModelOverrides(top_k=40))
        assert fmt._top_k == 40

    def test_apply_none_fields_unchanged(self) -> None:
        fmt = AnthropicFormat(model="claude-3-sonnet", temperature=0.5, max_tokens=100)
        fmt.apply_model_overrides(ModelOverrides(top_p=0.8))
        assert fmt._temperature == 0.5
        assert fmt._max_tokens == 100
        assert fmt._top_p == 0.8

    def test_apply_empty_overrides(self) -> None:
        fmt = AnthropicFormat(model="claude-3-sonnet", temperature=0.5)
        fmt.apply_model_overrides(ModelOverrides())
        assert fmt._temperature == 0.5


class TestFormatMessagesSystemExtract:
    def test_system_extracted_to_top_level(self) -> None:
        fmt = AnthropicFormat(model="claude-3-sonnet")
        messages = [
            ChatMessage.system(text="You are helpful"),
            ChatMessage.user(text_or_blocks="hello"),
        ]
        system_prompt, formatted = fmt._format_messages(messages)
        assert system_prompt == "You are helpful"
        assert len(formatted) == 1
        assert formatted[0]["role"] == "user"

    def test_multiple_system_messages_joined(self) -> None:
        fmt = AnthropicFormat(model="claude-3-sonnet")
        messages = [
            ChatMessage.system(text="Part 1"),
            ChatMessage.system(text="Part 2"),
            ChatMessage.user(text_or_blocks="hello"),
        ]
        system_prompt, formatted = fmt._format_messages(messages)
        assert "Part 1" in system_prompt
        assert "Part 2" in system_prompt

    def test_no_system_messages(self) -> None:
        fmt = AnthropicFormat(model="claude-3-sonnet")
        messages = [ChatMessage.user(text_or_blocks="hello")]
        system_prompt, formatted = fmt._format_messages(messages)
        assert system_prompt is None


class TestFormatMessagesTextOnly:
    def test_user_and_assistant(self) -> None:
        fmt = AnthropicFormat(model="claude-3-sonnet")
        messages = [
            ChatMessage.user(text_or_blocks="hello"),
            ChatMessage.ai(text="hi"),
        ]
        _, formatted = fmt._format_messages(messages)
        assert len(formatted) == 2
        assert formatted[0]["role"] == "user"
        assert formatted[1]["role"] == "assistant"


class TestFormatMessagesToolUse:
    def test_tool_call_block(self) -> None:
        fmt = AnthropicFormat(model="claude-3-sonnet")
        tc = ToolCallBlock(id="c1", name="read", arguments={"path": "/tmp"})
        messages = [ChatMessage.ai(tool_calls=[tc])]
        _, formatted = fmt._format_messages(messages)
        assert formatted[0]["role"] == "assistant"
        tool_use = formatted[0]["content"][0]
        assert tool_use["type"] == "tool_use"
        assert tool_use["id"] == "c1"
        assert tool_use["input"] == {"path": "/tmp"}

    def test_tool_result_block(self) -> None:
        fmt = AnthropicFormat(model="claude-3-sonnet")
        messages = [
            ChatMessage.tool(tool_call_id="c1", content="file content", name="read")
        ]
        _, formatted = fmt._format_messages(messages)
        assert formatted[0]["role"] == "user"
        tool_result = formatted[0]["content"][0]
        assert tool_result["type"] == "tool_result"
        assert tool_result["tool_use_id"] == "c1"

    def test_tool_result_error(self) -> None:
        fmt = AnthropicFormat(model="claude-3-sonnet")
        messages = [
            ChatMessage.tool(
                tool_call_id="c1", content="err", success=False, error="not found"
            )
        ]
        _, formatted = fmt._format_messages(messages)
        tool_result = formatted[0]["content"][0]
        assert tool_result["is_error"] is True
        assert tool_result["content"] == "not found"


class TestFormatMessagesThinking:
    def test_thinking_block(self) -> None:
        fmt = AnthropicFormat(model="claude-3-sonnet")
        messages = [ChatMessage.ai(reasoning="let me think")]
        _, formatted = fmt._format_messages(messages)
        thinking = formatted[0]["content"][0]
        assert thinking["type"] == "thinking"
        assert thinking["thinking"] == "let me think"


class TestFormatMessagesImage:
    def test_image_base64(self) -> None:
        fmt = AnthropicFormat(model="claude-3-sonnet")
        img = ImageBlock(base64="abc", mime_type="image/png")
        messages = [ChatMessage.user(text_or_blocks=[img])]
        _, formatted = fmt._format_messages(messages)
        img_result = formatted[0]["content"][0]
        assert img_result["type"] == "image"
        assert img_result["source"]["type"] == "base64"
        assert img_result["source"]["data"] == "abc"
        assert img_result["source"]["media_type"] == "image/png"


class TestFormatMessagesFile:
    def test_file_block(self) -> None:
        fmt = AnthropicFormat(model="claude-3-sonnet")
        file = FileBlock(base64="filedata", mime_type="application/pdf")
        messages = [ChatMessage.user(text_or_blocks=[file])]
        _, formatted = fmt._format_messages(messages)
        doc = formatted[0]["content"][0]
        assert doc["type"] == "document"
        assert doc["source"]["data"] == "filedata"


class TestFormatTools:
    def test_openai_format_conversion(self) -> None:
        fmt = AnthropicFormat(model="claude-3-sonnet")
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "read",
                    "parameters": {"type": "object"},
                    "description": "Read file",
                },
            }
        ]
        result = fmt._format_tools(tools)
        assert result[0]["name"] == "read"
        assert result[0]["input_schema"] == {"type": "object"}
        assert result[0]["description"] == "Read file"

    def test_custom_format_conversion(self) -> None:
        fmt = AnthropicFormat(model="claude-3-sonnet")
        tools = [
            {"name": "read", "parameters": {"type": "object"}, "description": "Read file"}
        ]
        result = fmt._format_tools(tools)
        assert result[0]["name"] == "read"
        assert result[0]["input_schema"] == {"type": "object"}


class TestParseResponse:
    def test_text_block(self) -> None:
        fmt = AnthropicFormat(model="claude-3-sonnet")
        resp = _make_anthropic_response(
            content_blocks=[SimpleNamespace(type="text", text="Hello")]
        )
        result = fmt._parse_response(resp)
        assert isinstance(result.content_blocks[0], TextBlock)
        assert result.content_blocks[0].text == "Hello"

    def test_thinking_block(self) -> None:
        fmt = AnthropicFormat(model="claude-3-sonnet")
        resp = _make_anthropic_response(
            content_blocks=[SimpleNamespace(type="thinking", thinking="hmm")]
        )
        result = fmt._parse_response(resp)
        assert isinstance(result.content_blocks[0], ReasoningBlock)
        assert result.content_blocks[0].reasoning == "hmm"

    def test_thinking_incomplete_when_tool_use(self) -> None:
        fmt = AnthropicFormat(model="claude-3-sonnet")
        resp = _make_anthropic_response(
            content_blocks=[SimpleNamespace(type="thinking", thinking="hmm")],
            stop_reason="tool_use",
        )
        result = fmt._parse_response(resp)
        assert result.content_blocks[0].incomplete is True

    def test_tool_use_block(self) -> None:
        fmt = AnthropicFormat(model="claude-3-sonnet")
        resp = _make_anthropic_response(
            content_blocks=[
                SimpleNamespace(type="tool_use", id="c1", name="read", input={"path": "/tmp"})
            ]
        )
        result = fmt._parse_response(resp)
        assert isinstance(result.content_blocks[0], ToolCallBlock)
        assert result.content_blocks[0].name == "read"
        assert result.content_blocks[0].arguments == {"path": "/tmp"}

    def test_tool_use_string_input(self) -> None:
        fmt = AnthropicFormat(model="claude-3-sonnet")
        resp = _make_anthropic_response(
            content_blocks=[
                SimpleNamespace(
                    type="tool_use", id="c1", name="read", input='{"path":"/tmp"}'
                )
            ]
        )
        result = fmt._parse_response(resp)
        assert isinstance(result.content_blocks[0], ToolCallBlock)
        assert result.content_blocks[0].arguments == {"path": "/tmp"}

    def test_tool_use_invalid_json_input(self) -> None:
        fmt = AnthropicFormat(model="claude-3-sonnet")
        resp = _make_anthropic_response(
            content_blocks=[
                SimpleNamespace(
                    type="tool_use", id="c1", name="read", input="not json"
                )
            ]
        )
        result = fmt._parse_response(resp)
        assert isinstance(result.content_blocks[0], ToolCallBlock)
        assert result.content_blocks[0].arguments == {}

    def test_empty_content(self) -> None:
        fmt = AnthropicFormat(model="claude-3-sonnet")
        resp = _make_anthropic_response(content_blocks=[])
        result = fmt._parse_response(resp)
        assert isinstance(result.content_blocks[0], TextBlock)
        assert result.content_blocks[0].text == ""

    def test_token_usage(self) -> None:
        fmt = AnthropicFormat(model="claude-3-sonnet")
        usage = SimpleNamespace(input_tokens=100, output_tokens=50)
        resp = _make_anthropic_response(usage=usage)
        result = fmt._parse_response(resp)
        assert result.token_usage is not None
        assert result.token_usage.input_tokens == 100
        assert result.token_usage.output_tokens == 50

    def test_response_metadata(self) -> None:
        fmt = AnthropicFormat(model="claude-3-sonnet")
        resp = _make_anthropic_response(model="claude-3-opus", stop_reason="tool_use")
        result = fmt._parse_response(resp)
        assert result.response_metadata["model"] == "claude-3-opus"
        assert result.response_metadata["stop_reason"] == "tool_use"


class TestConfigureTools:
    def test_configure_tools(self) -> None:
        fmt = AnthropicFormat(model="claude-3-sonnet")
        tools = [{"name": "read", "parameters": {"type": "object"}}]
        fmt.configure_tools(tools)
        assert fmt._tools == tools


class TestGenerateIntegration:
    @pytest.mark.asyncio
    async def test_generate_calls_client(self) -> None:
        fmt = AnthropicFormat(model="claude-3-sonnet", api_key="sk-ant-test")

        mock_client = AsyncMock()
        anthropic_resp = _make_anthropic_response()
        mock_client.messages = SimpleNamespace()
        mock_client.messages.create = AsyncMock(return_value=anthropic_resp)
        fmt._client = mock_client

        messages = [ChatMessage.user(text_or_blocks="hello")]
        result = await fmt.generate(messages)
        assert isinstance(result, LLMResponse)
        assert result.text == "Hello"
