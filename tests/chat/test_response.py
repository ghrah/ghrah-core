# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import pytest

from ghrah.chat.content import ReasoningBlock, TextBlock
from ghrah.chat.format import LLMResponse, TokenUsage
from ghrah.chat.response import (
    extract_reasoning_content,
    extract_response_metadata,
    extract_token_usage,
)


class TestExtractTokenUsage:
    def test_with_token_usage(self) -> None:
        resp = LLMResponse(
            content_blocks=[TextBlock(text="Hello")],
            token_usage=TokenUsage(input_tokens=100, output_tokens=50, total_tokens=150),
        )
        result = extract_token_usage(resp)
        assert result is not None
        assert result.input_tokens == 100
        assert result.output_tokens == 50
        assert result.total_tokens == 150

    def test_all_zero_returns_none(self) -> None:
        resp = LLMResponse(
            content_blocks=[TextBlock(text="Hello")],
            token_usage=TokenUsage(input_tokens=0, output_tokens=0, total_tokens=0),
        )
        assert extract_token_usage(resp) is None

    def test_no_token_usage_fallback_to_response_metadata(self) -> None:
        resp = LLMResponse(
            content_blocks=[TextBlock(text="Hello")],
            response_metadata={
                "token_usage": {
                    "prompt_tokens": 200,
                    "completion_tokens": 80,
                    "total_tokens": 280,
                },
            },
        )
        result = extract_token_usage(resp)
        assert result is not None
        assert result.input_tokens == 200
        assert result.output_tokens == 80
        assert result.total_tokens == 280

    def test_no_metadata_returns_none(self) -> None:
        resp = LLMResponse(content_blocks=[TextBlock(text="Hello")])
        assert extract_token_usage(resp) is None

    def test_rejects_non_llmresponse(self) -> None:
        with pytest.raises(TypeError, match="Expected LLMResponse"):
            extract_token_usage("not a response")  # type: ignore[arg-type]


class TestExtractReasoningContent:
    def test_with_reasoning(self) -> None:
        resp = LLMResponse(
            content_blocks=[ReasoningBlock(reasoning="thinking..."), TextBlock(text="answer")],
        )
        assert extract_reasoning_content(resp) == "thinking..."

    def test_no_reasoning_returns_none(self) -> None:
        resp = LLMResponse(content_blocks=[TextBlock(text="answer")])
        assert extract_reasoning_content(resp) is None

    def test_empty_reasoning_returns_none(self) -> None:
        resp = LLMResponse(
            content_blocks=[ReasoningBlock(reasoning=""), TextBlock(text="answer")]
        )
        assert extract_reasoning_content(resp) is None

    def test_empty_content_blocks_returns_none(self) -> None:
        resp = LLMResponse(content_blocks=[])
        assert extract_reasoning_content(resp) is None

    def test_rejects_non_llmresponse(self) -> None:
        with pytest.raises(TypeError, match="Expected LLMResponse"):
            extract_reasoning_content(42)  # type: ignore[arg-type]


class TestExtractResponseMetadata:
    def test_with_metadata(self) -> None:
        meta = {"model": "gpt-4", "finish_reason": "stop"}
        resp = LLMResponse(
            content_blocks=[TextBlock(text="Hello")],
            response_metadata=meta,
        )
        result = extract_response_metadata(resp)
        assert result == meta

    def test_returns_copy(self) -> None:
        meta = {"model": "gpt-4"}
        resp = LLMResponse(
            content_blocks=[TextBlock(text="Hello")],
            response_metadata=meta,
        )
        result = extract_response_metadata(resp)
        result["extra"] = "value"
        assert "extra" not in meta

    def test_empty_metadata_returns_empty(self) -> None:
        resp = LLMResponse(
            content_blocks=[TextBlock(text="Hello")],
            response_metadata={},
        )
        assert extract_response_metadata(resp) == {}

    def test_no_metadata_returns_empty(self) -> None:
        resp = LLMResponse(content_blocks=[TextBlock(text="Hello")])
        assert extract_response_metadata(resp) == {}

    def test_rejects_non_llmresponse(self) -> None:
        with pytest.raises(TypeError, match="Expected LLMResponse"):
            extract_response_metadata({"key": "val"})  # type: ignore[arg-type]
