# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import asyncio
import logging
from collections import deque
from typing import Any

from ghrah.core.server.connection_manager import ConnectionManager
from ghrah.protocol.types import (
    ClientType,
    EventType,
    Message,
)

logger = logging.getLogger(__name__)


class EventStore:
    def __init__(self, capacity: int = 1000) -> None:
        self._capacity = capacity
        self._buffer: deque[tuple[int, dict[str, Any]]] = deque()
        self._seq_counter: int = 0

    def store(self, event_dict: dict[str, Any]) -> int:
        self._seq_counter += 1
        self._buffer.append((self._seq_counter, event_dict))
        while len(self._buffer) > self._capacity:
            self._buffer.popleft()
        return self._seq_counter

    def replay_since(self, last_seq_id: int) -> list[dict[str, Any]]:
        return [evt for seq, evt in self._buffer if seq > last_seq_id]


class EventBus:
    EVENT_CLIENT_TYPE_MAP: dict[str, list[ClientType]] = {
        EventType.ABILITY_RESULT.value: [ClientType.SUBJECT],
        EventType.AGENT_SPAWNED.value: [ClientType.SUBJECT],
        EventType.AGENT_TERMINATED.value: [ClientType.SUBJECT],
        EventType.AGENT_RESPONSE.value: [ClientType.SUBJECT],
        EventType.ACTION_CHAIN_UPDATED.value: [ClientType.SUBJECT],
        EventType.AGENT_ERROR.value: [ClientType.SUBJECT],
        EventType.HEALTH_STATUS.value: [ClientType.SUBJECT],
        EventType.HITL_REQUEST.value: [ClientType.SUBJECT],
        EventType.WORKSPACE_CREATED.value: [ClientType.SUBJECT],
        EventType.WORKSPACE_DESTROYED.value: [ClientType.SUBJECT],
        EventType.WORKSPACE_SNAPSHOT_CREATED.value: [ClientType.SUBJECT],
        EventType.WORKSPACE_ROLLED_BACK.value: [ClientType.SUBJECT],
        EventType.MANIFEST_ABILITY_CREATED.value: [ClientType.SUBJECT],
        EventType.MANIFEST_ABILITY_UPDATED.value: [ClientType.SUBJECT],
        EventType.MANIFEST_ABILITY_DELETED.value: [ClientType.SUBJECT],
        EventType.MANIFEST_AGENT_CREATED.value: [ClientType.SUBJECT],
        EventType.MANIFEST_AGENT_UPDATED.value: [ClientType.SUBJECT],
        EventType.MANIFEST_AGENT_DELETED.value: [ClientType.SUBJECT],
        EventType.SESSION_CREATED.value: [ClientType.SUBJECT],
        EventType.SESSION_SWITCHED.value: [ClientType.SUBJECT],
        EventType.SESSION_ARCHIVED.value: [ClientType.SUBJECT],
        EventType.SESSION_DELETED.value: [ClientType.SUBJECT],
        EventType.SESSION_LIST_RESULT.value: [ClientType.SUBJECT],
    }

    def __init__(self, connection_manager: ConnectionManager) -> None:
        self._connection_manager = connection_manager
        self._running = False
        self._event_queue: asyncio.Queue[Message] = asyncio.Queue()
        self.event_store = EventStore()

    async def start(self) -> None:
        self._running = True
        logger.info("EventBus started")

    async def stop(self) -> None:
        self._running = False
        logger.info("EventBus stopped")

    def subscribe(
        self,
        session_id: str,
        agent_names: list[str] | None = None,
        event_types: list[str] | None = None,
    ) -> None:
        self._connection_manager.subscribe(
            session_id=session_id,
            agent_names=agent_names,
            event_types=event_types,
        )

    async def publish(
        self,
        event: Message,
        client_type: ClientType | None = None,
    ) -> int:
        event_type = event.type
        agent_name = event.payload.get("agent_name")

        message_dict = event.model_dump_with_timestamp()

        seq_id = self.event_store.store(message_dict)
        message_dict["seq_id"] = seq_id

        if client_type is not None:
            sent_count = await self._connection_manager.broadcast(
                message=message_dict,
                agent_name=agent_name,
                event_type=event_type,
            )
        else:
            target_types = self.EVENT_CLIENT_TYPE_MAP.get(
                event_type, [ClientType.SUBJECT]
            )
            sent_count = 0
            for ct in target_types:
                count = await self._connection_manager.broadcast(
                    message=message_dict,
                    agent_name=agent_name,
                    event_type=event_type,
                )
                sent_count += count

        logger.debug(
            f"Event '{event_type}' published to {sent_count} sessions "
            f"(agent={agent_name})"
        )
        return sent_count

    async def emit(
        self,
        event_type: EventType,
        payload: dict[str, Any],
    ) -> int:
        event = Message(
            type=event_type.value,
            payload=payload,
        )
        return await self.publish(event)

    async def enqueue(self, event: Message) -> None:
        await self._event_queue.put(event)

    async def process_queue(self) -> None:
        while self._running:
            try:
                event = await asyncio.wait_for(
                    self._event_queue.get(), timeout=1.0
                )
                await self.publish(event)
            except TimeoutError:
                continue
            except Exception as e:
                logger.error(f"Error processing event queue: {e}")

    async def emit_agent_spawned(
        self, agent_name: str, config: dict[str, Any]
    ) -> int:
        return await self.emit(
            EventType.AGENT_SPAWNED,
            {"name": agent_name, "config": config},
        )

    async def emit_agent_terminated(self, agent_name: str) -> int:
        return await self.emit(
            EventType.AGENT_TERMINATED,
            {"name": agent_name},
        )

    async def emit_agent_response(
        self,
        sender: str,
        recipient: str,
        content: str,
        message_type: str = "result",
        metadata: dict[str, Any] | None = None,
    ) -> int:
        return await self.emit(
            EventType.AGENT_RESPONSE,
            {
                "sender": sender,
                "recipient": recipient,
                "content": content,
                "message_type": message_type,
                "metadata": metadata or {},
            },
        )

    async def emit_action_chain_updated(
        self,
        agent_name: str,
        node: dict[str, Any],
    ) -> int:
        return await self.emit(
            EventType.ACTION_CHAIN_UPDATED,
            {"agent_name": agent_name, "node": node},
        )

    async def emit_agent_error(
        self, agent_name: str, error: str
    ) -> int:
        return await self.emit(
            EventType.AGENT_ERROR,
            {"agent_name": agent_name, "error": error},
        )

    async def emit_health_status(
        self, status: dict[str, bool]
    ) -> int:
        return await self.emit(
            EventType.HEALTH_STATUS,
            {"status": status},
        )

    async def emit_hitl_request(
        self,
        promise_id: str,
        agent_name: str,
        ability_name: str,
        tool_args: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
    ) -> int:
        return await self.emit(
            EventType.HITL_REQUEST,
            {
                "promise_id": promise_id,
                "agent_name": agent_name,
                "ability_name": ability_name,
                "tool_args": tool_args or {},
                "context": context or {},
            },
        )

    async def emit_ability_result(
        self,
        request_id: str,
        agent_name: str,
        ability_name: str,
        success: bool,
        result: Any = None,
        error: str | None = None,
    ) -> int:
        return await self.emit(
            EventType.ABILITY_RESULT,
            {
                "request_id": request_id,
                "agent_name": agent_name,
                "ability_name": ability_name,
                "success": success,
                "result": result,
                "error": error,
            },
        )

    async def emit_session_created(
        self,
        agent_name: str,
        session_id: str,
        branch_name: str,
        parent_session_id: str | None = None,
        fork_point_node_id: str | None = None,
    ) -> int:
        return await self.emit(
            EventType.SESSION_CREATED,
            {
                "agent_name": agent_name,
                "session_id": session_id,
                "branch_name": branch_name,
                "parent_session_id": parent_session_id,
                "fork_point_node_id": fork_point_node_id,
            },
        )

    async def emit_session_switched(
        self,
        agent_name: str,
        session_id: str,
        branch_name: str,
    ) -> int:
        return await self.emit(
            EventType.SESSION_SWITCHED,
            {
                "agent_name": agent_name,
                "session_id": session_id,
                "branch_name": branch_name,
            },
        )

    async def emit_session_archived(
        self,
        agent_name: str,
        session_id: str,
    ) -> int:
        return await self.emit(
            EventType.SESSION_ARCHIVED,
            {
                "agent_name": agent_name,
                "session_id": session_id,
            },
        )

    async def emit_session_deleted(
        self,
        agent_name: str,
        session_id: str,
    ) -> int:
        return await self.emit(
            EventType.SESSION_DELETED,
            {
                "agent_name": agent_name,
                "session_id": session_id,
            },
        )
