# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""BroadcastMessageAbility：向集群中所有 Agent 广播消息。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from ghrah.abilities.base import Ability, ActionOutcome, ActionResult
from ghrah.abilities.builtin._cluster_common import _NO_SUPERVISOR_ERROR

if TYPE_CHECKING:
    from ghrah.abilities.context import AbilityExecutionContext
    from ghrah.abilities.hooks import Hook


class BroadcastMessageInput(BaseModel):
    model_config = {"extra": "forbid"}

    content: str = Field(
        min_length=1,
        description="Message content to broadcast to all agents",
    )


class BroadcastMessageAbility(Ability):
    """向集群中所有 Agent 广播消息。

    通过 SupervisorActor.broadcast() 向所有已注册 Agent
    发送消息（排除自身），收集所有回复。
    """

    @property
    def name(self) -> str:
        return "broadcast_message"

    def bind_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "broadcast_message",
                "description": (
                    "Broadcast a message to all agents in the cluster "
                    "(excluding the sender) and collect their responses. "
                    "Use this for cluster-wide announcements or queries."
                ),
                "parameters": BroadcastMessageInput.model_json_schema(),
            },
        }

    def to_prompt_description(self) -> str:
        return (
            "broadcast_message(content: str) -> dict: "
            "Broadcast a message to all agents and collect their responses"
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
        content = tool_args.get("content", "")

        if not content:
            return ActionResult(
                outcome=ActionOutcome.FAILURE,
                data={"error": "content is required"},
            )

        sender = context.agent_name or "unknown"

        try:
            responses = await context.supervisor.broadcast(
                content=content,
                sender=sender,
            )
            return ActionResult(
                outcome=ActionOutcome.SUCCESS,
                data={"responses": responses, "agent_count": len(responses)},
            )
        except Exception as e:
            return ActionResult(
                outcome=ActionOutcome.FAILURE,
                data={"error": f"Failed to broadcast message: {e}"},
            )
