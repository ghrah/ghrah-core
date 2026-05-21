# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""SlidingWindowStrategy：滑动窗口策略。

保留最近 N 条非系统消息，丢弃更旧的消息。
系统消息不计入窗口大小，始终保留。

适用场景：固定窗口大小的场景，简单高效。
"""

from __future__ import annotations

from ghrah.chat.message import ChatMessage
from ghrah.context.window import WindowStrategy, _split_system_messages

__all__ = ["SlidingWindowStrategy"]


class SlidingWindowStrategy(WindowStrategy):
    """滑动窗口策略 — 保留最近 N 条消息。

    行为：
    - ChatMessage(role="system") 不计入窗口大小，始终保留
    - 保留最近 window_size 条非 system 消息
    - 如果非 system 消息数 <= window_size，不做任何操作

    适用场景：固定窗口大小的场景，简单高效。

    Args:
        window_size: 窗口大小（保留的最近消息条数），默认 20
    """

    def __init__(self, window_size: int = 20) -> None:
        if window_size <= 0:
            raise ValueError(f"window_size must be positive, got {window_size}")
        self._window_size = window_size

    @property
    def window_size(self) -> int:
        """窗口大小。"""
        return self._window_size

    async def apply(self, messages: list[ChatMessage], token_budget: int) -> list[ChatMessage]:
        """应用滑动窗口策略。

        Args:
            messages: 输入消息列表
            token_budget: token 预算（此策略不使用此参数，仅保留接口一致）

        Returns:
            窗口内的消息列表
        """
        system_msgs, other_msgs = _split_system_messages(messages)

        # 如果消息数在窗口内，直接返回
        if len(other_msgs) <= self._window_size:
            return list(messages)

        # 保留最近 window_size 条
        trimmed = other_msgs[-self._window_size :]
        return system_msgs + trimmed

    @property
    def name(self) -> str:
        """策略名称。"""
        return "sliding_window"
