# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""LLMSummaryStrategy：LLM 摘要策略。

使用 LLM 总结旧消息，用一条摘要消息替代大量历史对话，
从而减少 token 数量，同时保留关键语义信息。

行为：
- 将消息分为"旧消息"和"新消息"
- 对"旧消息"使用 LLM 生成摘要
- 用一条 system 消息替代旧消息（标记为上下文摘要）
- 新消息保持不变
- LLM 调用失败时回退到简单截断（保留最新消息）

适用场景：长对话场景，需要保留对话语义但减少 token 数。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ghrah.chat.message import ChatMessage
from ghrah.context.window import WindowStrategy, _split_system_messages, estimate_tokens

if TYPE_CHECKING:
    from ghrah.chat.format import ChatFormat

__all__ = ["LLMSummaryStrategy"]

logger = logging.getLogger(__name__)

# 默认摘要提示词
_DEFAULT_SUMMARY_PROMPT = (
    "Please summarize the following conversation concisely, "
    "preserving key facts, decisions, and any important context. "
    "Write the summary in the same language as the conversation."
)

# 摘要消息前缀
_SUMMARY_PREFIX = "[Context Summary] "


class LLMSummaryStrategy(WindowStrategy):
    """LLM 摘要策略 — 用 LLM 总结旧消息。

    行为：
    - 如果总 token 在预算内，不生成摘要
    - 将非 system 消息分为"旧"和"新"（3/4 预算分给新消息）
    - 对旧消息调用 LLM 生成摘要
    - 用一条 system 消息替代旧消息
    - LLM 调用失败时回退到简单截断

    适用场景：长对话场景，需要保留对话语义但减少 token 数。

    Args:
        llm: ChatFormat 实例
        summary_prompt: 摘要提示词（可选，使用默认提示词）
    """

    def __init__(
        self,
        llm: ChatFormat | None = None,
        summary_prompt: str | None = None,
    ) -> None:
        self._llm = llm
        self._summary_prompt = summary_prompt or _DEFAULT_SUMMARY_PROMPT

    @property
    def summary_prompt(self) -> str:
        """摘要提示词。"""
        return self._summary_prompt

    async def apply(self, messages: list[ChatMessage], token_budget: int) -> list[ChatMessage]:
        """应用 LLM 摘要策略。

        Args:
            messages: 输入消息列表
            token_budget: token 预算

        Returns:
            压缩后的消息列表
        """
        # 如果已在预算内，直接返回
        current_tokens = estimate_tokens(messages)
        if current_tokens <= token_budget:
            return list(messages)

        system_msgs, other_msgs = _split_system_messages(messages)

        if not other_msgs:
            return list(messages)

        # 计算分割点：3/4 预算分给新消息
        system_tokens = estimate_tokens(system_msgs)
        remaining_budget = token_budget - system_tokens
        new_budget = int(remaining_budget * 0.75)

        # 从尾部开始累积，确定"新消息"范围
        split_index = self._find_split_index(other_msgs, new_budget)

        # 如果所有消息都是"新消息"，无法生成摘要，直接返回
        if split_index <= 0:
            return system_msgs + other_msgs

        old_msgs = other_msgs[:split_index]
        new_msgs = other_msgs[split_index:]

        # 生成摘要
        summary_msg = await self._generate_summary(old_msgs)

        if summary_msg is not None:
            return system_msgs + [summary_msg] + new_msgs
        else:
            # LLM 调用失败，回退到简单截断（只保留新消息）
            logger.warning("LLM summary failed, falling back to truncation")
            return system_msgs + new_msgs

    def _find_split_index(self, messages: list[ChatMessage], new_budget: int) -> int:
        """找到分割点：从尾部累积消息直到超过 new_budget。

        返回旧消息的结束索引（新消息从 split_index 开始）。

        Args:
            messages: 非 system 消息列表
            new_budget: 新消息的 token 预算

        Returns:
            分割索引
        """
        cumulative = 0
        split_index = len(messages)

        for i in range(len(messages) - 1, -1, -1):
            msg_tokens = estimate_tokens([messages[i]])
            cumulative += msg_tokens
            if cumulative > new_budget:
                # 当前消息也属于旧消息
                split_index = i + 1
                break
            split_index = i

        return split_index

    async def _generate_summary(self, old_messages: list[ChatMessage]) -> ChatMessage | None:
        """调用 LLM 生成旧消息的摘要。

        Args:
            old_messages: 要总结的消息列表

        Returns:
            摘要 ChatMessage(role="system")，失败返回 None
        """
        # 格式化旧消息为文本
        conversation_text = self._format_messages_for_summary(old_messages)

        if not conversation_text.strip():
            return None

        if self._llm is None:
            logger.warning("LLMSummaryStrategy has no LLM configured, skipping summary")
            return None

        try:
            summary_messages = [
                ChatMessage.system(text=self._summary_prompt),
                ChatMessage.user(text_or_blocks=conversation_text),
            ]
            response = await self._llm.generate(summary_messages)

            summary_content = response.text or ""
            return ChatMessage.system(text=_SUMMARY_PREFIX + summary_content)

        except Exception:
            logger.exception("Failed to generate LLM summary")
            return None

    def _format_messages_for_summary(self, messages: list[ChatMessage]) -> str:
        """将消息列表格式化为摘要用的文本。

        Args:
            messages: 消息列表

        Returns:
            格式化后的文本
        """
        lines: list[str] = []
        for msg in messages:
            role = self._get_role_label(msg)
            content = msg.text
            lines.append(f"{role}: {content}")

        return "\n".join(lines)

    def _get_role_label(self, msg: ChatMessage) -> str:
        """获取消息的角色标签。

        Args:
            msg: ChatMessage 对象

        Returns:
            角色标签字符串
        """
        if msg.role == "system":
            return "System"
        elif msg.role == "user":
            return "Human"
        elif msg.role == "ai":
            if msg.has_tool_calls:
                return "AI"
            return "AI"
        elif msg.role == "tool":
            tool_results = msg.tool_results
            if tool_results:
                name = tool_results[0].name or "unknown"
                return f"Tool({name})"
            return "Tool"
        else:
            return "Unknown"

    @property
    def llm(self) -> ChatFormat | None:
        return self._llm

    def set_llm(self, llm: ChatFormat) -> None:
        self._llm = llm

    @property
    def name(self) -> str:
        """策略名称。"""
        return "llm_summary"
