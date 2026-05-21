# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""窗口管理策略单元测试。

覆盖四种内置策略：
- TruncationStrategy
- SlidingWindowStrategy
- ToolCallFoldStrategy
- LLMSummaryStrategy
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from ghrah.chat.content import TextBlock, ToolCallBlock
from ghrah.chat.format import ChatFormat, LLMResponse
from ghrah.chat.message import ChatMessage
from ghrah.context.strategies.llm_summary import LLMSummaryStrategy
from ghrah.context.strategies.sliding_window import SlidingWindowStrategy
from ghrah.context.strategies.tool_call_fold import ToolCallFoldStrategy
from ghrah.context.strategies.truncation import TruncationStrategy

# ----------------------------------------------------------------
# 辅助工厂
# ----------------------------------------------------------------


def _sys(content: str = "system") -> ChatMessage:
    return ChatMessage.system(text=content)


def _human(content: str = "hello") -> ChatMessage:
    return ChatMessage.user(text_or_blocks=content)


def _ai(content: str = "response") -> ChatMessage:
    return ChatMessage.ai(text=content)


def _ai_with_tool_calls(content: str = "") -> ChatMessage:
    """带 tool_calls 的 ChatMessage。"""
    return ChatMessage.ai(
        content_blocks=[
            *([TextBlock(text=content)] if content else []),
            ToolCallBlock(
                id="tc1",
                name="read_file",
                arguments={"path": "/some/very/long/path/to/file.txt"},
            ),
            ToolCallBlock(
                id="tc2",
                name="search",
                arguments={"query": "a" * 200},
            ),
        ],
    )


def _tool(
    content: str = "result", tool_call_id: str = "tc1", name: str | None = None
) -> ChatMessage:
    return ChatMessage.tool(tool_call_id=tool_call_id, content=content, name=name)


def _long_content(length: int) -> str:
    """生成长度为 length 的重复字符串。"""
    return "x" * length


# ----------------------------------------------------------------
# TestTruncationStrategy
# ----------------------------------------------------------------


class TestTruncationStrategy:
    """TruncationStrategy 简单截断测试。"""

    @pytest.mark.asyncio
    async def test_name(self) -> None:
        """策略名称。"""
        assert TruncationStrategy().name == "truncation"

    @pytest.mark.asyncio
    async def test_within_budget_no_truncation(self) -> None:
        """消息在预算内时不截断。"""
        msgs = [_human("short")]
        strategy = TruncationStrategy()
        result = await strategy.apply(msgs, token_budget=10000)
        assert result == msgs

    @pytest.mark.asyncio
    async def test_over_budget_removes_oldest(self) -> None:
        """超出预算时从最旧的消息开始移除。"""
        msgs = [_human("a" * 200), _human("b" * 200), _human("c" * 200)]
        strategy = TruncationStrategy()
        budget = 110
        result = await strategy.apply(msgs, token_budget=budget)
        assert len(result) == 2
        assert result[0].text == "b" * 200
        assert result[1].text == "c" * 200

    @pytest.mark.asyncio
    async def test_preserves_system_message(self) -> None:
        """SystemMessage 始终保留。"""
        msgs = [_sys("system"), _human("a" * 200), _human("b" * 200)]
        strategy = TruncationStrategy()
        budget = 30
        result = await strategy.apply(msgs, token_budget=budget)
        assert any(m.role == "system" for m in result)

    @pytest.mark.asyncio
    async def test_system_message_only(self) -> None:
        """只有 SystemMessage 时不会被移除。"""
        msgs = [_sys("system prompt here")]
        strategy = TruncationStrategy()
        result = await strategy.apply(msgs, token_budget=1)
        assert len(result) == 1
        assert result[0].role == "system"

    @pytest.mark.asyncio
    async def test_does_not_modify_original(self) -> None:
        """不修改原始消息列表。"""
        msgs = [_human("a"), _human("b")]
        original_len = len(msgs)
        strategy = TruncationStrategy()
        await strategy.apply(msgs, token_budget=1)
        assert len(msgs) == original_len

    @pytest.mark.asyncio
    async def test_empty_messages(self) -> None:
        """空消息列表返回空列表。"""
        strategy = TruncationStrategy()
        result = await strategy.apply([], token_budget=100)
        assert result == []


# ----------------------------------------------------------------
# TestSlidingWindowStrategy
# ----------------------------------------------------------------


