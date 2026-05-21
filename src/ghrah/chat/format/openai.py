# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import logging
from typing import Any

from ghrah.chat.content import (
    AudioBlock,
    ErrorBlock,
    FileBlock,
    ImageBlock,
    ReasoningBlock,
    TextBlock,
    ToolCallBlock,
)
from ghrah.chat.format import ChatFormat, LLMResponse, TokenUsage
from ghrah.chat.message import ChatMessage

logger = logging.getLogger(__name__)


class OpenAIFormat(ChatFormat):
    def __init__(
        self,
        model: str = "",
        api_key: str | None = None,
        base_url: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
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
            import openai

            kwargs: dict[str, Any] = {}
            if self._api_key:
                kwargs["api_key"] = self._api_key
            if self._base_url:
                kwargs["base_url"] = self._base_url
            self._client = openai.AsyncOpenAI(**kwargs)
        return self._client

    async def generate(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        client = self._get_client()
        formatted = self._format_messages(messages)

        api_kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": formatted,
            "temperature": self._temperature,
        }
        if self._max_tokens is not None:
            api_kwargs["max_tokens"] = self._max_tokens
        if self._top_p is not None:
            api_kwargs["top_p"] = self._top_p

        effective_tools = tools or self._tools
        if effective_tools:
            api_kwargs["tools"] = self._format_tools(effective_tools)

        response = await client.chat.completions.create(**api_kwargs)
        return self._parse_response(response)

    def _format_messages(self, messages: list[ChatMessage]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for msg in messages:
            role = "assistant" if msg.role == "ai" else msg.role
            formatted = self._format_single_message(msg, role)
            if isinstance(formatted, list):
                result.extend(formatted)
            else:
                result.append(formatted)
        return result

    def _format_single_message(
        self, msg: ChatMessage, role: str
    ) -> dict[str, Any] | list[dict[str, Any]]:
        if msg.role == "tool":
            results = msg.tool_results
            if results:
                return {
                    "role": "tool",
                    "tool_call_id": results[0].tool_call_id,
                    "content": results[0].content,
                }
            return {"role": "tool", "tool_call_id": "", "content": ""}

        has_multimodal = any(
            isinstance(b, (ImageBlock, AudioBlock, FileBlock)) for b in msg.content_blocks
        )

        if not has_multimodal and not msg.has_tool_calls:
            text_parts = []
            for b in msg.content_blocks:
                if isinstance(b, TextBlock):
                    text_parts.append(b.text)
                elif isinstance(b, ReasoningBlock):
                    pass
            content = "".join(text_parts) or None
            d: dict[str, Any] = {"role": role, "content": content}

            reasoning_blocks = msg.find_blocks(ReasoningBlock)
            if reasoning_blocks and msg.role == "ai":
                d["reasoning_content"] = reasoning_blocks[0].reasoning

            tool_calls_list = msg.tool_calls
            if tool_calls_list and msg.role == "ai":
                d["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                        },
                    }
                    for tc in tool_calls_list
                ]
            return d

        content_parts: list[dict[str, Any]] = []
        for b in msg.content_blocks:
            if isinstance(b, TextBlock):
                content_parts.append({"type": "text", "text": b.text})
            elif isinstance(b, ReasoningBlock):
                pass
            elif isinstance(b, ImageBlock):
                if b.url:
                    content_parts.append(
                        {
                            "type": "image_url",
                            "image_url": {"url": b.url},
                        }
                    )
                elif b.base64:
                    img_part: dict[str, Any] = {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{b.mime_type or 'image/png'};base64,{b.base64}"
                        },
                    }
                    content_parts.append(img_part)
            elif isinstance(b, AudioBlock):
                content_parts.append(
                    {
                        "type": "input_audio",
                        "input_audio": {
                            "data": b.data,
                            "format": b.mime_type.split("/")[-1] if b.mime_type else "wav",
                        },
                    }
                )
            elif isinstance(b, FileBlock):
                file_part: dict[str, Any] = {
                    "type": "file",
                    "file": {},
                }
                if b.base64:
                    file_part["file"]["file_data"] = (
                        f"data:{b.mime_type or 'application/octet-stream'};base64,{b.base64}"
                    )
                if b.filename:
                    file_part["file"]["filename"] = b.filename
                content_parts.append(file_part)

        result_dict: dict[str, Any] = {"role": role, "content": content_parts}

        reasoning_blocks = msg.find_blocks(ReasoningBlock)
        if reasoning_blocks and msg.role == "ai":
            result_dict["reasoning_content"] = reasoning_blocks[0].reasoning

        tool_calls_list = msg.tool_calls
        if tool_calls_list and msg.role == "ai":
            result_dict["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                    },
                }
                for tc in tool_calls_list
            ]

        return result_dict

    def _format_tools(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        formatted: list[dict[str, Any]] = []
        for tool in tools:
            if "function" in tool and "type" in tool:
                formatted.append(tool)
            else:
                func_schema: dict[str, Any] = {
                    "name": tool.get("name", ""),
                    "parameters": tool.get("parameters", tool.get("args", {})),
                }
                if tool.get("description"):
                    func_schema["description"] = tool["description"]
                formatted.append({"type": "function", "function": func_schema})
        return formatted

    def _parse_response(self, response: Any) -> LLMResponse:
        choice = response.choices[0] if response.choices else None
        if choice is None:
            return LLMResponse(
                content_blocks=[
                    ErrorBlock(error_type="provider_error", message="No choices in response")
                ]
            )

        message = choice.message
        content_blocks: list[Any] = []

        # DeepSeek reasoning_content
        reasoning_content = getattr(message, "reasoning_content", None)
        if reasoning_content:
            content_blocks.append(ReasoningBlock(reasoning=str(reasoning_content)))

        # Parse content (text)
        content = getattr(message, "content", None)
        if content:
            if isinstance(content, str):
                content_blocks.append(TextBlock(text=content))
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict):
                        if part.get("type") == "text":
                            content_blocks.append(TextBlock(text=part.get("text", "")))
                        elif part.get("type") == "reasoning":
                            content_blocks.append(
                                ReasoningBlock(
                                    reasoning=str(part.get("text", part.get("reasoning", "")))
                                )
                            )

        # Parse tool_calls
        tool_calls = getattr(message, "tool_calls", None)
        if tool_calls:
            for tc in tool_calls:
                arguments: dict[str, Any] = {}
                func = getattr(tc, "function", None)
                if func:
                    args_str = getattr(func, "arguments", "{}")
                    try:
                        arguments = json.loads(args_str) if isinstance(args_str, str) else args_str
                    except (json.JSONDecodeError, TypeError):
                        arguments = {}
                    name = getattr(func, "name", "")
                else:
                    arguments = tc.get("arguments", tc.get("args", {}))
                    name = tc.get("name", "")

                content_blocks.append(
                    ToolCallBlock(
                        id=getattr(tc, "id", ""),
                        name=name,
                        arguments=arguments,
                    )
                )

        if not content_blocks and not tool_calls:
            content_blocks.append(TextBlock(text=""))

        # Token usage
        token_usage = None
        usage = getattr(response, "usage", None)
        if usage:
            token_usage = TokenUsage(
                input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                output_tokens=getattr(usage, "completion_tokens", 0) or 0,
                total_tokens=getattr(usage, "total_tokens", 0) or 0,
            )

        # Response metadata
        response_metadata: dict[str, Any] = {}
        model_name = getattr(response, "model", None)
        if model_name:
            response_metadata["model"] = model_name
        finish_reason = getattr(choice, "finish_reason", None)
        if finish_reason:
            response_metadata["finish_reason"] = finish_reason
        raw_usage = getattr(response, "usage", None)
        if raw_usage:
            response_metadata["usage"] = {
                "prompt_tokens": getattr(raw_usage, "prompt_tokens", 0),
                "completion_tokens": getattr(raw_usage, "completion_tokens", 0),
                "total_tokens": getattr(raw_usage, "total_tokens", 0),
            }

        return LLMResponse(
            content_blocks=content_blocks,
            token_usage=token_usage,
            response_metadata=response_metadata,
            raw=response,
        )
