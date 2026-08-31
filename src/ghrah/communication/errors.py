# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""通信领域异常 — Agent 注册/发现和路由相关。"""

from __future__ import annotations

from ghrah.core._base_error import ActorAgentError

__all__ = ["RegistryError", "AgentNotFoundError"]


class RegistryError(ActorAgentError):
    """Agent 注册/发现相关错误"""

    pass


class AgentNotFoundError(RegistryError):
    """Agent 未在注册中心找到"""

    def __init__(self, agent_name: str):
        self.agent_name = agent_name
        super().__init__(f"Agent not found: {agent_name}")
