from __future__ import annotations

from typing import Any

from ghrah.protocol.types import (
    AgentSpawnedPayload,
    EventType,
    HealthStatusPayload,
    Message,
)

from ghrah.core.server.connection_manager import ConnectionManager
from ghrah.core.server.event_bus import EventBus


class _FakeWebSocket:
    def __init__(self) -> None:
        self.accepted = False
        self.sent: list[dict[str, Any]] = []

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, message: dict[str, Any]) -> None:
        self.sent.append(message)


async def test_emit_session_events_use_nested_session_payload() -> None:
    manager = ConnectionManager()
    websocket = _FakeWebSocket()
    await manager.connect("subject-1", websocket)
    bus = EventBus(manager)

    created_count = await bus.emit_session_created(
        agent_name="agent-a",
        session_id="session-1",
        branch_name="main",
        parent_session_id="parent-1",
        fork_point_node_id="node-1",
    )
    switched_count = await bus.emit_session_switched(
        agent_name="agent-a",
        session_id="session-2",
        branch_name="feature",
    )

    assert created_count == 1
    assert switched_count == 1

    created = websocket.sent[0]
    assert created["type"] == EventType.SESSION_CREATED.value
    assert created["payload"]["agent_name"] == "agent-a"
    assert created["payload"]["session"]["session_id"] == "session-1"
    assert created["payload"]["session"]["agent_name"] == "agent-a"
    assert created["payload"]["session"]["branch_name"] == "main"
    assert created["payload"]["session"]["parent_session_id"] == "parent-1"
    assert created["payload"]["session"]["fork_point_node_id"] == "node-1"

    switched = websocket.sent[1]
    assert switched["type"] == EventType.SESSION_SWITCHED.value
    assert switched["payload"]["agent_name"] == "agent-a"
    assert switched["payload"]["session"]["session_id"] == "session-2"
    assert switched["payload"]["session"]["branch_name"] == "feature"


async def test_publish_without_agent_name_is_not_filtered_by_agent_subscription() -> None:
    manager = ConnectionManager()
    websocket = _FakeWebSocket()
    await manager.connect("subject-1", websocket)
    manager.subscribe("subject-1", agent_names=["agent-a"])
    bus = EventBus(manager)

    count = await bus.publish(
        Message(
            type=EventType.HEALTH_STATUS.value,
            payload=HealthStatusPayload(status={"ok": True}),
        )
    )

    assert count == 1
    assert websocket.sent[0]["type"] == EventType.HEALTH_STATUS.value


async def test_agent_spawned_name_field_does_not_change_subscription_filter() -> None:
    manager = ConnectionManager()
    websocket = _FakeWebSocket()
    await manager.connect("subject-1", websocket)
    manager.subscribe("subject-1", agent_names=["agent-a"])
    bus = EventBus(manager)

    count = await bus.publish(
        Message(
            type=EventType.AGENT_SPAWNED.value,
            payload=AgentSpawnedPayload.model_validate(
                {"name": "agent-b", "config": {"name": "agent-b"}}
            ),
        )
    )

    assert count == 1
    assert websocket.sent[0]["type"] == EventType.AGENT_SPAWNED.value
