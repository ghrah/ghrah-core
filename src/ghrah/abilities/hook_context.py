# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""Context object consumed by HookRunner."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ghrah.abilities.execution_frame import ExecutionFrame
from ghrah.abilities.hooks import HookPoint
from ghrah.abilities.invocation import AbilityInvocation

if TYPE_CHECKING:
    from ghrah.abilities.context import AbilityExecutionContext
    from ghrah.types.results import ActionResult

__all__ = ["HookContext"]


@dataclass
class HookContext:
    """Real hook input, adapted to AbilityExecutionContext for legacy hooks."""

    point: HookPoint
    frame: ExecutionFrame = field(default_factory=ExecutionFrame)
    invocation: AbilityInvocation = field(default_factory=AbilityInvocation)
    result: ActionResult | None = None

    @classmethod
    def from_ability_context(
        cls,
        point: HookPoint,
        context: AbilityExecutionContext,
        result: ActionResult | None = None,
    ) -> HookContext:
        """Build a HookContext that shares data/services with the facade."""

        return cls(
            point=point,
            frame=ExecutionFrame(
                data=context.data,
                services=context.services,
                agent_state=context.agent_state,
                last_action_result=context.last_action_result,
            ),
            invocation=context.invocation,
            result=result,
        )

    def to_ability_context(self) -> AbilityExecutionContext:
        """Adapt this hook context to the legacy hook interface."""

        from ghrah.abilities.context import AbilityExecutionContext

        return AbilityExecutionContext(
            invocation=self.invocation,
            data=self.frame.data,
            services=self.frame.services,
            agent_state=self.frame.agent_state,
            last_action_result=self.frame.last_action_result,
        )
