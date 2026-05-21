# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""自定义异常层次结构"""


class ActorAgentError(Exception):
    """Actor-Agent 框架基础异常"""

    pass


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


class LLMError(ActorAgentError):
    """LLM 调用相关错误"""

    def __init__(self, provider: str, message: str):
        self.provider = provider
        super().__init__(f"LLM[{provider}]: {message}")


class MessageError(ActorAgentError):
    """消息处理错误"""

    pass


class ToolError(ActorAgentError):
    """工具执行错误"""

    def __init__(self, tool_name: str, message: str):
        self.tool_name = tool_name
        super().__init__(f"Tool[{tool_name}]: {message}")


class RegistryError(ActorAgentError):
    """Agent 注册/发现相关错误"""

    pass


class AgentNotFoundError(RegistryError):
    """Agent 未在注册中心找到"""

    def __init__(self, agent_name: str):
        self.agent_name = agent_name
        super().__init__(f"Agent not found: {agent_name}")


class RoutingError(ActorAgentError):
    """消息路由错误"""

    pass


class CommunicationTimeoutError(ActorAgentError):
    """Agent 间通信超时"""

    def __init__(self, sender: str, recipient: str, timeout: float):
        self.sender = sender
        self.recipient = recipient
        self.timeout = timeout
        super().__init__(f"Communication timeout: {sender} -> {recipient} after {timeout}s")


class AbilityError(ActorAgentError):
    """Ability 执行相关错误"""

    def __init__(self, ability_name: str, message: str):
        self.ability_name = ability_name
        super().__init__(f"Ability[{ability_name}]: {message}")


class AbilityNotFoundError(AbilityError):
    """Ability 未找到"""

    def __init__(self, ability_name: str):
        super().__init__(ability_name, f"Ability not found: {ability_name}")


class HookError(ActorAgentError):
    """Hook 执行相关错误"""

    def __init__(self, hook_point: str, message: str):
        self.hook_point = hook_point
        super().__init__(f"Hook[{hook_point}]: {message}")
