# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""WindowManager 和 token 估算的单元测试。

覆盖：
- estimate_tokens / estimate_message_tokens
- WindowManager 策略组合器
- _split_system_messages 辅助函数
- WindowableMessage Protocol 兼容性（mock 消息独立测试）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from ghrah.chat.content import TextBlock, ToolCallBlock
from ghrah.chat.message import ChatMessage
from ghrah.context.window import (
    WindowManager,
    WindowStrategy,
    _split_system_messages,
    estimate_message_tokens,
    estimate_tokens,
)

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


def _tool(content: str = "result", tool_call_id: str = "tc1") -> ChatMessage:
    return ChatMessage.tool(tool_call_id=tool_call_id, content=content)


# ----------------------------------------------------------------
# Mock WindowableMessage（独立于 ChatMessage 测试）
# ----------------------------------------------------------------


@dataclass
class MockBlock:
    """满足 WindowableBlock Protocol 的 mock block。"""
    type: str
    _text: str = ""
    _arguments: dict[str, Any] | None = None
    _name: str = ""
    _content: str = ""
    _base64: str | None = None
    _url: str | None = None
    _data: str = ""

    @property
    def text(self) -> str:
        return self._text

    @property
    def arguments(self) -> dict[str, Any]:
        return self._arguments or {}

    @property
    def name(self) -> str:
        return self._name

    @property
    def content(self) -> str:
        return self._content

    @property
    def base64(self) -> str | None:
        return self._base64

    @property
    def url(self) -> str | None:
        return self._url

    @property
    def data(self) -> str:
        return self._data


@dataclass
class MockMessage:
    """满足 WindowableMessage Protocol 的 mock 消息。"""
    role: str
    _content_blocks: list[MockBlock] = field(default_factory=list)
    _text: str = ""
    _source: str | None = None
    _metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def content_blocks(self) -> list[MockBlock]:
        return self._content_blocks

    @property
    def text(self) -> str:
        return self._text

    @property
    def has_tool_calls(self) -> bool:
        return any(b.type == "tool_call" for b in self._content_blocks)

    @property
    def tool_results(self) -> list[MockBlock]:
        return [b for b in self._content_blocks if b.type == "tool_result"]

    @property
    def source(self) -> str | None:
        return self._source

    @property
    def metadata(self) -> dict[str, Any]:
        return self._metadata

    def to_dict(self) -> dict[str, Any]:
        return {"role": self.role, "text": self._text}


def _mock_sys(text: str = "system") -> MockMessage:
    return MockMessage(
        role="system",
        _content_blocks=[MockBlock(type="text", _text=text)],
        _text=text,
    )


def _mock_human(text: str = "hello") -> MockMessage:
    return MockMessage(
        role="user",
        _content_blocks=[MockBlock(type="text", _text=text)],
        _text=text,
    )


# ----------------------------------------------------------------
# 空操作策略（用于测试 WindowManager 管道）
# ----------------------------------------------------------------


class NoOpStrategy(WindowStrategy):
    """空操作策略，原样返回消息。"""

    async def apply(self, messages: list, token_budget: int) -> list:
        return list(messages)

    @property
    def name(self) -> str:
        return "noop"


class ReverseStrategy(WindowStrategy):
    """反转消息顺序的策略（用于验证管道执行顺序）。"""

    async def apply(self, messages: list, token_budget: int) -> list:
        return list(reversed(messages))

    @property
    def name(self) -> str:
        return "reverse"


class DropFirstStrategy(WindowStrategy):
    """丢弃第一条非 System 消息的策略。"""

    async def apply(self, messages: list, token_budget: int) -> list:
        system_msgs, other_msgs = _split_system_messages(messages)
        if other_msgs:
            return system_msgs + other_msgs[1:]
        return list(messages)

    @property
    def name(self) -> str:
        return "drop_first"


# ----------------------------------------------------------------
# TestTokenEstimation
# ----------------------------------------------------------------


