# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""Agent 注册中心：维护 name → actor handle 的映射。

AgentRegistry 是普通 Python 类，由 SupervisorActor 内部持有，
避免额外的 remote call 开销。
"""

from __future__ import annotations

import dataclasses
import logging
import time
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from ghrah.communication.errors import AgentNotFoundError, RegistryError
from ghrah.types.config_types import AgentConfig

logger = logging.getLogger(__name__)


@dataclass
class AgentInfo:
    """注册的 Agent 信息。

    Attributes:
        name: Agent 唯一名称
        config: Agent 框架层配置
        actor_handle: agent actor 引用
        created_at: 注册时间戳
        incarnation_id: 每次成功注册生成的运行实例 ID。
    """

    name: str
    config: AgentConfig
    actor_handle: Any
    created_at: float = field(default_factory=time.time)
    incarnation_id: str = field(default_factory=lambda: uuid4().hex)

    def to_dict(self) -> dict[str, Any]:
        """转换为可序列化的字典。"""
        return {
            "agent_id": self.config.effective_agent_id,
            "incarnation_id": self.incarnation_id,
            "name": self.name,
            "config": _agent_config_to_dict(self.config) if self.config else None,
            "description": self.config.description,
            "created_at": self.created_at,
        }


def _agent_config_to_dict(config: AgentConfig) -> dict[str, Any]:
    """将 AgentConfig 序列化为 wire 契约 dict（对齐 AgentConfigPayload）。

    显式字段构造保持 wire 契约子集稳定。ContextConfig 为纯数据
    dataclass，可直接用 dataclasses.asdict 序列化。
    """
    return {
        "agent_id": config.effective_agent_id,
        "name": config.name,
        "agent_config_name": config.agent_config_name,
        "description": config.description,
        "system_prompt": config.system_prompt,
        "max_iterations": config.max_iterations,
        "communication_timeout": config.communication_timeout,
        "window": dataclasses.asdict(config.window) if config.window else None,
        "context": dataclasses.asdict(config.context) if config.context else None,
        "model_overrides": (
            dataclasses.asdict(config.model_overrides)
            if config.model_overrides
            else None
        ),
    }


class AgentRegistry:
    """Agent 注册中心。

    维护 Agent 名称到 actor handle 的映射，
    支持 Agent 的注册、注销和发现。

    由 SupervisorActor 内部持有的普通对象。
    """

    def __init__(self) -> None:
        self._agents: dict[str, AgentInfo] = {}
        self._agent_ids: dict[str, str] = {}

    def register(
        self,
        name: str,
        config: AgentConfig,
        actor_handle: Any,
    ) -> None:
        """注册一个 Agent。

        Args:
            name: Agent 唯一名称
            config: Agent 配置
            actor_handle: agent actor 引用

        Raises:
            RegistryError: 如果同名 Agent 已注册
        """
        if name in self._agents:
            raise RegistryError(f"Agent already registered: {name}")
        agent_id = config.effective_agent_id
        if agent_id in self._agent_ids:
            raise RegistryError(f"Agent ID already registered: {agent_id}")

        info = AgentInfo(
            name=name,
            config=config,
            actor_handle=actor_handle,
        )
        self._agents[name] = info
        self._agent_ids[agent_id] = name
        logger.info(f"Agent registered: {name}")

    def unregister(self, name: str) -> None:
        """注销一个 Agent。

        Args:
            name: Agent 名称

        Raises:
            AgentNotFoundError: 如果 Agent 未注册
        """
        if name not in self._agents:
            raise AgentNotFoundError(name)

        info = self._agents.pop(name)
        self._agent_ids.pop(info.config.effective_agent_id, None)
        logger.info(f"Agent unregistered: {name}")

    def get_handle(self, name: str) -> Any:
        """获取 Agent 的 actor handle。

        Args:
            name: Agent 名称

        Returns:
            agent actor 引用

        Raises:
            AgentNotFoundError: 如果 Agent 未注册
        """
        info = self._agents.get(name)
        if info is None:
            raise AgentNotFoundError(name)
        return info.actor_handle

    def get_info(self, name: str) -> AgentInfo:
        """获取 Agent 的完整信息。

        Args:
            name: Agent 名称

        Returns:
            Agent 注册信息

        Raises:
            AgentNotFoundError: 如果 Agent 未注册
        """
        info = self._agents.get(name)
        if info is None:
            raise AgentNotFoundError(name)
        return info

    def get_info_by_id(self, agent_id: str) -> AgentInfo:
        """按稳定 agent_id 获取注册信息。"""
        name = self._agent_ids.get(agent_id)
        if name is None:
            raise AgentNotFoundError(agent_id)
        return self.get_info(name)

    def resolve_name(self, agent_id: str) -> str:
        """把稳定 agent_id 解析为当前 CoreUnit 内的局部名称。"""
        name = self._agent_ids.get(agent_id)
        if name is None:
            raise AgentNotFoundError(agent_id)
        return name

    def list_agents(self) -> list[AgentInfo]:
        """列出所有已注册的 Agent。

        Returns:
            AgentInfo 列表
        """
        return list(self._agents.values())

    def list_names(self) -> list[str]:
        """列出所有已注册的 Agent 名称。

        Returns:
            Agent 名称列表
        """
        return list(self._agents.keys())

    def exists(self, name: str) -> bool:
        """检查 Agent 是否已注册。

        Args:
            name: Agent 名称

        Returns:
            是否已注册
        """
        return name in self._agents

    def __len__(self) -> int:
        return len(self._agents)

    def __contains__(self, name: str) -> bool:
        return self.exists(name)
