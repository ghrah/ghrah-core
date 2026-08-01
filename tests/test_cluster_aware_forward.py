# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""Core cluster 感知转发测试。

覆盖 Core→Subject 方向按 cluster 反查绑定 subject session 的转发：
- 多 cluster 多 subject session：persist / execute_ability 转发不串扰
- <internal> 路径（RemoteBackend / RemoteAbilityExecutor 等价）经
  SupervisorActor 的 cluster-aware sender 包装注入 cluster_id
- 未绑定统一报 SUBJECT_SESSION_NOT_BOUND，不回退 subject_sessions[0]
- 排除自身 session（不回环）
- 回归：单 cluster 单 session（MVP 等价）行为不变
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from ghrah.protocol.types import CommandType, Message, create_command_result

from ghrah.communication.supervisor import SupervisorActor, _ClusterAwareSender
from ghrah.core.server.connection_manager import ConnectionManager
from ghrah.core.server.event_bus import EventBus
from ghrah.core.server.router import MessageRouter

# ─── fixtures ───


def _mock_ws() -> MagicMock:
    ws = MagicMock()
    ws.send_json = AsyncMock()
    return ws


@pytest.fixture
def connection_manager():
    cm = ConnectionManager()
    # 注册四个 session：发令 sA/sB（绑 cluster A/B）+ subject SA/SB（绑 cluster A/B）
    cm._connections["sA"] = _mock_ws()
    cm._connections["sB"] = _mock_ws()
    cm._connections["SA"] = _mock_ws()
    cm._connections["SB"] = _mock_ws()
    return cm


@pytest.fixture
def event_bus(connection_manager):
    return EventBus(connection_manager)


@pytest.fixture
def router(connection_manager, event_bus):
    r = MessageRouter(connection_manager=connection_manager, event_bus=event_bus)
    # cluster A 绑定 subject session SA；cluster B 绑定 subject session SB
    # （bind_session 排他：一个 cluster 只能绑一个 session）
    r.bind_session("SA", "A")
    r.bind_session("SB", "B")
    return r


def _make_msg(command: CommandType, payload: dict, request_id: str) -> Message:
    return Message(type=command.value, payload=payload, request_id=request_id)


def _wire_send_to_resolve(router: MessageRouter, request_id: str) -> None:
    """让 connection_manager.send_to 在转发后立即 resolve pending future。

    模拟 Subject 同步返回 command_result。
    """
    orig_send_to = router._connection_manager.send_to

    async def _fake_send_to(session_id: str, message: dict) -> bool:
        await orig_send_to(session_id, message)
        # 模拟 Subject 立即回 command_result
        result_msg = create_command_result(
            request_id=request_id,
            success=True,
            data={"echo_session": session_id},
        )
        await router.resolve_command_result(result_msg, session_id)
        return True

    router._connection_manager.send_to = _fake_send_to  # type: ignore[method-assign]


# ─── persist 转发不串扰 ───


@pytest.mark.asyncio
async def test_persist_forward_routes_to_bound_cluster_subject_session(router):
    """cluster A 的发令 session（绑定 cluster A）发 persist → 转发到 SA，不发 SB。"""
    # 发令 session sA 绑定 cluster A
    # 注意：bind_session 排他，SA 已绑 cluster A；用单独 dict 模拟发令 session 绑定
    router._session_cluster["sA"] = "A"

    _wire_send_to_resolve(router, "req-persist-a")

    msg = _make_msg(CommandType.PERSIST_SAVE_NODE, {"agent_name": "x"}, "req-persist-a")
    result = await router.handle_command(msg, "sA")

    assert result.payload.success is True
    assert result.payload.data["echo_session"] == "SA"


@pytest.mark.asyncio
async def test_persist_forward_does_not_cross_talk(router):
    """cluster A 与 cluster B 各自的 persist 转发互不串扰。"""
    router._session_cluster["sA"] = "A"
    router._session_cluster["sB"] = "B"

    # cluster A persist
    _wire_send_to_resolve(router, "req-a")
    msg_a = _make_msg(CommandType.PERSIST_SAVE_NODE, {"agent_name": "x"}, "req-a")
    res_a = await router.handle_command(msg_a, "sA")
    assert res_a.payload.data["echo_session"] == "SA"

    # cluster B persist
    _wire_send_to_resolve(router, "req-b")
    msg_b = _make_msg(CommandType.PERSIST_SAVE_NODE, {"agent_name": "x"}, "req-b")
    res_b = await router.handle_command(msg_b, "sB")
    assert res_b.payload.data["echo_session"] == "SB"


