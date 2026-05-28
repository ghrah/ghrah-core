# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""集群通信 Ability 测试：QueryAgentsAbility, SendMessageAbility,
BroadcastMessageAbility, SpawnAgentAbility, TerminateAgentAbility。
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

from ghrah.abilities.base import ActionOutcome
from ghrah.abilities.builtin.broadcast_message import BroadcastMessageAbility
from ghrah.abilities.builtin.query_agents import QueryAgentsAbility
from ghrah.abilities.builtin.send_message import SendMessageAbility
from ghrah.abilities.builtin.spawn_agent import SpawnAgentAbility
from ghrah.abilities.builtin.terminate_agent import TerminateAgentAbility
from ghrah.abilities.context import AbilityExecutionContext
from ghrah.core.config import AgentConfig


def _make_context(
    supervisor: Any = None,
    agent_name: str = "test-agent",
    tool_args: dict[str, Any] | None = None,
    **overrides: Any,
) -> AbilityExecutionContext:
    defaults: dict[str, Any] = {
        "supervisor": supervisor,
        "agent_name": agent_name,
        "tool_args": tool_args or {},
    }
    defaults.update(overrides)
    return AbilityExecutionContext(**defaults)


def _make_supervisor(
    list_agents_return: list[dict[str, Any]] | None = None,
    send_return: str = "response from target",
    broadcast_return: list[str] | None = None,
    spawn_agent_return: str = "new-agent",
) -> MagicMock:
    supervisor = MagicMock()
    supervisor.list_agents = AsyncMock(return_value=list_agents_return or [])
    supervisor.send = AsyncMock(return_value=send_return)
    supervisor.broadcast = AsyncMock(return_value=broadcast_return or ["ok"])
    supervisor.spawn_agent = AsyncMock(return_value=spawn_agent_return)
    return supervisor


# ── QueryAgentsAbility 测试 ──


class TestQueryAgentsAbility:
    def test_name(self) -> None:
        ability = QueryAgentsAbility()
        assert ability.name == "query_agents"

    def test_bind_tool(self) -> None:
        ability = QueryAgentsAbility()
        schema = ability.bind_tool()
        assert schema is not None
        assert schema["type"] == "function"
        func = schema["function"]
        assert func["name"] == "query_agents"
        assert "filter" in func["parameters"]["properties"]

    def test_get_hooks_empty(self) -> None:
        ability = QueryAgentsAbility()
        assert ability.get_hooks() == []

    async def test_execute_no_supervisor(self) -> None:
        ctx = _make_context(supervisor=None)
        ability = QueryAgentsAbility()
        result = await ability.execute(ctx)
        assert result.outcome == ActionOutcome.FAILURE
        assert "No supervisor" in result.data["error"]

    async def test_execute_returns_agents(self) -> None:
        agents = [
            {"name": "planner", "description": "Task planner"},
            {"name": "coder", "description": "Code writer"},
        ]
        supervisor = _make_supervisor(list_agents_return=agents)
        ctx = _make_context(supervisor=supervisor)
        ability = QueryAgentsAbility()
        result = await ability.execute(ctx)
        assert result.outcome == ActionOutcome.SUCCESS
        assert result.data["count"] == 2
        assert result.data["agents"] == agents

    async def test_execute_with_filter(self) -> None:
        agents = [
            {"name": "planner", "description": "Task planner"},
            {"name": "coder", "description": "Code writer"},
            {"name": "code-reviewer", "description": "Code reviewer"},
        ]
        supervisor = _make_supervisor(list_agents_return=agents)
        ctx = _make_context(supervisor=supervisor, tool_args={"filter": "code"})
        ability = QueryAgentsAbility()
        result = await ability.execute(ctx)
        assert result.outcome == ActionOutcome.SUCCESS
        assert result.data["count"] == 2
        names = [a["name"] for a in result.data["agents"]]
        assert "coder" in names
        assert "code-reviewer" in names
        assert "planner" not in names

    async def test_execute_list_agents_exception(self) -> None:
        supervisor = _make_supervisor()
        supervisor.list_agents = AsyncMock(side_effect=RuntimeError("registry error"))
        ctx = _make_context(supervisor=supervisor)
        ability = QueryAgentsAbility()
        result = await ability.execute(ctx)
        assert result.outcome == ActionOutcome.FAILURE
        assert "registry error" in result.data["error"]


# ── SendMessageAbility 测试 ──


