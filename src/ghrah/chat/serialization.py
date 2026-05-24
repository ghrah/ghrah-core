# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import Any

from ghrah.chat.message import ChatMessage

__all__ = [
    "serialize_messages",
    "deserialize_messages",
]


def serialize_messages(messages: list[ChatMessage] | None) -> list[dict[str, Any]] | None:
    if messages is None:
        return None
    return [m.to_dict() for m in messages]


def deserialize_messages(data: list[dict[str, Any]] | None) -> list[ChatMessage] | None:
    if data is None:
        return None
    result: list[ChatMessage] = []
    for item in data:
        result.append(ChatMessage.from_dict(item))
    return result
