# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""远程持久化后端：通过 CommandSender 将持久化命令发送到 Subject。

RemoteBackend 是 PersistenceBackend 的远程实现，所有持久化操作
通过 CommandSender（由 MessageRouter 实现）发送到 Subject 的
SubjectPersistenceService 执行。

在新架构中，Core 是服务器，通过 MessageRouter 与 Subject 通信，
不再需要 WebSocket 客户端。

设计原则：
- Core 不碰 I/O：所有持久化操作委托给 Subject
- 显式优先于隐式：每个方法明确发送对应的命令类型
- 组合优先于继承：通过 CommandSender 组合通信能力

命令协议：
- save_node → persist_save_node
- load_node → persist_load_node
- load_chain → persist_load_chain
- save_chain_meta → persist_save_chain_meta
- load_chain_meta → persist_load_chain_meta
- save_messages → persist_save_messages
- load_messages → persist_load_messages
- delete_chain → persist_delete_chain
- list_agents → persist_list_agents
- save_session → persist_save_session
- load_session → persist_load_session
- list_sessions → persist_list_sessions
- delete_sessions → persist_delete_sessions
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from ghrah.context.node import ContextNode
from ghrah.context.persistence.backend import PersistenceBackend
from ghrah.context.persistence.serialization import deserialize_node, serialize_node
from ghrah.context.session import Session

if TYPE_CHECKING:
    from ghrah.core.command_sender import CommandSender

logger = logging.getLogger(__name__)

__all__ = ["RemoteBackend"]


