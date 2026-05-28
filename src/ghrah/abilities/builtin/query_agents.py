# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""QueryAgentsAbility：查询集群中已注册的 Agent 信息。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from ghrah.abilities.base import Ability, ActionOutcome, ActionResult
from ghrah.abilities.builtin._cluster_common import _NO_SUPERVISOR_ERROR

if TYPE_CHECKING:
    from ghrah.abilities.context import AbilityExecutionContext
    from ghrah.abilities.hooks import Hook


class QueryAgentsInput(BaseModel):
    model_config = {"extra": "forbid"}

    filter: str | None = Field(
        default=None,
        description="Optional substring to filter agent names",
    )


class QueryAgentsAbility(Ability):
    """查询集群中已注册的 Agent 信息。

    通过 SupervisorActor.list_agents() 获取所有已注册 Agent 的信息，
    支持按名称子串过滤。

    无 Supervisor 时返回 FAILURE。
    """

    @property
    def name(self) -> str:
        return "query_agents"

    def bind_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "query_agents",
                "description": (
                    "Query registered agents in the cluster. "
                    "Returns a list of agent names and descriptions. "
                    "Optionally filter by a substring match on agent name."
                ),
                "parameters": QueryAgentsInput.model_json_schema(),
            },
        }

    def to_prompt_description(self) -> str:
        return (
            "query_agents(filter: str | None = None) -> dict: "
            "Query registered agents in the cluster"
        )

    def get_hooks(self) -> list[Hook]:
        return []

    async def execute(self, context: AbilityExecutionContext) -> ActionResult:
        if context.supervisor is None:
            return ActionResult(
                outcome=ActionOutcome.FAILURE,
                data={"error": _NO_SUPERVISOR_ERROR},
            )

        tool_args = context.tool_args or context.accumulated_data.get("tool_args", {})
        name_filter = tool_args.get("filter")

        try:
            agents = await context.supervisor.list_agents()
        except Exception as e:
            return ActionResult(
                outcome=ActionOutcome.FAILURE,
                data={"error": f"Failed to query agents: {e}"},
            )

        if name_filter:
            name_lower = name_filter.lower()
            agents = [a for a in agents if name_lower in a.get("name", "").lower()]

        return ActionResult(
            outcome=ActionOutcome.SUCCESS,
            data={"agents": agents, "count": len(agents)},
        )
