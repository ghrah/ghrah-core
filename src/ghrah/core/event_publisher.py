# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""事件发布接口。

定义 ghrah-core 的事件发布抽象，支持：
1. 本地模式：事件仅记录日志（NullEventPublisher，默认行为）
2. Unit 挂载模式：事件由宿主注入的 EventPublisher 实现处理（如 CoreUnit 的
   UnitEventPublisher，通过 ctx.emit 推送到宿主事件流）

设计原则：
- 显式优先于隐式：EventPublisher 通过注入方式使用，默认为 NullEventPublisher
- 事件流方向：Core → EventPublisher → Subject（确认/记录）→ Observer（渲染/审批）
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from ghrah.core.events import CoreEvent

logger = logging.getLogger(__name__)

__all__ = ["EventPublisher", "NullEventPublisher"]


class EventPublisher(ABC):
    """事件发布接口。

    所有方法为 async，实现类可对接本地日志、宿主事件流等。
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
