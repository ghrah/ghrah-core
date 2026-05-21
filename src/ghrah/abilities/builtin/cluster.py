# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""集群通信 Ability：Agent 发现、消息路由、广播、动态创建。

提供 4 个内建 Ability，使 Agent 能在集群中发现其他 Agent 并与之通信：
- QueryAgentsAbility: 查询集群中已注册的 Agent 信息
- SendMessageAbility: 向指定 Agent 发送消息并等待回复
- BroadcastMessageAbility: 向集群中所有 Agent 广播消息
- SpawnAgentAbility: 动态创建新的平级 Agent

这些 Ability 依赖 SupervisorActor 提供路由和生命周期管理。
通过 AbilityExecutionContext.supervisor 注入 SupervisorActor 引用。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from ghrah.abilities.base import Ability, ActionOutcome, ActionResult
from ghrah.core.config import AgentConfig

if TYPE_CHECKING:
    from ghrah.abilities.context import AbilityExecutionContext
    from ghrah.abilities.hooks import Hook

logger = logging.getLogger(__name__)

__all__ = [
    "QueryAgentsAbility",
    "SendMessageAbility",
    "BroadcastMessageAbility",
    "SpawnAgentAbility",
    "QueryAgentsInput",
    "SendMessageInput",
    "BroadcastMessageInput",
    "SpawnAgentInput",
]


class QueryAgentsInput(BaseModel):
    model_config = {"extra": "forbid"}

    filter: str | None = Field(
        default=None,
        description="Optional substring to filter agent names",
    )


class SendMessageInput(BaseModel):
    model_config = {"extra": "forbid"}

    target: str = Field(
        min_length=1,
        description="Target agent name to send the message to",
    )
    content: str = Field(
        min_length=1,
        description="Message content to send",
    )


class BroadcastMessageInput(BaseModel):
    model_config = {"extra": "forbid"}

    content: str = Field(
        min_length=1,
        description="Message content to broadcast to all agents",
    )


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


_NO_SUPERVISOR_ERROR = (
    "No supervisor configured. "
    "Cluster abilities require a SupervisorActor to be injected "
    "via AbilityExecutionContext.supervisor."
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


class SendMessageAbility(Ability):
    """向指定 Agent 发送消息并等待回复。

    通过 SupervisorActor.send() 向目标 Agent 发送消息，
    并同步等待目标 Agent 的回复。
    """

    @property
    def name(self) -> str:
        return "send_message"

    def bind_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "send_message",
                "description": (
                    "Send a message to a specific agent in the cluster "
                    "and wait for its response. Use this for direct "
                    "point-to-point communication between agents."
                ),
                "parameters": SendMessageInput.model_json_schema(),
            },
        }

    def to_prompt_description(self) -> str:
        return (
            "send_message(target: str, content: str) -> dict: "
            "Send a message to a specific agent and receive its response"
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
        target = tool_args.get("target", "")
        content = tool_args.get("content", "")

        if not target:
            return ActionResult(
                outcome=ActionOutcome.FAILURE,
                data={"error": "target is required"},
            )
        if not content:
            return ActionResult(
                outcome=ActionOutcome.FAILURE,
                data={"error": "content is required"},
            )

        sender = context.agent_name or "unknown"

        try:
            response = await context.supervisor.send(
                target=target,
                content=content,
                sender=sender,
            )
            return ActionResult(
                outcome=ActionOutcome.SUCCESS,
                data={"response": response, "target": target},
            )
        except Exception as e:
            return ActionResult(
                outcome=ActionOutcome.FAILURE,
                data={"error": f"Failed to send message to '{target}': {e}"},
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
