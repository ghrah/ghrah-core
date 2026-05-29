# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""事件发布接口。

定义 ghrah-core 的事件发布抽象，支持：
1. 本地模式：事件仅记录日志（NullEventPublisher，默认行为）
2. 服务器模式：事件通过本地 EventBus 推送到连接的 Subject/Observer（ServerEventPublisher）

设计原则：
- 显式优先于隐式：EventPublisher 通过注入方式使用，默认为 NullEventPublisher
- 事件流方向：Core → EventBus → Subject（确认/记录）→ Observer（渲染/审批）
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

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
from ghrah.protocol.types import Message

if TYPE_CHECKING:
    from ghrah.core.server.event_bus import EventBus

logger = logging.getLogger(__name__)

__all__ = ["EventPublisher", "NullEventPublisher", "ServerEventPublisher"]


class EventPublisher(ABC):
    """事件发布接口。

    所有方法为 async，实现类可对接本地日志、服务器 EventBus 等。
    """

    @abstractmethod
    async def publish(self, event: CoreEvent) -> None:
        """发布事件。

        Args:
            event: Core 事件
        """
        ...


class NullEventPublisher(EventPublisher):
    """空实现 — 本地模式使用，仅记录日志。

    作为 ActorAgent 的默认 EventPublisher，确保本地模式零侵入。
    不推送任何事件到外部系统。
    """

    async def publish(self, event: CoreEvent) -> None:
        """仅记录日志，不推送。"""
        logger.debug(
            f"Event published (null): {event.event_type.value} for agent {event.agent_name}"
        )


class ServerEventPublisher(EventPublisher):
    """通过本地 EventBus 推送事件到连接的 Subject/Observer。

    在服务器模式下注入到 ActorAgent，将 Core 事件发布到本地 EventBus，
    由 EventBus 广播到所有订阅的 Subject 和 Observer 连接。

    Attributes:
        _event_bus: 服务器 EventBus 实例
    """

    def __init__(self, event_bus: EventBus) -> None:
        """初始化 ServerEventPublisher。

        Args:
            event_bus: 服务器 EventBus 实例
        """
        self._event_bus = event_bus

    async def publish(self, event: CoreEvent) -> None:
        """通过 EventBus 将事件发布到服务器。

        将 CoreEvent 转换为 Message 并发布到本地 EventBus。

        Args:
            event: Core 事件
        """
        try:
            message = self._create_event_message(event)
            msg = Message(
                type=message["type"],
                payload=message["payload"],
            )
            await self._event_bus.publish(msg)
            logger.debug(
                f"Event published (server): {event.event_type.value} for agent {event.agent_name}"
            )
        except Exception as e:
            logger.error(
                f"Failed to publish event {event.event_type.value} "
                f"for agent {event.agent_name}: {e}"
            )

    def _create_event_message(self, event: CoreEvent) -> dict:
        """将 CoreEvent 转换为服务器消息格式。

        Args:
            event: Core 事件

        Returns:
            服务器消息字典
        """
        event_type_map = {
            CoreEventType.HITL_REQUEST: "hitl_request",
            CoreEventType.ACTION_CHAIN_UPDATED: "action_chain_updated",
            CoreEventType.AGENT_ERROR: "agent_error",
            CoreEventType.AGENT_RESPONSE: "agent_response",
            CoreEventType.SESSION_CREATED: "session_created",
            CoreEventType.SESSION_SWITCHED: "session_switched",
            CoreEventType.SESSION_ARCHIVED: "session_archived",
            CoreEventType.SESSION_DELETED: "session_deleted",
        }

        payload: dict = {
            "agent_name": event.agent_name,
            "event_type": event_type_map.get(event.event_type.value, event.event_type.value),
        }

        if isinstance(event, HITLRequestEvent):
            payload.update(
                {
                    "ability_name": event.ability_name,
                    "tool_call": event.tool_call,
                    "context": event.context,
                }
            )
        elif isinstance(event, ActionChainUpdatedEvent):
            payload.update(
                {
                    "node": event.node,
                }
            )
        elif isinstance(event, AgentErrorEvent):
            payload.update(
                {
                    "error": event.error,
                }
            )
        elif isinstance(event, AgentResponseEvent):
            payload_update: dict[str, Any] = {
                "content": event.content,
                "message_type": event.message_type,
                "metadata": event.metadata,
            }
            if event.content_blocks is not None:
                payload_update["content_blocks"] = event.content_blocks
            payload.update(payload_update)
        elif isinstance(event, SessionCreatedEvent):
            payload.update(
                {
                    "session_id": event.session_id,
                    "branch_name": event.branch_name,
                    "parent_session_id": event.parent_session_id,
                    "fork_point_node_id": event.fork_point_node_id,
                }
            )
        elif isinstance(event, SessionSwitchedEvent):
            payload.update(
                {
                    "session_id": event.session_id,
                    "branch_name": event.branch_name,
                }
            )
        elif isinstance(event, SessionArchivedEvent):
            payload.update(
                {
                    "session_id": event.session_id,
                }
            )
        elif isinstance(event, SessionDeletedEvent):
            payload.update(
                {
                    "session_id": event.session_id,
                }
            )

        event_type_str = event_type_map.get(event.event_type.value, event.event_type.value)
        return {
            "type": event_type_str,
            "payload": payload,
        }



