# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""AbilityExecutionContext compatibility facade.

The facade keeps the old construction and attribute surface while delegating the
real invocation/data/services fields to the new execution-context structures.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ghrah.abilities.execution_data import ExecutionData
from ghrah.abilities.execution_services import (
    AGENT_NAME,
    CONTEXT_MANAGER,
    SUPERVISOR,
    ExecutionServices,
)
from ghrah.abilities.invocation import AbilityInvocation
from ghrah.core.supervisor_protocol import SupervisorProtocol

if TYPE_CHECKING:
    from ghrah.core.window_protocol import ContextManagerProtocol
    from ghrah.types.results import ActionResult

__all__ = ["AbilityExecutionContext"]


@dataclass(init=False)
class AbilityExecutionContext:
    """Compatibility facade for ability execution context.

    Old attributes such as current_ability_name, tool_args, context_manager, and
    accumulated_data remain available as properties that read/write the new
    invocation/data/services structures.
    """

    invocation: AbilityInvocation = field(default_factory=AbilityInvocation)
    data: ExecutionData = field(default_factory=ExecutionData)
    services: ExecutionServices = field(default_factory=ExecutionServices)
    agent_state: dict[str, Any] = field(default_factory=dict)
    last_action_result: ActionResult | None = None

    def __init__(
        self,
        *,
        invocation: AbilityInvocation | None = None,
        data: ExecutionData | None = None,
        services: ExecutionServices | None = None,
        agent_state: dict[str, Any] | None = None,
        current_ability_name: str = "",
        tool_args: dict[str, Any] | None = None,
        context_manager: ContextManagerProtocol | None = None,
        supervisor: SupervisorProtocol | None = None,
        agent_name: str = "",
        accumulated_data: dict[str, Any] | None = None,
        last_action_result: ActionResult | None = None,
    ) -> None:
        base_invocation = invocation or AbilityInvocation()
        ability_name = current_ability_name or base_invocation.ability_name
        args = tool_args if tool_args is not None else base_invocation.tool_args
        self.invocation = AbilityInvocation(
            ability_name=ability_name,
            tool_args=args,
            tool_call_id=base_invocation.tool_call_id,
        )

        self.data = data or ExecutionData()
        if accumulated_data is not None:
            self.data = ExecutionData(accumulated_data)

        self.services = services or ExecutionServices()
        if context_manager is not None:
            self.services.set(CONTEXT_MANAGER, context_manager)
        if supervisor is not None:
            self.services.set(SUPERVISOR, supervisor)
        if agent_name:
            self.services.set(AGENT_NAME, agent_name)

        self.agent_state = agent_state if agent_state is not None else {}
        self.last_action_result = last_action_result

    @property
    def current_ability_name(self) -> str:
        return self.invocation.ability_name

    @current_ability_name.setter
    def current_ability_name(self, value: str) -> None:
        self.invocation = AbilityInvocation(
            ability_name=value,
            tool_args=self.invocation.tool_args,
            tool_call_id=self.invocation.tool_call_id,
        )

    @property
    def tool_args(self) -> dict[str, Any]:
        return self.invocation.tool_args

    @tool_args.setter
    def tool_args(self, value: dict[str, Any]) -> None:
        self.invocation = AbilityInvocation(
            ability_name=self.invocation.ability_name,
            tool_args=value,
            tool_call_id=self.invocation.tool_call_id,
        )

    @property
    def accumulated_data(self) -> dict[str, Any]:
        return self.data.raw

    @accumulated_data.setter
    def accumulated_data(self, value: dict[str, Any]) -> None:
        self.data = ExecutionData(value)

    @property
    def context_manager(self) -> ContextManagerProtocol | None:
        return self.services.get(CONTEXT_MANAGER)

    @context_manager.setter
    def context_manager(self, value: ContextManagerProtocol | None) -> None:
        self.services.set(CONTEXT_MANAGER, value)

    @property
    def supervisor(self) -> SupervisorProtocol | None:
        return self.services.get(SUPERVISOR)

    @supervisor.setter
    def supervisor(self, value: SupervisorProtocol | None) -> None:
        self.services.set(SUPERVISOR, value)

    @property
    def agent_name(self) -> str:
        return self.services.get(AGENT_NAME, "") or ""

    @agent_name.setter
    def agent_name(self, value: str) -> None:
        self.services.set(AGENT_NAME, value)

    def get_ability_state(self) -> dict[str, Any]:
        """获取当前 ability 作用域的状态（只读快照）。"""

        if not self.current_ability_name:
            return {}
        return copy.deepcopy(self.agent_state.get(self.current_ability_name, {}))

    def update_state(self, changes: dict[str, Any]) -> None:
        """更新当前 ability 作用域的状态。"""

        context_manager = self.services.get(CONTEXT_MANAGER)
        if context_manager is None:
            raise RuntimeError(
                "Cannot update state: context_manager is not set. "
                "This context may have been created outside the drive loop."
            )
        scoped_changes = {self.current_ability_name: changes}
        context_manager.apply_state_changes(scoped_changes)
        if self.current_ability_name in self.agent_state:
            self._merge_dict(self.agent_state[self.current_ability_name], changes)
        else:
            self.agent_state[self.current_ability_name] = copy.deepcopy(changes)

    def update_global_state(self, changes: dict[str, Any]) -> None:
        """更新全局状态（非作用域）。"""

        context_manager = self.services.get(CONTEXT_MANAGER)
        if context_manager is None:
            raise RuntimeError("Cannot update state: context_manager is not set.")
        context_manager.apply_state_changes(changes)
        self._merge_dict(self.agent_state, changes)

    @staticmethod
    def _merge_dict(base: dict, override: dict) -> None:
        """就地递归合并 override 到 base。"""

        for key, value in override.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                AbilityExecutionContext._merge_dict(base[key], value)
            else:
                base[key] = value