class TestSlidingWindowStrategy:
    """SlidingWindowStrategy 滑动窗口测试。"""

    @pytest.mark.asyncio
    async def test_name(self) -> None:
        """策略名称。"""
        assert SlidingWindowStrategy().name == "sliding_window"

    def test_default_window_size(self) -> None:
        """默认窗口大小为 20。"""
        strategy = SlidingWindowStrategy()
        assert strategy.window_size == 20

    def test_custom_window_size(self) -> None:
        """自定义窗口大小。"""
        strategy = SlidingWindowStrategy(window_size=5)
        assert strategy.window_size == 5

    def test_invalid_window_size_raises(self) -> None:
        """无效窗口大小抛出 ValueError。"""
        with pytest.raises(ValueError, match="positive"):
            SlidingWindowStrategy(window_size=0)
        with pytest.raises(ValueError, match="positive"):
            SlidingWindowStrategy(window_size=-1)

    @pytest.mark.asyncio
    async def test_within_window_no_change(self) -> None:
        """消息数在窗口内时不裁剪。"""
        msgs = [_human("a"), _human("b")]
        strategy = SlidingWindowStrategy(window_size=5)
        result = await strategy.apply(msgs, token_budget=10000)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_exceeds_window_trims(self) -> None:
        """超出窗口大小时保留最近 N 条。"""
        msgs = [_human(str(i)) for i in range(10)]
        strategy = SlidingWindowStrategy(window_size=3)
        result = await strategy.apply(msgs, token_budget=10000)
        assert len(result) == 3
        assert result[0].text == "7"
        assert result[1].text == "8"
        assert result[2].text == "9"

    @pytest.mark.asyncio
    async def test_preserves_system_messages(self) -> None:
        """SystemMessage 不计入窗口大小。"""
        msgs = [_sys("sys")] + [_human(str(i)) for i in range(10)]
        strategy = SlidingWindowStrategy(window_size=3)
        result = await strategy.apply(msgs, token_budget=10000)
        assert len(result) == 4
        assert result[0].role == "system"
        assert result[1].text == "7"
        assert result[2].text == "8"
        assert result[3].text == "9"

    @pytest.mark.asyncio
    async def test_system_messages_not_counted_in_window(self) -> None:
        """多条 SystemMessage 都不计入窗口。"""
        msgs = [_sys("s1"), _sys("s2")] + [_human(str(i)) for i in range(10)]
        strategy = SlidingWindowStrategy(window_size=3)
        result = await strategy.apply(msgs, token_budget=10000)
        assert len(result) == 5
        sys_count = sum(1 for m in result if m.role == "system")
        assert sys_count == 2

    @pytest.mark.asyncio
    async def test_does_not_modify_original(self) -> None:
        """不修改原始消息列表。"""
        msgs = [_human(str(i)) for i in range(10)]
        original_len = len(msgs)
        strategy = SlidingWindowStrategy(window_size=3)
        await strategy.apply(msgs, token_budget=10000)
        assert len(msgs) == original_len

    @pytest.mark.asyncio
    async def test_empty_messages(self) -> None:
        """空消息列表返回空列表。"""
        strategy = SlidingWindowStrategy(window_size=3)
        result = await strategy.apply([], token_budget=10000)
        assert result == []


# ----------------------------------------------------------------
# TestToolCallFoldStrategy
# ----------------------------------------------------------------


