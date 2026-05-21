# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""测试 LLM 响应元数据提取工具函数。

覆盖 extract_token_usage、extract_reasoning_content、extract_response_metadata
在各种 LLMResponse 格式下的行为。
"""

import pytest

from ghrah.chat.content import ReasoningBlock, TextBlock
from ghrah.chat.format import LLMResponse, TokenUsage
from ghrah.llm.response_utils import (
    extract_reasoning_content,
    extract_response_metadata,
    extract_token_usage,
)

# ----------------------------------------------------------------
# extract_token_usage 测试
# ----------------------------------------------------------------


class TestExtractTokenUsage:
    """测试 extract_token_usage 函数。"""

    def test_usage_metadata_standard(self) -> None:
        """标准 TokenUsage 格式。"""
        response = LLMResponse(
            content_blocks=[TextBlock(text="Hello")],
            token_usage=TokenUsage(input_tokens=100, output_tokens=50, total_tokens=150),
        )
        result = extract_token_usage(response)
        assert result is not None
        assert result.input_tokens == 100
        assert result.output_tokens == 50
        assert result.total_tokens == 150

    def test_usage_metadata_with_zero_tokens(self) -> None:
        """TokenUsage 中所有 token 为 0 时返回 None。"""
        response = LLMResponse(
            content_blocks=[TextBlock(text="Hello")],
            token_usage=TokenUsage(input_tokens=0, output_tokens=0, total_tokens=0),
        )
        result = extract_token_usage(response)
        assert result is None

    def test_response_metadata_openai_format(self) -> None:
        """OpenAI 原始 token_usage 格式（response_metadata 中）。"""
        response = LLMResponse(
            content_blocks=[TextBlock(text="Hello")],
            response_metadata={
                "model_name": "gpt-4",
                "token_usage": {
                    "prompt_tokens": 200,
                    "completion_tokens": 80,
                    "total_tokens": 280,
                },
            },
        )
        result = extract_token_usage(response)
        assert result is not None
        assert result.input_tokens == 200
        assert result.output_tokens == 80
        assert result.total_tokens == 280

    def test_usage_metadata_priority_over_response_metadata(self) -> None:
        """token_usage 优先于 response_metadata.token_usage。"""
        response = LLMResponse(
            content_blocks=[TextBlock(text="Hello")],
            token_usage=TokenUsage(input_tokens=100, output_tokens=50, total_tokens=150),
            response_metadata={
                "token_usage": {
                    "prompt_tokens": 999,
                    "completion_tokens": 999,
                    "total_tokens": 999,
                },
            },
        )
        result = extract_token_usage(response)
        assert result is not None
        assert result.input_tokens == 100
        assert result.output_tokens == 50
        assert result.total_tokens == 150

    def test_no_metadata(self) -> None:
        """没有 token_usage 和 response_metadata 时返回 None。"""
        response = LLMResponse(content_blocks=[TextBlock(text="Hello")])
        result = extract_token_usage(response)
        assert result is None

    def test_empty_response_metadata(self) -> None:
        """response_metadata 为空字典时返回 None。"""
        response = LLMResponse(
            content_blocks=[TextBlock(text="Hello")],
            response_metadata={},
        )
        result = extract_token_usage(response)
        assert result is None

    def test_response_metadata_without_token_usage(self) -> None:
        """response_metadata 中没有 token_usage 键时返回 None。"""
        response = LLMResponse(
            content_blocks=[TextBlock(text="Hello")],
            response_metadata={"model_name": "gpt-4", "finish_reason": "stop"},
        )
        result = extract_token_usage(response)
        assert result is None

    def test_partial_usage_metadata_only_input(self) -> None:
        """token_usage 仅有 input_tokens 时仍能提取。"""
        response = LLMResponse(
            content_blocks=[TextBlock(text="Hello")],
            token_usage=TokenUsage(input_tokens=50, output_tokens=0, total_tokens=0),
        )
        result = extract_token_usage(response)
        assert result is not None
        assert result.input_tokens == 50


# ----------------------------------------------------------------
# extract_reasoning_content 测试
# ----------------------------------------------------------------


class TestExtractReasoningContent:
    """测试 extract_reasoning_content 函数。"""

    def test_reasoning_content_in_content_blocks(self) -> None:
        """content_blocks 中包含 ReasoningBlock。"""
        response = LLMResponse(
            content_blocks=[
                ReasoningBlock(reasoning="Let me think about this..."),
                TextBlock(text="The answer is 42"),
            ],
        )
        result = extract_reasoning_content(response)
        assert result == "Let me think about this..."

    def test_no_reasoning_content(self) -> None:
        """没有 ReasoningBlock 时返回 None。"""
        response = LLMResponse(content_blocks=[TextBlock(text="The answer is 42")])
        result = extract_reasoning_content(response)
        assert result is None

    def test_empty_content_blocks(self) -> None:
        """空 content_blocks 时返回 None。"""
        response = LLMResponse(content_blocks=[])
        result = extract_reasoning_content(response)
        assert result is None

    def test_reasoning_content_is_empty_string(self) -> None:
        """ReasoningBlock 的 reasoning 为空字符串时返回 None。"""
        response = LLMResponse(
            content_blocks=[
                ReasoningBlock(reasoning=""),
                TextBlock(text="Hello"),
            ],
        )
        result = extract_reasoning_content(response)
        assert result is None

    def test_text_only_content(self) -> None:
        """只有 TextBlock 没有 ReasoningBlock 时返回 None。"""
        response = LLMResponse(
            content_blocks=[TextBlock(text="The answer is 42")],
        )
        result = extract_reasoning_content(response)
        assert result is None


# ----------------------------------------------------------------
# extract_response_metadata 测试
# ----------------------------------------------------------------


class TestExtractResponseMetadata:
    """测试 extract_response_metadata 函数。"""

    def test_with_response_metadata(self) -> None:
        """正常提取 response_metadata。"""
        response = LLMResponse(
            content_blocks=[TextBlock(text="Hello")],
            response_metadata={
                "model_name": "deepseek-chat",
                "finish_reason": "stop",
                "token_usage": {"prompt_tokens": 10},
            },
        )
        result = extract_response_metadata(response)
        assert result == {
            "model_name": "deepseek-chat",
            "finish_reason": "stop",
            "token_usage": {"prompt_tokens": 10},
        }

    def test_empty_response_metadata(self) -> None:
        """response_metadata 为空字典时返回空字典。"""
        response = LLMResponse(
            content_blocks=[TextBlock(text="Hello")],
            response_metadata={},
        )
        result = extract_response_metadata(response)
        assert result == {}

    def test_no_response_metadata(self) -> None:
        """没有 response_metadata 时返回空字典。"""
        response = LLMResponse(content_blocks=[TextBlock(text="Hello")])
        result = extract_response_metadata(response)
        assert result == {}

    def test_returns_copy(self) -> None:
        """返回的是副本，不与原始对象共享引用。"""
        original_meta = {"model_name": "gpt-4", "finish_reason": "stop"}
        response = LLMResponse(
            content_blocks=[TextBlock(text="Hello")],
            response_metadata=original_meta,
        )
        result = extract_response_metadata(response)
        assert result == original_meta
        result["extra"] = "value"
        assert "extra" not in original_meta


# ----------------------------------------------------------------
# TokenUsage dataclass 测试
# ----------------------------------------------------------------


class TestTokenUsage:
    """测试 TokenUsage dataclass。"""

    def test_default_values(self) -> None:
        """默认值全为 0。"""
        usage = TokenUsage()
        assert usage.input_tokens == 0
        assert usage.output_tokens == 0
        assert usage.total_tokens == 0

    def test_to_dict(self) -> None:
        """to_dict 正确转换。"""
        usage = TokenUsage(input_tokens=100, output_tokens=50, total_tokens=150)
        d = usage.to_dict()
        assert d == {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150}

    def test_from_dict(self) -> None:
        """from_dict 正确创建。"""
        d = {"input_tokens": 200, "output_tokens": 100, "total_tokens": 300}
        usage = TokenUsage.from_dict(d)
        assert usage.input_tokens == 200
        assert usage.output_tokens == 100
        assert usage.total_tokens == 300

    def test_from_dict_partial(self) -> None:
        """from_dict 对缺失字段使用默认值 0。"""
        usage = TokenUsage.from_dict({"input_tokens": 50})
        assert usage.input_tokens == 50
        assert usage.output_tokens == 0
        assert usage.total_tokens == 0

    def test_from_dict_empty(self) -> None:
        """from_dict 空字典全部默认为 0。"""
        usage = TokenUsage.from_dict({})
        assert usage.input_tokens == 0
        assert usage.output_tokens == 0
        assert usage.total_tokens == 0

    def test_round_trip(self) -> None:
        """to_dict → from_dict 往返一致。"""
        original = TokenUsage(input_tokens=42, output_tokens=24, total_tokens=66)
        restored = TokenUsage.from_dict(original.to_dict())
        assert restored == original


# ----------------------------------------------------------------
# 输入类型验证测试
# ----------------------------------------------------------------


class TestInputTypeValidation:
    """测试 extract_* 函数对非 LLMResponse 输入的类型验证。"""

    def test_extract_token_usage_rejects_non_llmresponse(self) -> None:
        """extract_token_usage 应拒绝非 LLMResponse 输入。"""
        with pytest.raises(TypeError, match="Expected LLMResponse"):
            extract_token_usage("not an LLMResponse")  # type: ignore[arg-type]

    def test_extract_token_usage_rejects_none(self) -> None:
        """extract_token_usage 应拒绝 None 输入。"""
        with pytest.raises(TypeError, match="Expected LLMResponse"):
            extract_token_usage(None)  # type: ignore[arg-type]

    def test_extract_reasoning_content_rejects_non_llmresponse(self) -> None:
        """extract_reasoning_content 应拒绝非 LLMResponse 输入。"""
        with pytest.raises(TypeError, match="Expected LLMResponse"):
            extract_reasoning_content(42)  # type: ignore[arg-type]

    def test_extract_response_metadata_rejects_non_llmresponse(self) -> None:
        """extract_response_metadata 应拒绝非 LLMResponse 输入。"""
        with pytest.raises(TypeError, match="Expected LLMResponse"):
            extract_response_metadata({"key": "value"})  # type: ignore[arg-type]
