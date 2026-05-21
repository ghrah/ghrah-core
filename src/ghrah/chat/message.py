# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from ghrah.chat.content import (
    AudioBlock,
    ContentBlock,
    FileBlock,
    ImageBlock,
    ReasoningBlock,
    TextBlock,
    ToolCallBlock,
    ToolResultBlock,
    block_from_dict,
    block_to_dict,
)


@dataclass
class ChatMessage:
    role: Literal["system", "user", "ai", "tool"]
    content_blocks: list[ContentBlock] = field(default_factory=list)
    source: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def text(self) -> str:
        return "".join(b.text for b in self.content_blocks if isinstance(b, TextBlock))

    @property
    def tool_calls(self) -> list[ToolCallBlock]:
        return [b for b in self.content_blocks if isinstance(b, ToolCallBlock)]

    @property
    def has_tool_calls(self) -> bool:
        return any(isinstance(b, ToolCallBlock) for b in self.content_blocks)

    @property
    def reasoning(self) -> str | None:
        for b in self.content_blocks:
            if isinstance(b, ReasoningBlock):
                return b.reasoning
        return None

    @property
    def images(self) -> list[ImageBlock]:
        return [b for b in self.content_blocks if isinstance(b, ImageBlock)]

    @property
    def is_multimodal(self) -> bool:
        return any(isinstance(b, (ImageBlock, AudioBlock, FileBlock)) for b in self.content_blocks)

    @property
    def tool_results(self) -> list[ToolResultBlock]:
        return [b for b in self.content_blocks if isinstance(b, ToolResultBlock)]

    @classmethod
    def system(cls, text: str, source: str | None = "system", **kwargs: Any) -> ChatMessage:
        return cls(role="system", content_blocks=[TextBlock(text=text)], source=source, **kwargs)

    @classmethod
    def user(
        cls,
        text_or_blocks: str | list[ContentBlock] | None = None,
        source: str | None = "human",
        **kwargs: Any,
    ) -> ChatMessage:
        if text_or_blocks is None:
            content: list[ContentBlock] = []
        elif isinstance(text_or_blocks, str):
            content = [TextBlock(text=text_or_blocks)]
        else:
            content = text_or_blocks
        return cls(role="user", content_blocks=content, source=source, **kwargs)

    @classmethod
    def ai(
        cls,
        content_blocks: list[ContentBlock] | None = None,
        text: str | None = None,
        tool_calls: list[ToolCallBlock] | None = None,
        reasoning: str | None = None,
        source: str | None = None,
        **kwargs: Any,
    ) -> ChatMessage:
        blocks: list[ContentBlock] = list(content_blocks or [])
        if reasoning:
            blocks.append(ReasoningBlock(reasoning=reasoning))
        if text:
            blocks.append(TextBlock(text=text))
        if tool_calls:
            blocks.extend(tool_calls)
        return cls(role="ai", content_blocks=blocks, source=source, **kwargs)

    @classmethod
    def tool(
        cls,
        tool_call_id: str,
        content: str,
        name: str | None = None,
        success: bool = True,
        error: str | None = None,
        source: str | None = None,
        **kwargs: Any,
    ) -> ChatMessage:
        return cls(
            role="tool",
            content_blocks=[
                ToolResultBlock(
                    tool_call_id=tool_call_id,
                    name=name or "",
                    content=content,
                    success=success,
                    error=error,
                )
            ],
            source=source,
            **kwargs,
        )

    def find_blocks(self, block_type: type) -> list[Any]:
        return [b for b in self.content_blocks if isinstance(b, block_type)]

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "content_blocks": [block_to_dict(b) for b in self.content_blocks],
            "source": self.source,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ChatMessage:
        blocks_data = data.get("content_blocks", [])
        content_blocks: list[ContentBlock] = []
        for bd in blocks_data:
            if isinstance(bd, dict):
                content_blocks.append(block_from_dict(bd))  # type: ignore[arg-type]
            else:
                raise ValueError(f"Invalid content_block entry: {bd!r}")

        role = data.get("role", "user")
        valid_roles = ("system", "user", "ai", "tool")
        if role not in valid_roles:
            if role == "assistant":
                role = "ai"
            else:
                raise ValueError(f"Invalid role: {role!r}, expected one of {valid_roles}")

        return cls(
            role=role,
            content_blocks=content_blocks,
            source=data.get("source"),
            metadata=data.get("metadata", {}),
        )
