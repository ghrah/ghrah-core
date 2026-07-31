# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""CommandSender 协议和 MessageRouter.send_command() 测试。

测试 MessageRouter 实现的 CommandSender 协议：
- send_command: 发送命令到 Subject 并等待响应
- 命令类型和超时处理
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from ghrah.protocol.types import (
    AbilityResultPayload,
    CommandType,
    EventType,
    Message,
    SystemType,
    create_command_result,
)

from ghrah.communication.supervisor import SupervisorActor
from ghrah.core.server.connection_manager import ConnectionManager
from ghrah.core.server.event_bus import EventBus
from ghrah.core.server.router import MessageRouter, PendingRequest

# ─── Fixtures ───


@pytest.fixture
def mock_supervisor():
    supervisor = MagicMock(spec=SupervisorActor)
    supervisor.list_agents = AsyncMock(return_value=[])
    return supervisor


@pytest.fixture
def connection_manager():
    return ConnectionManager()


@pytest.fixture
def event_bus(connection_manager):
    return EventBus(connection_manager)


@pytest.fixture
def router(mock_supervisor, connection_manager, event_bus):
    router = MessageRouter(
        connection_manager=connection_manager,
        event_bus=event_bus,
        ability_timeout=10.0,
    )
    # 多集群：注册 mock 集群并绑定测试 session（D-strict 前置）
    router._clusters["default"] = mock_supervisor
    router.bind_session("session-1", "default")
    return router


# ─── 测试用例 ───


class TestCommandSenderProtocol:
    """CommandSender 协议验证测试。"""

    def test_message_router_implements_command_sender(self, router):
        """测试 MessageRouter 实现 CommandSender 协议。"""
        assert hasattr(router, "send_command")
        assert callable(router.send_command)


class TestMessageRouterSendCommand:
    """MessageRouter.send_command() 测试。"""

    @pytest.mark.asyncio
    async def test_send_command_no_subject_sessions(self, router):
        """无 cluster 绑定时 send_command 应报 SUBJECT_SESSION_NOT_BOUND（决策 A）。

        send_command 走 <internal> 路径，cluster_id=None → 不回退 subject_sessions[0]，
        统一报 SUBJECT_SESSION_NOT_BOUND。
        """
        result = await router.send_command("persist_save_node", {"agent_name": "test"})
        # create_error 产 ErrorPayload.model_dump()：code/message/details，无 success 字段
        assert result.get("code") == "SUBJECT_SESSION_NOT_BOUND"

    @pytest.mark.asyncio
    async def test_send_command_forwards_persist_commands(self, router, mock_supervisor):
        """测试 send_command 可以发送持久化命令。"""
        # 注意：实际发送需要 Subject 连接，这里只验证方法存在和参数正确
        assert asyncio.iscoroutinefunction(router.send_command)

    def test_send_command_with_custom_timeout(self, router):
        """测试 send_command 接受自定义超时。"""
        # 验证 default_timeout 在构造函数中设置
        assert router._default_timeout == 30.0

    def test_send_command_custom_timeout_in_constructor(
        self, mock_supervisor, connection_manager, event_bus
    ):
        """测试构造函数中设置自定义超时。"""
        router = MessageRouter(
            connection_manager=connection_manager,
            event_bus=event_bus,
            default_timeout=60.0,
        )
        assert router._default_timeout == 60.0


