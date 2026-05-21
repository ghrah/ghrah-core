# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""持久化后端抽象基类。

定义 ContextManager 链式数据的统一存储接口。
所有方法为 async，子类可对接文件系统、Redis、数据库等存储后端。

数据组织：
- 节点（ContextNode）：按 agent_name 分组，支持按 ID 或按 agent 加载
- 链元信息：分支映射（branch_name → head_node_id）+ 当前状态 + 活跃 session ID
- 消息列表：当前完整消息（用于快速恢复 MessageStore）
- Session：Agent 内的迭代分支元数据
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ghrah.context.node import ContextNode
from ghrah.context.session import Session

__all__ = ["PersistenceBackend"]


class PersistenceBackend(ABC):
    """持久化后端抽象基类。

    定义 ContextManager 链式数据的统一存储接口。
    所有方法为 async，子类可对接文件系统、Redis、数据库等存储后端。

    数据组织：
    - 节点（ContextNode）：按 agent_name 分组，支持按 ID 或按 agent 加载
    - 链元信息：分支映射 + 活跃 session ID + 当前状态
    - 消息列表：当前完整消息（用于快速恢复 MessageStore）
    - Session：Agent 内的迭代分支元数据
    """

    @abstractmethod
    async def save_node(self, node: ContextNode) -> None:
        """保存单个节点。

        Args:
            node: 要保存的 ContextNode
        """

    @abstractmethod
    async def load_node(self, node_id: str) -> ContextNode | None:
        """加载单个节点。

        Args:
            node_id: 节点 ID

        Returns:
            对应的 ContextNode，不存在则返回 None
        """

    @abstractmethod
    async def load_chain(self, agent_name: str) -> list[ContextNode]:
        """加载指定 agent 的所有节点（按时间/迭代顺序）。

        Args:
            agent_name: Agent 名称

        Returns:
            节点列表（按 iteration 升序排列）
        """

    @abstractmethod
    async def save_chain_meta(
        self,
        agent_name: str,
        branches: dict[str, str],
        current_state: dict[str, Any],
        active_session_id: str = "",
    ) -> None:
        """保存链的元信息：分支映射 + 活跃 session ID + 当前状态。

        Args:
            agent_name: Agent 名称
            branches: 分支名 → head node ID 的映射
            current_state: 当前 Agent 状态快照
            active_session_id: 当前活跃 session 的 ID
        """

    @abstractmethod
    async def load_chain_meta(
        self, agent_name: str
    ) -> tuple[dict[str, str], str, dict[str, Any]] | None:
        """加载链的元信息。

        Args:
            agent_name: Agent 名称

        Returns:
            (branches, active_session_id, current_state) 三元组，
            不存在则返回 None。
        """

    @abstractmethod
    async def save_messages(self, agent_name: str, messages: list[Any]) -> None:
        """保存当前完整消息列表。

        Args:
            agent_name: Agent 名称
            messages: ChatMessage 列表
        """

    @abstractmethod
    async def load_messages(self, agent_name: str) -> list[Any]:
        """加载消息列表。

        Args:
            agent_name: Agent 名称

        Returns:
            ChatMessage 列表，不存在则返回空列表
        """

    @abstractmethod
    async def delete_chain(self, agent_name: str) -> None:
        """删除指定 agent 的所有持久化数据。

        Args:
            agent_name: Agent 名称
        """

    @abstractmethod
    async def list_agents(self) -> list[str]:
        """列出所有有持久化数据的 agent 名称。

        Returns:
            agent 名称列表
        """

    # ----------------------------------------------------------------
    # Session 管理
    # ----------------------------------------------------------------

    @abstractmethod
    async def save_session(self, session: Session) -> None:
        """保存或更新 session。

        Args:
            session: Session 实例
        """

    @abstractmethod
    async def load_session(self, session_id: str) -> Session | None:
        """按 ID 加载 session。

        Args:
            session_id: session ID

        Returns:
            Session 实例，不存在则返回 None
        """

    @abstractmethod
    async def list_sessions(self, agent_name: str) -> list[Session]:
        """列出 Agent 的所有 session。

        Args:
            agent_name: Agent 名称

        Returns:
            Session 列表
        """

    @abstractmethod
    async def delete_sessions(self, agent_name: str) -> None:
        """删除 Agent 的所有 session 数据。

        Args:
            agent_name: Agent 名称
        """
