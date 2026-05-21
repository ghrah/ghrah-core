# Chat Module

ghrah's `chat/` module is a self-contained LLM interaction layer that replaces LangChain's message types and LLM client wrappers. The core idea is to **encapsulate interaction formats rather than providers** — all vendor APIs follow two primary formats (OpenAI format and Anthropic format), so only two Format adapters need to be implemented.

## Design Motivation

ghrah only used three narrow LangChain features (LLM client wrappers, message type system, Tool binding & parsing) without using its core capabilities. Building the `chat/` module brings the following advantages:

- **Eliminate heavy dependencies**: No longer depends on `langchain-core` and its transitive dependencies
- **Support mid-reasoning tool calls**: Models like DeepSeek v4 Pro can interleave reasoning, text, and tool_calls in a single response
- **Support multimodal**: Images, audio, files, and other non-text content
- **Multi-Agent message tracing**: The `source` field tracks message origin in the Actor model

## ContentBlock Type System

[`ContentBlock`](../src/ghrah/chat/content.py) is a union type for content blocks. A single message can contain multiple blocks of different types:

```python
from ghrah.chat.content import (
    TextBlock,
    ReasoningBlock,
    ImageBlock,
    AudioBlock,
    FileBlock,
    ToolCallBlock,
    ToolResultBlock,
    ErrorBlock,
    ToolCallChunkBlock,
)

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
```

### Block Type Descriptions

| Type | Fields | Description |
|------|--------|-------------|
| `TextBlock` | `text: str` | Text content, the most basic Block |
| `ReasoningBlock` | `reasoning: str`, `incomplete: bool` | Reasoning content (DeepSeek reasoning_content, Claude thinking) |
| `ImageBlock` | `url`, `base64`, `mime_type` | Image (URL or base64 encoded) |
| `AudioBlock` | `data`, `mime_type` | Audio data |
| `FileBlock` | `url`, `base64`, `mime_type`, `filename` | File (PDF, code, etc.) |
| `ToolCallBlock` | `id`, `name`, `arguments` | Tool call request |
| `ToolResultBlock` | `tool_call_id`, `name`, `content`, `success`, `error` | Tool call result |
| `ErrorBlock` | `error_type`, `message`, `details` | Error information |
| `ToolCallChunkBlock` | `index`, `id`, `name`, `arguments_chunk` | Streaming tool call chunk (reserved) |

### Serialization

Each Block can be serialized via `block_to_dict` / `block_from_dict`:

```python
from ghrah.chat.content import block_to_dict, block_from_dict, TextBlock

block = TextBlock(text="Hello")
data = block_to_dict(block)  # {"type": "text", "text": "Hello"}
restored = block_from_dict(data)  # TextBlock(text="Hello")
```

## ChatMessage

[`ChatMessage`](../src/ghrah/chat/message.py) is the unified message type used for LLM interaction:

```python
from ghrah.chat.message import ChatMessage

msg = ChatMessage(
    role="user",                          # "system" | "user" | "ai" | "tool"
    content_blocks=[TextBlock(text="Hello")],
    source="human",                       # Message source tracking
    metadata={},                          # Additional metadata
)
```

### Factory Methods

ChatMessage provides convenient factory methods:

```python
# System message
sys_msg = ChatMessage.system("You are an assistant")

# User message
user_msg = ChatMessage.user("Hello")
user_msg = ChatMessage.user([TextBlock(text="Look at this image"), ImageBlock(url="https://...")])

# AI message
ai_msg = ChatMessage.ai(text="Let me help you", reasoning="User needs help...")
ai_msg = ChatMessage.ai(
    text="Let me check the file",
    tool_calls=[ToolCallBlock(id="call_1", name="read_file", arguments={"path": "/tmp/a.txt"})],
)

# Tool result message
tool_msg = ChatMessage.tool(
    tool_call_id="call_1",
    content="File contents...",
    name="read_file",
    success=True,
)
```

### Convenience Properties

```python
msg = ChatMessage.ai(
    text="Let me check the file",
    reasoning="User needs to read a file",
    tool_calls=[ToolCallBlock(id="call_1", name="read_file", arguments={})],
)

msg.text           # "Let me check the file" — concatenation of all TextBlock text
msg.tool_calls     # [ToolCallBlock(...)] — all ToolCallBlocks
msg.has_tool_calls # True
msg.reasoning      # "User needs to read a file" — first ReasoningBlock's content
msg.images         # [] — all ImageBlocks
msg.is_multimodal  # False — whether it contains images/audio/files
msg.tool_results   # [] — all ToolResultBlocks
```

### source Field

The `source` field is used to track message origin in multi-Agent scenarios. In the Actor model, messages may flow between multiple Agents, and `source` records the original producer:

```python
# Agent A sends message to Agent B
msg = ChatMessage.user("Please process this task", source="agent_a")
```

### Serialization

```python
data = msg.to_dict()
restored = ChatMessage.from_dict(data)
```

## LLMResponse

[`LLMResponse`](../src/ghrah/chat/format/__init__.py) is the unified response returned by ChatFormat:

```python
from ghrah.chat.format import LLMResponse, TokenUsage

response = LLMResponse(
    content_blocks=[TextBlock(text="Hello"), ToolCallBlock(id="c1", name="tool", arguments={})],
    token_usage=TokenUsage(input_tokens=10, output_tokens=20, total_tokens=30),
    response_metadata={"model": "gpt-4o"},
    raw=None,
)

response.text           # "Hello"
response.tool_calls     # [ToolCallBlock(...)]
response.reasoning      # None
response.to_chat_message(source="gpt-4o")  # Convert to ChatMessage
```