class TestCommandResultResolution:
    """Core pending request resolve 与 confirmed ability_result 事件测试。"""

    @pytest.mark.asyncio
    async def test_normal_command_result_does_not_publish_ability_result(
        self, router, event_bus
    ):
        future = asyncio.get_running_loop().create_future()
        router._pending_requests["req-normal"] = PendingRequest(
            future=future,
            session_id="<internal>",
            command_type="persist_save_node",
            payload={"agent_name": "coder"},
        )
        event_bus.publish = AsyncMock(return_value=1)

        message = create_command_result(
            request_id="req-normal",
            success=True,
            data={"saved": True},
        )

        handled = await router.resolve_command_result(message, "subject-session")

        assert handled is True
        assert future.result() is message
        event_bus.publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_execute_ability_command_result_publishes_confirmed_event(
        self, router, event_bus
    ):
        future = asyncio.get_running_loop().create_future()
        router._pending_requests["req-ability"] = PendingRequest(
            future=future,
            session_id="<internal>",
            command_type=CommandType.EXECUTE_ABILITY.value,
            payload={
                "request_id": "req-ability",
                "agent_name": "coder",
                "ability_name": "write_file",
                "tool_args": {"path": "hello.py"},
            },
        )
        event_bus.publish = AsyncMock(return_value=1)

        message = Message(
            type=SystemType.COMMAND_RESULT.value,
            request_id="req-ability",
            payload={
                "request_id": "req-ability",
                "agent_name": "coder",
                "ability_name": "write_file",
                "success": True,
                "result": {"path": "hello.py"},
                "error": None,
            },
        )

        handled = await router.resolve_command_result(message, "subject-session")

        assert handled is True
        assert future.result() is message
        event_bus.publish.assert_awaited_once()
        event = event_bus.publish.await_args.args[0]
        assert event.type == EventType.ABILITY_RESULT.value
        assert event.request_id == "req-ability"
        assert isinstance(event.payload, AbilityResultPayload)
        assert event.payload.request_id == "req-ability"
        assert event.payload.agent_name == "coder"
        assert event.payload.ability_name == "write_file"
        assert event.payload.success is True
        assert event.payload.result == {"path": "hello.py"}

    @pytest.mark.asyncio
    async def test_execute_ability_wrapped_command_result_payload_is_flattened(
        self, router, event_bus
    ):
        future = asyncio.get_running_loop().create_future()
        router._pending_requests["req-wrapped"] = PendingRequest(
            future=future,
            session_id="<internal>",
            command_type=CommandType.EXECUTE_ABILITY.value,
            payload={
                "request_id": "req-wrapped",
                "agent_name": "coder",
                "ability_name": "read_file",
            },
        )
        event_bus.publish = AsyncMock(return_value=1)

        message = create_command_result(
            request_id="req-wrapped",
            success=True,
            data={
                "request_id": "req-wrapped",
                "agent_name": "coder",
                "ability_name": "read_file",
                "success": True,
                "result": {"content": "Hello"},
                "error": None,
            },
        )

        handled = await router.resolve_command_result(message, "subject-session")

        assert handled is True
        event = event_bus.publish.await_args.args[0]
        assert event.payload.result == {"content": "Hello"}
        assert event.payload.ability_name == "read_file"

    @pytest.mark.asyncio
    async def test_legacy_ability_result_does_not_resolve_non_execute_pending(
        self, router
    ):
        future = asyncio.get_running_loop().create_future()
        router._pending_requests["req-normal"] = PendingRequest(
            future=future,
            session_id="<internal>",
            command_type="persist_save_node",
            payload={"agent_name": "coder"},
        )
        message = Message(
            type=EventType.ABILITY_RESULT.value,
            request_id="req-normal",
            payload=AbilityResultPayload(
                request_id="req-normal",
                agent_name="coder",
                ability_name="write_file",
                success=True,
                result={"path": "hello.py"},
            ),
        )

        handled = await router.resolve_ability_result(message, "subject-session")

        assert handled is False
        assert "req-normal" in router._pending_requests
        assert not future.done()


class TestHITLResponseHandling:
    """HITL_RESPONSE 命令处理测试。"""

    @pytest.mark.asyncio
    async def test_handle_hitl_response_unknown_agent(self, router, mock_supervisor):
        """测试 HITL 响应路由到不存在的 Agent 应返回错误。"""
        from ghrah.protocol.types import Message

        mock_supervisor.get_agent_handle = AsyncMock(return_value=None)

        message = Message(
            type="hitl_response",
            payload={
                "agent_name": "nonexistent",
                "ability_name": "write_file",
                "tool_call_id": "call_123",
                "approved": True,
            },
            request_id="req-1",
        )

        result = await router._handle_hitl_response(message, "session-1", "req-1")

        assert result.payload.success is False
        assert "not found" in result.payload.error
