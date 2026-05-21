# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""ghrah-core 事件定义。

与 ghrah-protocol 的 EventType 对齐，定义 Core 侧产生的事件类型。
Core 产生的事件通过 EventBus 推送到 Subject 连接，
Subject 再将相关事件转发给 Observer。

事件流方向：
    Core → Subject（确认/记录）→ Observer（渲染/审批）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

__all__ = [
    "CoreEventType",
    "CoreEvent",
    "HITLRequestEvent",
    "ActionChainUpdatedEvent",
    "AgentErrorEvent",
    "AgentResponseEvent",
]


class CoreEventType(str, Enum):
    """Core 产生的事件类型。

    与 ghrah-protocol 的 EventType 对齐：
    - HITL_REQUEST ↔ EventType.HITL_REQUEST
    - ACTION_CHAIN_UPDATED ↔ EventType.ACTION_CHAIN_UPDATED
    - AGENT_ERROR ↔ EventType.AGENT_ERROR
    - AGENT_RESPONSE ↔ EventType.AGENT_RESPONSE
    """

    HITL_REQUEST = "hitl_request"
    ACTION_CHAIN_UPDATED = "action_chain_updated"
    AGENT_ERROR = "agent_error"
    AGENT_RESPONSE = "agent_response"


@dataclass
class CoreEvent:
    """Core 事件基类。

    Attributes:
        event_type: 事件类型
        agent_name: 产生事件的 Agent 名称
        data: 事件附加数据
    """

    event_type: CoreEventType
    agent_name: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class HITLRequestEvent(CoreEvent):
    """HITL 请求事件。

    Agent 需要人类批准时产生此事件，经 Core Server 推送给 Subject。
    Subject 的 HITLNotary 记录后广播给 Observer 渲染审批界面。

    Attributes:
        ability_name: 请求 HITL 的 Ability 名称
        tool_call: 工具调用参数
        context: 附加上下文（含 tool_call_id）
    """

    event_type: CoreEventType = field(default=CoreEventType.HITL_REQUEST, init=False)
    ability_name: str = ""
    tool_call: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class ActionChainUpdatedEvent(CoreEvent):
    """ActionChain 变更事件。

    ContextManager commit/rollback 时产生此事件。
    Subject 的 ActionChainLedger 持久化后广播给 Observer 渲染 Timeline。

    Attributes:
        node: 变更的节点数据
    """

    event_type: CoreEventType = field(default=CoreEventType.ACTION_CHAIN_UPDATED, init=False)
    node: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentErrorEvent(CoreEvent):
    """Agent 错误事件。

    Agent 驱动循环发生错误时产生此事件。

    Attributes:
        error: 错误信息
    """

    event_type: CoreEventType = field(default=CoreEventType.AGENT_ERROR, init=False)
    error: str = ""


@dataclass
class AgentResponseEvent(CoreEvent):
    """Agent 响应事件。

    Agent 完成任务产生最终回复时产生此事件。

    Attributes:
        content: 响应内容
        message_type: 消息类型（result/error/delegate）
        metadata: 附加元数据
    """

    event_type: CoreEventType = field(default=CoreEventType.AGENT_RESPONSE, init=False)
    content: str = ""
    message_type: str = "result"
    metadata: dict[str, Any] = field(default_factory=dict)