class TestSendMessageAbility:
    def test_name(self) -> None:
        ability = SendMessageAbility()
        assert ability.name == "send_message"

    def test_bind_tool(self) -> None:
        ability = SendMessageAbility()
        schema = ability.bind_tool()
        assert schema is not None
        func = schema["function"]
        assert func["name"] == "send_message"
        params = func["parameters"]["properties"]
        assert "target" in params
        assert "content" in params
        required = func["parameters"].get("required", [])
        assert "target" in required
        assert "content" in required

    async def test_execute_no_supervisor(self) -> None:
        ctx = _make_context(supervisor=None, tool_args={"target": "agent-b", "content": "hello"})
        ability = SendMessageAbility()
        result = await ability.execute(ctx)
        assert result.outcome == ActionOutcome.FAILURE
        assert "No supervisor" in result.data["error"]

    async def test_execute_success_sync(self) -> None:
        supervisor = _make_supervisor(send_return="done!")
        ctx = _make_context(
            supervisor=supervisor,
            agent_name="agent-a",
            tool_args={"target": "agent-b", "content": "hello", "fire_and_forget": False},
        )
        ability = SendMessageAbility()
        result = await ability.execute(ctx)
        assert result.outcome == ActionOutcome.SUCCESS
        assert result.data["response"] == "done!"
        assert result.data["target"] == "agent-b"
        assert result.data["mode"] == "sync"
        supervisor.send.assert_awaited_once_with(
            target="agent-b", content="hello", sender="agent-a"
        )

    async def test_execute_missing_target(self) -> None:
        supervisor = _make_supervisor()
        ctx = _make_context(supervisor=supervisor, tool_args={"content": "hello"})
        ability = SendMessageAbility()
        result = await ability.execute(ctx)
        assert result.outcome == ActionOutcome.FAILURE
        assert "target is required" in result.data["error"]

    async def test_execute_missing_content(self) -> None:
        supervisor = _make_supervisor()
        ctx = _make_context(supervisor=supervisor, tool_args={"target": "agent-b"})
        ability = SendMessageAbility()
        result = await ability.execute(ctx)
        assert result.outcome == ActionOutcome.FAILURE
        assert "content is required" in result.data["error"]

    async def test_execute_send_exception_sync(self) -> None:
        supervisor = _make_supervisor()
        supervisor.send = AsyncMock(side_effect=RuntimeError("timeout"))
        ctx = _make_context(
            supervisor=supervisor,
            tool_args={"target": "agent-b", "content": "hello", "fire_and_forget": False},
        )
        ability = SendMessageAbility()
        result = await ability.execute(ctx)
        assert result.outcome == ActionOutcome.FAILURE
        assert "timeout" in result.data["error"]


# ── BroadcastMessageAbility 测试 ──


class TestBroadcastMessageAbility:
    def test_name(self) -> None:
        ability = BroadcastMessageAbility()
        assert ability.name == "broadcast_message"

    def test_bind_tool(self) -> None:
        ability = BroadcastMessageAbility()
        schema = ability.bind_tool()
        assert schema is not None
        func = schema["function"]
        assert func["name"] == "broadcast_message"
        params = func["parameters"]["properties"]
        assert "content" in params

    async def test_execute_no_supervisor(self) -> None:
        ctx = _make_context(supervisor=None, tool_args={"content": "hello all"})
        ability = BroadcastMessageAbility()
        result = await ability.execute(ctx)
        assert result.outcome == ActionOutcome.FAILURE
        assert "No supervisor" in result.data["error"]

    async def test_execute_success(self) -> None:
        responses = ["ack from b", "ack from c"]
        supervisor = _make_supervisor(broadcast_return=responses)
        ctx = _make_context(
            supervisor=supervisor,
            agent_name="agent-a",
            tool_args={"content": "hello all"},
        )
        ability = BroadcastMessageAbility()
        result = await ability.execute(ctx)
        assert result.outcome == ActionOutcome.SUCCESS
        assert result.data["responses"] == responses
        assert result.data["agent_count"] == 2
        supervisor.broadcast.assert_awaited_once_with(
            content="hello all", sender="agent-a"
        )

    async def test_execute_missing_content(self) -> None:
        supervisor = _make_supervisor()
        ctx = _make_context(supervisor=supervisor, tool_args={})
        ability = BroadcastMessageAbility()
        result = await ability.execute(ctx)
        assert result.outcome == ActionOutcome.FAILURE
        assert "content is required" in result.data["error"]

    async def test_execute_broadcast_exception(self) -> None:
        supervisor = _make_supervisor()
        supervisor.broadcast = AsyncMock(side_effect=RuntimeError("network error"))
        ctx = _make_context(
            supervisor=supervisor,
            tool_args={"content": "hello all"},
        )
        ability = BroadcastMessageAbility()
        result = await ability.execute(ctx)
        assert result.outcome == ActionOutcome.FAILURE
        assert "network error" in result.data["error"]


# ── SpawnAgentAbility 测试 ──


