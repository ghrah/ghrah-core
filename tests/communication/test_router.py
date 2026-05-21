# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""MessageRouter 单元测试。

使用 mock 模拟 agent handle。
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from ghrah.communication.registry import AgentRegistry
from ghrah.communication.router import MessageRouter
from ghrah.core.config import AgentConfig
from ghrah.core.exceptions import (
    AgentNotFoundError,
    CommunicationTimeoutError,
    RoutingError,
)
from ghrah.core.message import Message, MessageType


def _make_async_response(response: Message) -> asyncio.coroutines:
    """创建一个返回指定 response 的协程。"""

    async def _coro() -> Message:
        return response

    return _coro()


@pytest.fixture
def registry_with_agents() -> tuple[AgentRegistry, dict[str, MagicMock]]:
    """创建包含两个 mock Agent 的 Registry。"""
    registry = AgentRegistry()
    handles = {}

    for name in ["agent-a", "agent-b"]:
        config = AgentConfig(
            name=name,
            description=f"Test agent {name}",
        )
        handle = MagicMock()
        mock_response = Message(
            sender=name,
            recipient="user",
            content=f"Response from {name}",
            type=MessageType.RESULT,
        )
        handle.receive = AsyncMock(return_value=mock_response)
        registry.register(name, config, handle)
        handles[name] = handle

    return registry, handles


@pytest.fixture
def router(registry_with_agents: tuple[AgentRegistry, dict]) -> MessageRouter:
    """创建 MessageRouter 实例。"""
    registry, _ = registry_with_agents
    return MessageRouter(registry, default_timeout=5.0)


