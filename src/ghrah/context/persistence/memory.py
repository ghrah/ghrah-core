# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""InMemoryBackend：纯内存持久化后端。

数据存储在进程内存中，进程退出即丢失。
适用于测试和不需要持久化的场景。
"""

from __future__ import annotations

import copy
from typing import Any

from ghrah.context.node import ContextNode
from ghrah.context.persistence.backend import PersistenceBackend
from ghrah.context.session import Session

__all__ = ["InMemoryBackend"]


class InMemoryBackend(PersistenceBackend):
    """纯内存后端 — 零依赖默认选项。

    数据存储在进程内存中，进程退出即丢失。
    适用于测试和不需要持久化的场景。

    内部结构：
    - _nodes: dict[str, ContextNode] — node_id → node 全局索引
    - _agent_nodes: dict[str, list[str]] — agent_name → node_id 列表（按追加顺序）
    - _chain_meta: dict[str, dict] — agent_name → {branches, active_session_id, current_state}
    - _messages: dict[str, list[Any]] — agent_name → ChatMessage 列表
    - _sessions: dict[str, Session] — session_id → Session
    - _agent_sessions: dict[str, list[str]] — agent_name → session_id 列表
    """

    def __init__(self) -> None:
        self._nodes: dict[str, ContextNode] = {}
        self._agent_nodes: dict[str, list[str]] = {}
        self._chain_meta: dict[str, dict[str, Any]] = {}
        self._messages: dict[str, list[Any]] = {}
        self._sessions: dict[str, Session] = {}
        self._agent_sessions: dict[str, list[str]] = {}

    async def save_node(self, node: ContextNode) -> None:
        """保存节点到内存。同时更新 agent_nodes 索引。"""
        self._nodes[node.id] = node
        if node.agent_name not in self._agent_nodes:
            self._agent_nodes[node.agent_name] = []
        # 避免重复追加（同节点 ID）
        node_ids = self._agent_nodes[node.agent_name]
        if node.id not in node_ids:
            node_ids.append(node.id)

    async def load_node(self, node_id: str) -> ContextNode | None:
        """从内存加载节点。"""
        return self._nodes.get(node_id)

    async def load_chain(self, agent_name: str) -> list[ContextNode]:
        """加载指定 agent 的所有节点，按 iteration 升序排列。"""
        node_ids = self._agent_nodes.get(agent_name, [])
        nodes = [self._nodes[nid] for nid in node_ids if nid in self._nodes]
        nodes.sort(key=lambda n: n.iteration)
        return nodes

    async def save_chain_meta(
        self,
        agent_name: str,
        branches: dict[str, str],
        current_state: dict[str, Any],
        active_session_id: str = "",
    ) -> None:
        """保存链元信息到内存。"""
        self._chain_meta[agent_name] = {
            "branches": dict(branches),
            "active_session_id": active_session_id,
            "current_state": copy.deepcopy(current_state),
        }

    async def load_chain_meta(
        self, agent_name: str
    ) -> tuple[dict[str, str], str, dict[str, Any]] | None:
        """从内存加载链元信息。"""
        meta = self._chain_meta.get(agent_name)
        if meta is None:
            return None
        return (
            dict(meta["branches"]),
            meta.get("active_session_id", ""),
            copy.deepcopy(meta["current_state"]),
        )

    async def save_messages(self, agent_name: str, messages: list[Any]) -> None:
        """保存消息列表到内存（深拷贝）。"""
        self._messages[agent_name] = copy.deepcopy(messages)

    async def load_messages(self, agent_name: str) -> list[Any]:
        """从内存加载消息列表。"""
        msgs = self._messages.get(agent_name, [])
        return copy.deepcopy(msgs)

    async def delete_chain(self, agent_name: str) -> None:
        """删除指定 agent 的所有数据。"""
        # 删除节点
        node_ids = self._agent_nodes.pop(agent_name, [])
        for nid in node_ids:
            self._nodes.pop(nid, None)
        # 删除元信息和消息
        self._chain_meta.pop(agent_name, None)
        self._messages.pop(agent_name, None)
        # 删除 session
        session_ids = self._agent_sessions.pop(agent_name, [])
        for sid in session_ids:
            self._sessions.pop(sid, None)

    async def list_agents(self) -> list[str]:
        """列出所有有数据的 agent。"""
        all_agents: set[str] = set()
        all_agents.update(self._agent_nodes.keys())
        all_agents.update(self._chain_meta.keys())
        all_agents.update(self._messages.keys())
        all_agents.update(self._agent_sessions.keys())
        return sorted(all_agents)

    # ----------------------------------------------------------------
    # Session 管理
    # ----------------------------------------------------------------

    async def save_session(self, session: Session) -> None:
        """保存或更新 session 到内存。"""
        self._sessions[session.session_id] = session
        if session.agent_name not in self._agent_sessions:
            self._agent_sessions[session.agent_name] = []
        session_ids = self._agent_sessions[session.agent_name]
        if session.session_id not in session_ids:
            session_ids.append(session.session_id)

    async def load_session(self, session_id: str) -> Session | None:
        """从内存加载 session。"""
        return self._sessions.get(session_id)

    async def list_sessions(self, agent_name: str) -> list[Session]:
        """从内存列出 agent 的所有 session。"""
        session_ids = self._agent_sessions.get(agent_name, [])
        sessions = [self._sessions[sid] for sid in session_ids if sid in self._sessions]
        return sessions

    async def delete_sessions(self, agent_name: str) -> None:
        """删除 agent 的所有 session 数据。"""
        session_ids = self._agent_sessions.pop(agent_name, [])
        for sid in session_ids:
            self._sessions.pop(sid, None)
