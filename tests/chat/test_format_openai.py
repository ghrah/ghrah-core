# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from ghrah.chat.content import (
    AudioBlock,
    ErrorBlock,
    FileBlock,
    ImageBlock,
    ReasoningBlock,
    TextBlock,
    ToolCallBlock,
)
from ghrah.chat.format import LLMResponse
from ghrah.chat.format.openai import OpenAIFormat
from ghrah.chat.message import ChatMessage
from ghrah.core.config import ModelOverrides


def _make_openai_response(
    content: str = "Hello",
    tool_calls: list[Any] | None = None,
    reasoning_content: str | None = None,
    usage: Any = None,
    model: str = "gpt-4o",
    finish_reason: str = "stop",
) -> SimpleNamespace:
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    if reasoning_content:
        message.reasoning_content = reasoning_content
    choice = SimpleNamespace(message=message, finish_reason=finish_reason)
    resp_usage = usage or SimpleNamespace(
        prompt_tokens=10, completion_tokens=5, total_tokens=15
    )
    return SimpleNamespace(choices=[choice], model=model, usage=resp_usage)


def _make_tool_call(
    id: str = "c1", name: str = "read", args: str = '{"path":"/tmp"}'
) -> SimpleNamespace:
    return SimpleNamespace(
        id=id, function=SimpleNamespace(name=name, arguments=args)
    )


class TestOpenAIFormatInit:
    def test_default_params(self) -> None:
        fmt = OpenAIFormat(model="gpt-4o")
        assert fmt.model == "gpt-4o"
        assert fmt._temperature == 0.7
        assert fmt._max_tokens is None
        assert fmt._top_p is None

    def test_custom_params(self) -> None:
        fmt = OpenAIFormat(
            model="gpt-4",
            api_key="sk-test",
            temperature=0.5,
            max_tokens=100,
            top_p=0.9,
        )
        assert fmt.model == "gpt-4"
        assert fmt._api_key == "sk-test"
        assert fmt._temperature == 0.5
        assert fmt._max_tokens == 100
        assert fmt._top_p == 0.9


class TestOpenAIFormatApplyModelOverrides:
    def test_apply_temperature(self) -> None:
        fmt = OpenAIFormat(model="gpt-4o")
        fmt.apply_model_overrides(ModelOverrides(temperature=0.1))
        assert fmt._temperature == 0.1

    def test_apply_max_tokens(self) -> None:
        fmt = OpenAIFormat(model="gpt-4o")
        fmt.apply_model_overrides(ModelOverrides(max_tokens=999))
        assert fmt._max_tokens == 999

    def test_apply_top_p(self) -> None:
        fmt = OpenAIFormat(model="gpt-4o")
        fmt.apply_model_overrides(ModelOverrides(top_p=0.5))
        assert fmt._top_p == 0.5

    def test_apply_top_k(self) -> None:
        fmt = OpenAIFormat(model="gpt-4o")
        fmt.apply_model_overrides(ModelOverrides(top_k=40))
        assert fmt._top_k == 40

    def test_apply_none_fields_unchanged(self) -> None:
        fmt = OpenAIFormat(model="gpt-4o", temperature=0.5, max_tokens=100)
        fmt.apply_model_overrides(ModelOverrides(top_p=0.8))
        assert fmt._temperature == 0.5
        assert fmt._max_tokens == 100
        assert fmt._top_p == 0.8

    def test_apply_empty_overrides(self) -> None:
        fmt = OpenAIFormat(model="gpt-4o", temperature=0.5)
        fmt.apply_model_overrides(ModelOverrides())
        assert fmt._temperature == 0.5


class TestFormatMessagesTextOnly:
    def test_system_user_ai(self) -> None:
        fmt = OpenAIFormat(model="gpt-4o")
        messages = [
            ChatMessage.system(text="You are helpful"),
            ChatMessage.user(text_or_blocks="hello"),
            ChatMessage.ai(text="hi"),
        ]
        result = fmt._format_messages(messages)
        assert len(result) == 3
        assert result[0] == {"role": "system", "content": "You are helpful"}
        assert result[1] == {"role": "user", "content": "hello"}
        assert result[2] == {"role": "assistant", "content": "hi"}

    def test_ai_role_mapped_to_assistant(self) -> None:
        fmt = OpenAIFormat(model="gpt-4o")
        messages = [ChatMessage.ai(text="response")]
        result = fmt._format_messages(messages)
        assert result[0]["role"] == "assistant"

    def test_empty_content_maps_to_none(self) -> None:
        fmt = OpenAIFormat(model="gpt-4o")
        messages = [ChatMessage.ai(text="")]
        result = fmt._format_messages(messages)
        assert result[0]["content"] is None


