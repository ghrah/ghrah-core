# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""ContextNode：链式上下文的不可变节点。

每个节点记录一次迭代（可能包含多个并行 ability 执行）后的状态快照。
节点一旦创建即不可修改（frozen=True），类似 Git commit。

设计要点：
- frozen=True 保证不可变性
- agent_state / metadata / action_results 在 __post_init__ 中 deep copy 确保隔离
- messages_delta 存 ChatMessage（增量），messages_snapshot 存完整快照
- ability_names 和 action_results 为列表，支持单次迭代多工具并行执行
"""

from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

__all__ = ["ContextNode"]


@dataclass(frozen=True)
class ContextNode:
    """链式上下文节点 — 记录一次迭代后的不可变快照。

    Attributes:
        id: 唯一标识（UUID4 hex[:12]）
        parent_id: 父节点 ID，根节点为 None
        agent_name: 所属 Agent 名称
        timestamp: 创建时间（UTC）
        iteration: 迭代序号（从 0 开始）
        ability_names: 本轮执行的 ability 名称列表（支持多工具并行）
        agent_state: 此刻的 Agent 状态快照（deep copy，与其他节点隔离）
        messages_delta: 本轮新增的 ChatMessage 列表
        messages_snapshot: 完整消息快照，仅在快照节点非 None
        is_snapshot: 是否为快照节点
        action_results: 本轮执行结果列表，每项为 dict 包含 ability_name 和 action_result
        metadata: 扩展信息（回滚标记、分支信息等）
        branch_name: 所属分支名
        session_id: 所属 session 的 ID，空字符串表示根节点或向后兼容
    """

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    parent_id: str | None = None
    agent_name: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    iteration: int = 0
    ability_names: list[str] = field(default_factory=list)
    agent_state: dict[str, Any] = field(default_factory=dict)
    messages_delta: list[Any] = field(default_factory=list)
    messages_snapshot: list[Any] | None = None
    is_snapshot: bool = False
    action_results: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    branch_name: str = "main"
    session_id: str = ""

    def __post_init__(self) -> None:
        """确保可变字段在 frozen dataclass 中被隔离（deep copy）。"""
        # frozen dataclass 中不能直接赋值，需要通过 object.__setattr__
        if self.agent_state:
            object.__setattr__(self, "agent_state", copy.deepcopy(self.agent_state))
        if self.messages_delta:
            object.__setattr__(self, "messages_delta", list(self.messages_delta))
        if self.messages_snapshot is not None:
            object.__setattr__(self, "messages_snapshot", list(self.messages_snapshot))
        if self.metadata:
            object.__setattr__(self, "metadata", copy.deepcopy(self.metadata))
        if self.ability_names:
            object.__setattr__(self, "ability_names", list(self.ability_names))
        if self.action_results:
            object.__setattr__(self, "action_results", copy.deepcopy(self.action_results))

    @classmethod
    def create_root(
        cls,
        agent_name: str,
        agent_state: dict[str, Any] | None = None,
        messages: list[Any] | None = None,
    ) -> ContextNode:
        """创建根节点（parent_id=None, iteration=0, ability_names=['init']）。

        根节点总是快照节点（is_snapshot=True, messages_snapshot 存完整初始消息）。

        Args:
            agent_name: 所属 Agent 名称
            agent_state: 初始 Agent 状态
            messages: 初始完整消息列表

        Returns:
            根节点
        """
        return cls(
            parent_id=None,
            agent_name=agent_name,
            iteration=0,
            ability_names=["init"],
            agent_state=agent_state or {},
            messages_snapshot=messages or [],
            is_snapshot=True,
        )
