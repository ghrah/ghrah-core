# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""Agent 注册中心：维护 name → actor handle 的映射。

AgentRegistry 是普通 Python 类，由 SupervisorActor 内部持有，
避免额外的 remote call 开销。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from ghrah.core.config import AgentConfig
from ghrah.core.exceptions import AgentNotFoundError, RegistryError

logger = logging.getLogger(__name__)


@dataclass
class AgentInfo:
    """注册的 Agent 信息。

    Attributes:
        name: Agent 唯一名称
        config: Agent 框架层配置
        actor_handle: agent actor 引用
        created_at: 注册时间戳
    """

    name: str
    config: AgentConfig
    actor_handle: Any
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        """转换为可序列化的字典。"""
        return {
            "name": self.name,
            "description": self.config.description,
            "created_at": self.created_at,
        }


class AgentRegistry:
    """Agent 注册中心。

    维护 Agent 名称到 actor handle 的映射，
    支持 Agent 的注册、注销和发现。

    由 SupervisorActor 内部持有的普通对象。
    """

    def __init__(self) -> None:
        self._agents: dict[str, AgentInfo] = {}

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

        info = AgentInfo(
            name=name,
            config=config,
            actor_handle=actor_handle,
        )
        self._agents[name] = info
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

        del self._agents[name]
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
