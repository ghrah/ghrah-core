# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""核心抽象层：Agent 配置、消息、异常、事件、HITL 等基础定义"""

from ghrah.core._base_error import ActorAgentError
from ghrah.core.ability_protocol import (
    AbilityProtocol,
    ExecutorProtocol,
    RegistryProtocol,
)
from ghrah.core.command_sender import CommandSender
from ghrah.core.config import AgentConfig, ContextConfig, ModelOverrides, WindowConfig
from ghrah.core.event_publisher import (
    EventPublisher,
    NullEventPublisher,
    ServerEventPublisher,
)
from ghrah.core.events import (
    ActionChainUpdatedEvent,
    AgentErrorEvent,
    AgentResponseEvent,
    CoreEvent,
    CoreEventType,
    HITLRequestEvent,
)
from ghrah.core.exceptions import (
    AgentError,
    AgentInitializationError,
    AgentTimeoutError,
    CommunicationTimeoutError,
    HookError,
    RoutingError,
    ToolError,
)
from ghrah.core.hitl import HITLFutureStore, HITLResult
from ghrah.core.llm_protocol import LLMProtocol, LLMResponseProtocol
from ghrah.core.message import AgentMessage, MessageType
from ghrah.core.supervisor_protocol import SupervisorProtocol
from ghrah.core.window_protocol import (
    ContextManagerProtocol,
    MessageFactory,
    SummaryLLMProtocol,
    SummaryResponseProtocol,
    WindowableBlock,
    WindowableMessage,
)

__all__ = [
    # 基础异常
    "ActorAgentError",
    # 协议
    "AbilityProtocol",
    "ExecutorProtocol",
    "RegistryProtocol",
    # Supervisor 协议
    "SupervisorProtocol",
    # 窗口协议
    "WindowableBlock",
    "WindowableMessage",
    "MessageFactory",
    "SummaryLLMProtocol",
    "SummaryResponseProtocol",
    "ContextManagerProtocol",
    # LLM 协议
    "LLMProtocol",
    "LLMResponseProtocol",
    # 事件
    "ActionChainUpdatedEvent",
    "AgentErrorEvent",
    "AgentResponseEvent",
    "CoreEvent",
    "CoreEventType",
    "HITLRequestEvent",
    # 事件发布
    "EventPublisher",
    "ServerEventPublisher",
    "NullEventPublisher",
    # 命令发送
    "CommandSender",
    # HITL
    "HITLFutureStore",
    "HITLResult",
    # 配置
    "AgentConfig",
    "ContextConfig",
    "ModelOverrides",
    "WindowConfig",
    # 异常 — core 领域
    "AgentError",
    "AgentInitializationError",
    "AgentTimeoutError",
    "CommunicationTimeoutError",
    "HookError",
    "RoutingError",
    "ToolError",
    # 异常 — re-export from domain modules (lazy)
    "AbilityError",
    "AbilityNotFoundError",
    "AgentNotFoundError",
    "LLMError",
    "RegistryError",
    # 消息
    "AgentMessage",
    "MessageType",
]


def __getattr__(name: str) -> type:
    if name in {
        "AbilityError",
        "AbilityNotFoundError",
        "AgentNotFoundError",
        "LLMError",
        "RegistryError",
    }:
        import importlib

        _DOMAIN_MAP = {
            "AbilityError": "ghrah.abilities.errors",
            "AbilityNotFoundError": "ghrah.abilities.errors",
            "AgentNotFoundError": "ghrah.communication.errors",
            "LLMError": "ghrah.llm.errors",
            "RegistryError": "ghrah.communication.errors",
        }
        module = importlib.import_module(_DOMAIN_MAP[name])
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