class RemoteBackend(PersistenceBackend):
    """远程持久化后端 — 通过 CommandSender 将持久化操作委托给 Subject。

    所有 PersistenceBackend 接口方法通过 CommandSender 发送命令到 Subject。

    Core 是服务器，通过 MessageRouter（实现 CommandSender 协议）与 Subject 通信。

    用法::

        # 在 Core 服务器启动时注入 MessageRouter
        command_sender = router  # MessageRouter 实例
        backend = RemoteBackend(command_sender=command_sender, agent_name="my-agent")

        # 通过 ContextConfig 创建
        config = ContextConfig(persistence_type="remote")
        config.set_command_sender(command_sender, agent_name="my-agent")
        backend = config.create_persistence()
    """

    def __init__(
        self,
        command_sender: CommandSender,
        agent_name: str = "",
        request_timeout: float = 30.0,
    ) -> None:
        self._command_sender = command_sender
        self._agent_name = agent_name
        self._request_timeout = request_timeout

    def _validate_response(self, result: dict[str, Any], operation: str) -> None:
        if not result.get("success", False):
            error_msg = result.get("error", result.get("message", "unknown error"))
            raise RuntimeError(f"Remote persistence '{operation}' failed: {error_msg}")

    async def save_node(self, node: ContextNode) -> None:
        serialized = serialize_node(node)
        result = await self._command_sender.send_command(
            "persist_save_node",
            {"agent_name": self._agent_name, "node": serialized},
            timeout=self._request_timeout,
        )
        self._validate_response(result, "save_node")
        logger.debug(f"Saved node {node.id} to remote backend")

    async def load_node(self, node_id: str) -> ContextNode | None:
        result = await self._command_sender.send_command(
            "persist_load_node",
            {"agent_name": self._agent_name, "node_id": node_id},
            timeout=self._request_timeout,
        )
        self._validate_response(result, "load_node")

        node_data = result.get("data", {}).get("node")
        if node_data is None:
            return None

        return deserialize_node(node_data)

    async def load_chain(self, agent_name: str) -> list[ContextNode]:
        result = await self._command_sender.send_command(
            "persist_load_chain",
            {"agent_name": agent_name},
            timeout=self._request_timeout,
        )
        self._validate_response(result, "load_chain")

        nodes_data = result.get("data", {}).get("nodes", [])
        return [deserialize_node(n) for n in nodes_data]

    async def save_chain_meta(
        self,
        agent_name: str,
        branches: dict[str, str],
        current_state: dict[str, Any],
        active_session_id: str = "",
    ) -> None:
        result = await self._command_sender.send_command(
            "persist_save_chain_meta",
            {
                "agent_name": agent_name,
                "branches": branches,
                "current_state": current_state,
                "active_session_id": active_session_id,
            },
            timeout=self._request_timeout,
        )
        self._validate_response(result, "save_chain_meta")
        logger.debug(f"Saved chain meta for agent {agent_name} to remote backend")

    async def load_chain_meta(
        self, agent_name: str
    ) -> tuple[dict[str, str], str, dict[str, Any]] | None:
        result = await self._command_sender.send_command(
            "persist_load_chain_meta",
            {"agent_name": agent_name},
            timeout=self._request_timeout,
        )
        self._validate_response(result, "load_chain_meta")

        data = result.get("data")
        if data is None:
            return None

        return (
            data.get("branches", {}),
            data.get("active_session_id", ""),
            data.get("current_state", {}),
        )

    async def save_messages(self, agent_name: str, messages: list[Any]) -> None:
        from ghrah.context.persistence.serialization import serialize_messages

        serialized = serialize_messages(messages)
        result = await self._command_sender.send_command(
            "persist_save_messages",
            {
                "agent_name": agent_name,
                "messages": serialized,
            },
            timeout=self._request_timeout,
        )
        self._validate_response(result, "save_messages")
        logger.debug(f"Saved messages for agent {agent_name} to remote backend")

    async def load_messages(self, agent_name: str) -> list[Any]:
        from ghrah.context.persistence.serialization import deserialize_messages

        result = await self._command_sender.send_command(
            "persist_load_messages",
            {"agent_name": agent_name},
            timeout=self._request_timeout,
        )
        self._validate_response(result, "load_messages")

        messages_data = result.get("data", {}).get("messages", [])
        if not messages_data:
            return []

        return deserialize_messages(messages_data)

    async def delete_chain(self, agent_name: str) -> None:
        result = await self._command_sender.send_command(
            "persist_delete_chain",
            {"agent_name": agent_name},
            timeout=self._request_timeout,
        )
        self._validate_response(result, "delete_chain")
        logger.debug(f"Deleted chain for agent {agent_name} from remote backend")

    async def list_agents(self) -> list[str]:
        result = await self._command_sender.send_command(
            "persist_list_agents",
            {},
            timeout=self._request_timeout,
        )
        self._validate_response(result, "list_agents")

        return result.get("data", {}).get("agents", [])

    async def save_session(self, session: Session) -> None:
        """保存或更新 session 到远程 Subject。"""
        from ghrah.context.persistence.serialization import serialize_session

        serialized = serialize_session(session)
        result = await self._command_sender.send_command(
            "persist_save_session",
            {"session": serialized},
            timeout=self._request_timeout,
        )
        self._validate_response(result, "save_session")
        logger.debug(f"Saved session {session.session_id} to remote backend")

    async def load_session(self, session_id: str) -> Session | None:
        """从远程 Subject 按 ID 加载 session。"""
        from ghrah.context.persistence.serialization import deserialize_session

        result = await self._command_sender.send_command(
            "persist_load_session",
            {"session_id": session_id},
            timeout=self._request_timeout,
        )
        self._validate_response(result, "load_session")

        session_data = result.get("data", {}).get("session")
        if session_data is None:
            return None

        return deserialize_session(session_data)

    async def list_sessions(self, agent_name: str) -> list[Session]:
        """列出远程 Subject 上 Agent 的所有 session。"""
        from ghrah.context.persistence.serialization import deserialize_session

        result = await self._command_sender.send_command(
            "persist_list_sessions",
            {"agent_name": agent_name},
            timeout=self._request_timeout,
        )
        self._validate_response(result, "list_sessions")

        sessions_data = result.get("data", {}).get("sessions", [])
        return [deserialize_session(s) for s in sessions_data]

    async def delete_sessions(self, agent_name: str) -> None:
        """删除远程 Subject 上 Agent 的所有 session 数据。"""
        result = await self._command_sender.send_command(
            "persist_delete_sessions",
            {"agent_name": agent_name},
            timeout=self._request_timeout,
        )
        self._validate_response(result, "delete_sessions")
        logger.debug(f"Deleted sessions for agent {agent_name} from remote backend")
