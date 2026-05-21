# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""chat 模块：交互格式层。

核心数据模型：
- ContentBlock 系列：TextBlock, ReasoningBlock, ImageBlock, AudioBlock, FileBlock,
  ToolCallBlock, ToolResultBlock, ErrorBlock, ToolCallChunkBlock（预留）
- ChatMessage：统一消息表示（content_blocks + source）
- LLMResponse：统一的 LLM 响应
- ChatFormat：格式适配器抽象基类
- TokenUsage：token 用量

格式适配器：
- OpenAIFormat：OpenAI 兼容格式（含 DeepSeek reasoning_content + 多模态）
- AnthropicFormat：Anthropic 格式（含 thinking + tool_result 转换）

序列化：
- serialize_messages / deserialize_messages：ChatMessage 列表序列化
- 支持 ChatMessage 和旧格式自动迁移

工具函数：
- extract_token_usage / extract_reasoning_content / extract_response_metadata
"""

from ghrah.chat.content import (
    AudioBlock,
    ContentBlock,
    ErrorBlock,
    FileBlock,
    ImageBlock,
    ReasoningBlock,
    StreamingBlock,
    TextBlock,
    ToolCallBlock,
    ToolCallChunkBlock,
    ToolResultBlock,
    block_from_dict,
    block_to_dict,
)
from ghrah.chat.format import ChatFormat, LLMResponse, TokenUsage
from ghrah.chat.message import ChatMessage
from ghrah.chat.response import (
    extract_reasoning_content,
    extract_response_metadata,
    extract_token_usage,
)
from ghrah.chat.serialization import (
    deserialize_messages,
    migrate_langchain_messages,
    serialize_messages,
)

__all__ = [
    # Content blocks
    "TextBlock",
    "ReasoningBlock",
    "ImageBlock",
    "AudioBlock",
    "FileBlock",
    "ToolCallBlock",
    "ToolResultBlock",
    "ErrorBlock",
    "ToolCallChunkBlock",
    "ContentBlock",
    "StreamingBlock",
    "block_from_dict",
    "block_to_dict",
    # Message
    "ChatMessage",
    # Format
    "ChatFormat",
    "LLMResponse",
    "TokenUsage",
    # Response utils
    "extract_token_usage",
    "extract_reasoning_content",
    "extract_response_metadata",
    # Serialization
    "serialize_messages",
    "deserialize_messages",
    "migrate_langchain_messages",  # deprecated alias
]
