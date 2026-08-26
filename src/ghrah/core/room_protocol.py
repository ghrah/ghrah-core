# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""Room bridge：Core → Subject Room 侧的最小协议面（Room 计划附录 send 回路）。

Core 保持 standalone（零 subject 依赖）：本模块只定义 Protocol 与基于
Ouroboros ``ctx.serial`` 命令面的桥接实现（duck-typed serial 回调）。

通道语义（附录 D3 定死 serial，保持命令面统一）：
- ``resolve_recipients``：经 ``command/room_get`` 逐 room 展开 agent 成员，
  ∪ extra_targets 去重。
- ``append_room_log``：经 ``command/room_send``（author_type="agent"）落账，
  RoomUnit ``append_log`` 收敛双路径。
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

__all__ = [
    "ROOM_BRIDGE_UNAVAILABLE_ERROR",
    "RoomBridgeProtocol",
    "SerialRoomBridge",
]

logger = logging.getLogger(__name__)

ROOM_BRIDGE_UNAVAILABLE_ERROR = (
    "Room bridge is not available. The send ability requires a Subject host "
    "context (Ouroboros ctx.serial) wired via CoreUnit."
)

SerialFn = Callable[[str, dict[str, Any]], Awaitable[Any]]


class RoomBridgeProtocol(Protocol):
    """Core 侧所需的 Room 查询/落账最小契约（Subject RoomManager duck-type）。"""

    async def resolve_recipients(
        self, room_ids: list[str], extra_targets: list[str] | None = None
    ) -> dict[str, Any]:
        """recipients = Σ room 的 agent 成员 ∪ extra_targets 去重。

        Returns:
            ``{"success": bool, "data"?: {"recipients": [...], "rooms": [...]},
            "error"?: str}``
        """
        ...

    async def append_room_log(
        self,
        room_id: str,
        author: str,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """向 room 追加一条 RoomLog（author_type 固定 "agent"）。"""
        ...


class SerialRoomBridge:
    """基于宿主 ctx.serial 的 RoomBridge 实现（协议命令面客户端）。

    Args:
        serial: 宿主 serial 回调（``ctx.serial(name, payload)``），
            duck-typed，Core 不 import Ouroboros。
    """

    def __init__(self, serial: SerialFn) -> None:
        self._serial = serial

    async def _command(self, name: str, payload: dict[str, Any]) -> dict[str, Any]:
        result = await self._serial(f"command/{name}", payload)
        if not isinstance(result, dict):
            return {"success": False, "error": f"Unexpected result for {name}"}
        return result

    async def resolve_recipients(
        self, room_ids: list[str], extra_targets: list[str] | None = None
    ) -> dict[str, Any]:
        recipients: list[str] = []
        seen: set[str] = set()
        rooms: list[dict[str, Any]] = []
        for room_id in room_ids:
            result = await self._command("room_get", {"room_id": room_id})
            if not result.get("success"):
                error = result.get("error") or f"room not found: {room_id}"
                return {"success": False, "error": error}
            room = (result.get("data") or {}).get("room") or {}
            rooms.append(room)
            for member in room.get("members", []):
                if (
                    member.get("subject_type") == "agent"
                    and member.get("subject") not in seen
                ):
                    subject = member["subject"]
                    seen.add(subject)
                    recipients.append(subject)
        for target in extra_targets or []:
            if target not in seen:
                seen.add(target)
                recipients.append(target)
        return {"success": True, "data": {"recipients": recipients, "rooms": rooms}}

    async def append_room_log(
        self,
        room_id: str,
        author: str,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return await self._command(
            "room_send",
            {
                "room_id": room_id,
                "author": author,
                "author_type": "agent",
                "data": data or {},
            },
        )
