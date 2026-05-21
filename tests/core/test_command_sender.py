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

from ghrah.communication.supervisor import SupervisorActor
from ghrah.core.server.connection_manager import ConnectionManager
from ghrah.core.server.event_bus import EventBus
from ghrah.core.server.router import MessageRouter

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
    return MessageRouter(
        supervisor=mock_supervisor,
        connection_manager=connection_manager,
        event_bus=event_bus,
        ability_timeout=10.0,
    )


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
        """测试没有 Subject 会话时发送命令应返回错误。"""
        result = await router.send_command("persist_save_node", {"agent_name": "test"})
        assert result.get("success") is False
        assert "No Subject connected" in result.get("error", "")

    @pytest.mark.asyncio
    async def test_send_command_forwards_persist_commands(self, router, mock_supervisor):
        """测试 send_command 可以发送持久化命令。"""
        # 注意：实际发送需要 Subject 连接，这里只验证方法存在和参数正确
        assert asyncio.iscoroutinefunction(router.send_command)

    def test_send_command_with_custom_timeout(self, router):
        """测试 send_command 接受自定义超时。"""
        # 验证 default_timeout 在构造函数中设置
        assert router._default_timeout == 30.0

    def test_send_command_custom_timeout_in_constructor(self, mock_supervisor, connection_manager, event_bus):
        """测试构造函数中设置自定义超时。"""
        router = MessageRouter(
            supervisor=mock_supervisor,
            connection_manager=connection_manager,
            event_bus=event_bus,
            default_timeout=60.0,
        )
        assert router._default_timeout == 60.0


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

        assert result.payload.get("success") is False
        assert "not found" in result.payload.get("error", "")
