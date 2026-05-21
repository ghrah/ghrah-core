# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""窗口管理策略实现。

提供四种内置的上下文压缩策略：

- TruncationStrategy：简单截断，保留最新消息
- SlidingWindowStrategy：固定窗口大小，保留最近 N 条
- ToolCallFoldStrategy：折叠冗长的工具调用返回
- LLMSummaryStrategy：用 LLM 总结旧消息

策略可自由组合，通过 WindowManager 管道式执行。
"""

from ghrah.context.strategies.llm_summary import LLMSummaryStrategy
from ghrah.context.strategies.sliding_window import SlidingWindowStrategy
from ghrah.context.strategies.tool_call_fold import ToolCallFoldStrategy
from ghrah.context.strategies.truncation import TruncationStrategy

__all__ = [
    "TruncationStrategy",
    "SlidingWindowStrategy",
    "ToolCallFoldStrategy",
    "LLMSummaryStrategy",
]
