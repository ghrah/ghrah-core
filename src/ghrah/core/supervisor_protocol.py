# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""Supervisor 协议定义 — core 层仅依赖此协议。

通过 Protocol（structural subtyping）定义 Supervisor 的接口契约，
使 abilities 层的 AbilityExecutionContext 可以仅依赖此协议
而非 communication.supervisor.SupervisorActor 的具体实现。
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

__all__ = ["SupervisorProtocol"]


@runtime_checkable
class SupervisorProtocol(Protocol):
    """Supervisor 最小接口协议 — Ability 执行上下文仅依赖此协议。

    定义 builtin cluster abilities 所需的 Supervisor 方法。
    方法签名中使用 Any 替代具体类型（如 AgentConfig、AbilityProtocol），
    避免 protocol 层反向依赖 communication 或 types。
    """

    async def list_agents(self) -> list[dict[str, Any]]: ...

    async def terminate_agent(self, name: str) -> None: ...

    async def spawn_agent(
        self, config: Any, abilities: list[Any] | None = None
    ) -> str: ...

    async def send(
        self,
        target: str,
        content: str,
        sender: str = "user",
        **kwargs: Any,
    ) -> str: ...

    async def broadcast(
        self,
        content: str,
        sender: str = "user",
        **kwargs: Any,
    ) -> list[dict[str, str]]: ...

    async def get_agent_handle(self, name: str) -> Any: ...
