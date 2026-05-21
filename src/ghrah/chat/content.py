# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class TextBlock:
    type: Literal["text"] = "text"
    text: str = ""


@dataclass
class ReasoningBlock:
    type: Literal["reasoning"] = "reasoning"
    reasoning: str = ""
    incomplete: bool = False


@dataclass
class ImageBlock:
    type: Literal["image"] = "image"
    url: str | None = None
    base64: str | None = None
    mime_type: str | None = None


@dataclass
class AudioBlock:
    type: Literal["audio"] = "audio"
    data: str = ""
    mime_type: str = ""


@dataclass
class FileBlock:
    type: Literal["file"] = "file"
    url: str | None = None
    base64: str | None = None
    mime_type: str | None = None
    filename: str | None = None


@dataclass
class ToolCallBlock:
    type: Literal["tool_call"] = "tool_call"
    id: str = ""
    name: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolResultBlock:
    type: Literal["tool_result"] = "tool_result"
    tool_call_id: str = ""
    name: str | None = None
    content: str = ""
    success: bool = True
    error: str | None = None


@dataclass
class ErrorBlock:
    type: Literal["error"] = "error"
    error_type: str = ""
    message: str = ""
    details: dict[str, Any] | None = None


@dataclass
class ToolCallChunkBlock:
    type: Literal["tool_call_chunk"] = "tool_call_chunk"
    index: int = 0
    id: str | None = None
    name: str | None = None
    arguments_chunk: str = ""


ContentBlock = (
    TextBlock
    | ReasoningBlock
    | ImageBlock
    | AudioBlock
    | FileBlock
    | ToolCallBlock
    | ToolResultBlock
    | ErrorBlock
)

StreamingBlock = TextBlock | ToolCallChunkBlock

_BLOCK_TYPE_MAP: dict[str, type] = {
    "text": TextBlock,
    "reasoning": ReasoningBlock,
    "image": ImageBlock,
    "audio": AudioBlock,
    "file": FileBlock,
    "tool_call": ToolCallBlock,
    "tool_result": ToolResultBlock,
    "error": ErrorBlock,
    "tool_call_chunk": ToolCallChunkBlock,
}


def block_from_dict(data: dict[str, Any]) -> ContentBlock | ToolCallChunkBlock:
    block_type = data.get("type", "")
    cls = _BLOCK_TYPE_MAP.get(block_type)
    if cls is None:
        raise ValueError(f"Unknown block type: {block_type!r}")
    valid_fields = {f.name for f in cls.__dataclass_fields__.values() if f.name != "type"}  # type: ignore[attr-defined]
    kwargs = {k: v for k, v in data.items() if k in valid_fields}
    return cls(**kwargs)  # type: ignore[no-any-return]


def block_to_dict(block: ContentBlock | ToolCallChunkBlock) -> dict[str, Any]:
    result: dict[str, Any] = {"type": block.type}
    for f in block.__dataclass_fields__.values():
        if f.name == "type":
            continue
        val = getattr(block, f.name)
        if val is not None and not (
            isinstance(val, (list, dict)) and len(val) == 0 and f.name == "arguments"
        ):
            result[f.name] = val
    return result