## ChatFormat Adapters

[`ChatFormat`](../src/ghrah/chat/format/__init__.py) is the abstract base class for LLM interaction, encapsulating message format differences across SDKs:

```python
from abc import ABC, abstractmethod
from ghrah.chat.format import ChatFormat, LLMResponse

class ChatFormat(ABC):
    @abstractmethod
    async def generate(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        ...
    
    def configure_tools(self, tools: list[dict[str, Any]]) -> None:
        self._tools = tools
```

### OpenAIFormat

[`OpenAIFormat`](../src/ghrah/chat/format/openai.py) adapts the OpenAI/DeepSeek compatible format:

- Supports `reasoning_content` (DeepSeek reasoning output)
- Supports multimodal input (image URL, base64)
- Supports tool calls (`tool_calls`)
- Uses `openai` SDK's `AsyncOpenAI` client

```python
from ghrah.chat.format.openai import OpenAIFormat

fmt = OpenAIFormat(
    model="gpt-4o",
    api_key="sk-...",
    base_url="https://api.openai.com/v1",  # Optional, compatible with DeepSeek etc.
    temperature=0.7,
    max_tokens=4096,
)

response = await fmt.generate(messages=[ChatMessage.user("Hello")])
```

### AnthropicFormat

[`AnthropicFormat`](../src/ghrah/chat/format/anthropic.py) adapts the Anthropic format:

- Supports `thinking` blocks (Claude reasoning output)
- Supports `tool_use` / `tool_result` conversion
- System prompt passed via `system` parameter (not in message list)
- Uses `anthropic` SDK's `AsyncAnthropic` client

```python
from ghrah.chat.format.anthropic import AnthropicFormat

fmt = AnthropicFormat(
    model="claude-sonnet-4-20250514",
    api_key="sk-ant-...",
    temperature=0.7,
    max_tokens=4096,
)

response = await fmt.generate(messages=[ChatMessage.user("Hello")])
```

### create_format Factory Function

Creates the corresponding ChatFormat based on `provider_type`:

```python
from ghrah.chat.format import create_format

fmt = create_format("openai", model="gpt-4o", api_key="sk-...")
fmt = create_format("anthropic", model="claude-sonnet-4-20250514", api_key="sk-ant-...")
```

## LLMFactory

[`LLMFactory`](../src/ghrah/llm/factory.py) automatically creates a ChatFormat from agentconf:

```python
from ghrah.llm.factory import LLMFactory
from agentconf import AgentsConfig

resolved = AgentsConfig().resolve_agent("assistant")
fmt = LLMFactory.create(resolved)
# Automatically selects OpenAIFormat or AnthropicFormat based on resolved.provider_type
```

## Message Serialization & Migration

[`serialization.py`](../src/ghrah/chat/serialization.py) provides ChatMessage list serialization/deserialization with automatic LangChain legacy format migration:

```python
from ghrah.chat.serialization import serialize_messages, deserialize_messages, migrate_langchain_messages

# Serialize
data = serialize_messages(messages)

# Deserialize (auto-detects new/legacy format)
messages = deserialize_messages(data)

# Explicitly migrate LangChain format
migrated = migrate_langchain_messages(langchain_data)
```

LangChain legacy format messages are automatically converted during deserialization:

| LangChain Type | ChatMessage role | source |
|----------------|------------------|--------|
| `HumanMessage` | `user` | `human` |
| `AIMessage` | `ai` | `None` |
| `SystemMessage` | `system` | `system` |
| `ToolMessage` | `tool` | `None` |

## Response Utilities

[`response.py`](../src/ghrah/chat/response.py) provides utility functions for extracting metadata from LLMResponse:

```python
from ghrah.chat.response import extract_token_usage, extract_reasoning_content, extract_response_metadata

token_usage = extract_token_usage(response)       # TokenUsage | None
reasoning = extract_reasoning_content(response)   # str | None
metadata = extract_response_metadata(response)    # dict
```

## Module Structure

```
src/ghrah/chat/
├── __init__.py          # Public API re-exports
├── content.py           # ContentBlock type system and serialization
├── message.py           # ChatMessage dataclass
├── response.py          # LLMResponse metadata extraction utilities
├── serialization.py     # Message serialization/deserialization + LangChain migration
└── format/
    ├── __init__.py      # ChatFormat ABC, LLMResponse, TokenUsage, create_format
    ├── openai.py        # OpenAIFormat
    └── anthropic.py     # AnthropicFormat
```

## Relationship with Framework-level Message

ghrah has two message types for different layers:

| Type | Module | Purpose |
|------|--------|---------|
| `Message` | `ghrah.core.message` | Inter-Agent communication (framework-level protocol) |
| `ChatMessage` | `ghrah.chat.message` | LLM interaction (chat-level protocol) |

`Message` is used for message passing between ActorAgents, while `ChatMessage` is used for LLM interaction. ActorAgent internally converts `Message` to `ChatMessage` before interacting with the LLM.

## Next Steps

- [Core Concepts](core-concepts_en.md) — Understand ChatFormat's position in the three pillars
- [Dual-Mode Architecture](distributed-mode_en.md) — Learn about ChatFormat usage in local and distributed modes
- [Configuration Reference](configuration_en.md) — Learn about LLM configuration management