class TestTokenEstimation:
    """token 估算函数测试。"""

    def test_estimate_empty_list(self) -> None:
        """空消息列表 token 数为 0。"""
        assert estimate_tokens([]) == 0

    def test_estimate_single_human_message(self) -> None:
        """单条 HumanMessage 的 token 估算。"""
        msg = _human("a" * 100)
        tokens = estimate_message_tokens(msg)
        assert tokens == 25  # 100 / 4

    def test_estimate_single_empty_message(self) -> None:
        """空内容的消息至少 1 token。"""
        msg = _human("")
        tokens = estimate_message_tokens(msg)
        assert tokens >= 1

    def test_estimate_ai_with_tool_calls(self) -> None:
        """ChatMessage 带 tool_calls 时额外计算参数大小。"""
        msg = _ai_with_tool_calls()
        tokens = estimate_message_tokens(msg)
        assert tokens > 1

    def test_estimate_tool_message(self) -> None:
        """ToolMessage 的 token 估算。"""
        msg = _tool("x" * 200)
        tokens = estimate_message_tokens(msg)
        assert tokens == 50  # 200 / 4

    def test_estimate_multiple_messages(self) -> None:
        """多条消息的 token 累加。"""
        messages = [
            _human("a" * 40),  # 10
            _ai("b" * 80),  # 20
            _human("c" * 120),  # 30
        ]
        total = estimate_tokens(messages)
        assert total == 60  # 10 + 20 + 30

    def test_estimate_system_message(self) -> None:
        """SystemMessage 的 token 估算。"""
        msg = _sys("You are a helpful assistant." * 10)
        tokens = estimate_message_tokens(msg)
        assert tokens > 0


class TestTokenEstimationWithMock:
    """使用 MockMessage 测试 token 估算（脱离 ChatMessage 依赖）。"""

    def test_estimate_mock_text_message(self) -> None:
        """MockMessage 的 token 估算。"""
        msg = _mock_human("a" * 100)
        tokens = estimate_message_tokens(msg)
        assert tokens == 25  # 100 / 4

    def test_estimate_mock_empty_message(self) -> None:
        """空 MockMessage 至少 1 token。"""
        msg = _mock_human("")
        tokens = estimate_message_tokens(msg)
        assert tokens >= 1

    def test_estimate_mock_multiple_messages(self) -> None:
        """多条 MockMessage 的 token 累加。"""
        messages = [
            _mock_human("a" * 40),
            _mock_human("b" * 80),
        ]
        total = estimate_tokens(messages)
        assert total == 30  # 10 + 20

    def test_estimate_plain_object_fallback(self) -> None:
        """普通对象（无 WindowableMessage）的降级估算。"""
        class SimpleObj:
            text = "hello world"

        obj = SimpleObj()
        tokens = estimate_message_tokens(obj)
        assert tokens >= 1


# ----------------------------------------------------------------
# TestSplitSystemMessages
# ----------------------------------------------------------------


class TestSplitSystemMessages:
    """_split_system_messages 辅助函数测试。"""

    def test_no_system_messages(self) -> None:
        """无 system 消息时全部归入 other。"""
        msgs = [_human("hi"), _ai("hello")]
        sys, other = _split_system_messages(msgs)
        assert sys == []
        assert len(other) == 2

    def test_only_system_messages(self) -> None:
        """只有 system 消息时 other 为空。"""
        msgs = [_sys("a"), _sys("b")]
        sys, other = _split_system_messages(msgs)
        assert len(sys) == 2
        assert other == []

    def test_mixed_messages(self) -> None:
        """混合消息正确分离。"""
        msgs = [_sys("system"), _human("hi"), _sys("system2"), _ai("response")]
        sys, other = _split_system_messages(msgs)
        assert len(sys) == 2
        assert len(other) == 2
        assert all(m.role == "system" for m in sys)
        assert all(m.role != "system" for m in other)

    def test_empty_list(self) -> None:
        """空列表返回两个空列表。"""
        sys, other = _split_system_messages([])
        assert sys == []
        assert other == []

    def test_mixed_with_mock_messages(self) -> None:
        """MockMessage 也能正确分离。"""
        msgs = [_mock_sys("sys"), _mock_human("hi")]
        sys, other = _split_system_messages(msgs)
        assert len(sys) == 1
        assert len(other) == 1
        assert sys[0].role == "system"


# ----------------------------------------------------------------
# TestWindowManager
# ----------------------------------------------------------------


