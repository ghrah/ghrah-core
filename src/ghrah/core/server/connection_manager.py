# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import logging
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class WebSocketConnectionError(Exception):
    def __init__(self, session_id: str, message: str):
        self.session_id = session_id
        super().__init__(f"Connection[{session_id}]: {message}")


class SubscriptionError(Exception):
    def __init__(self, session_id: str, message: str):
        self.session_id = session_id
        super().__init__(f"Subscription[{session_id}]: {message}")


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[str, WebSocket] = {}
        self._subscriptions: dict[str, set[str]] = {}
        self._event_subscriptions: dict[str, set[str]] = {}
        self._client_ids: dict[str, str] = {}

    async def connect(
        self,
        session_id: str,
        websocket: WebSocket,
        client_id: str | None = None,
    ) -> None:
        if session_id in self._connections:
            raise WebSocketConnectionError(session_id, "Session already connected")

        await websocket.accept()
        self._connections[session_id] = websocket
        self._subscriptions[session_id] = {"*"}
        self._event_subscriptions[session_id] = set()
        if client_id is not None:
            self._client_ids[client_id] = session_id
        logger.info(
            f"Session connected: {session_id}"
            f"{f', client_id={client_id}' if client_id else ''})"
        )

    def disconnect(self, session_id: str) -> None:
        self._connections.pop(session_id, None)
        self._subscriptions.pop(session_id, None)
        self._event_subscriptions.pop(session_id, None)
        stale_cids = [cid for cid, sid in self._client_ids.items() if sid == session_id]
        for cid in stale_cids:
            del self._client_ids[cid]
        logger.info(f"Session disconnected: {session_id}")

    def disconnect_by_client_id(self, client_id: str) -> str | None:
        old_session_id = self._client_ids.pop(client_id, None)
        if old_session_id is None:
            return None
        if old_session_id in self._connections:
            self.disconnect(old_session_id)
            logger.info(f"Evicted stale session {old_session_id} for client_id={client_id}")
        return old_session_id

    def get_connection(self, session_id: str) -> WebSocket | None:
        return self._connections.get(session_id)

    @property
    def active_sessions(self) -> list[str]:
        return list(self._connections.keys())

    @property
    def connection_count(self) -> int:
        return len(self._connections)

    def get_subscription_info(self, session_id: str) -> dict[str, list[str]]:
        return {
            "subscribed_agents": list(self._subscriptions.get(session_id, set())),
            "subscribed_events": list(self._event_subscriptions.get(session_id, set())),
        }

    def subscribe(
        self,
        session_id: str,
        agent_names: list[str] | None = None,
        event_types: list[str] | None = None,
    ) -> None:
        if session_id not in self._connections:
            raise SubscriptionError(session_id, "Session not found")

        if agent_names is not None:
            if "*" in agent_names:
                self._subscriptions[session_id] = {"*"}
            else:
                current = self._subscriptions.get(session_id, set())
                if "*" in current:
                    self._subscriptions[session_id] = set(agent_names)
                else:
                    current.update(agent_names)
                    self._subscriptions[session_id] = current

        if event_types is not None:
            self._event_subscriptions[session_id] = set(event_types)

        logger.debug(
            f"Session {session_id} subscribed: "
            f"agents={self._subscriptions.get(session_id)}, "
            f"events={self._event_subscriptions.get(session_id)}"
        )

    def unsubscribe(
        self,
        session_id: str,
        agent_names: list[str] | None = None,
        event_types: list[str] | None = None,
    ) -> None:
        if session_id not in self._connections:
            raise SubscriptionError(session_id, "Session not found")

        if agent_names is not None:
            current = self._subscriptions.get(session_id, set())
            current -= set(agent_names)
            self._subscriptions[session_id] = current

        if event_types is not None:
            current = self._event_subscriptions.get(session_id, set())
            current -= set(event_types)
            self._event_subscriptions[session_id] = current

        logger.debug(
            f"Session {session_id} unsubscribed: "
            f"agents={self._subscriptions.get(session_id)}, "
            f"events={self._event_subscriptions.get(session_id)}"
        )

    def get_subscribed_sessions(
        self,
        agent_name: str | None = None,
        event_type: str | None = None,
    ) -> list[str]:
        result: list[str] = []

        for session_id, subscribed_agents in self._subscriptions.items():
            agent_match = (
                "*" in subscribed_agents
                or agent_name is None
                or agent_name in subscribed_agents
            )

            event_subs = self._event_subscriptions.get(session_id, set())
            event_match = (
                len(event_subs) == 0
                or event_type is None
                or event_type in event_subs
            )

            if agent_match and event_match:
                result.append(session_id)

        return result

    async def broadcast(
        self,
        message: dict[str, Any],
        agent_name: str | None = None,
        event_type: str | None = None,
        exclude_session: str | None = None,
    ) -> int:
        target_sessions = self.get_subscribed_sessions(agent_name, event_type)

        if exclude_session and exclude_session in target_sessions:
            target_sessions.remove(exclude_session)

        sent_count = 0
        failed_sessions: list[str] = []
        for session_id in target_sessions:
            websocket = self._connections.get(session_id)
            if websocket is None:
                continue

            try:
                await websocket.send_json(message)
                sent_count += 1
            except Exception:
                logger.warning(f"Failed to send to session {session_id}, removing")
                failed_sessions.append(session_id)

        for session_id in failed_sessions:
            self.disconnect(session_id)

        return sent_count

    async def send_to(self, session_id: str, message: dict[str, Any]) -> bool:
        websocket = self._connections.get(session_id)
        if websocket is None:
            logger.warning(f"Session {session_id} not found for send")
            return False

        try:
            await websocket.send_json(message)
            return True
        except Exception:
            logger.warning(f"Failed to send to session {session_id}")
            self.disconnect(session_id)
            return False
