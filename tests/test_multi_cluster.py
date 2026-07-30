# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""多集群基础设施测试。

- init_cluster 创建 + 绑定 + 幂等重绑定 + CLUSTER_ALREADY_BOUND 排他
- shutdown_cluster 终止 + 移除 + 清绑定
- cluster_status / list_clusters 免绑定控制面读命令
- agent 命令按 session 绑定路由到正确集群（互不串扰）
- D-strict：未绑定发 agent 命令 → CLUSTER_NOT_INITIALIZED
- M1：断连只解绑不清集群，重连重 init 重绑定后 agents 仍可 list
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from ghrah.protocol.types import CommandType, Message

from ghrah.communication.supervisor import SupervisorActor
from ghrah.core.server.connection_manager import ConnectionManager
from ghrah.core.server.event_bus import EventBus
from ghrah.core.server.router import MessageRouter


def _msg(command: CommandType, payload: dict, request_id: str = "req-1") -> Message:
    return Message(type=command.value, payload=payload, request_id=request_id)


def _mock_supervisor(agents: list[dict] | None = None) -> MagicMock:
    supervisor = MagicMock(spec=SupervisorActor)
    supervisor.list_agents = AsyncMock(return_value=agents or [])
    supervisor.health_check = AsyncMock(return_value={})
    supervisor.terminate_agent = AsyncMock()
    return supervisor


@pytest.fixture
def connection_manager():
    return ConnectionManager()


@pytest.fixture
def event_bus(connection_manager):
    return EventBus(connection_manager)


@pytest.fixture
def router(connection_manager, event_bus):
    return MessageRouter(connection_manager=connection_manager, event_bus=event_bus)


# ─── init_cluster ───


@pytest.mark.asyncio
async def test_init_cluster_creates_supervisor_and_binds(router, event_bus):
    result = await router._handle_init_cluster(
        _msg(CommandType.INIT_CLUSTER, {"cluster_id": "a", "config": {"k": 1}}),
        "s1",
        "req-1",
    )

    assert result.payload.success is True
    assert result.payload.data == {
        "initialized": True,
        "cluster_id": "a",
        "config": {"k": 1},
    }
    supervisor = router._clusters["a"]
    assert isinstance(supervisor, SupervisorActor)
    # command_sender / event_bus 注入到新建 SupervisorActor
    assert supervisor._command_sender is router
    assert supervisor._event_bus is event_bus
    # 双向绑定
    assert router.get_cluster_for_session("s1") is supervisor
    assert router._cluster_session == {"a": "s1"}


@pytest.mark.asyncio
async def test_init_cluster_idempotent_rebind_same_session(router):
    for _ in range(2):
        result = await router._handle_init_cluster(
            _msg(CommandType.INIT_CLUSTER, {"cluster_id": "a"}), "s1", "req-1"
        )
        assert result.payload.success is True
    # 复用同一 SupervisorActor，绑定不变
    assert len(router._clusters) == 1
    assert router._cluster_session == {"a": "s1"}


@pytest.mark.asyncio
async def test_init_cluster_rebind_when_unbound(router):
    await router._handle_init_cluster(
        _msg(CommandType.INIT_CLUSTER, {"cluster_id": "a"}), "s1", "req-1"
    )
    router.unbind_session("s1")

    result = await router._handle_init_cluster(
        _msg(CommandType.INIT_CLUSTER, {"cluster_id": "a"}), "s2", "req-2"
    )

    assert result.payload.success is True
    assert router._cluster_session == {"a": "s2"}


@pytest.mark.asyncio
async def test_init_cluster_already_bound_by_other_active_session(
    router, connection_manager
):
    connection_manager._connections["s1"] = MagicMock()
    await router._handle_init_cluster(
        _msg(CommandType.INIT_CLUSTER, {"cluster_id": "a"}), "s1", "req-1"
    )

    result = await router._handle_init_cluster(
        _msg(CommandType.INIT_CLUSTER, {"cluster_id": "a"}), "s2", "req-2"
    )

    assert result.payload.code == "CLUSTER_ALREADY_BOUND"
    # 原绑定不被劫持
    assert router._cluster_session == {"a": "s1"}


@pytest.mark.asyncio
async def test_init_cluster_rebinds_stale_binding(router):
    """旧 session 已断连（不在 active_sessions）的陈旧绑定可被重绑定。"""
    await router._handle_init_cluster(
        _msg(CommandType.INIT_CLUSTER, {"cluster_id": "a"}), "s1", "req-1"
    )
    # s1 从未注册到 connection_manager → 视为断连

    result = await router._handle_init_cluster(
        _msg(CommandType.INIT_CLUSTER, {"cluster_id": "a"}), "s2", "req-2"
    )

    assert result.payload.success is True
    assert router._cluster_session == {"a": "s2"}


# ─── shutdown_cluster ───


@pytest.mark.asyncio
async def test_shutdown_cluster_terminates_removes_and_unbinds(router):
    supervisor = _mock_supervisor(agents=[{"name": "a1"}, {"name": "a2"}])
    router._clusters["b"] = supervisor
    router.bind_session("s1", "b")

    result = await router._handle_shutdown_cluster(
        _msg(CommandType.SHUTDOWN_CLUSTER, {"cluster_id": "b"}), "s1", "req-1"
    )

    assert result.payload.success is True
    assert result.payload.data == {
        "shutdown": True,
        "cluster_id": "b",
        "terminated_agents": 2,
    }
    assert supervisor.terminate_agent.await_count == 2
    assert "b" not in router._clusters
    assert router._session_cluster == {}
    assert router._cluster_session == {}