class TestToolCallFoldStrategy:
    """ToolCallFoldStrategy ToolCall 折叠测试。"""

    @pytest.mark.asyncio
    async def test_name(self) -> None:
        """策略名称。"""
        assert ToolCallFoldStrategy().name == "tool_call_fold"

    def test_default_max_length(self) -> None:
        """默认最大长度为 500。"""
        strategy = ToolCallFoldStrategy()
        assert strategy.max_content_length == 500

    def test_custom_max_length(self) -> None:
        """自定义最大长度。"""
        strategy = ToolCallFoldStrategy(max_content_length=100)
        assert strategy.max_content_length == 100

    def test_invalid_max_length_raises(self) -> None:
        """无效最大长度抛出 ValueError。"""
        with pytest.raises(ValueError, match="positive"):
            ToolCallFoldStrategy(max_content_length=0)
        with pytest.raises(ValueError, match="positive"):
            ToolCallFoldStrategy(max_content_length=-1)

    @pytest.mark.asyncio
    async def test_no_tool_messages_no_change(self) -> None:
        """没有 ToolMessage 时不做任何处理。"""
        msgs = [_sys("sys"), _human("hi"), _ai("response")]
        strategy = ToolCallFoldStrategy()
        result = await strategy.apply(msgs, token_budget=10000)
        assert len(result) == 3
        assert all(m.text == orig.text for m, orig in zip(result, msgs))

    @pytest.mark.asyncio
    async def test_short_tool_message_not_folded(self) -> None:
        """短 ToolMessage 不被折叠。"""
        msgs = [_tool("short result")]
        strategy = ToolCallFoldStrategy(max_content_length=500)
        result = await strategy.apply(msgs, token_budget=10000)
        assert len(result) == 1
        assert result[0].tool_results[0].content == "short result"

    @pytest.mark.asyncio
    async def test_long_tool_message_folded(self) -> None:
        """长 ToolMessage 被截断并添加标记。"""
        long_content = _long_content(1000)
        msgs = [_tool(long_content)]
        strategy = ToolCallFoldStrategy(max_content_length=100)
        result = await strategy.apply(msgs, token_budget=10000)
        assert len(result) == 1
        assert len(result[0].tool_results[0].content) < len(long_content)
        assert "truncated" in result[0].tool_results[0].content
        assert "1000 chars" in result[0].tool_results[0].content

    @pytest.mark.asyncio
    async def test_fold_preserves_tool_call_id(self) -> None:
        """折叠后 tool_call_id 保持不变。"""
        msgs = [_tool(_long_content(1000), tool_call_id="call_abc123")]
        strategy = ToolCallFoldStrategy(max_content_length=100)
        result = await strategy.apply(msgs, token_budget=10000)
        assert result[0].tool_results[0].tool_call_id == "call_abc123"

    @pytest.mark.asyncio
    async def test_fold_preserves_name(self) -> None:
        """折叠后 name 保持不变。"""
        msgs = [_tool(_long_content(1000), tool_call_id="tc1", name="read_file")]
        strategy = ToolCallFoldStrategy(max_content_length=100)
        result = await strategy.apply(msgs, token_budget=10000)
        assert result[0].tool_results[0].name == "read_file"

    @pytest.mark.asyncio
    async def test_preserves_ai_message_tool_calls(self) -> None:
        """AI 消息的 tool_calls 不被修改。"""
        ai_msg = ChatMessage.ai(
            content_blocks=[
                ToolCallBlock(id="tc1", name="read_file", arguments={"path": "/test"}),
            ],
        )
        tool_msg = _tool(_long_content(1000), tool_call_id="tc1")
        msgs = [ai_msg, tool_msg]
        strategy = ToolCallFoldStrategy(max_content_length=100)
        result = await strategy.apply(msgs, token_budget=10000)
        assert result[0].tool_calls == ai_msg.tool_calls
        assert "truncated" in result[1].tool_results[0].content

    @pytest.mark.asyncio
    async def test_mixed_messages_partial_fold(self) -> None:
        """混合消息中只折叠超长的 ToolMessage。"""
        msgs = [
            _human("question"),
            _ai("calling tool"),
            _tool("short"),
            _ai("calling another"),
            _tool(_long_content(1000)),
        ]
        strategy = ToolCallFoldStrategy(max_content_length=100)
        result = await strategy.apply(msgs, token_budget=10000)
        assert len(result) == 5
        assert result[2].tool_results[0].content == "short"
        assert "truncated" in result[4].tool_results[0].content

    @pytest.mark.asyncio
    async def test_does_not_modify_original(self) -> None:
        """不修改原始消息列表。"""
        msgs = [_tool(_long_content(1000))]
        original_content = msgs[0].tool_results[0].content
        strategy = ToolCallFoldStrategy(max_content_length=100)
        await strategy.apply(msgs, token_budget=10000)
        assert msgs[0].tool_results[0].content == original_content

    @pytest.mark.asyncio
    async def test_empty_messages(self) -> None:
        """空消息列表返回空列表。"""
        strategy = ToolCallFoldStrategy()
        result = await strategy.apply([], token_budget=10000)
        assert result == []


# ----------------------------------------------------------------
# TestLLMSummaryStrategy
# ----------------------------------------------------------------


