# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import Any

from ghrah.chat.content import ReasoningBlock
from ghrah.chat.format.openai import OpenAIFormat
from ghrah.chat.message import ChatMessage


class DeepSeekFormat(OpenAIFormat):
    """DeepSeek format adapter.

    Extends OpenAIFormat to ensure ``reasoning_content`` is always included as
    a top-level field on AI messages that contain a ``ReasoningBlock``, even
    when the message also carries ``tool_calls`` or multimodal content.

    DeepSeek's thinking mode requires all prior ``reasoning_content`` to be
    passed back verbatim; omitting it causes a 400 error::

        'The `reasoning_content` in the thinking mode must be passed back
         to the API.'
    """

    def _format_single_message(
        self, msg: ChatMessage, role: str
    ) -> dict[str, Any] | list[dict[str, Any]]:
        result = super()._format_single_message(msg, role)

        if msg.role == "ai" and isinstance(result, dict):
            if "reasoning_content" not in result:
                reasoning_blocks = msg.find_blocks(ReasoningBlock)
                if reasoning_blocks:
                    result["reasoning_content"] = reasoning_blocks[0].reasoning

        return result
