# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""LLM 响应元数据提取工具函数。

从 LLMResponse 中提取 token 用量、CoT 思考内容和厂商原始响应元数据。
"""

from __future__ import annotations

from typing import Any

from ghrah.chat.format import LLMResponse, TokenUsage

__all__ = [
    "extract_token_usage",
    "extract_reasoning_content",
    "extract_response_metadata",
]


def extract_token_usage(response: LLMResponse) -> TokenUsage | None:
    if not isinstance(response, LLMResponse):
        raise TypeError(f"Expected LLMResponse, got {type(response).__name__}")

    if response.token_usage is not None:
        tu = response.token_usage
        if tu.input_tokens or tu.output_tokens or tu.total_tokens:
            return tu

    if response.response_metadata and isinstance(response.response_metadata, dict):
        raw_usage = response.response_metadata.get("token_usage")
        if isinstance(raw_usage, dict):
            return TokenUsage(
                input_tokens=raw_usage.get("prompt_tokens", 0),
                output_tokens=raw_usage.get("completion_tokens", 0),
                total_tokens=raw_usage.get("total_tokens", 0),
            )

    return None


def extract_reasoning_content(response: LLMResponse) -> str | None:
    if not isinstance(response, LLMResponse):
        raise TypeError(f"Expected LLMResponse, got {type(response).__name__}")
    result = response.reasoning
    if not result:
        return None
    return result


def extract_response_metadata(response: LLMResponse) -> dict[str, Any]:
    """从 LLMResponse 提取厂商原始响应元数据。

    Args:
        response: LLMResponse 对象

    Returns:
        响应元数据字典，如果不存在则返回空 dict

    Raises:
        TypeError: 如果 response 不是 LLMResponse 类型
    """
    if not isinstance(response, LLMResponse):
        raise TypeError(f"Expected LLMResponse, got {type(response).__name__}")

    if response.response_metadata and isinstance(response.response_metadata, dict):
        return dict(response.response_metadata)
    return {}
