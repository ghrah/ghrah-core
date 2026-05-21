# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""ContextManager: Git 链式上下文管理。

为每个 ActorAgent 提供不可变的链式上下文管理，
支持原子性状态变更、delta+定期快照消息存储、分支继承、异步持久化、Session 管理。

Phase 1 公共 API：
- ContextNode: 不可变链式节点
- ActionChain: 链管理器
- MessageStore: 运行时消息存储
- StateManager: 事务性状态管理器
- ContextManager: 上下文管理器门面类
- Session: 迭代会话数据模型
- create_rebased_context: 跨 Agent 上下文继承工厂函数
- WindowStrategy: 窗口策略接口
- WindowManager: 窗口管理器
- estimate_tokens / estimate_message_tokens: token 估算
- TruncationStrategy: 简单截断策略
- SlidingWindowStrategy: 滑动窗口策略
- ToolCallFoldStrategy: ToolCall 折叠策略
- LLMSummaryStrategy: LLM 摘要策略
- PersistenceBackend: 持久化后端抽象基类
- InMemoryBackend: 纯内存持久化后端
- JsonFileBackend: 基于 JSON 文件的持久化后端
- serialize_node / deserialize_node: 节点序列化工具
- serialize_action_result / deserialize_action_result: ActionResult 序列化工具
- serialize_action_results / deserialize_action_results: action_results 列表序列化工具
- serialize_messages / deserialize_messages: 消息序列化工具
"""

from ghrah.context.chain import ActionChain
from ghrah.context.manager import ContextManager
from ghrah.context.message_store import MessageStore
from ghrah.context.node import ContextNode
from ghrah.context.persistence import (
    InMemoryBackend,
    JsonFileBackend,
    PersistenceBackend,
    deserialize_action_result,
    deserialize_action_results,
    deserialize_messages,
    deserialize_node,
    serialize_action_result,
    serialize_action_results,
    serialize_messages,
    serialize_node,
)
from ghrah.context.rebase import create_rebased_context
from ghrah.context.session import Session
from ghrah.context.state import StateManager
from ghrah.context.strategies.llm_summary import LLMSummaryStrategy
from ghrah.context.strategies.sliding_window import SlidingWindowStrategy
from ghrah.context.strategies.tool_call_fold import ToolCallFoldStrategy
from ghrah.context.strategies.truncation import TruncationStrategy
from ghrah.context.window import (
    WindowManager,
    WindowStrategy,
    estimate_message_tokens,
    estimate_tokens,
)

__all__ = [
    "ContextNode",
    "ActionChain",
    "MessageStore",
    "StateManager",
    "ContextManager",
    "Session",
    "create_rebased_context",
    "WindowStrategy",
    "WindowManager",
    "estimate_tokens",
    "estimate_message_tokens",
    "TruncationStrategy",
    "SlidingWindowStrategy",
    "ToolCallFoldStrategy",
    "LLMSummaryStrategy",
    "PersistenceBackend",
    "InMemoryBackend",
    "JsonFileBackend",
    "serialize_node",
    "deserialize_node",
    "serialize_action_result",
    "deserialize_action_result",
    "serialize_action_results",
    "deserialize_action_results",
    "serialize_messages",
    "deserialize_messages",
]