class TestLLMSummaryStrategy:
    """LLMSummaryStrategy LLM 摘要测试。"""

    @pytest.mark.asyncio
    async def test_name(self) -> None:
        """策略名称。"""
        llm = MagicMock(spec=ChatFormat)
        llm.generate = AsyncMock()
        strategy = LLMSummaryStrategy(llm=llm)
        assert strategy.name == "llm_summary"

    @pytest.mark.asyncio
    async def test_within_budget_no_summary(self) -> None:
        """消息在预算内时不生成摘要。"""
        llm = MagicMock(spec=ChatFormat)
        llm.generate = AsyncMock()
        strategy = LLMSummaryStrategy(llm=llm)
        msgs = [_human("short")]
        result = await strategy.apply(msgs, token_budget=10000)
        assert result == msgs
        llm.generate.assert_not_called()

    @pytest.mark.asyncio
    async def test_generates_summary_for_old_messages(self) -> None:
        """超出预算时对旧消息生成摘要。"""
        mock_response = LLMResponse(
            content_blocks=[TextBlock(text="This is a summary of the conversation.")]
        )
        llm = MagicMock(spec=ChatFormat)
        llm.generate = AsyncMock(return_value=mock_response)

        strategy = LLMSummaryStrategy(llm=llm)

        msgs = [_human(f"Message {i} " + "x" * 100) for i in range(20)]
        budget = 200

        result = await strategy.apply(msgs, token_budget=budget)

        llm.generate.assert_called_once()

        summary_msgs = [m for m in result if m.role == "system" and "[Context Summary]" in m.text]
        assert len(summary_msgs) >= 1

    @pytest.mark.asyncio
    async def test_preserves_recent_messages(self) -> None:
        """摘要后保留最新消息。"""
        mock_response = LLMResponse(content_blocks=[TextBlock(text="Summary here.")])
        llm = MagicMock(spec=ChatFormat)
        llm.generate = AsyncMock(return_value=mock_response)

        strategy = LLMSummaryStrategy(llm=llm)

        msgs = [_human(f"Message {i} " + "x" * 100) for i in range(20)]
        budget = 500

        result = await strategy.apply(msgs, token_budget=budget)

        result_texts = [m.text for m in result]
        assert any("Message 19" in t for t in result_texts)

    @pytest.mark.asyncio
    async def test_summary_message_is_system_message(self) -> None:
        """摘要消息是 system 角色类型。"""
        mock_response = LLMResponse(content_blocks=[TextBlock(text="Summary content.")])
        llm = MagicMock(spec=ChatFormat)
        llm.generate = AsyncMock(return_value=mock_response)

        strategy = LLMSummaryStrategy(llm=llm)
        msgs = [_human(f"Msg {i} " + "x" * 100) for i in range(20)]
        budget = 200

        result = await strategy.apply(msgs, token_budget=budget)

        summary_msgs = [m for m in result if m.role == "system"]
        assert len(summary_msgs) >= 1
        assert any("[Context Summary]" in m.text for m in summary_msgs)

    @pytest.mark.asyncio
    async def test_llm_failure_fallback_to_truncation(self) -> None:
        """LLM 调用失败时回退到截断（只保留新消息）。"""
        llm = MagicMock(spec=ChatFormat)
        llm.generate = AsyncMock(side_effect=Exception("LLM unavailable"))

        strategy = LLMSummaryStrategy(llm=llm)

        msgs = [_human(f"Msg {i} " + "x" * 100) for i in range(20)]
        budget = 500

        result = await strategy.apply(msgs, token_budget=budget)

        assert len(result) < len(msgs)
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_empty_old_messages_no_summary(self) -> None:
        """没有旧消息时不生成摘要。"""
        llm = MagicMock(spec=ChatFormat)
        llm.generate = AsyncMock()
        strategy = LLMSummaryStrategy(llm=llm)

        msgs = [_human("short")]
        await strategy.apply(msgs, token_budget=10000)
        llm.generate.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_messages_list(self) -> None:
        """空消息列表返回空列表。"""
        llm = MagicMock(spec=ChatFormat)
        llm.generate = AsyncMock()
        strategy = LLMSummaryStrategy(llm=llm)
        result = await strategy.apply([], token_budget=100)
        assert result == []
        llm.generate.assert_not_called()

    def test_custom_summary_prompt(self) -> None:
        """自定义摘要提示词。"""
        llm = MagicMock(spec=ChatFormat)
        strategy = LLMSummaryStrategy(llm=llm, summary_prompt="自定义摘要提示")
        assert strategy.summary_prompt == "自定义摘要提示"

    @pytest.mark.asyncio
    async def test_does_not_modify_original(self) -> None:
        """不修改原始消息列表。"""
        mock_response = LLMResponse(content_blocks=[TextBlock(text="Summary.")])
        llm = MagicMock(spec=ChatFormat)
        llm.generate = AsyncMock(return_value=mock_response)

        strategy = LLMSummaryStrategy(llm=llm)
        msgs = [_human(f"Msg {i} " + "x" * 100) for i in range(20)]
        original_len = len(msgs)
        await strategy.apply(msgs, token_budget=200)
        assert len(msgs) == original_len

    @pytest.mark.asyncio
    async def test_system_messages_preserved(self) -> None:
        """SystemMessage 在摘要过程中被保留。"""
        mock_response = LLMResponse(content_blocks=[TextBlock(text="Summary.")])
        llm = MagicMock(spec=ChatFormat)
        llm.generate = AsyncMock(return_value=mock_response)

        strategy = LLMSummaryStrategy(llm=llm)
        msgs = [_sys("system prompt")] + [_human(f"Msg {i} " + "x" * 100) for i in range(20)]
        budget = 300

        result = await strategy.apply(msgs, token_budget=budget)

        sys_msgs = [m for m in result if m.role == "system" and m.text == "system prompt"]
        assert len(sys_msgs) == 1