@pytest.mark.asyncio
async def test_shutdown_cluster_not_found(router):
    result = await router._handle_shutdown_cluster(
        _msg(CommandType.SHUTDOWN_CLUSTER, {"cluster_id": "ghost"}), "s1", "req-1"
    )
    assert result.payload.code == "CLUSTER_NOT_FOUND"


# ─── cluster_status / list_clusters（免绑定控制面读命令）───


@pytest.mark.asyncio
async def test_cluster_status_without_binding(router):
    supervisor = _mock_supervisor(agents=[{"name": "a1"}])
    supervisor.health_check = AsyncMock(return_value={"a1": True})
    router._clusters["a"] = supervisor

    result = await router._handle_cluster_status(
        _msg(CommandType.CLUSTER_STATUS, {"cluster_id": "a"}), "unbound-session", "req-1"
    )

    assert result.payload.success is True
    assert result.payload.data == {
        "cluster_id": "a",
        "active_agents": 1,
        "health": {"a1": True},
        "status": "running",
    }


@pytest.mark.asyncio
async def test_cluster_status_not_found(router):
    result = await router._handle_cluster_status(
        _msg(CommandType.CLUSTER_STATUS, {"cluster_id": "ghost"}), "s1", "req-1"
    )
    assert result.payload.code == "CLUSTER_NOT_FOUND"


@pytest.mark.asyncio
async def test_list_clusters_reports_all_with_bound_flag(router):
    router._clusters["a"] = _mock_supervisor(agents=[{"name": "a1"}])
    router._clusters["b"] = _mock_supervisor()
    router.bind_session("s1", "a")

    result = await router._handle_list_clusters(
        _msg(CommandType.LIST_CLUSTERS, {}), "unbound-session", "req-1"
    )

    assert result.payload.success is True
    clusters = {c["cluster_id"]: c for c in result.payload.data["clusters"]}
    assert clusters["a"] == {
        "cluster_id": "a",
        "active_agents": 1,
        "status": "running",
        "bound": True,
    }
    assert clusters["b"] == {
        "cluster_id": "b",
        "active_agents": 0,
        "status": "running",
        "bound": False,
    }


# ─── agent 命令路由（D-strict）───


@pytest.mark.asyncio
async def test_agent_commands_route_to_bound_cluster(router):
    supervisor_a = _mock_supervisor(agents=[{"name": "agent-a"}])
    supervisor_b = _mock_supervisor(agents=[{"name": "agent-b"}])
    router._clusters["a"] = supervisor_a
    router._clusters["b"] = supervisor_b
    router.bind_session("s1", "a")
    router.bind_session("s2", "b")

    result_a = await router._handle_list_agents(
        _msg(CommandType.LIST_AGENTS, {}), "s1", "req-1"
    )
    result_b = await router._handle_list_agents(
        _msg(CommandType.LIST_AGENTS, {}), "s2", "req-2"
    )

    # 互不串扰：各自命中绑定集群
    assert [a["name"] for a in result_a.payload.data["agents"]] == ["agent-a"]
    assert [a["name"] for a in result_b.payload.data["agents"]] == ["agent-b"]
    supervisor_a.list_agents.assert_awaited_once()
    supervisor_b.list_agents.assert_awaited_once()


@pytest.mark.asyncio
async def test_unbound_session_agent_command_rejected(router):
    result = await router._handle_list_agents(
        _msg(CommandType.LIST_AGENTS, {}), "unbound-session", "req-1"
    )
    assert result.payload.code == "CLUSTER_NOT_INITIALIZED"

    result = await router._handle_health_check(
        _msg(CommandType.HEALTH_CHECK, {}), "unbound-session", "req-2"
    )
    assert result.payload.code == "CLUSTER_NOT_INITIALIZED"


# ─── M1：集群独立于连接 ───


@pytest.mark.asyncio
async def test_disconnect_unbinds_but_cluster_survives_and_rebinds(router):
    supervisor = _mock_supervisor(agents=[{"name": "agent-a"}])
    router._clusters["a"] = supervisor
    router.bind_session("s1", "a")

    # WS 断开：只解绑，不清集群与 agents
    router.unbind_session("s1")

    assert "a" in router._clusters
    assert router._session_cluster == {}
    assert router._cluster_session == {}

    # 未绑定状态下集群仍可读（控制面免绑定）
    status = await router._handle_cluster_status(
        _msg(CommandType.CLUSTER_STATUS, {"cluster_id": "a"}), "s2", "req-2"
    )
    assert status.payload.data["active_agents"] == 1

    # 重连后重发 init（幂等）重绑定回原集群，agents 仍可 list
    reinit = await router._handle_init_cluster(
        _msg(CommandType.INIT_CLUSTER, {"cluster_id": "a"}), "s2", "req-3"
    )
    assert reinit.payload.success is True

    agents = await router._handle_list_agents(
        _msg(CommandType.LIST_AGENTS, {}), "s2", "req-4"
    )
    assert [a["name"] for a in agents.payload.data["agents"]] == ["agent-a"]
