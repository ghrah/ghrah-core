# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from ghrah.chat.content import (
    ReasoningBlock,
    TextBlock,
    ToolCallBlock,
)
from ghrah.chat.format.deepseek import DeepSeekFormat
from ghrah.chat.message import ChatMessage


class TestDeepSeekFormatReasoningOnly:
    def test_reasoning_block_in_ai_message_simple_path(self) -> None:
        fmt = DeepSeekFormat(model="deepseek-reasoner")
        messages = [ChatMessage.ai(reasoning="think step by step", text="answer")]
        result = fmt._format_messages(messages)
        assert result[0]["reasoning_content"] == "think step by step"
        assert result[0]["content"] == "answer"
        assert result[0]["role"] == "assistant"


class TestDeepSeekFormatReasoningWithToolCalls:
    def test_reasoning_and_tool_calls(self) -> None:
        fmt = DeepSeekFormat(model="deepseek-reasoner")
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

    def test_reasoning_with_tool_calls_no_text(self) -> None:
        fmt = DeepSeekFormat(model="deepseek-reasoner")
        tc = ToolCallBlock(id="c2", name="write", arguments={"path": "/out"})
        messages = [
            ChatMessage.ai(
                content_blocks=[
                    ReasoningBlock(reasoning="Let me write this"),
                    tc,
                ]
            )
        ]
        result = fmt._format_messages(messages)
        assert result[0]["reasoning_content"] == "Let me write this"
        assert "tool_calls" in result[0]


class TestDeepSeekFormatReasoningWithMultimodal:
    def test_reasoning_with_image(self) -> None:
        from ghrah.chat.content import ImageBlock

        fmt = DeepSeekFormat(model="deepseek-reasoner")
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
        text_parts = [p for p in content_parts if p.get("type") == "text"]
        image_parts = [p for p in content_parts if p.get("type") == "image_url"]
        assert len(text_parts) == 1
        assert len(image_parts) == 1


class TestDeepSeekFormatRoundTrip:
    def test_reasoning_preserved_after_format_parse(self) -> None:
        fmt = DeepSeekFormat(model="deepseek-reasoner")
        messages = [
            ChatMessage.ai(reasoning="initial thought", text="hello"),
        ]
        formatted = fmt._format_messages(messages)
        assert formatted[0]["reasoning_content"] == "initial thought"
        assert formatted[0]["role"] == "assistant"

    def test_no_reasoning_block_no_reasoning_content(self) -> None:
        fmt = DeepSeekFormat(model="deepseek-reasoner")
        messages = [ChatMessage.ai(text="just a reply")]
        result = fmt._format_messages(messages)
        assert "reasoning_content" not in result[0]

    def test_user_message_no_reasoning_content(self) -> None:
        fmt = DeepSeekFormat(model="deepseek-reasoner")
        messages = [
            ChatMessage.user(text_or_blocks=[ReasoningBlock(reasoning="user thought")])
        ]
        result = fmt._format_messages(messages)
        assert "reasoning_content" not in result[0]


class TestDeepSeekFormatDeepSeekSpecificScenario:
    def test_multi_turn_with_reasoning_and_tool_call(self) -> None:
        fmt = DeepSeekFormat(model="deepseek-reasoner")
        tc1 = ToolCallBlock(id="call_1", name="get_weather", arguments={"city": "Beijing"})
        tc2 = ToolCallBlock(id="call_2", name="get_weather", arguments={"city": "Tokyo"})

        messages = [
            ChatMessage.system(text="You are a helpful assistant."),
            ChatMessage.user(text_or_blocks="What's the weather in Beijing and Tokyo?"),
            ChatMessage.ai(
                content_blocks=[
                    ReasoningBlock(reasoning="User wants weather for two cities"),
                    TextBlock(text=""),
                    tc1,
                    tc2,
                ]
            ),
            ChatMessage.tool(tool_call_id="call_1", content="Sunny, 25C"),
            ChatMessage.tool(tool_call_id="call_2", content="Rainy, 18C"),
            ChatMessage.ai(
                content_blocks=[
                    ReasoningBlock(reasoning="Now I have both results"),
                    TextBlock(text="Beijing is sunny 25C, Tokyo is rainy 18C"),
                ]
            ),
        ]

        result = fmt._format_messages(messages)

        assert result[0]["role"] == "system"
        assert result[1]["role"] == "user"
        assert result[1]["content"] == "What's the weather in Beijing and Tokyo?"

        ai_with_tools = result[2]
        assert ai_with_tools["role"] == "assistant"
        assert ai_with_tools["reasoning_content"] == "User wants weather for two cities"
        assert len(ai_with_tools["tool_calls"]) == 2

        assert result[3]["role"] == "tool"
        assert result[3]["tool_call_id"] == "call_1"

        assert result[4]["role"] == "tool"
        assert result[4]["tool_call_id"] == "call_2"

        ai_final = result[5]
        assert ai_final["role"] == "assistant"
        assert ai_final["reasoning_content"] == "Now I have both results"
        assert ai_final["content"] == "Beijing is sunny 25C, Tokyo is rainy 18C"