class TestSpawnAgentAbility:
    def test_name(self) -> None:
        ability = SpawnAgentAbility()
        assert ability.name == "spawn_agent"

    def test_bind_tool(self) -> None:
        ability = SpawnAgentAbility()
        schema = ability.bind_tool()
        assert schema is not None
        func = schema["function"]
        assert func["name"] == "spawn_agent"
        params = func["parameters"]["properties"]
        assert "name" in params
        assert "description" in params
        assert "system_prompt" in params
        assert "abilities" in params
        required = func["parameters"].get("required", [])
        assert "name" in required

    async def test_execute_no_supervisor(self) -> None:
        ctx = _make_context(
            supervisor=None,
            tool_args={"name": "new-agent"},
        )
        ability = SpawnAgentAbility()
        result = await ability.execute(ctx)
        assert result.outcome == ActionOutcome.FAILURE
        assert "No supervisor" in result.data["error"]

    async def test_execute_spawn_success(self) -> None:
        supervisor = _make_supervisor(spawn_agent_return="new-agent")
        ctx = _make_context(
            supervisor=supervisor,
            agent_name="spawner",
            tool_args={"name": "new-agent"},
        )
        ability = SpawnAgentAbility()
        result = await ability.execute(ctx)
        assert result.outcome == ActionOutcome.SUCCESS
        assert result.data["agent_name"] == "new-agent"
        assert result.data["status"] == "spawned"
        supervisor.spawn_agent.assert_awaited_once()
        call_args = supervisor.spawn_agent.call_args
        config = call_args[0][0]
        assert isinstance(config, AgentConfig)
        assert config.name == "new-agent"
        assert call_args[1].get("abilities") is None

    async def test_execute_spawn_with_abilities(self) -> None:
        supervisor = _make_supervisor(spawn_agent_return="worker-1")
        ctx = _make_context(
            supervisor=supervisor,
            agent_name="spawner",
            tool_args={
                "name": "worker-1",
                "description": "A worker agent",
                "system_prompt": "You are a worker.",
                "abilities": ["conversation", "end_task"],
            },
        )
        ability = SpawnAgentAbility()
        result = await ability.execute(ctx)
        assert result.outcome == ActionOutcome.SUCCESS
        assert result.data["agent_name"] == "worker-1"
        supervisor.spawn_agent.assert_awaited_once()
        call_args = supervisor.spawn_agent.call_args
        config = call_args[0][0]
        assert config.name == "worker-1"
        assert config.description == "A worker agent"
        assert config.system_prompt == "You are a worker."
        abilities = call_args[1].get("abilities")
        assert abilities is not None
        assert len(abilities) == 2
        ability_names = [a.name for a in abilities]
        assert "conversation" in ability_names
        assert "end_task" in ability_names

    async def test_execute_spawn_with_unknown_ability(self) -> None:
        supervisor = _make_supervisor(spawn_agent_return="worker-2")
        ctx = _make_context(
            supervisor=supervisor,
            agent_name="spawner",
            tool_args={
                "name": "worker-2",
                "abilities": ["conversation", "nonexistent_ability"],
            },
        )
        ability = SpawnAgentAbility()
        result = await ability.execute(ctx)
        assert result.outcome == ActionOutcome.SUCCESS
        supervisor.spawn_agent.assert_awaited_once()
        call_args = supervisor.spawn_agent.call_args
        abilities = call_args[1].get("abilities")
        assert abilities is not None
        assert len(abilities) == 1
        assert abilities[0].name == "conversation"

    async def test_execute_spawn_missing_name(self) -> None:
        supervisor = _make_supervisor()
        ctx = _make_context(supervisor=supervisor, tool_args={})
        ability = SpawnAgentAbility()
        result = await ability.execute(ctx)
        assert result.outcome == ActionOutcome.FAILURE
        assert "name is required" in result.data["error"]

    async def test_execute_spawn_exception(self) -> None:
        supervisor = _make_supervisor()
        supervisor.spawn_agent = AsyncMock(side_effect=RuntimeError("name conflict"))
        ctx = _make_context(
            supervisor=supervisor,
            tool_args={"name": "dup-agent"},
        )
        ability = SpawnAgentAbility()
        result = await ability.execute(ctx)
        assert result.outcome == ActionOutcome.FAILURE
        assert "name conflict" in result.data["error"]


# ── AbilityRegistry 注册测试 ──