class TestFormatMessagesWithToolCalls:
    def test_tool_calls_in_ai_message(self) -> None:
        fmt = OpenAIFormat(model="gpt-4o")
        tc = ToolCallBlock(id="c1", name="read", arguments={"path": "/tmp"})
        messages = [ChatMessage.ai(tool_calls=[tc])]
        result = fmt._format_messages(messages)
        assert result[0]["role"] == "assistant"
        assert "tool_calls" in result[0]
        assert result[0]["tool_calls"][0]["function"]["name"] == "read"

    def test_tool_result_message(self) -> None:
        fmt = OpenAIFormat(model="gpt-4o")
        messages = [ChatMessage.tool(tool_call_id="c1", content="file content")]
        result = fmt._format_messages(messages)
        assert result[0]["role"] == "tool"
        assert result[0]["tool_call_id"] == "c1"
        assert result[0]["content"] == "file content"

    def test_tool_result_empty(self) -> None:
        fmt = OpenAIFormat(model="gpt-4o")
        msg = ChatMessage(role="tool", content_blocks=[])
        result = fmt._format_messages(messages=[msg])
        assert result[0]["role"] == "tool"
        assert result[0]["tool_call_id"] == ""


class TestFormatMessagesReasoning:
    def test_reasoning_block_in_ai(self) -> None:
        fmt = OpenAIFormat(model="gpt-4o")
        messages = [ChatMessage.ai(reasoning="think step by step", text="answer")]
        result = fmt._format_messages(messages)
        assert result[0]["reasoning_content"] == "think step by step"
        assert result[0]["content"] == "answer"

    def test_reasoning_block_with_tool_calls(self) -> None:
        fmt = OpenAIFormat(model="gpt-4o")
        tc = ToolCallBlock(id="c1", name="read", arguments={"path": "/tmp"})
        messages = [
            ChatMessage.ai(
                content_blocks=[
                    ReasoningBlock(reasoning="I need to read the file"),
                    TextBlock(text=""),
                    tc,
                ]
            )
        ]
        result = fmt._format_messages(messages)
        assert result[0]["role"] == "assistant"
        assert result[0]["reasoning_content"] == "I need to read the file"
        assert "tool_calls" in result[0]
        assert result[0]["tool_calls"][0]["function"]["name"] == "read"

    def test_reasoning_block_with_image(self) -> None:
        fmt = OpenAIFormat(model="gpt-4o")
        messages = [
            ChatMessage.ai(
                content_blocks=[
                    ReasoningBlock(reasoning="analyzing image"),
                    TextBlock(text="I see the image"),
                    ImageBlock(url="https://example.com/img.png"),
                ]
            )
        ]
        result = fmt._format_messages(messages)
        assert result[0]["reasoning_content"] == "analyzing image"
        content_parts = result[0]["content"]
        assert any(p.get("type") == "image_url" for p in content_parts)


class TestFormatMessagesMultimodal:
    def test_image_url(self) -> None:
        fmt = OpenAIFormat(model="gpt-4o")
        messages = [ChatMessage.user(text_or_blocks=[ImageBlock(url="https://img.png")])]
        result = fmt._format_messages(messages)
        assert result[0]["content"][0]["type"] == "image_url"
        assert result[0]["content"][0]["image_url"]["url"] == "https://img.png"

    def test_image_base64(self) -> None:
        fmt = OpenAIFormat(model="gpt-4o")
        img = ImageBlock(base64="abc", mime_type="image/png")
        messages = [ChatMessage.user(text_or_blocks=[img])]
        result = fmt._format_messages(messages)
        assert result[0]["content"][0]["type"] == "image_url"
        assert "data:image/png;base64,abc" in result[0]["content"][0]["image_url"]["url"]

    def test_audio_block(self) -> None:
        fmt = OpenAIFormat(model="gpt-4o")
        audio = AudioBlock(data="audiodata", mime_type="audio/wav")
        messages = [ChatMessage.user(text_or_blocks=[audio])]
        result = fmt._format_messages(messages)
        assert result[0]["content"][0]["type"] == "input_audio"
        assert result[0]["content"][0]["input_audio"]["format"] == "wav"

    def test_file_block(self) -> None:
        fmt = OpenAIFormat(model="gpt-4o")
        file = FileBlock(
            base64="filedata", mime_type="application/pdf", filename="doc.pdf"
        )
        messages = [ChatMessage.user(text_or_blocks=[file])]
        result = fmt._format_messages(messages)
        assert result[0]["content"][0]["type"] == "file"
        assert result[0]["content"][0]["file"]["filename"] == "doc.pdf"


class TestFormatTools:
    def test_openai_format_passthrough(self) -> None:
        fmt = OpenAIFormat(model="gpt-4o")
        tools = [{"type": "function", "function": {"name": "read", "parameters": {}}}]
        result = fmt._format_tools(tools)
        assert result == tools

    def test_custom_format_conversion(self) -> None:
        fmt = OpenAIFormat(model="gpt-4o")
        tools = [
            {"name": "read", "parameters": {"type": "object"}, "description": "Read a file"}
        ]
        result = fmt._format_tools(tools)
        assert result[0]["type"] == "function"
        assert result[0]["function"]["name"] == "read"
        assert result[0]["function"]["description"] == "Read a file"


