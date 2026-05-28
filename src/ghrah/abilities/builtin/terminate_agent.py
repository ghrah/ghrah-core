# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""TerminateAgentAbility：终止集群中的一个 Agent。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from ghrah.abilities.base import Ability, ActionOutcome, ActionResult
from ghrah.abilities.builtin._cluster_common import _NO_SUPERVISOR_ERROR

if TYPE_CHECKING:
    from ghrah.abilities.context import AbilityExecutionContext
    from ghrah.abilities.hooks import Hook


class TerminateAgentInput(BaseModel):
    model_config = {"extra": "forbid"}

    agent_name: str = Field(
        min_length=1,
        description="Name of the agent to terminate",
    )


class TerminateAgentAbility(Ability):
    """终止集群中的一个 Agent。

    通过 SupervisorActor.terminate_agent() 从集群中移除指定 Agent。
    Agent 被终止后将无法再接收消息。仅在确定 Agent 不再需要时使用。
    """

    @property
    def name(self) -> str:
        return "terminate_agent"

    def bind_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "terminate_agent",
                "description": (
                    "Terminate an agent in the cluster. "
                    "The agent will be removed and cannot receive further messages. "
                    "Only use this when you are certain the agent is no longer needed. "
                    "Persistent agents can receive follow-up messages without re-initialization."
                ),
                "parameters": TerminateAgentInput.model_json_schema(),
            },
        }

    def to_prompt_description(self) -> str:
        return (
            "terminate_agent(agent_name: str) -> dict: "
            "Terminate an agent in the cluster"
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
        agent_name = tool_args.get("agent_name", "")

        if not agent_name:
            return ActionResult(
                outcome=ActionOutcome.FAILURE,
                data={"error": "agent_name is required"},
            )

        try:
            await context.supervisor.terminate_agent(agent_name)
            return ActionResult(
                outcome=ActionOutcome.SUCCESS,
                data={"agent_name": agent_name, "status": "terminated"},
            )
        except Exception as e:
            return ActionResult(
                outcome=ActionOutcome.FAILURE,
                data={"error": f"Failed to terminate agent '{agent_name}': {e}"},
            )