class TestWindowManager:
    """WindowManager 策略组合器测试。"""

    def test_init_default_max_tokens(self) -> None:
        """默认 max_tokens 为 4096。"""
        wm = WindowManager()
        assert wm.max_tokens == 4096

    def test_init_custom_max_tokens(self) -> None:
        """自定义 max_tokens。"""
        wm = WindowManager(max_tokens=8192)
        assert wm.max_tokens == 8192

    def test_init_no_strategies(self) -> None:
        """无策略时 strategies 为空列表。"""
        wm = WindowManager()
        assert wm.strategies == []

    def test_init_with_strategies(self) -> None:
        """传入策略列表。"""
        s1 = NoOpStrategy()
        s2 = ReverseStrategy()
        wm = WindowManager(strategies=[s1, s2])
        assert len(wm.strategies) == 2

    def test_add_strategy(self) -> None:
        """动态添加策略。"""
        wm = WindowManager()
        wm.add_strategy(NoOpStrategy())
        assert len(wm.strategies) == 1
        wm.add_strategy(ReverseStrategy())
        assert len(wm.strategies) == 2

    @pytest.mark.asyncio
    async def test_apply_no_strategies_returns_copy(self) -> None:
        """无策略时返回消息的浅拷贝。"""
        msgs = [_human("hi")]
        wm = WindowManager()
        result = await wm.apply(msgs)
        assert result == msgs
        assert result is not msgs

    @pytest.mark.asyncio
    async def test_apply_single_strategy(self) -> None:
        """单个策略正确应用。"""
        msgs = [_human("a"), _human("b")]
        wm = WindowManager(strategies=[ReverseStrategy()])
        result = await wm.apply(msgs)
        assert result == [_human("b"), _human("a")]

    @pytest.mark.asyncio
    async def test_apply_multiple_strategies_in_order(self) -> None:
        """多个策略按顺序应用（管道式执行）。"""
        msgs = [_sys("sys"), _human("a"), _human("b"), _human("c")]
        wm = WindowManager(strategies=[DropFirstStrategy(), ReverseStrategy()])
        result = await wm.apply(msgs)
        assert len(result) == 3
        assert result[0].text == "c"
        assert result[1].text == "b"
        assert result[2].role == "system"

    @pytest.mark.asyncio
    async def test_apply_with_max_tokens_override(self) -> None:
        """apply 的 max_tokens 参数覆盖默认值。"""
        wm = WindowManager(max_tokens=4096)
        budgets_seen: list[int] = []

        class BudgetCapture(WindowStrategy):
            async def apply(self, messages: list, token_budget: int) -> list:
                budgets_seen.append(token_budget)
                return list(messages)

            @property
            def name(self) -> str:
                return "budget_capture"

        wm.add_strategy(BudgetCapture())
        await wm.apply([_human("hi")], max_tokens=2048)
        assert budgets_seen == [2048]

    @pytest.mark.asyncio
    async def test_apply_uses_default_max_tokens(self) -> None:
        """apply 不传 max_tokens 时使用默认值。"""
        wm = WindowManager(max_tokens=8192)
        budgets_seen: list[int] = []

        class BudgetCapture(WindowStrategy):
            async def apply(self, messages: list, token_budget: int) -> list:
                budgets_seen.append(token_budget)
                return list(messages)

            @property
            def name(self) -> str:
                return "budget_capture"

        wm.add_strategy(BudgetCapture())
        await wm.apply([_human("hi")])
        assert budgets_seen == [8192]

    def test_estimate_tokens_delegates(self) -> None:
        """estimate_tokens 委托给模块级函数。"""
        wm = WindowManager()
        msgs = [_human("a" * 100)]
        assert wm.estimate_tokens(msgs) == estimate_tokens(msgs)

    def test_strategies_returns_copy(self) -> None:
        """strategies 属性返回副本，修改不影响内部。"""
        wm = WindowManager(strategies=[NoOpStrategy()])
        strategies = wm.strategies
        strategies.append(ReverseStrategy())
        assert len(wm.strategies) == 1

    def test_message_factory_property(self) -> None:
        """message_factory 属性可设置和读取。"""
        wm = WindowManager()
        assert wm.message_factory is None

    @pytest.mark.asyncio
    async def test_apply_with_mock_messages(self) -> None:
        """使用 MockMessage（满足 WindowableMessage Protocol）也能正确工作。"""
        msgs = [_mock_sys("sys"), _mock_human("hi")]
        wm = WindowManager()
        result = await wm.apply(msgs)
        assert len(result) == 2