class TestClusterAbilityRegistry:
    def test_all_cluster_abilities_registered(self) -> None:
        from ghrah.abilities.registry import AbilityRegistry

        assert AbilityRegistry.has("query_agents")
        assert AbilityRegistry.has("send_message")
        assert AbilityRegistry.has("broadcast_message")
        assert AbilityRegistry.has("spawn_agent")
        assert AbilityRegistry.has("terminate_agent")

    def test_registry_create_query_agents(self) -> None:
        from ghrah.abilities.registry import AbilityRegistry

        ability = AbilityRegistry.create("query_agents")
        assert isinstance(ability, QueryAgentsAbility)

    def test_registry_create_send_message(self) -> None:
        from ghrah.abilities.registry import AbilityRegistry

        ability = AbilityRegistry.create("send_message")
        assert isinstance(ability, SendMessageAbility)

    def test_registry_create_broadcast_message(self) -> None:
        from ghrah.abilities.registry import AbilityRegistry

        ability = AbilityRegistry.create("broadcast_message")
        assert isinstance(ability, BroadcastMessageAbility)

    def test_registry_create_spawn_agent(self) -> None:
        from ghrah.abilities.registry import AbilityRegistry

        ability = AbilityRegistry.create("spawn_agent")
        assert isinstance(ability, SpawnAgentAbility)

    def test_registry_create_terminate_agent(self) -> None:
        from ghrah.abilities.registry import AbilityRegistry

        ability = AbilityRegistry.create("terminate_agent")
        assert isinstance(ability, TerminateAgentAbility)


# ── TerminateAgentAbility 测试 ──


class TestTerminateAgentAbility:
    def test_name(self) -> None:
        ability = TerminateAgentAbility()
        assert ability.name == "terminate_agent"

    def test_bind_tool(self) -> None:
        ability = TerminateAgentAbility()
        schema = ability.bind_tool()
        assert schema is not None
        func = schema["function"]
        assert func["name"] == "terminate_agent"
        params = func["parameters"]["properties"]
        assert "agent_name" in params
        required = func["parameters"].get("required", [])
        assert "agent_name" in required

    async def test_execute_no_supervisor(self) -> None:
        ctx = _make_context(
            supervisor=None,
            tool_args={"agent_name": "worker-1"},
        )
        ability = TerminateAgentAbility()
        result = await ability.execute(ctx)
        assert result.outcome == ActionOutcome.FAILURE
        assert "No supervisor" in result.data["error"]

    async def test_execute_success(self) -> None:
        supervisor = MagicMock()
        supervisor.terminate_agent = AsyncMock()
        ctx = _make_context(
            supervisor=supervisor,
            tool_args={"agent_name": "worker-1"},
        )
        ability = TerminateAgentAbility()
        result = await ability.execute(ctx)
        assert result.outcome == ActionOutcome.SUCCESS
        assert result.data["agent_name"] == "worker-1"
        assert result.data["status"] == "terminated"
        supervisor.terminate_agent.assert_awaited_once_with("worker-1")

    async def test_execute_missing_agent_name(self) -> None:
        supervisor = MagicMock()
        supervisor.terminate_agent = AsyncMock()
        ctx = _make_context(supervisor=supervisor, tool_args={})
        ability = TerminateAgentAbility()
        result = await ability.execute(ctx)
        assert result.outcome == ActionOutcome.FAILURE
        assert "agent_name is required" in result.data["error"]

    async def test_execute_terminate_exception(self) -> None:
        supervisor = MagicMock()
        supervisor.terminate_agent = AsyncMock(side_effect=RuntimeError("not found"))
        ctx = _make_context(
            supervisor=supervisor,
            tool_args={"agent_name": "ghost"},
        )
        ability = TerminateAgentAbility()
        result = await ability.execute(ctx)
        assert result.outcome == ActionOutcome.FAILURE
        assert "not found" in result.data["error"]


# ── SendMessageAbility 异步模式测试 ──


class TestSendMessageAbilityAsync:
    async def test_execute_fire_and_forget_default(self) -> None:
        supervisor = _make_supervisor(send_return="async reply")
        ctx = _make_context(
            supervisor=supervisor,
            agent_name="agent-a",
            tool_args={"target": "agent-b", "content": "hello", "fire_and_forget": True},
        )
        ability = SendMessageAbility()
        result = await ability.execute(ctx)
        assert result.outcome == ActionOutcome.SUCCESS
        assert result.data["mode"] == "async"
        assert result.data["target"] == "agent-b"

    async def test_execute_sync_mode(self) -> None:
        supervisor = _make_supervisor(send_return="sync reply")
        ctx = _make_context(
            supervisor=supervisor,
            agent_name="agent-a",
            tool_args={"target": "agent-b", "content": "hello", "fire_and_forget": False},
        )
        ability = SendMessageAbility()
        result = await ability.execute(ctx)
        assert result.outcome == ActionOutcome.SUCCESS
        assert result.data["mode"] == "sync"
        assert result.data["response"] == "sync reply"
        supervisor.send.assert_awaited_once_with(
            target="agent-b", content="hello", sender="agent-a"
        )
