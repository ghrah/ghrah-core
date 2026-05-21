# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""消息路由器：根据消息的 recipient 字段路由到目标 Agent。

MessageRouter 是普通 Python 类，由 SupervisorActor 内部持有。
支持直接发送、广播和超时机制。
"""

from __future__ import annotations

import asyncio
import logging

from ghrah.communication.registry import AgentRegistry
from ghrah.core.exceptions import (
    AgentNotFoundError,
    CommunicationTimeoutError,
    RoutingError,
)
from ghrah.core.message import Message, MessageType

logger = logging.getLogger(__name__)

# 默认通信超时（秒）
DEFAULT_TIMEOUT = 300.0


class MessageRouter:
    """消息路由器。

    根据 Message.recipient 路由消息到目标 Agent：
    - 指定名称：路由到单个 Agent 并等待响应
    - "*"：广播到所有已注册 Agent

    路由流程：
        1. 从 AgentRegistry 获取目标 Agent 的 actor handle
        2. 调用 await actor_handle.receive(message)
        3. 等待响应（支持超时）

    Args:
        registry: Agent 注册中心实例
        default_timeout: 默认通信超时时间（秒）
    """

    def __init__(self, registry: AgentRegistry, default_timeout: float = DEFAULT_TIMEOUT) -> None:
        self._registry = registry
        self._default_timeout = default_timeout

    async def route(self, message: Message, timeout: float | None = None) -> Message:
        """路由消息到目标 Agent 并等待响应。

        Args:
            message: 要路由的消息
            timeout: 超时时间（秒），None 使用默认值，-1 表示无限等待

        Returns:
            目标 Agent 的回复消息

        Raises:
            AgentNotFoundError: 目标 Agent 未注册
            CommunicationTimeoutError: 通信超时
            RoutingError: 路由过程中出错
        """
        effective_timeout = timeout if timeout is not None else self._default_timeout
        target = message.recipient

        # 广播消息
        if target == "*":
            results = await self.broadcast(message)
            # 广播返回多个结果，此处返回第一个
            return results[0] if results else message

        # 检查目标是否存在
        if not self._registry.exists(target):
            raise AgentNotFoundError(target)

        try:
            handle = self._registry.get_handle(target)
            logger.debug(f"Routing message: {message.sender} -> {target}")

            if effective_timeout < 0:
                response = await handle.receive(message)
            else:
                response = await asyncio.wait_for(
                    handle.receive(message),
                    timeout=effective_timeout,
                )
            return response

        except TimeoutError:
            raise CommunicationTimeoutError(
                sender=message.sender,
                recipient=target,
                timeout=effective_timeout,
            )
        except (AgentNotFoundError, CommunicationTimeoutError):
            raise
        except Exception as e:
            raise RoutingError(
                f"Failed to route message from {message.sender} to {target}: {e}"
            ) from e

    async def broadcast(self, message: Message, exclude: str | None = None) -> list[Message]:
        """广播消息到所有已注册 Agent。

        并行发送到所有 Agent，收集所有响应。

        Args:
            message: 要广播的消息
            exclude: 排除的 Agent 名称（通常是发送者自己）

        Returns:
            所有 Agent 的回复列表
        """
        agents = self._registry.list_agents()
        targets = [info for info in agents if info.name != exclude and info.name != message.sender]

        if not targets:
            logger.debug("No targets for broadcast")
            return []

        logger.debug(f"Broadcasting from {message.sender} to {[t.name for t in targets]}")

        # 并行发送到所有目标
        tasks = []
        for info in targets:
            # 为每个目标创建独立的消息（保持 sender 不变，recipient 为具体 Agent）
            target_message = Message(
                sender=message.sender,
                recipient=info.name,
                content=message.content,
                type=message.type,
                metadata=dict(message.metadata),
                reply_to=message.reply_to,
            )
            tasks.append(info.actor_handle.receive(target_message))

        # 并行等待所有响应
        try:
            responses = await asyncio.gather(*tasks, return_exceptions=True)
        except Exception as e:
            raise RoutingError(f"Broadcast failed: {e}") from e

        # 收集成功的响应，记录错误
        results: list[Message] = []
        for i, resp in enumerate(responses):
            if isinstance(resp, Exception):
                logger.error(f"Broadcast to {targets[i].name} failed: {resp}")
            else:
                results.append(resp)

        return results

    async def send_and_wait(
        self,
        target: str,
        content: str,
        sender: str = "user",
        msg_type: MessageType = MessageType.CHAT,
        timeout: float | None = None,
    ) -> Message:
        """便捷方法：发送消息并等待响应。

        Args:
            target: 目标 Agent 名称
            content: 消息内容
            sender: 发送者标识
            msg_type: 消息类型
            timeout: 超时时间（秒），None 使用默认值，-1 表示无限等待

        Returns:
            目标 Agent 的回复
        """
        message = Message(
            sender=sender,
            recipient=target,
            content=content,
            type=msg_type,
        )
        return await self.route(message, timeout=timeout)
