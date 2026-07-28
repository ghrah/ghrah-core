# SPDX-FileCopyrightText: 2026 chenxya <chenxya.org>
#
# SPDX-License-Identifier: Apache-2.0

"""MessageRouter._handle_list_agents 契约测试。

验证重连/冷启动后 Observer 重建 agent 列表所需的响应契约：
data 形如 {"agents": [{name, config, description, created_at}, ...]}，
与 webui bind.ts 的 `Array.isArray(data.agents)` 消费点对齐。
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from ghrah.protocol.types import CommandType, Message

from ghrah.communication.supervisor import SupervisorActor
from ghrah.core.server.connection_manager import ConnectionManager
from ghrah.core.server.event_bus import EventBus
from ghrah.core.server.router import MessageRouter
from ghrah.types.config_types import AgentConfig


@pytest.fixture
def mock_supervisor():
    return MagicMock(spec=SupervisorActor)


@pytest.fixture
def router(mock_supervisor):
    return MessageRouter(
        supervisor=mock_supervisor,
        connection_manager=ConnectionManager(),
        event_bus=EventBus(ConnectionManager()),
    )


def _make_message(command: CommandType) -> Message:
    return Message(type=command.value, payload={}, request_id="req-1")


@pytest.mark.asyncio
async def test_list_agents_wraps_result_in_agents_key(router, mock_supervisor):
    """list_agents 响应 data 为 {"agents": [...]}, 与 webui 契约对齐。"""
    mock_supervisor.list_agents.return_value = [
        {"name": "agent-a", "config": {"name": "agent-a"}, "description": "A"},
        {"name": "agent-b", "config": {"name": "agent-b"}, "description": "B"},
    ]

    result = await router._handle_list_agents(
        _make_message(CommandType.LIST_AGENTS), "session-1", "req-1"
    )

    assert result.payload.success is True
    data = result.payload.data
    assert isinstance(data, dict)
    assert isinstance(data["agents"], list)
    assert {a["name"] for a in data["agents"]} == {"agent-a", "agent-b"}
    assert data["agents"][0]["config"]["name"] == "agent-a"


@pytest.mark.asyncio
async def test_list_agents_empty_returns_agents_key(router, mock_supervisor):
    """空集群时 data 仍为 {"agents": []}, 而非裸空数组。"""
    mock_supervisor.list_agents.return_value = []

    result = await router._handle_list_agents(
        _make_message(CommandType.LIST_AGENTS), "session-1", "req-1"
    )

    assert result.payload.data == {"agents": []}


@pytest.mark.asyncio
async def test_list_agents_payload_carries_config_from_registry():
    """端到端：supervisor.list_agents 返回的 config 字段来自 AgentInfo.to_dict。"""
    from ghrah.communication.registry import AgentRegistry

    registry = AgentRegistry()
    config = AgentConfig(
        name="agent-x",
        description="X agent",
        system_prompt="be x",
        max_iterations=7,
    )
    registry.register("agent-x", config, MagicMock())

    agents = [info.to_dict() for info in registry.list_agents()]
    assert agents[0]["config"]["name"] == "agent-x"
    assert agents[0]["config"]["system_prompt"] == "be x"
    assert agents[0]["config"]["max_iterations"] == 7
