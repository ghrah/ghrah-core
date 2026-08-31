# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""SendAbility：向 room（及可选定向 targets）发消息的 send 工具。

Room 计划 D2/附录 send 回路（agent 自觉调用路径）：
- 入参 ``{room_ids, targets?, message}``；
- recipients = Σ room 的 agent 成员 ∪ targets 去重（RoomBridge 解析）；
- Supervisor 投递（后台 fire-and-forget，排除发送者自身）；
- 投递完成后逐 room 经 RoomBridge（``ctx.serial("command/room_send")``）
  落账，RoomUnit ``append_log`` 收敛双路径。
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from ghrah.abilities.base import Ability
from ghrah.abilities.builtin._cluster_common import _NO_SUPERVISOR_ERROR
from ghrah.core.room_protocol import (
    ROOM_BRIDGE_UNAVAILABLE_ERROR,
    RoomBridgeProtocol,
)
from ghrah.types.results import ActionOutcome, ActionResult

if TYPE_CHECKING:
    from ghrah.abilities.context import AbilityExecutionContext
    from ghrah.abilities.hooks import Hook

logger = logging.getLogger(__name__)


class SendInput(BaseModel):
    model_config = {"extra": "forbid"}

    room_ids: list[str] = Field(
        min_length=1,
        description="Room ids to send the message to (members are resolved as recipients)",
    )
    message: str = Field(
        min_length=1,
        description="Message content to send",
    )
    targets: list[str] | None = Field(
        default=None,
        description=(
            "Optional extra direct targets (agent names) in addition to "
            "the room members"
        ),
    )


class SendAbility(Ability):
    """send 工具：room 维度发信（成员展开 + Supervisor 投递 + RoomLog 落账）。"""

    @property
    def name(self) -> str:
        return "send"

    def bind_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "send",
                "description": (
                    "Send a message to rooms. Recipients are all agent members "
                    "of the given rooms plus optional direct targets. The "
                    "message is appended to each room's log and delivered via "
                    "the supervisor."
                ),
                "parameters": SendInput.model_json_schema(),
            },
        }

    def to_prompt_description(self) -> str:
        return (
            "send(room_ids: list[str], message: str, targets: list[str] | None = None) -> dict: "
            "Send a message to rooms (members resolved as recipients) with room log append"
        )

    def get_hooks(self) -> list[Hook]:
        return []

    async def execute(self, context: AbilityExecutionContext) -> ActionResult:
        supervisor = context.supervisor
        if supervisor is None:
            return ActionResult(
                outcome=ActionOutcome.FAILURE,
                data={"error": _NO_SUPERVISOR_ERROR},
            )
        bridge: RoomBridgeProtocol | None = getattr(supervisor, "room_bridge", None)
        if bridge is None:
            return ActionResult(
                outcome=ActionOutcome.FAILURE,
                data={"error": ROOM_BRIDGE_UNAVAILABLE_ERROR},
            )

        tool_args = context.tool_args or context.accumulated_data.get("tool_args", {})
        try:
            args = SendInput.model_validate(
                {k: v for k, v in tool_args.items() if k in SendInput.model_fields}
            )
        except Exception as e:
            return ActionResult(
                outcome=ActionOutcome.FAILURE,
                data={"error": f"invalid send args: {e}"},
            )

        sender = context.agent_name or "unknown"
        targets = args.targets or []

        resolved = await bridge.resolve_recipients(args.room_ids, targets)
        if not resolved.get("success"):
            return ActionResult(
                outcome=ActionOutcome.FAILURE,
                data={"error": resolved.get("error") or "failed to resolve recipients"},
            )
        resolved_data = resolved.get("data") or {}
        recipients: list[str] = list(resolved_data.get("recipients", []))
        # 投递排除发送者自身（broadcast 同语义）
        to_deliver = [r for r in recipients if r != sender]

        # Supervisor 投递：fire-and-forget（回复由目标 agent 自行处理后记入链路）
        for target in to_deliver:
            asyncio.create_task(self._deliver(supervisor, target, args.message, sender))

        # 逐 room 落账（author_type="agent"，RoomLog data = {message, targets?}）
        data: dict[str, Any] = {"message": args.message}
        if targets:
            data["targets"] = targets
        appended: list[str] = []
        for room_id in args.room_ids:
            log_result = await bridge.append_room_log(room_id, author=sender, data=data)
            if not log_result.get("success"):
                return ActionResult(
                    outcome=ActionOutcome.FAILURE,
                    data={
                        "error": (
                            f"delivered but failed to append room log for "
                            f"'{room_id}': {log_result.get('error')}"
                        ),
                        "recipients": recipients,
                        "appended_rooms": appended,
                    },
                )
            appended.append(room_id)

        return ActionResult(
            outcome=ActionOutcome.SUCCESS,
            data={
                "recipients": recipients,
                "delivered_to": to_deliver,
                "rooms": appended,
                "status": "sent",
            },
        )

    @staticmethod
    async def _deliver(
        supervisor: Any, target: str, content: str, sender: str
    ) -> None:
        try:
            await supervisor.send(target=target, content=content, sender=sender)
        except Exception as e:
            logger.error("SendAbility: delivery to '%s' failed: %s", target, e)
