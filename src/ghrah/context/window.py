# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""WindowManager：LLM 上下文窗口管理器。

提供策略模式的窗口压缩框架，支持多种压缩策略的组合管道式执行。

核心组件：
- WindowStrategy：策略接口，定义 apply() 方法
- WindowManager：策略组合器，按顺序应用多个策略
- estimate_tokens / estimate_message_tokens：token 估算工具函数

设计要点：
- 策略按注册顺序依次应用，形成处理管道
- ChatMessage(role="system") 始终被保护，不参与截断/折叠
- token 估算使用字符近似法（1 token ≈ 4 字符），零外部依赖
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

from ghrah.chat.content import (
    AudioBlock,
    FileBlock,
    ImageBlock,
    TextBlock,
    ToolCallBlock,
    ToolResultBlock,
)
from ghrah.chat.message import ChatMessage

__all__ = [
    "WindowStrategy",
    "WindowManager",
    "estimate_tokens",
    "estimate_message_tokens",
]

# token 估算常量：1 token ≈ 4 个字符
_CHARS_PER_TOKEN = 4


def estimate_message_tokens(message: Any) -> int:
    """估算单条消息的 token 数。

    使用字符近似法：len(content) // CHARS_PER_TOKEN。
    对于 ChatMessage，遍历 content_blocks 估算。
    ToolCallBlock 额外按参数大小估算。

    Args:
        message: ChatMessage 或兼容对象

    Returns:
        估算的 token 数
    """
    if isinstance(message, ChatMessage):
        total = 0
        for block in message.content_blocks:
            if isinstance(block, TextBlock):
                total += max(1, len(block.text) // _CHARS_PER_TOKEN)
            elif isinstance(block, ToolCallBlock):
                args_str = (
                    json.dumps(block.arguments, ensure_ascii=False) if block.arguments else ""
                )
                total += max(1, len(args_str) // _CHARS_PER_TOKEN)
                total += max(1, len(block.name) // _CHARS_PER_TOKEN)
            elif isinstance(block, ToolResultBlock):
                total += max(1, len(block.content) // _CHARS_PER_TOKEN)
            elif isinstance(block, ImageBlock):
                size = len(block.base64) if block.base64 else (len(block.url) if block.url else 0)
                total += max(1, size // _CHARS_PER_TOKEN)
            elif isinstance(block, AudioBlock):
                total += max(1, len(block.data) // _CHARS_PER_TOKEN)
            elif isinstance(block, FileBlock):
                size = len(block.base64) if block.base64 else (len(block.url) if block.url else 0)
                total += max(1, size // _CHARS_PER_TOKEN)
            else:
                total += 1
        return max(1, total)

    # 降级处理：尝试获取 text 属性
    content = getattr(message, "text", None)
    if content is not None:
        return max(1, len(str(content)) // _CHARS_PER_TOKEN)
    content = getattr(message, "content", str(message))
    return max(1, len(str(content)) // _CHARS_PER_TOKEN)


def estimate_tokens(messages: list[Any]) -> int:
    """估算消息列表的总 token 数。

    Args:
        messages: 消息列表

    Returns:
        总 token 数估算值
    """
    return sum(estimate_message_tokens(m) for m in messages)


class WindowStrategy(ABC):
    """LLM 上下文窗口压缩策略接口。

    每个策略接收消息列表和 token 预算，返回压缩后的消息列表。
    策略不应修改原始消息列表（返回新列表）。

    系统消息保护约定：
    - ChatMessage(role="system") 始终保留，不参与截断/折叠
    - 具体策略负责在 apply() 中分离和保护系统消息
    """

    @abstractmethod
    async def apply(self, messages: list[ChatMessage], token_budget: int) -> list[ChatMessage]:
        """应用压缩策略。

        Args:
            messages: 输入消息列表
            token_budget: 剩余 token 预算

        Returns:
            压缩后的消息列表（新列表，不修改原列表）
        """
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """策略名称，用于日志和调试。"""
        ...


def _split_system_messages(
    messages: list[ChatMessage],
) -> tuple[list[ChatMessage], list[ChatMessage]]:
    """将消息列表分为系统消息和非系统消息。

    Args:
        messages: 输入消息列表

    Returns:
        (system_messages, other_messages) 元组
    """
    system_msgs: list[ChatMessage] = []
    other_msgs: list[ChatMessage] = []
    for msg in messages:
        if msg.role == "system":
            system_msgs.append(msg)
        else:
            other_msgs.append(msg)
    return system_msgs, other_msgs


class WindowManager:
    """LLM 上下文窗口管理器 — 组合多个 WindowStrategy。

    管道式执行：策略按注册顺序依次应用，每个策略接收上一个策略的输出。

    推荐的默认执行顺序：
    1. ToolCallFoldStrategy — 折叠冗长的工具返回（减少单条消息体积）
    2. LLMSummaryStrategy   — 总结旧消息（用摘要替代历史）
    3. SlidingWindowStrategy — 确保总消息数在窗口内
    4. TruncationStrategy    — 最终兜底，暴力截断

    Args:
        strategies: 策略列表（按执行顺序）
        max_tokens: 默认 token 预算
    """

    def __init__(
        self,
        strategies: list[WindowStrategy] | None = None,
        max_tokens: int = 4096,
    ) -> None:
        self._strategies: list[WindowStrategy] = list(strategies) if strategies else []
        self._max_tokens = max_tokens

    @property
    def max_tokens(self) -> int:
        """默认 token 预算。"""
        return self._max_tokens

    @property
    def strategies(self) -> list[WindowStrategy]:
        """已注册的策略列表（副本）。"""
        return list(self._strategies)

    def add_strategy(self, strategy: WindowStrategy) -> None:
        """添加策略到管道末尾。

        Args:
            strategy: 要添加的策略
        """
        self._strategies.append(strategy)

    async def apply(
        self, messages: list[ChatMessage], max_tokens: int | None = None
    ) -> list[ChatMessage]:
        """按顺序应用所有策略。

        Args:
            messages: 输入消息列表
            max_tokens: 覆盖默认 max_tokens

        Returns:
            压缩后的消息列表
        """
        budget = max_tokens if max_tokens is not None else self._max_tokens
        result = list(messages)  # 浅拷贝

        for strategy in self._strategies:
            result = await strategy.apply(result, budget)

        return result

    def estimate_tokens(self, messages: list[ChatMessage]) -> int:
        """估算消息列表的总 token 数。

        Args:
            messages: 消息列表

        Returns:
            估算的 token 数
        """
        return estimate_tokens(messages)
