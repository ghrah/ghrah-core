# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import Any, Literal

from ghrah.chat.content import (
    ImageBlock,
    ReasoningBlock,
    TextBlock,
    ToolCallBlock,
    ToolResultBlock,
)
from ghrah.chat.message import ChatMessage

__all__ = [
    "serialize_messages",
    "deserialize_messages",
    "migrate_langchain_messages",
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
        # Check for new format (has "role" + "content_blocks" keys)
        if "role" in item and "content_blocks" in item:
            result.append(ChatMessage.from_dict(item))
        elif "type" in item and item["type"] == "constructor":
            # LangChain old format migration
            migrated = _migrate_langchain_message(item)
            if migrated is not None:
                result.append(migrated)
        else:
            # Try treating as new format anyway
            result.append(ChatMessage.from_dict(item))
    return result


_LANGCHAIN_ROLE_MAP: dict[str, Literal["system", "user", "ai", "tool"]] = {
    "HumanMessage": "user",
    "AIMessage": "ai",
    "SystemMessage": "system",
    "ToolMessage": "tool",
}

_LANGCHAIN_SOURCE_MAP = {
    "HumanMessage": "human",
    "AIMessage": None,
    "SystemMessage": "system",
    "ToolMessage": None,
}


def _migrate_langchain_message(data: dict[str, Any]) -> ChatMessage | None:
    """DEPRECATED: 迁移兼容函数，将序列化时遇到的旧 LangChain 格式 dict 转换为 ChatMessage。

    新代码不应依赖此函数。仅用于 deserialize_messages 中的向后兼容迁移。
    后续版本移除旧格式支持后可删除。
    """
    id_path = data.get("id", [])
    lc_type = id_path[-1] if id_path else ""
    kwargs = data.get("kwargs", {})

    role = _LANGCHAIN_ROLE_MAP.get(lc_type)
    if role is None:
        return None

    source = _LANGCHAIN_SOURCE_MAP.get(lc_type)
    content_blocks: list[Any] = []
    metadata: dict[str, Any] = {}

    content = kwargs.get("content")
    if content is not None:
        if isinstance(content, str):
            content_blocks.append(TextBlock(text=content))
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    block_type = block.get("type", "")
                    if block_type == "text":
                        content_blocks.append(TextBlock(text=block.get("text", "")))
                    elif block_type == "reasoning":
                        content_blocks.append(ReasoningBlock(reasoning=block.get("reasoning", "")))
                    elif block_type == "image_url":
                        url = block.get("image_url", {}).get("url", "")
                        content_blocks.append(ImageBlock(url=url))

    tool_calls = kwargs.get("tool_calls")
    if tool_calls and isinstance(tool_calls, list):
        for tc in tool_calls:
            if isinstance(tc, dict):
                arguments = tc.get("args", tc.get("arguments", {}))
                if isinstance(arguments, str):
                    import json

                    try:
                        arguments = json.loads(arguments)
                    except (json.JSONDecodeError, TypeError):
                        arguments = {}
                content_blocks.append(
                    ToolCallBlock(
                        id=tc.get("id", ""),
                        name=tc.get("name", ""),
                        arguments=arguments if isinstance(arguments, dict) else {},
                    )
                )

    additional_kwargs = kwargs.get("additional_kwargs", {})
    if additional_kwargs:
        reasoning = additional_kwargs.get("reasoning_content")
        if reasoning and isinstance(reasoning, str):
            content_blocks.insert(0, ReasoningBlock(reasoning=reasoning))

    if lc_type == "ToolMessage":
        tool_call_id = kwargs.get("tool_call_id", "")
        tc_name = kwargs.get("name")
        tc_content = kwargs.get("content", "")
        tc_content_str = tc_content if isinstance(tc_content, str) else str(tc_content)
        return ChatMessage(
            role="tool",
            content_blocks=[
                ToolResultBlock(
                    tool_call_id=tool_call_id,
                    name=tc_name,
                    content=tc_content_str,
                )
            ],
            source=source,
        )

    response_metadata = kwargs.get("response_metadata")
    if response_metadata and isinstance(response_metadata, dict):
        metadata = response_metadata

    return ChatMessage(
        role=role,
        content_blocks=content_blocks,
        source=source,
        metadata=metadata,
    )


# DEPRECATED: migrate_langchain_messages 是 deserialize_messages 的别名，
# 保留用于向后兼容。新代码应直接使用 deserialize_messages。
migrate_langchain_messages = deserialize_messages