# ─── execute_ability 转发（外部 WS 路径，b 路径）───


@pytest.mark.asyncio
async def test_execute_ability_forward_routes_by_session_binding(router):
    """execute_ability 经 handle_command 外部 WS 路径，cluster 来自发令 session 绑定。"""
    router._session_cluster["sA"] = "A"

    _wire_send_to_resolve(router, "req-exec-a")

    msg = _make_msg(
        CommandType.EXECUTE_ABILITY,
        {
            "request_id": "req-exec-a",
            "agent_name": "coder",
            "ability_name": "write_file",
            "tool_args": {"path": "a.py"},
        },
        "req-exec-a",
    )
    result = await router.handle_command(msg, "sA")

    assert result.payload.success is True
    assert result.payload.data["echo_session"] == "SA"


# ─── <internal> 路径：cluster-aware sender ───


@pytest.mark.asyncio
async def test_internal_path_cluster_aware_sender_routes_to_bound_session(router):
    """RemoteBackend/RemoteAbilityExecutor 等价：cluster-aware sender 注入 cluster_id
    → send_command 经 <internal> 路径转发到该 cluster 绑定的 subject session。"""
    _wire_send_to_resolve(router, "req-internal-a")

    result = await router.send_command(
        "persist_save_node",
        {"agent_name": "coder"},
        request_id="req-internal-a",
        cluster_id="A",
    )

    assert result["success"] is True
    assert result["data"]["echo_session"] == "SA"


@pytest.mark.asyncio
async def test_internal_path_cluster_b_routes_to_sb(router):
    _wire_send_to_resolve(router, "req-internal-b")

    result = await router.send_command(
        "persist_save_node",
        {"agent_name": "coder"},
        request_id="req-internal-b",
        cluster_id="B",
    )

    assert result["data"]["echo_session"] == "SB"


@pytest.mark.asyncio
async def test_cluster_aware_sender_wrapper_injects_cluster_id(router):
    """_ClusterAwareSender 包装层自动注入 SupervisorActor 的 cluster_id。"""
    sender = _ClusterAwareSender(router, cluster_id="A")

    _wire_send_to_resolve(router, "req-wrap")

    # 调用方不传 cluster_id，包装层应注入 "A"
    result = await sender.send_command(
        "persist_save_node",
        {"agent_name": "coder"},
        request_id="req-wrap",
    )

    assert result["data"]["echo_session"] == "SA"


@pytest.mark.asyncio
async def test_supervisor_actor_constructs_cluster_aware_sender(router):
    """SupervisorActor 有 cluster_id 时构造 cluster-aware sender 包装。"""
    sup = SupervisorActor(
        command_sender=router,
        event_bus=router._event_bus,
        cluster_id="A",
    )
    assert isinstance(sup._cluster_aware_sender, _ClusterAwareSender)
    assert sup._cluster_aware_sender._router is router
    assert sup._cluster_aware_sender._cluster_id == "A"
    # 原始 router 仍保留在 _command_sender
    assert sup._command_sender is router


@pytest.mark.asyncio
async def test_supervisor_actor_without_cluster_id_keeps_raw_sender(router):
    """SupervisorActor 无 cluster_id 时 _cluster_aware_sender = 原始 sender（向后兼容）。"""
    sup = SupervisorActor(command_sender=router, event_bus=router._event_bus)
    assert sup._cluster_aware_sender is router


# ─── 未绑定报错 ───


@pytest.mark.asyncio
async def test_persist_unbound_session_reports_subject_session_not_bound(router):
    """发令 session 无 cluster 绑定 → SUBJECT_SESSION_NOT_BOUND。"""
    msg = _make_msg(CommandType.PERSIST_SAVE_NODE, {"agent_name": "x"}, "req-unbound")
    result = await router.handle_command(msg, "unbound-session")

    assert result.payload.code == "SUBJECT_SESSION_NOT_BOUND"


