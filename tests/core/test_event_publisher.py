# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""EventPublisher 和事件类型测试。

测试事件发布机制的核心功能：
- CoreEventType 枚举值
- CoreEvent 数据类
- HITLRequestEvent / ActionChainUpdatedEvent / AgentErrorEvent / AgentResponseEvent
- NullEventPublisher 行为
- ServerEventPublisher 消息格式转换（通过 EventBus）
"""

from unittest.mock import AsyncMock

import pytest

from ghrah.core.event_publisher import EventPublisher, NullEventPublisher, ServerEventPublisher
from ghrah.core.events import (
    ActionChainUpdatedEvent,
    AgentErrorEvent,
    AgentResponseEvent,
    CoreEvent,
    CoreEventType,
    HITLRequestEvent,
    SessionArchivedEvent,
    SessionCreatedEvent,
    SessionDeletedEvent,
    SessionSwitchedEvent,
)


class MockEventBus:
    """模拟 EventBus，记录 publish 调用。"""

    def __init__(self) -> None:
        self.published_events: list = []

    async def publish(self, event: object) -> int:
        self.published_events.append(event)
        return 1


class TestCoreEventType:
    """CoreEventType 枚举测试。"""

    def test_event_type_values(self) -> None:
        """测试事件类型枚举值。"""
        assert CoreEventType.HITL_REQUEST.value == "hitl_request"
        assert CoreEventType.ACTION_CHAIN_UPDATED.value == "action_chain_updated"
        assert CoreEventType.AGENT_ERROR.value == "agent_error"
        assert CoreEventType.AGENT_RESPONSE.value == "agent_response"

    def test_event_type_is_string(self) -> None:
        """测试事件类型是字符串枚举。"""
        assert isinstance(CoreEventType.HITL_REQUEST, str)


class TestCoreEventDataclasses:
    """CoreEvent 数据类测试。"""

    def test_core_event_base(self) -> None:
        """测试 CoreEvent 基类。"""
        event = CoreEvent(
            event_type=CoreEventType.AGENT_ERROR,
            agent_name="test-agent",
            data={"key": "value"},
        )
        assert event.event_type == CoreEventType.AGENT_ERROR
        assert event.agent_name == "test-agent"
        assert event.data == {"key": "value"}

    def test_core_event_default_data(self) -> None:
        """测试 CoreEvent 默认 data 为空字典。"""
        event = CoreEvent(
            event_type=CoreEventType.AGENT_ERROR,
            agent_name="test-agent",
        )
        assert event.data == {}

    def test_hitl_request_event(self) -> None:
        """测试 HITLRequestEvent。"""
        event = HITLRequestEvent(
            agent_name="test-agent",
            ability_name="write_file",
            tool_call={"path": "/tmp/test.txt", "content": "hello"},
            context={"tool_call_id": "abc123"},
        )
        assert event.event_type == CoreEventType.HITL_REQUEST
        assert event.agent_name == "test-agent"
        assert event.ability_name == "write_file"
        assert event.tool_call == {"path": "/tmp/test.txt", "content": "hello"}
        assert event.context == {"tool_call_id": "abc123"}

    def test_hitl_request_event_defaults(self) -> None:
        """测试 HITLRequestEvent 默认值。"""
        event = HITLRequestEvent(agent_name="test-agent")
        assert event.event_type == CoreEventType.HITL_REQUEST
        assert event.ability_name == ""
        assert event.tool_call == {}
        assert event.context == {}

    def test_action_chain_updated_event(self) -> None:
        """测试 ActionChainUpdatedEvent。"""
        event = ActionChainUpdatedEvent(
            agent_name="test-agent",
            node={"id": "node-1", "action": "read_file"},
        )
        assert event.event_type == CoreEventType.ACTION_CHAIN_UPDATED
        assert event.node == {"id": "node-1", "action": "read_file"}

    def test_agent_error_event(self) -> None:
        """测试 AgentErrorEvent。"""
        event = AgentErrorEvent(
            agent_name="test-agent",
            error="LLM timeout",
        )
        assert event.event_type == CoreEventType.AGENT_ERROR
        assert event.error == "LLM timeout"

    def test_agent_response_event(self) -> None:
        """测试 AgentResponseEvent。"""
        event = AgentResponseEvent(
            agent_name="test-agent",
            content="Task completed",
            message_type="result",
            metadata={"tokens": 150},
        )
        assert event.event_type == CoreEventType.AGENT_RESPONSE
        assert event.content == "Task completed"
        assert event.message_type == "result"
        assert event.metadata == {"tokens": 150}

    def test_agent_response_event_defaults(self) -> None:
        """测试 AgentResponseEvent 默认值。"""
        event = AgentResponseEvent(agent_name="test-agent")
        assert event.event_type == CoreEventType.AGENT_RESPONSE
        assert event.content == ""
        assert event.content_blocks is None
        assert event.message_type == "result"
        assert event.metadata == {}

    def test_agent_response_event_with_content_blocks(self) -> None:
        """测试 AgentResponseEvent 带 content_blocks。"""
        blocks = [
            {"type": "reasoning", "reasoning": "思考..."},
            {"type": "text", "text": "回复"},
        ]
        event = AgentResponseEvent(
            agent_name="test-agent",
            content="回复",
            content_blocks=blocks,
            message_type="result",
        )
        assert event.content_blocks is not None
        assert len(event.content_blocks) == 2
        assert event.content_blocks[0]["type"] == "reasoning"
        assert event.content_blocks[1]["type"] == "text"


class TestNullEventPublisher:
    """NullEventPublisher 测试。"""

    @pytest.mark.asyncio
    async def test_publish_does_not_raise(self) -> None:
        """测试 NullEventPublisher.publish() 不抛异常。"""
        publisher = NullEventPublisher()
        event = CoreEvent(
            event_type=CoreEventType.AGENT_ERROR,
            agent_name="test-agent",
        )
        # 应正常完成，不抛异常
        await publisher.publish(event)

    @pytest.mark.asyncio
    async def test_publish_with_hitl_request(self) -> None:
        """测试 NullEventPublisher 发布 HITLRequestEvent。"""
        publisher = NullEventPublisher()
        event = HITLRequestEvent(
            agent_name="test-agent",
            ability_name="write_file",
        )
        await publisher.publish(event)


class TestServerEventPublisher:
    """ServerEventPublisher 测试。"""

    @pytest.mark.asyncio
    async def test_publish_calls_event_bus(self) -> None:
        """测试 ServerEventPublisher 通过 EventBus 发布事件。"""
        event_bus = MockEventBus()
        publisher = ServerEventPublisher(event_bus)

        event = HITLRequestEvent(
            agent_name="test-agent",
            ability_name="write_file",
            tool_call={"path": "/tmp/test.txt"},
            context={"tool_call_id": "abc123"},
        )

        await publisher.publish(event)

        # 验证 EventBus 收到事件
        assert len(event_bus.published_events) == 1

    @pytest.mark.asyncio
    async def test_publish_action_chain_updated(self) -> None:
        """测试发布 ActionChainUpdatedEvent。"""
        event_bus = MockEventBus()
        publisher = ServerEventPublisher(event_bus)

        event = ActionChainUpdatedEvent(
            agent_name="test-agent",
            node={"id": "node-1"},
        )

        await publisher.publish(event)
        assert len(event_bus.published_events) == 1

    @pytest.mark.asyncio
    async def test_publish_agent_error(self) -> None:
        """测试发布 AgentErrorEvent。"""
        event_bus = MockEventBus()
        publisher = ServerEventPublisher(event_bus)

        event = AgentErrorEvent(
            agent_name="test-agent",
            error="LLM timeout",
        )

        await publisher.publish(event)
        assert len(event_bus.published_events) == 1

    @pytest.mark.asyncio
    async def test_publish_agent_response(self) -> None:
        """测试发布 AgentResponseEvent。"""
        event_bus = MockEventBus()
        publisher = ServerEventPublisher(event_bus)

        event = AgentResponseEvent(
            agent_name="test-agent",
            content="Task completed",
            message_type="result",
            metadata={"tokens": 150},
        )

        await publisher.publish(event)
        assert len(event_bus.published_events) == 1

    @pytest.mark.asyncio
    async def test_publish_handles_error_gracefully(self) -> None:
        """测试 ServerEventPublisher 发布失败时不抛异常。"""
        event_bus = MockEventBus()
        event_bus.publish = AsyncMock(side_effect=Exception("EventBus error"))
        publisher = ServerEventPublisher(event_bus)

        event = CoreEvent(
            event_type=CoreEventType.AGENT_ERROR,
            agent_name="test-agent",
        )

        # 应正常完成，不抛异常（错误被捕获并记录日志）
        await publisher.publish(event)

    def test_create_event_message_hitl_request(self) -> None:
        """测试 _create_event_message 生成 HITL 请求消息格式。"""
        event_bus = MockEventBus()
        publisher = ServerEventPublisher(event_bus)

        event = HITLRequestEvent(
            agent_name="test-agent",
            ability_name="write_file",
            tool_call={"path": "/tmp/test.txt"},
            context={"tool_call_id": "abc123"},
        )

        message = publisher._create_event_message(event)

        assert message["type"] == "hitl_request"
        assert "event_type" not in message
        assert message["payload"]["agent_name"] == "test-agent"
        assert message["payload"]["ability_name"] == "write_file"
        assert message["payload"]["tool_call"] == {"path": "/tmp/test.txt"}
        assert message["payload"]["context"] == {"tool_call_id": "abc123"}

    def test_create_event_message_agent_response(self) -> None:
        """测试 _create_event_message 生成 AgentResponse 消息格式。"""
        event_bus = MockEventBus()
        publisher = ServerEventPublisher(event_bus)

        event = AgentResponseEvent(
            agent_name="test-agent",
            content="Task completed",
            message_type="result",
            metadata={"tokens": 150},
        )

        message = publisher._create_event_message(event)

        assert message["type"] == "agent_response"
        assert "event_type" not in message
        assert message["payload"]["agent_name"] == "test-agent"
        assert message["payload"]["content"] == "Task completed"
        assert "content_blocks" not in message["payload"]

    def test_create_event_message_agent_response_with_content_blocks(self) -> None:
        """测试 _create_event_message 含 content_blocks 的 AgentResponse 消息格式。"""
        event_bus = MockEventBus()
        publisher = ServerEventPublisher(event_bus)

        blocks = [
            {"type": "reasoning", "reasoning": "思考过程", "incomplete": False},
            {"type": "text", "text": "最终回复"},
        ]
        event = AgentResponseEvent(
            agent_name="test-agent",
            content="最终回复",
            content_blocks=blocks,
            message_type="result",
            metadata={"tokens": 200},
        )

        message = publisher._create_event_message(event)

        assert message["type"] == "agent_response"
        assert message["payload"]["content"] == "最终回复"
        assert message["payload"]["content_blocks"] == blocks
        assert message["payload"]["content_blocks"][0]["type"] == "reasoning"
        assert message["payload"]["content_blocks"][1]["type"] == "text"

    def test_create_event_message_action_chain_updated(self) -> None:
        """测试 _create_event_message 生成 ActionChainUpdated 消息格式。"""
        event_bus = MockEventBus()
        publisher = ServerEventPublisher(event_bus)

        event = ActionChainUpdatedEvent(
            agent_name="test-agent",
            node={"iteration": 1, "ability_names": ["conversation"]},
        )

        message = publisher._create_event_message(event)

        assert message["type"] == "action_chain_updated"
        assert "event_type" not in message
        assert message["payload"]["agent_name"] == "test-agent"
        assert message["payload"]["node"]["iteration"] == 1

    def test_create_event_message_agent_error(self) -> None:
        """测试 _create_event_message 生成 AgentError 消息格式。"""
        event_bus = MockEventBus()
        publisher = ServerEventPublisher(event_bus)

        event = AgentErrorEvent(
            agent_name="test-agent",
            error="LLM timeout",
        )

        message = publisher._create_event_message(event)

        assert message["type"] == "agent_error"
        assert "event_type" not in message
        assert message["payload"]["agent_name"] == "test-agent"
        assert message["payload"]["error"] == "LLM timeout"





class TestEventPublisherInterface:
    """EventPublisher 接口测试。"""

    def test_null_event_publisher_is_event_publisher(self) -> None:
        """测试 NullEventPublisher 是 EventPublisher 的子类。"""
        assert isinstance(NullEventPublisher(), EventPublisher)

    def test_server_event_publisher_is_event_publisher(self) -> None:
        """测试 ServerEventPublisher 是 EventPublisher 的子类。"""
        event_bus = MockEventBus()
        assert isinstance(ServerEventPublisher(event_bus), EventPublisher)

    def test_cannot_instantiate_abstract_event_publisher(self) -> None:
        """测试不能直接实例化抽象 EventPublisher。"""
        with pytest.raises(TypeError):
            EventPublisher()  # type: ignore[abstract]


class TestSessionEventDataclasses:
    """Session 事件数据类测试。"""

    def test_session_created_event(self) -> None:
        """测试 SessionCreatedEvent。"""
        event = SessionCreatedEvent(
            agent_name="test-agent",
            session_id="sess-123",
            branch_name="session-1",
            parent_session_id="sess-000",
            fork_point_node_id="node-5",
        )
        assert event.event_type == CoreEventType.SESSION_CREATED
        assert event.agent_name == "test-agent"
        assert event.session_id == "sess-123"
        assert event.branch_name == "session-1"
        assert event.parent_session_id == "sess-000"
        assert event.fork_point_node_id == "node-5"

    def test_session_created_event_defaults(self) -> None:
        """测试 SessionCreatedEvent 默认值。"""
        event = SessionCreatedEvent(agent_name="test-agent")
        assert event.event_type == CoreEventType.SESSION_CREATED
        assert event.session_id == ""
        assert event.branch_name == ""
        assert event.parent_session_id is None
        assert event.fork_point_node_id is None

    def test_session_switched_event(self) -> None:
        """测试 SessionSwitchedEvent。"""
        event = SessionSwitchedEvent(
            agent_name="test-agent",
            session_id="sess-456",
            branch_name="session-2",
        )
        assert event.event_type == CoreEventType.SESSION_SWITCHED
        assert event.session_id == "sess-456"
        assert event.branch_name == "session-2"

    def test_session_archived_event(self) -> None:
        """测试 SessionArchivedEvent。"""
        event = SessionArchivedEvent(
            agent_name="test-agent",
            session_id="sess-789",
        )
        assert event.event_type == CoreEventType.SESSION_ARCHIVED
        assert event.session_id == "sess-789"

    def test_session_deleted_event(self) -> None:
        """测试 SessionDeletedEvent。"""
        event = SessionDeletedEvent(
            agent_name="test-agent",
            session_id="sess-999",
        )
        assert event.event_type == CoreEventType.SESSION_DELETED
        assert event.session_id == "sess-999"


class TestSessionEventPublishing:
    """Session 事件发布测试。"""

    @pytest.mark.asyncio
    async def test_publish_session_created_via_null_publisher(self) -> None:
        """测试 NullEventPublisher 发布 SessionCreatedEvent。"""
        publisher = NullEventPublisher()
        event = SessionCreatedEvent(
            agent_name="test-agent",
            session_id="sess-001",
            branch_name="branch-1",
        )
        await publisher.publish(event)

    @pytest.mark.asyncio
    async def test_publish_session_created_via_server_publisher(self) -> None:
        """测试 ServerEventPublisher 发布 SessionCreatedEvent。"""
        event_bus = MockEventBus()
        publisher = ServerEventPublisher(event_bus)

        event = SessionCreatedEvent(
            agent_name="test-agent",
            session_id="sess-001",
            branch_name="branch-1",
            parent_session_id="sess-000",
            fork_point_node_id="node-5",
        )

        await publisher.publish(event)
        assert len(event_bus.published_events) == 1

    @pytest.mark.asyncio
    async def test_publish_session_switched_via_server_publisher(self) -> None:
        """测试 ServerEventPublisher 发布 SessionSwitchedEvent。"""
        event_bus = MockEventBus()
        publisher = ServerEventPublisher(event_bus)

        event = SessionSwitchedEvent(
            agent_name="test-agent",
            session_id="sess-002",
            branch_name="branch-2",
        )

        await publisher.publish(event)
        assert len(event_bus.published_events) == 1

    @pytest.mark.asyncio
    async def test_publish_session_archived_via_server_publisher(self) -> None:
        """测试 ServerEventPublisher 发布 SessionArchivedEvent。"""
        event_bus = MockEventBus()
        publisher = ServerEventPublisher(event_bus)

        event = SessionArchivedEvent(
            agent_name="test-agent",
            session_id="sess-001",
        )

        await publisher.publish(event)
        assert len(event_bus.published_events) == 1

    @pytest.mark.asyncio
    async def test_publish_session_deleted_via_server_publisher(self) -> None:
        """测试 ServerEventPublisher 发布 SessionDeletedEvent。"""
        event_bus = MockEventBus()
        publisher = ServerEventPublisher(event_bus)

        event = SessionDeletedEvent(
            agent_name="test-agent",
            session_id="sess-001",
        )

        await publisher.publish(event)
        assert len(event_bus.published_events) == 1

    def test_create_event_message_session_created(self) -> None:
        """测试 _create_event_message 生成 SessionCreated 消息格式。"""
        event_bus = MockEventBus()
        publisher = ServerEventPublisher(event_bus)

        event = SessionCreatedEvent(
            agent_name="test-agent",
            session_id="sess-001",
            branch_name="branch-1",
            parent_session_id="sess-000",
            fork_point_node_id="node-5",
        )

        message = publisher._create_event_message(event)

        assert message["type"] == "session_created"
        assert message["payload"]["agent_name"] == "test-agent"
        assert message["payload"]["session_id"] == "sess-001"
        assert message["payload"]["branch_name"] == "branch-1"
        assert message["payload"]["parent_session_id"] == "sess-000"
        assert message["payload"]["fork_point_node_id"] == "node-5"

    def test_create_event_message_session_switched(self) -> None:
        """测试 _create_event_message 生成 SessionSwitched 消息格式。"""
        event_bus = MockEventBus()
        publisher = ServerEventPublisher(event_bus)

        event = SessionSwitchedEvent(
            agent_name="test-agent",
            session_id="sess-002",
            branch_name="branch-2",
        )

        message = publisher._create_event_message(event)

        assert message["type"] == "session_switched"
        assert message["payload"]["agent_name"] == "test-agent"
        assert message["payload"]["session_id"] == "sess-002"
        assert message["payload"]["branch_name"] == "branch-2"

    def test_create_event_message_session_archived(self) -> None:
        """测试 _create_event_message 生成 SessionArchived 消息格式。"""
        event_bus = MockEventBus()
        publisher = ServerEventPublisher(event_bus)

        event = SessionArchivedEvent(
            agent_name="test-agent",
            session_id="sess-001",
        )

        message = publisher._create_event_message(event)

        assert message["type"] == "session_archived"
        assert message["payload"]["agent_name"] == "test-agent"
        assert message["payload"]["session_id"] == "sess-001"

    def test_create_event_message_session_deleted(self) -> None:
        """测试 _create_event_message 生成 SessionDeleted 消息格式。"""
        event_bus = MockEventBus()
        publisher = ServerEventPublisher(event_bus)

        event = SessionDeletedEvent(
            agent_name="test-agent",
            session_id="sess-001",
        )

        message = publisher._create_event_message(event)

        assert message["type"] == "session_deleted"
        assert message["payload"]["agent_name"] == "test-agent"
        assert message["payload"]["session_id"] == "sess-001"
