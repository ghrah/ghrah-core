# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import logging
from typing import Any

from ghrah.chat.content import (
    FileBlock,
    ImageBlock,
    ReasoningBlock,
    TextBlock,
    ToolCallBlock,
)
from ghrah.chat.format import ChatFormat, LLMResponse, TokenUsage
from ghrah.chat.message import ChatMessage

logger = logging.getLogger(__name__)


class AnthropicFormat(ChatFormat):
    def __init__(
        self,
        model: str = "",
        api_key: str | None = None,
        base_url: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        top_p: float | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__()
        self._model = model
        self._api_key = api_key
        self._base_url = base_url
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._top_p = top_p
        self._top_k: int | None = None
        self._client: Any = None

    @property
    def model(self) -> str:
        return self._model

    def apply_model_overrides(self, overrides: ModelOverrides) -> None:

        super().apply_model_overrides(overrides)
        if overrides.top_k is not None:
            self._top_k = overrides.top_k

    def _get_client(self) -> Any:
        if self._client is None:
            import anthropic

            kwargs: dict[str, Any] = {}
            if self._api_key:
                kwargs["api_key"] = self._api_key
            if self._base_url:
                kwargs["base_url"] = self._base_url
            self._client = anthropic.AsyncAnthropic(**kwargs)
        return self._client

    async def generate(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        client = self._get_client()
        system_prompt, formatted = self._format_messages(messages)

        api_kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": formatted,
            "max_tokens": self._max_tokens,
            "temperature": self._temperature,
        }
        if system_prompt is not None:
            api_kwargs["system"] = system_prompt

        effective_tools = tools or self._tools
        if effective_tools:
            api_kwargs["tools"] = self._format_tools(effective_tools)

        if self._top_p is not None:
            api_kwargs["top_p"] = self._top_p
        if self._top_k is not None:
            api_kwargs["top_k"] = self._top_k

        response = await client.messages.create(**api_kwargs)
        return self._parse_response(response)

    def _format_messages(
        self, messages: list[ChatMessage]
    ) -> tuple[str | None, list[dict[str, Any]]]:
        system_parts: list[str] = []
        formatted: list[dict[str, Any]] = []

        for msg in messages:
            if msg.role == "system":
                system_parts.append(msg.text)
                continue

            if msg.role == "tool":
                for tr in msg.tool_results:
                    content_blocks_for_result: list[dict[str, Any]] = []
                    if isinstance(tr.content, str) and tr.content:
                        content_blocks_for_result.append({"type": "text", "text": tr.content})
                    elif isinstance(tr.content, list):
                        content_blocks_for_result = tr.content

                    tool_result_dict: dict[str, Any] = {
                        "type": "tool_result",
                        "tool_use_id": tr.tool_call_id,
                    }
                    if tr.name:
                        tool_result_dict["name"] = tr.name
                    if not tr.success and tr.error:
                        tool_result_dict["is_error"] = True
                        tool_result_dict["content"] = tr.error
                    else:
                        tool_result_dict["content"] = content_blocks_for_result or tr.content

                    formatted.append(
                        {
                            "role": "user",
                            "content": [tool_result_dict],
                        }
                    )
                continue

            role = "assistant" if msg.role == "ai" else msg.role

            content_parts: list[dict[str, Any]] = []
            for b in msg.content_blocks:
                if isinstance(b, TextBlock):
                    content_parts.append({"type": "text", "text": b.text})
                elif isinstance(b, ImageBlock):
                    source: dict[str, Any] = {"type": "base64"}
                    if b.mime_type:
                        source["media_type"] = b.mime_type
                    if b.base64:
                        source["data"] = b.base64
                    content_parts.append({"type": "image", "source": source})
                elif isinstance(b, ToolCallBlock):
                    content_parts.append(
                        {
                            "type": "tool_use",
                            "id": b.id,
                            "name": b.name,
                            "input": b.arguments,
                        }
                    )
                elif isinstance(b, ReasoningBlock):
                    content_parts.append(
                        {
                            "type": "thinking",
                            "thinking": b.reasoning,
                        }
                    )
                elif isinstance(b, FileBlock):
                    doc_source: dict[str, Any] = {"type": "base64"}
                    if b.mime_type:
                        doc_source["media_type"] = b.mime_type
                    if b.base64:
                        doc_source["data"] = b.base64
                    content_parts.append(
                        {
                            "type": "document",
                            "source": doc_source,
                        }
                    )

            if content_parts:
                formatted.append({"role": role, "content": content_parts})
            else:
                text_content = msg.text or ""
                formatted.append({"role": role, "content": text_content or ""})

        system_prompt = "\n\n".join(system_parts) if system_parts else None
        return system_prompt, formatted

    def _format_tools(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        formatted: list[dict[str, Any]] = []
        for tool in tools:
            if "function" in tool and "type" in tool and tool["type"] == "function":
                func = tool["function"]
                schema: dict[str, Any] = {
                    "name": func.get("name", ""),
                    "input_schema": func.get("parameters", func.get("args", {})),
                }
                if func.get("description"):
                    schema["description"] = func["description"]
                formatted.append(schema)
            else:
                schema = {
                    "name": tool.get("name", ""),
                    "input_schema": tool.get("parameters", tool.get("args", {})),
                }
                if tool.get("description"):
                    schema["description"] = tool["description"]
                formatted.append(schema)
        return formatted

    def _parse_response(self, response: Any) -> LLMResponse:
        content_blocks: list[Any] = []
        stop_reason = getattr(response, "stop_reason", None)

        for block in response.content:
            block_type = getattr(block, "type", "")

            if block_type == "text":
                content_blocks.append(TextBlock(text=block.text))

            elif block_type == "thinking":
                thinking_text = getattr(block, "thinking", "")
                incomplete = stop_reason == "tool_use"
                content_blocks.append(
                    ReasoningBlock(
                        reasoning=thinking_text,
                        incomplete=incomplete,
                    )
                )

            elif block_type == "tool_use":
                arguments: dict[str, Any] = {}
                input_data = getattr(block, "input", {})
                if isinstance(input_data, dict):
                    arguments = input_data
                elif isinstance(input_data, str):
                    try:
                        arguments = json.loads(input_data)
                    except (json.JSONDecodeError, TypeError):
                        arguments = {}

                content_blocks.append(
                    ToolCallBlock(
                        id=getattr(block, "id", ""),
                        name=getattr(block, "name", ""),
                        arguments=arguments,
                    )
                )

        if not content_blocks:
            content_blocks.append(TextBlock(text=""))

        token_usage = None
        usage = getattr(response, "usage", None)
        if usage:
            token_usage = TokenUsage(
                input_tokens=getattr(usage, "input_tokens", 0) or 0,
                output_tokens=getattr(usage, "output_tokens", 0) or 0,
            )

        response_metadata: dict[str, Any] = {}
        model_name = getattr(response, "model", None)
        if model_name:
            response_metadata["model"] = model_name
        if stop_reason:
            response_metadata["stop_reason"] = stop_reason

        return LLMResponse(
            content_blocks=content_blocks,
            token_usage=token_usage,
            response_metadata=response_metadata,
            raw=response,
        )
