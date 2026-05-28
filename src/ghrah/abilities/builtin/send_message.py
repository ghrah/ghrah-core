# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""SendMessageAbility：向指定 Agent 发送消息，支持同步等待和异步投递。"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from ghrah.abilities.base import Ability, ActionOutcome, ActionResult
from ghrah.abilities.builtin._cluster_common import _NO_SUPERVISOR_ERROR
from ghrah.chat.message import ChatMessage

if TYPE_CHECKING:
    from ghrah.abilities.context import AbilityExecutionContext
    from ghrah.abilities.hooks import Hook

logger = logging.getLogger(__name__)


class SendMessageInput(BaseModel):
    model_config = {"extra": "forbid"}

    target: str = Field(
        min_length=1,
        description="Target agent name to send the message to",
    )
    content: str = Field(
        min_length=1,
        description="Message content to send",
    )
    fire_and_forget: bool = Field(
        default=True,
        description=(
            "If true (default), send message asynchronously — the calling agent "
            "continues working immediately, and the reply is injected back into "
            "its message queue for the next iteration. "
            "If false, wait synchronously for the reply (legacy behavior)."
        ),
    )


class SendMessageAbility(Ability):
    """向指定 Agent 发送消息，支持同步等待和异步投递两种模式。

    同步模式（fire_and_forget=False）：调用 supervisor.send() 并等待回复。
    异步模式（fire_and_forget=True，默认）：后台发送消息，将回复回注到
    主控 Agent 的消息队列，使其在下一轮迭代中自然消费。
    """

    @property
    def name(self) -> str:
        return "send_message"

    def bind_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "send_message",
                "description": (
                    "Send a message to a specific agent in the cluster. "
                    "By default (fire_and_forget=true), sends asynchronously — "
                    "the calling agent continues immediately and the reply arrives "
                    "in the next iteration. Set fire_and_forget=false to wait for "
                    "the reply synchronously."
                ),
                "parameters": SendMessageInput.model_json_schema(),
            },
        }

    def to_prompt_description(self) -> str:
        return (
            "send_message(target: str, content: str, fire_and_forget: bool = True) -> dict: "
            "Send a message to a specific agent (async by default, sync if fire_and_forget=false)"
        )

    def get_hooks(self) -> list[Hook]:
        return []

    async def execute(self, context: AbilityExecutionContext) -> ActionResult:
        if context.supervisor is None:
            return ActionResult(
                outcome=ActionOutcome.FAILURE,
                data={"error": _NO_SUPERVISOR_ERROR},
            )

        tool_args = context.tool_args or context.accumulated_data.get("tool_args", {})
        target = tool_args.get("target", "")
        content = tool_args.get("content", "")
        fire_and_forget = tool_args.get("fire_and_forget", True)

        if not target:
            return ActionResult(
                outcome=ActionOutcome.FAILURE,
                data={"error": "target is required"},
            )
        if not content:
            return ActionResult(
                outcome=ActionOutcome.FAILURE,
                data={"error": "content is required"},
            )

        sender = context.agent_name or "unknown"

        if fire_and_forget:
            asyncio.create_task(
                self._fire_and_reinject(context, sender, target, content)
            )
            return ActionResult(
                outcome=ActionOutcome.SUCCESS,
                data={"target": target, "status": "message_sent", "mode": "async"},
            )

        try:
            response = await context.supervisor.send(
                target=target,
                content=content,
                sender=sender,
            )
            return ActionResult(
                outcome=ActionOutcome.SUCCESS,
                data={"response": response, "target": target, "mode": "sync"},
            )
        except Exception as e:
            return ActionResult(
                outcome=ActionOutcome.FAILURE,
                data={"error": f"Failed to send message to '{target}': {e}"},
            )

    async def _fire_and_reinject(
        self,
        context: AbilityExecutionContext,
        sender: str,
        target: str,
        content: str,
    ) -> None:
        """后台任务：发送消息，将回复回注到主控的消息队列。"""
        try:
            reply = await context.supervisor.send(target, content, sender=sender)
            handle = await context.supervisor.get_agent_handle(sender)
            await handle.inject_message(
                ChatMessage.assistant(
                    text_or_blocks=f"[{target}] {reply}",
                    source=f"agent:{target}",
                )
            )
        except Exception as e:
            try:
                handle = await context.supervisor.get_agent_handle(sender)
                await handle.inject_message(
                    ChatMessage.assistant(
                        text_or_blocks=f"[{target} 错误] {e}",
                        source=f"agent:{target}",
                    )
                )
            except Exception:
                logger.error(
                    "SendMessageAbility: failed to reinject error message for %s: %s",
                    sender,
                    e,
                )