class TestParseResponse:
    def test_text_only(self) -> None:
        fmt = OpenAIFormat(model="gpt-4o")
        resp = _make_openai_response(content="Hello")
        result = fmt._parse_response(resp)
        assert isinstance(result.content_blocks[0], TextBlock)
        assert result.content_blocks[0].text == "Hello"

    def test_tool_calls(self) -> None:
        fmt = OpenAIFormat(model="gpt-4o")
        tc = _make_tool_call(id="c1", name="read", args='{"path":"/tmp"}')
        resp = _make_openai_response(content=None, tool_calls=[tc])
        result = fmt._parse_response(resp)
        tc_blocks = [b for b in result.content_blocks if isinstance(b, ToolCallBlock)]
        assert len(tc_blocks) == 1
        assert tc_blocks[0].name == "read"
        assert tc_blocks[0].arguments == {"path": "/tmp"}

    def test_tool_calls_invalid_json_args(self) -> None:
        fmt = OpenAIFormat(model="gpt-4o")
        tc = _make_tool_call(args="not json")
        resp = _make_openai_response(content=None, tool_calls=[tc])
        result = fmt._parse_response(resp)
        tc_blocks = [b for b in result.content_blocks if isinstance(b, ToolCallBlock)]
        assert len(tc_blocks) == 1
        assert tc_blocks[0].arguments == {}

    def test_reasoning_content(self) -> None:
        fmt = OpenAIFormat(model="gpt-4o")
        resp = _make_openai_response(content="answer", reasoning_content="thinking...")
        result = fmt._parse_response(resp)
        reasoning = [b for b in result.content_blocks if isinstance(b, ReasoningBlock)]
        assert len(reasoning) == 1
        assert reasoning[0].reasoning == "thinking..."

    def test_no_choices(self) -> None:
        fmt = OpenAIFormat(model="gpt-4o")
        resp = SimpleNamespace(choices=[], model="gpt-4o", usage=None)
        result = fmt._parse_response(resp)
        assert isinstance(result.content_blocks[0], ErrorBlock)

    def test_empty_content_and_no_tool_calls(self) -> None:
        fmt = OpenAIFormat(model="gpt-4o")
        resp = _make_openai_response(content=None, tool_calls=None)
        result = fmt._parse_response(resp)
        assert isinstance(result.content_blocks[-1], TextBlock)
        assert result.content_blocks[-1].text == ""

    def test_token_usage(self) -> None:
        fmt = OpenAIFormat(model="gpt-4o")
        usage = SimpleNamespace(prompt_tokens=100, completion_tokens=50, total_tokens=150)
        resp = _make_openai_response(usage=usage)
        result = fmt._parse_response(resp)
        assert result.token_usage is not None
        assert result.token_usage.input_tokens == 100
        assert result.token_usage.output_tokens == 50
        assert result.token_usage.total_tokens == 150

    def test_response_metadata(self) -> None:
        fmt = OpenAIFormat(model="gpt-4o")
        resp = _make_openai_response(model="gpt-4o-mini", finish_reason="length")
        result = fmt._parse_response(resp)
        assert result.response_metadata["model"] == "gpt-4o-mini"
        assert result.response_metadata["finish_reason"] == "length"

    def test_content_as_list_with_text_parts(self) -> None:
        fmt = OpenAIFormat(model="gpt-4o")
        message = SimpleNamespace(
            content=[{"type": "text", "text": "part1"}, {"type": "text", "text": "part2"}],
            tool_calls=None,
        )
        choice = SimpleNamespace(message=message, finish_reason="stop")
        resp = SimpleNamespace(choices=[choice], model="gpt-4o", usage=None)
        result = fmt._parse_response(resp)
        text_blocks = [b for b in result.content_blocks if isinstance(b, TextBlock)]
        assert len(text_blocks) == 2

    def test_content_as_list_with_reasoning(self) -> None:
        fmt = OpenAIFormat(model="gpt-4o")
        message = SimpleNamespace(
            content=[{"type": "reasoning", "text": "think", "reasoning": "think"}],
            tool_calls=None,
        )
        choice = SimpleNamespace(message=message, finish_reason="stop")
        resp = SimpleNamespace(choices=[choice], model="gpt-4o", usage=None)
        result = fmt._parse_response(resp)
        assert any(isinstance(b, ReasoningBlock) for b in result.content_blocks)


class TestConfigureTools:
    def test_configure_tools(self) -> None:
        fmt = OpenAIFormat(model="gpt-4o")
        tools = [{"type": "function", "function": {"name": "read", "parameters": {}}}]
        fmt.configure_tools(tools)
        assert fmt._tools == tools


class TestGenerateIntegration:
    @pytest.mark.asyncio
    async def test_generate_calls_client(self) -> None:
        fmt = OpenAIFormat(model="gpt-4o", api_key="sk-test")

        mock_client = AsyncMock()
        openai_resp = _make_openai_response()
        mock_client.chat = SimpleNamespace()
        mock_client.chat.completions = SimpleNamespace()
        mock_client.chat.completions.create = AsyncMock(return_value=openai_resp)
        fmt._client = mock_client

        messages = [ChatMessage.user(text_or_blocks="hello")]
        result = await fmt.generate(messages)
        assert isinstance(result, LLMResponse)
        assert result.text == "Hello"
