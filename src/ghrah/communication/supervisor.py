# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""Supervisor Actor：Agent 生命周期管理和消息路由入口。

SupervisorActor 是整个多 Agent 系统的中心编排者：
- 持有 AgentRegistry 和 MessageRouter
- 管理 Agent 的创建和销毁
- 提供消息路由和广播的入口
- 支持显式 Ability 注册，默认注册基础 Ability 组合
- 支持 Session 管理（创建、切换、列表、归档、删除）
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from ghrah.abilities.base import Ability
from ghrah.abilities.builtin.conversation import ConversationAbility
from ghrah.abilities.builtin.end_task import EndTaskAbility
from ghrah.agents.base import ActorAgent
from ghrah.communication.registry import AgentRegistry
from ghrah.communication.router import MessageRouter
from ghrah.core.config import AgentConfig
from ghrah.core.exceptions import (
    AgentNotFoundError,
    RegistryError,
)
from ghrah.core.message import Message, MessageType

if TYPE_CHECKING:
    from ghrah.core.command_sender import CommandSender
    from ghrah.core.server.event_bus import EventBus

logger = logging.getLogger(__name__)


class SupervisorActor:
    """监控和管理所有 Agent 的生命周期。

    作为多 Agent 系统的中心入口，负责：
    - Agent 的创建（spawn）和销毁（terminate）
    - 消息路由委托
    - 广播消息
    - 健康检查

    用法:
        # 创建 Supervisor
        supervisor = SupervisorActor()

        # 注册 Agent
        config = AgentConfig(name="planner", description="任务规划")
        await supervisor.spawn_agent(config)

        # 发送消息
        response = await supervisor.send("planner", "设计一个方案")

        # 广播
        responses = await supervisor.broadcast("大家好")
    """

    def __init__(
        self,
        command_sender: CommandSender | None = None,
        event_bus: EventBus | None = None,
        default_timeout: float = 300.0,
    ) -> None:
        self._command_sender = command_sender
        self._event_bus = event_bus
        self._registry = AgentRegistry()
        self._router = MessageRouter(self._registry, default_timeout=default_timeout)
        logger.info(
            f"SupervisorActor initialized"
            f"{' with command_sender' if command_sender else ''}"
            f"{' with event_bus' if event_bus else ''}"
            f" default_timeout={default_timeout}"
        )

    async def spawn_agent(
        self,
        config: AgentConfig,
        abilities: list[Ability] | None = None,
    ) -> str:
        """创建并注册一个 Agent，返回 agent name。

        创建 Agent 实例并注入自身引用，使 Agent 可以通过
        Supervisor 与其他 Agent 通信。

        Ability 注册策略：
        1. 如果传入 abilities 参数，使用用户指定的 Ability 列表
        2. 否则注册默认的基础 Ability 组合（ConversationAbility + EndTaskAbility）

        Args:
            config: Agent 配置
            abilities: 可选的自定义 Ability 列表。
                       None 表示注册默认基础 Ability。

        Returns:
            Agent 名称

        Raises:
            RegistryError: 如果同名 Agent 已注册
        """
        if self._registry.exists(config.name):
            raise RegistryError(f"Agent already registered: {config.name}")

        if self._command_sender is not None and config.context is not None:
            config.context.set_command_sender(self._command_sender, agent_name=config.name)

        supervisor_handle = self

        # 创建 ActorAgent 并注入 Supervisor 引用
        actor_handle = ActorAgent(config, supervisor_handle)

        # 注册 Ability
        if abilities is not None:
            # 用户指定了 Ability 列表
            for ability in abilities:
                actor_handle.register_ability(ability)
            logger.info(
                "Supervisor registered %d user-provided abilities for agent: %s — abilities=%s",
                len(abilities),
                config.name,
                [a.name for a in abilities],
            )
        else:
            # 注册默认基础 Ability 组合
            default_abilities: list[Ability] = [ConversationAbility(), EndTaskAbility()]
            for ability in default_abilities:
                actor_handle.register_ability(ability)
            logger.info(
                "Supervisor auto-registered %d default abilities for agent: %s — abilities=%s",
                len(default_abilities),
                config.name,
                [a.name for a in default_abilities],
            )

        self._registry.register(
            name=config.name,
            config=config,
            actor_handle=actor_handle,
        )

        if self._command_sender is not None or self._event_bus is not None:
            actor_handle.inject_command_sender(self._command_sender, self._event_bus)

        logger.info(f"Supervisor spawned agent: {config.name}")
        return config.name

    async def terminate_agent(self, name: str) -> None:
        """注销并终止 Agent。

        从注册中心移除 Agent。

        Args:
            name: Agent 名称

        Raises:
            AgentNotFoundError: 如果 Agent 未注册
        """
        self._registry.get_info(name)

        self._registry.unregister(name)

        logger.info(f"Supervisor terminated agent: {name}")

    async def list_agents(self) -> list[dict[str, Any]]:
        """列出所有活跃 Agent 信息。

        Returns:
            Agent 信息字典列表
        """
        agents = self._registry.list_agents()
        return [info.to_dict() for info in agents]

    async def route_message(self, message: Message, timeout: float | None = None) -> Message:
        """路由消息到目标 Agent。

        超时优先级：
        1. 显式传入的 timeout 参数
        2. 目标 Agent 配置的 communication_timeout
        3. Supervisor 的 default_timeout

        Args:
            message: 要路由的消息
            timeout: 超时时间（秒），None 使用目标 Agent 配置或默认值，-1 表示无限等待

        Returns:
            目标 Agent 的回复
        """
        effective_timeout = self._resolve_timeout(message.recipient, timeout)
        return await self._router.route(message, timeout=effective_timeout)

    def _resolve_timeout(self, target: str, timeout: float | None) -> float:
        """解析有效的通信超时时间。

        超时优先级：
        1. 显式传入的 timeout 参数（非 None 时直接使用）
        2. 目标 Agent 配置的 communication_timeout
        3. Router 的 default_timeout

        Args:
            target: 目标 Agent 名称
            timeout: 显式传入的超时参数，None 表示使用 Agent 配置或默认值

        Returns:
            有效的超时时间（秒），-1 表示无限等待
        """
        if timeout is not None:
            return timeout
        try:
            info = self._registry.get_info(target)
            return info.config.communication_timeout
        except AgentNotFoundError:
            return self._router._default_timeout

    async def send(
        self,
        target: str,
        content: str,
        sender: str = "user",
        msg_type: MessageType = MessageType.CHAT,
        timeout: float | None = None,
    ) -> str:
        """发送消息到指定 Agent，返回回复内容。

        超时优先级：
        1. 显式传入的 timeout 参数
        2. 目标 Agent 配置的 communication_timeout
        3. Supervisor 的 default_timeout

        Args:
            target: 目标 Agent 名称
            content: 消息内容
            sender: 发送者标识
            msg_type: 消息类型
            timeout: 超时时间（秒），None 使用目标 Agent 配置或默认值，-1 表示无限等待

        Returns:
            回复文本内容
        """
        effective_timeout = self._resolve_timeout(target, timeout)
        response = await self._router.send_and_wait(
            target=target,
            content=content,
            sender=sender,
            msg_type=msg_type,
            timeout=effective_timeout,
        )
        return response.content

    async def broadcast(
        self,
        content: str,
        sender: str = "user",
        msg_type: MessageType = MessageType.BROADCAST,
    ) -> list[str]:
        """广播消息到所有 Agent。

        Args:
            content: 消息内容
            sender: 发送者标识
            msg_type: 消息类型

        Returns:
            所有 Agent 回复内容列表
        """
        message = Message(
            sender=sender,
            recipient="*",
            content=content,
            type=msg_type,
        )
        responses = await self._router.broadcast(message)
        return [r.content for r in responses]

    async def delegate(self, from_agent: str, to_agent: str, content: str, timeout: float | None = None) -> str:
        """Agent 间委托：从一个 Agent 委托任务到另一个 Agent。

        超时优先级：
        1. 显式传入的 timeout 参数
        2. 目标 Agent 配置的 communication_timeout
        3. Supervisor 的 default_timeout

        Args:
            from_agent: 委托方 Agent 名称
            to_agent: 被委托方 Agent 名称
            content: 委托内容
            timeout: 超时时间（秒），None 使用目标 Agent 配置或默认值，-1 表示无限等待

        Returns:
            被委托方的回复内容

        Raises:
            AgentNotFoundError: 任一 Agent 未注册
        """
        if not self._registry.exists(from_agent):
            raise AgentNotFoundError(from_agent)
        if not self._registry.exists(to_agent):
            raise AgentNotFoundError(to_agent)

        message = Message(
            sender=from_agent,
            recipient=to_agent,
            content=content,
            type=MessageType.COMMAND,
        )
        effective_timeout = self._resolve_timeout(to_agent, timeout)
        response = await self._router.route(message, timeout=effective_timeout)
        return response.content

    async def register_ability_for_agent(
        self,
        agent_name: str,
        ability_type: str,
        ability_params: dict[str, Any] | None = None,
    ) -> str:
        """为指定 Agent 注册 Ability（通过 AbilityRegistry 动态创建）。

        通过类型名从 AbilityRegistry 查找 Ability 类并实例化，
        然后注册到目标 Agent。然后注册到目标 Agent。这使得外部调用方不再需要直接实例化 Ability，
        而是通过 Supervisor 在 Core 侧完成。

        Args:
            agent_name: Agent 名称
            ability_type: Ability 类型名（在 AbilityRegistry 中注册的）
            ability_params: Ability 构造参数

        Returns:
            注册的 Ability 名称

        Raises:
            AgentNotFoundError: Agent 未注册
            KeyError: Ability 类型未注册
        """
        from ghrah.abilities.registry import AbilityRegistry

        info = self._registry.get_info(agent_name)
        params = ability_params or {}

        # 通过 AbilityRegistry 创建实例
        ability = AbilityRegistry.create(ability_type, **params)

        # 注册到 Agent
        result = info.actor_handle.register_ability(ability)
        logger.info(
            f"Supervisor registered ability '{ability_type}' for agent '{agent_name}' via registry"
        )
        return result

    async def get_agent_handle(self, agent_name: str) -> Any:
        """获取 Agent 的 actor handle。

        供 Core Server 使用，用于直接调用 Agent 方法
        （如 receive_hitl_response）。

        Args:
            agent_name: Agent 名称

        Returns:
            Agent 实例引用

        Raises:
            AgentNotFoundError: Agent 未注册
        """
        info = self._registry.get_info(agent_name)
        return info.actor_handle

    async def create_session(
        self,
        agent_name: str,
        session_name: str | None = None,
        from_node_id: str | None = None,
        system_prompt: str | None = None,
        session_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """为指定 Agent 创建新 session。

        Args:
            agent_name: Agent 名称
            session_name: 可选的 session 名称
            from_node_id: 可选的 fork 起始节点 ID
            system_prompt: 可选的系统提示词
            session_metadata: 可选的元数据

        Returns:
            新 session 信息字典

        Raises:
            AgentNotFoundError: Agent 未注册
        """
        handle = await self.get_agent_handle(agent_name)
        session = await handle.create_session(
            from_node_id=from_node_id,
            system_prompt=system_prompt,
            session_name=session_name,
            session_metadata=session_metadata,
        )
        return {
            "session_id": session.session_id,
            "agent_name": session.agent_name,
            "branch_name": session.branch_name,
            "parent_session_id": session.parent_session_id,
            "fork_point_node_id": session.parent_node_id,
            "created_at": session.created_at.isoformat() if session.created_at else "",
        }

    async def switch_session(self, agent_name: str, session_id: str) -> dict[str, Any]:
        """切换指定 Agent 的活跃 session。

        Args:
            agent_name: Agent 名称
            session_id: 要切换到的 session ID

        Returns:
            切换后的 session 信息字典

        Raises:
            AgentNotFoundError: Agent 未注册
        """
        handle = await self.get_agent_handle(agent_name)
        await handle.switch_session(session_id)
        sessions = handle.list_sessions()
        for s in sessions:
            if s["session_id"] == session_id:
                return s
        return {"session_id": session_id, "agent_name": agent_name}

    async def list_sessions(self, agent_name: str) -> list[dict[str, Any]]:
        """列出指定 Agent 的所有 session。

        Args:
            agent_name: Agent 名称

        Returns:
            session 信息字典列表

        Raises:
            AgentNotFoundError: Agent 未注册
        """
        handle = await self.get_agent_handle(agent_name)
        return handle.list_sessions()

    async def archive_session(self, agent_name: str, session_id: str) -> None:
        """归档指定 Agent 的 session。

        Args:
            agent_name: Agent 名称
            session_id: 要归档的 session ID

        Raises:
            AgentNotFoundError: Agent 未注册
        """
        handle = await self.get_agent_handle(agent_name)
        await handle.archive_session(session_id)

    async def delete_session(self, agent_name: str, session_id: str) -> None:
        """删除指定 Agent 的 session。不能删除当前活跃的 session。

        Args:
            agent_name: Agent 名称
            session_id: 要删除的 session ID

        Raises:
            AgentNotFoundError: Agent 未注册
        """
        handle = await self.get_agent_handle(agent_name)
        await handle.delete_session(session_id)

    async def health_check(self) -> dict[str, bool]:
        """检查所有 Agent 的健康状态。

        通过调用每个 Agent 的 get_state 方法验证其可用性。

        Returns:
            {agent_name: is_healthy} 映射
        """
        results: dict[str, bool] = {}
        agents = self._registry.list_agents()

        for info in agents:
            try:
                # 尝试调用 Agent 的 get_state 方法验证其可用性
                info.actor_handle.get_state()
                results[info.name] = True
            except Exception as e:
                logger.warning(f"Health check failed for {info.name}: {e}")
                results[info.name] = False

        return results
