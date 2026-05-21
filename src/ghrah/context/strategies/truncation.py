# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""TruncationStrategy：简单截断策略。

保留最新的消息，从最旧的非系统消息开始丢弃，
直到总 token 数 <= token_budget。

适用场景：最终兜底策略，确保消息不超过预算。
"""

from __future__ import annotations

from ghrah.chat.message import ChatMessage
from ghrah.context.window import WindowStrategy, _split_system_messages, estimate_tokens

__all__ = ["TruncationStrategy"]


class TruncationStrategy(WindowStrategy):
    """简单截断策略 — 保留最新消息，丢弃旧的。

    行为：
    - ChatMessage(role="system") 始终保留
    - 从最旧的非 system 消息开始逐条移除
    - 直到总 token 数 <= token_budget 或只剩 system 消息

    适用场景：最终兜底策略，确保消息不超过预算。
    """

    async def apply(self, messages: list[ChatMessage], token_budget: int) -> list[ChatMessage]:
        """应用截断策略。

        Args:
            messages: 输入消息列表
            token_budget: token 预算

        Returns:
            截断后的消息列表
        """
        system_msgs, other_msgs = _split_system_messages(messages)

        # 如果已在预算内，直接返回
        current_tokens = estimate_tokens(messages)
        if current_tokens <= token_budget:
            return list(messages)

        # 从头部（最旧的）开始移除非 system 消息
        result_other = list(other_msgs)
        while result_other and estimate_tokens(system_msgs + result_other) > token_budget:
            result_other.pop(0)

        return system_msgs + result_other

    @property
    def name(self) -> str:
        """策略名称。"""
        return "truncation"