@pytest.mark.asyncio
async def test_execute_ability_unbound_session_reports_subject_session_not_bound(router):
    msg = _make_msg(
        CommandType.EXECUTE_ABILITY,
        {
            "request_id": "req-exec-unbound",
            "agent_name": "coder",
            "ability_name": "write_file",
            "tool_args": {},
        },
        "req-exec-unbound",
    )
    result = await router.handle_command(msg, "unbound-session")

    assert result.payload.code == "SUBJECT_SESSION_NOT_BOUND"


@pytest.mark.asyncio
async def test_internal_path_no_cluster_id_reports_subject_session_not_bound(router):
    """send_command(cluster_id=None) → SUBJECT_SESSION_NOT_BOUND（不回退）。"""
    result = await router.send_command(
        "persist_save_node",
        {"agent_name": "x"},
        cluster_id=None,
    )
    assert result.get("code") == "SUBJECT_SESSION_NOT_BOUND"


@pytest.mark.asyncio
async def test_cluster_without_bound_subject_session_reports_error(connection_manager, event_bus):
    """cluster 存在但 _cluster_session 无绑定 subject session → SUBJECT_SESSION_NOT_BOUND。"""
    r = MessageRouter(connection_manager=connection_manager, event_bus=event_bus)
    # cluster A 存在（有 supervisor）但无 subject session 绑定
    r._clusters["A"] = MagicMock(spec=SupervisorActor)

    # 发令 session 绑 cluster A，但 cluster A 无 subject session 绑定
    r._session_cluster["sX"] = "A"

    msg = _make_msg(CommandType.PERSIST_SAVE_NODE, {"agent_name": "x"}, "req-nobound")
    result = await r.handle_command(msg, "sX")

    assert result.payload.code == "SUBJECT_SESSION_NOT_BOUND"


# ─── 排除自身 ───


@pytest.mark.asyncio
async def test_persist_excludes_self_session(connection_manager, event_bus):
    """发令 session 同时是 cluster 绑定的 subject session 时，转发排除自身。

    若排除后无可用 target → SUBJECT_SESSION_NOT_BOUND。
    """
    r = MessageRouter(connection_manager=connection_manager, event_bus=event_bus)
    connection_manager._connections["only"] = _mock_ws()
    # only 既是发令 session 又是 cluster A 绑定的 subject session
    r.bind_session("only", "A")
    r._session_cluster["only"] = "A"

    msg = _make_msg(CommandType.PERSIST_SAVE_NODE, {"agent_name": "x"}, "req-self")
    result = await r.handle_command(msg, "only")

    # 排除自身后无可用 target
    assert result.payload.code == "SUBJECT_SESSION_NOT_BOUND"


# ─── 回归：单 cluster 单 session（MVP 等价）───


@pytest.mark.asyncio
async def test_single_cluster_single_session_mvp_equivalent(connection_manager, event_bus):
    """单 cluster 单 subject session：转发行为与改前 subject_sessions[0] 等价。"""
    r = MessageRouter(connection_manager=connection_manager, event_bus=event_bus)
    connection_manager._connections["subject-1"] = _mock_ws()
    r.bind_session("subject-1", "default")

    # 发令 session 绑 default（经 <internal> 路径模拟）
    _wire_send_to_resolve(r, "req-mvp")

    result = await r.send_command(
        "persist_save_node",
        {"agent_name": "x"},
        request_id="req-mvp",
        cluster_id="default",
    )

    assert result["success"] is True
    assert result["data"]["echo_session"] == "subject-1"


@pytest.mark.asyncio
async def test_single_cluster_persist_via_handle_command(connection_manager, event_bus):
    """单 cluster：外部 WS persist 转发到绑定 subject session（排除自身后仍命中）。"""
    r = MessageRouter(connection_manager=connection_manager, event_bus=event_bus)
    connection_manager._connections["client-1"] = _mock_ws()
    connection_manager._connections["subject-1"] = _mock_ws()
    r.bind_session("subject-1", "default")
    r._session_cluster["client-1"] = "default"

    _wire_send_to_resolve(r, "req-mvp-ext")

    msg = _make_msg(CommandType.PERSIST_SAVE_NODE, {"agent_name": "x"}, "req-mvp-ext")
    result = await r.handle_command(msg, "client-1")

    assert result.payload.success is True
    assert result.payload.data["echo_session"] == "subject-1"
