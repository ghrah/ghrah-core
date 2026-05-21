# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""CommandSender 协议 — 供服务器内部组件与 Subject 通信。

在新架构中，Core 即是 Server。Agent 和 RemoteBackend 不再需要 WebSocket 客户端，
而是通过 CommandSender 协议向连接的 Subject 发送命令并等待响应。

MessageRouter 实现此协议，通过 ConnectionManager 将命令转发到 Subject，
等待 command_result 或 ability_result 响应。
"""

from __future__ import annotations

from typing import Any, Protocol

__all__ = ["CommandSender", "AbilityResultCallback"]

AbilityResultCallback = Any


class CommandSender(Protocol):
    """命令发送协议 — 由 MessageRouter 实现。

    RemoteBackend 和 RemoteAbilityExecutor 通过此协议向 Subject 发送命令，
    无需了解 ConnectionManager 或 EventBus 的内部细节。
    """

    async def send_command(
        self,
        command_type: str,
        payload: dict[str, Any],
        request_id: str | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """发送命令到 Subject 并等待响应。

        Args:
            command_type: 命令类型（如 CommandType.EXECUTE_ABILITY.value）
            payload: 命令载荷
            request_id: 请求 ID（自动生成如果未提供）
            timeout: 超时时间（秒），None 使用默认值

        Returns:
            命令响应载荷字典

        Raises:
            ConnectionError: 没有可用的 Subject 连接
            asyncio.TimeoutError: 等待响应超时
        """
        ...
