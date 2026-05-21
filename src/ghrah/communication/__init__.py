# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""通信层：Agent 注册、消息路由和生命周期管理。

提供多 Agent 通信的核心组件：
- AgentRegistry: Agent 注册与发现
- MessageRouter: 消息路由与广播
- SupervisorActor: Agent 生命周期管理和系统入口
"""

from ghrah.communication.registry import AgentInfo, AgentRegistry
from ghrah.communication.router import MessageRouter
from ghrah.communication.supervisor import SupervisorActor

__all__ = [
    "AgentInfo",
    "AgentRegistry",
    "MessageRouter",
    "SupervisorActor",
]