class TestMessageRouter:
    """MessageRouter 测试套件。"""

    @pytest.mark.asyncio
    async def test_route_success(self, router: MessageRouter, registry_with_agents: tuple) -> None:
        """成功路由消息到目标 Agent。"""
        registry, handles = registry_with_agents

        message = Message(
            sender="user",
            recipient="agent-a",
            content="Hello agent-a",
            type=MessageType.CHAT,
        )

        mock_reply = Message(
            sender="agent-a",
            recipient="user",
            content="Hello from agent-a",
            type=MessageType.RESULT,
        )
        handles["agent-a"].receive = AsyncMock(return_value=mock_reply)

        response = await router.route(message)
        assert response.content == "Hello from agent-a"
        assert response.sender == "agent-a"

    @pytest.mark.asyncio
    async def test_route_agent_not_found(self, router: MessageRouter) -> None:
        """路由到未注册 Agent 抛出 AgentNotFoundError。"""
        message = Message(
            sender="user",
            recipient="nonexistent",
            content="Hello",
        )
        with pytest.raises(AgentNotFoundError, match="nonexistent"):
            await router.route(message)

    @pytest.mark.asyncio
    async def test_route_timeout(self, router: MessageRouter, registry_with_agents: tuple) -> None:
        """路由超时抛出 CommunicationTimeoutError。"""
        registry, handles = registry_with_agents

        message = Message(
            sender="user",
            recipient="agent-a",
            content="Hello",
        )

        # 模拟一个永远不返回的调用
        async def _hang(msg: Message) -> Message:
            await asyncio.sleep(100)
            return Message(sender="agent-a", recipient="user", content="never")

        handles["agent-a"].receive = AsyncMock(side_effect=_hang)

        with pytest.raises(CommunicationTimeoutError):
            await router.route(message, timeout=0.1)

    @pytest.mark.asyncio
    async def test_route_broadcast(
        self, router: MessageRouter, registry_with_agents: tuple
    ) -> None:
        """广播消息到所有 Agent。"""
        registry, handles = registry_with_agents

        for name in ["agent-a", "agent-b"]:
            mock_reply = Message(
                sender=name,
                recipient="user",
                content=f"Broadcast response from {name}",
                type=MessageType.RESULT,
            )
            handles[name].receive = AsyncMock(return_value=mock_reply)

        message = Message(
            sender="user",
            recipient="*",
            content="Broadcast message",
            type=MessageType.BROADCAST,
        )

        responses = await router.broadcast(message)
        assert len(responses) == 2
        contents = [r.content for r in responses]
        assert "Broadcast response from agent-a" in contents
        assert "Broadcast response from agent-b" in contents

    @pytest.mark.asyncio
    async def test_broadcast_exclude_sender(
        self, router: MessageRouter, registry_with_agents: tuple
    ) -> None:
        """广播排除指定 Agent。"""
        registry, handles = registry_with_agents

        message = Message(
            sender="agent-a",
            recipient="*",
            content="Broadcast from agent-a",
            type=MessageType.BROADCAST,
        )

        # agent-a 是发送者，应该被排除，只有 agent-b 收到
        mock_reply = Message(
            sender="agent-b",
            recipient="agent-a",
            content="Got it",
            type=MessageType.RESULT,
        )
        handles["agent-b"].receive = AsyncMock(return_value=mock_reply)

        responses = await router.broadcast(message)
        assert len(responses) == 1
        assert responses[0].sender == "agent-b"

    @pytest.mark.asyncio
    async def test_send_and_wait(self, router: MessageRouter, registry_with_agents: tuple) -> None:
        """便捷方法 send_and_wait。"""
        registry, handles = registry_with_agents

        mock_reply = Message(
            sender="agent-a",
            recipient="user",
            content="Quick response",
            type=MessageType.RESULT,
        )
        handles["agent-a"].receive = AsyncMock(return_value=mock_reply)

        response = await router.send_and_wait(
            target="agent-a",
            content="Quick question",
            sender="user",
        )
        assert response.content == "Quick response"

    @pytest.mark.asyncio
    async def test_broadcast_empty_registry(self) -> None:
        """空 Registry 广播返回空列表。"""
        registry = AgentRegistry()
        router = MessageRouter(registry)

        message = Message(
            sender="user",
            recipient="*",
            content="Anybody there?",
        )
        responses = await router.broadcast(message)
        assert responses == []

    @pytest.mark.asyncio
    async def test_route_handles_actor_error(
        self, router: MessageRouter, registry_with_agents: tuple
    ) -> None:
        """路由过程中 Actor 抛出异常时转换为 RoutingError。"""
        registry, handles = registry_with_agents

        message = Message(
            sender="user",
            recipient="agent-a",
            content="Hello",
        )

        # 模拟 Actor 调用抛出异常
        async def _fail(msg: Message) -> Message:
            raise RuntimeError("Actor internal error")

        handles["agent-a"].receive = AsyncMock(side_effect=_fail)

        with pytest.raises(RoutingError, match="Failed to route"):
            await router.route(message, timeout=1.0)

    @pytest.mark.asyncio
    async def test_route_infinite_wait(self, registry_with_agents: tuple) -> None:
        """timeout=-1 表示无限等待，不触发超时。"""
        registry, handles = registry_with_agents
        router = MessageRouter(registry, default_timeout=5.0)

        mock_reply = Message(
            sender="agent-a",
            recipient="user",
            content="Delayed response",
            type=MessageType.RESULT,
        )
        handles["agent-a"].receive = AsyncMock(return_value=mock_reply)

        message = Message(
            sender="user",
            recipient="agent-a",
            content="Hello with infinite wait",
        )

        response = await router.route(message, timeout=-1)
        assert response.content == "Delayed response"

    @pytest.mark.asyncio
    async def test_send_and_wait_infinite_wait(self, router: MessageRouter, registry_with_agents: tuple) -> None:
        """send_and_wait 支持 timeout=-1 无限等待。"""
        registry, handles = registry_with_agents

        mock_reply = Message(
            sender="agent-a",
            recipient="user",
            content="Infinite wait response",
            type=MessageType.RESULT,
        )
        handles["agent-a"].receive = AsyncMock(return_value=mock_reply)

        response = await router.send_and_wait(
            target="agent-a",
            content="Hello",
            timeout=-1,
        )
        assert response.content == "Infinite wait response"
