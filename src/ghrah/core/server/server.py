# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import asyncio
import logging
import uuid

from fastapi import WebSocket, WebSocketDisconnect

from ghrah.core.server.config import CoreServerConfig
from ghrah.core.server.connection_manager import ConnectionManager
from ghrah.core.server.event_bus import EventBus
from ghrah.core.server.router import MessageRouter
from ghrah.protocol.types import (
    CommandType,
    EventType,
    Message,
    SystemType,
    create_error,
    create_pong,
)

logger = logging.getLogger(__name__)


class WebSocketServer:
    def __init__(
        self,
        config: CoreServerConfig,
        connection_manager: ConnectionManager,
        router: MessageRouter,
        event_bus: EventBus,
    ) -> None:
        self._config = config
        self._connection_manager = connection_manager
        self._router = router
        self._event_bus = event_bus
        self._session_tasks: dict[str, set[asyncio.Task[None]]] = {}

    async def handle_connection(
        self,
        websocket: WebSocket,
    ) -> None:
        session_id = uuid.uuid4().hex[:16]

        client_id = websocket.query_params.get("client_id")

        if client_id:
            evicted = self._connection_manager.disconnect_by_client_id(client_id)
            if evicted:
                logger.info(
                    f"Evicted stale session {evicted} for client_id={client_id}"
                )

        try:
            await self._connection_manager.connect(
                session_id, websocket, client_id=client_id
            )
            logger.info(f"WebSocket session established: {session_id}")

            await self._connection_manager.send_to(
                session_id,
                Message(
                    type=SystemType.COMMAND_RESULT.value,
                    payload={
                        "success": True,
                        "data": {
                            "session_id": session_id,
                            "message": "Connected to ghrah-core",
                        },
                    },
                    request_id="connect",
                ).model_dump_with_timestamp(),
            )

            last_seq_id = 0
            try:
                raw_seq = websocket.query_params.get("last_seq_id", "0")
                last_seq_id = int(raw_seq)
            except (ValueError, TypeError):
                last_seq_id = 0

            if last_seq_id > 0:
                replay_events = self._event_bus.event_store.replay_since(last_seq_id)
                if replay_events:
                    logger.info(
                        f"Replaying {len(replay_events)} events to "
                        f"session {session_id} (last_seq_id={last_seq_id})"
                    )
                    for event_dict in replay_events:
                        await self._connection_manager.send_to(session_id, event_dict)

            await self._message_loop(session_id, websocket)

        except WebSocketDisconnect:
            logger.info(f"WebSocket disconnected: {session_id}")
        except Exception as e:
            logger.error(f"WebSocket error for session {session_id}: {e}")
        finally:
            self._cancel_session_tasks(session_id)
            self._connection_manager.disconnect(session_id)
            logger.info(f"Session cleaned up: {session_id}")

    async def _message_loop(
        self,
        session_id: str,
        websocket: WebSocket,
    ) -> None:
        self._session_tasks[session_id] = set()

        while True:
            try:
                raw_data = await websocket.receive_json()
            except WebSocketDisconnect:
                logger.info(f"WebSocket normal close from session {session_id}")
                break
            except Exception as e:
                logger.warning(f"Failed to receive message from {session_id}: {e}")
                break

            try:
                message = Message(**raw_data)
            except Exception as e:
                error_msg = create_error(
                    code="INVALID_MESSAGE",
                    message=f"Failed to parse message: {e}",
                )
                await self._connection_manager.send_to(
                    session_id, error_msg.model_dump_with_timestamp()
                )
                continue

            if message.type == SystemType.PING.value:
                pong = create_pong()
                await self._connection_manager.send_to(
                    session_id, pong.model_dump_with_timestamp()
                )
                continue

            if message.type == SystemType.COMMAND_RESULT.value:
                handled = await self._router.resolve_command_result(
                    message, session_id
                )
                if handled:
                    logger.debug(
                        f"Resolved pending request for "
                        f"command_result (session={session_id})"
                    )
                else:
                    logger.debug(
                        f"Unmatched command_result from "
                        f"session {session_id}: "
                        f"request_id={message.request_id}"
                    )
                continue

            if message.type == EventType.ABILITY_RESULT.value:
                resolved = await self._router.resolve_ability_result(
                    message, session_id
                )
                if resolved:
                    await self._event_bus.publish(message)
                    continue

            known_event_types = {e.value for e in EventType}
            if message.type in known_event_types and message.type != CommandType.HITL_RESPONSE.value:
                await self._router.handle_event(message, session_id)
                continue

            task = asyncio.create_task(
                self._handle_command_async(message, session_id),
                name=f"cmd-{session_id[:8]}-{message.type}",
            )
            self._session_tasks.setdefault(session_id, set()).add(task)
            task.add_done_callback(
                lambda t, sid=session_id: self._session_tasks.get(sid, set()).discard(t)
            )

    async def _handle_command_async(
        self, message: Message, session_id: str
    ) -> None:
        try:
            result = await self._router.handle_command(message, session_id)
            if result is not None:
                await self._connection_manager.send_to(
                    session_id, result.model_dump_with_timestamp()
                )
        except Exception as e:
            logger.error(f"Error in async command from {session_id}: {e}")
            error_msg = create_error(
                code="COMMAND_ERROR",
                message=str(e),
                request_id=message.request_id,
            )
            await self._connection_manager.send_to(
                session_id, error_msg.model_dump_with_timestamp()
            )

    def _cancel_session_tasks(self, session_id: str) -> None:
        tasks = self._session_tasks.pop(session_id, set())
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            logger.info(
                f"Cancelled {len(tasks)} background task(s) for session {session_id}"
            )
