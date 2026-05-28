# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""SpawnAgentAbility：动态创建新的平级 Agent。"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from ghrah.abilities.base import Ability, ActionOutcome, ActionResult
from ghrah.abilities.builtin._cluster_common import _NO_SUPERVISOR_ERROR
from ghrah.core.config import AgentConfig

if TYPE_CHECKING:
    from ghrah.abilities.context import AbilityExecutionContext
    from ghrah.abilities.hooks import Hook

logger = logging.getLogger(__name__)


class SpawnAgentInput(BaseModel):
    model_config = {"extra": "forbid"}

    name: str = Field(
        min_length=1,
        description="Unique name for the new agent",
    )
    description: str = Field(
        default="",
        description="Description of the new agent's role",
    )
    system_prompt: str = Field(
        default="",
        description="System prompt for the new agent",
    )
    abilities: list[str] | None = Field(
        default=None,
        description="List of ability type names to register (e.g. ['conversation', 'read_file'])",
    )


class SpawnAgentAbility(Ability):
    """动态创建新的平级 Agent。

    通过 SupervisorActor.spawn_agent() 在集群中创建一个新 Agent。
    新 Agent 与创建者平级，无父子层级关系。

    支持指定 Agent 名称、描述、系统提示词和初始 Ability 列表。
    """

    @property
    def name(self) -> str:
        return "spawn_agent"

    def bind_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "spawn_agent",
                "description": (
                    "Spawn a new peer agent in the cluster. "
                    "The new agent is at the same level as the spawner — "
                    "there is no parent-child hierarchy. "
                    "Specify the agent's name, optional description, "
                    "system prompt, and initial abilities."
                ),
                "parameters": SpawnAgentInput.model_json_schema(),
            },
        }

    def to_prompt_description(self) -> str:
        return (
            "spawn_agent(name: str, description: str = '', "
            "system_prompt: str = '', abilities: list[str] | None = None) -> dict: "
            "Spawn a new peer agent in the cluster"
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
        name = tool_args.get("name", "")
        description = tool_args.get("description", "")
        system_prompt = tool_args.get("system_prompt", "")
        ability_names = tool_args.get("abilities")

        if not name:
            return ActionResult(
                outcome=ActionOutcome.FAILURE,
                data={"error": "name is required"},
            )

        config = AgentConfig(
            name=name,
            description=description,
            system_prompt=system_prompt,
        )

        abilities = None
        if ability_names:
            from ghrah.abilities.registry import AbilityRegistry

            abilities = []
            for ability_type in ability_names:
                try:
                    ability = AbilityRegistry.create(ability_type)
                    abilities.append(ability)
                except KeyError:
                    logger.warning(
                        f"SpawnAgentAbility: unknown ability type '{ability_type}', skipping"
                    )

        try:
            agent_name = await context.supervisor.spawn_agent(config, abilities=abilities)
            return ActionResult(
                outcome=ActionOutcome.SUCCESS,
                data={"agent_name": agent_name, "status": "spawned"},
            )
        except Exception as e:
            return ActionResult(
                outcome=ActionOutcome.FAILURE,
                data={"error": f"Failed to spawn agent '{name}': {e}"},
            )
