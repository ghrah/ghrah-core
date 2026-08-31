# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""核心异常层次结构 — core 领域异常 + 延迟 re-export 各子领域异常。

已迁移到领域模块的异常通过 __getattr__ 延迟 re-export，
避免 core.exceptions ↔ 各领域 errors 模块的循环依赖。
旧 import 路径 `from ghrah.core.exceptions import LLMError` 仍然可用。
"""

from __future__ import annotations

from ghrah.core._base_error import ActorAgentError


class AgentError(ActorAgentError):
    """Agent 运行时错误"""

    def __init__(self, agent_name: str, message: str):
        self.agent_name = agent_name
        super().__init__(f"Agent[{agent_name}]: {message}")


class AgentInitializationError(AgentError):
    """Agent 初始化失败（如 LLM 客户端创建失败）"""

    pass


class AgentTimeoutError(AgentError):
    """Agent 处理超时"""

    def __init__(self, agent_name: str, timeout: float):
        self.timeout = timeout
        super().__init__(agent_name, f"Operation timed out after {timeout}s")


class ToolError(ActorAgentError):
    """工具执行错误"""

    def __init__(self, tool_name: str, message: str):
        self.tool_name = tool_name
        super().__init__(f"Tool[{tool_name}]: {message}")


class RoutingError(ActorAgentError):
    """消息路由错误"""

    pass


class CommunicationTimeoutError(ActorAgentError):
    """Agent 间通信超时"""

    def __init__(self, sender: str, recipient: str, timeout: float):
        self.sender = sender
        self.recipient = recipient
        self.timeout = timeout
        super().__init__(
            f"Communication timeout: {sender} -> {recipient} after {timeout}s"
        )


class HookError(ActorAgentError):
    """Hook 执行相关错误"""

    def __init__(self, hook_point: str, message: str):
        self.hook_point = hook_point
        super().__init__(f"Hook[{hook_point}]: {message}")


_RE_EXPORTS = {
    "LLMError": "ghrah.llm.errors",
    "RegistryError": "ghrah.communication.errors",
    "AgentNotFoundError": "ghrah.communication.errors",
    "AbilityError": "ghrah.abilities.errors",
    "AbilityNotFoundError": "ghrah.abilities.errors",
}


def __getattr__(name: str) -> type:
    if name in _RE_EXPORTS:
        import importlib

        module = importlib.import_module(_RE_EXPORTS[name])
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
