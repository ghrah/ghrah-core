# Chat 交互层

ghrah 的 `chat/` 模块是自建的 LLM 交互层。核心思路是**封装交互格式而非封装 Provider**——所有供应商的 API 都遵循两种主要格式（OpenAI 格式和 Anthropic 格式），以及拓展的比如DeepSeek格式(支持思维链中的工具调用)。

## 设计动机

ghrah 自建 `chat/` 模块带来以下优势：

- **消除重依赖**：不再依赖 `langchain-core` 及其传递依赖
- **支持推理中工具调用**：DeepSeek v4 Pro 等模型的响应可交错包含 reasoning、text、tool_calls
- **支持多模态**：图片、音频、文件等非文本内容
- **多 Agent 消息溯源**：`source` 字段追踪Agent集群模型下的消息来源

## ContentBlock 类型体系

[`ContentBlock`](../src/ghrah/chat/content.py) 是内容块的联合类型，一条消息可包含多个不同类型的内容块：

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

### Block 类型说明

| 类型 | 字段 | 说明 |
|------|------|------|
| `TextBlock` | `text: str` | 文本内容，最基础的 Block |
| `ReasoningBlock` | `reasoning: str`, `incomplete: bool` | 推理内容（DeepSeek reasoning_content、Claude thinking） |
| `ImageBlock` | `url`, `base64`, `mime_type` | 图片（URL 或 base64 编码） |
| `AudioBlock` | `data`, `mime_type` | 音频数据 |
| `FileBlock` | `url`, `base64`, `mime_type`, `filename` | 文件（PDF、代码等） |
| `ToolCallBlock` | `id`, `name`, `arguments` | 工具调用请求 |
| `ToolResultBlock` | `tool_call_id`, `name`, `content`, `success`, `error` | 工具调用结果 |
| `ErrorBlock` | `error_type`, `message`, `details` | 错误信息 |
| `ToolCallChunkBlock` | `index`, `id`, `name`, `arguments_chunk` | 流式工具调用片段（预留） |

### 序列化

每个 Block 都可以通过 `block_to_dict` / `block_from_dict` 序列化：

```python
from ghrah.chat.content import block_to_dict, block_from_dict, TextBlock

block = TextBlock(text="Hello")
data = block_to_dict(block)  # {"type": "text", "text": "Hello"}
restored = block_from_dict(data)  # TextBlock(text="Hello")
```

## ChatMessage

[`ChatMessage`](../src/ghrah/chat/message.py) 是与 LLM 交互时使用的统一消息类型：

```python
from ghrah.chat.message import ChatMessage

msg = ChatMessage(
    role="user",                          # "system" | "user" | "ai" | "tool"
    content_blocks=[TextBlock(text="Hello")],
    source="human",                       # 消息来源追踪
    metadata={},                          # 附加元数据
)
```

### 工厂方法

ChatMessage 提供便捷的工厂方法：

```python
# 系统消息
sys_msg = ChatMessage.system("你是一个助手")

# 用户消息
user_msg = ChatMessage.user("你好")
user_msg = ChatMessage.user([TextBlock(text="看这张图"), ImageBlock(url="https://...")])

# AI 消息
ai_msg = ChatMessage.ai(text="我来帮你", reasoning="用户需要帮助...")
ai_msg = ChatMessage.ai(
    text="让我查看文件",
    tool_calls=[ToolCallBlock(id="call_1", name="read_file", arguments={"path": "/tmp/a.txt"})],
)

# 工具结果消息
tool_msg = ChatMessage.tool(
    tool_call_id="call_1",
    content="文件内容...",
    name="read_file",
    success=True,
)
```

### 便捷属性

```python
msg = ChatMessage.ai(
    text="让我查看文件",
    reasoning="用户需要读取文件",
    tool_calls=[ToolCallBlock(id="call_1", name="read_file", arguments={})],
)

msg.text           # "让我查看文件" — 所有 TextBlock 的文本拼接
msg.tool_calls     # [ToolCallBlock(...)] — 所有 ToolCallBlock
msg.has_tool_calls # True
msg.reasoning      # "用户需要读取文件" — 第一个 ReasoningBlock 的内容
msg.images         # [] — 所有 ImageBlock
msg.is_multimodal  # False — 是否包含图片/音频/文件
msg.tool_results   # [] — 所有 ToolResultBlock
```

### source 字段

`source` 字段用于多 Agent 场景下追踪消息来源。在 Actor 模型中，消息可能在多个 Agent 之间流转，`source` 记录消息的原始产生者：

```python
# Agent A 发送消息给 Agent B
msg = ChatMessage.user("请处理这个任务", source="agent_a")
```

### 序列化

```python
data = msg.to_dict()
restored = ChatMessage.from_dict(data)
```

## LLMResponse

[`LLMResponse`](../src/ghrah/chat/format/__init__.py) 是 ChatFormat 返回的统一响应：

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
response.to_chat_message(source="gpt-4o")  # 转换为 ChatMessage
```

## ChatFormat 格式适配器

[`ChatFormat`](../src/ghrah/chat/format/__init__.py) 是 LLM 交互的抽象基类，封装不同 SDK 的消息格式差异：

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

[`OpenAIFormat`](../src/ghrah/chat/format/openai.py) 适配 OpenAI/DeepSeek 兼容格式：

- 支持 `reasoning_content`（DeepSeek 推理输出）
- 支持多模态输入（图片 URL、base64）
- 支持工具调用（`tool_calls`）
- 使用 `openai` SDK 的 `AsyncOpenAI` 客户端

```python
from ghrah.chat.format.openai import OpenAIFormat

fmt = OpenAIFormat(
    model="gpt-4o",
    api_key="sk-...",
    base_url="https://api.openai.com/v1",  # 可选，兼容 DeepSeek 等服务
    temperature=0.7,
    max_tokens=4096,
)

response = await fmt.generate(messages=[ChatMessage.user("Hello")])
```

### AnthropicFormat

[`AnthropicFormat`](../src/ghrah/chat/format/anthropic.py) 适配 Anthropic 格式：

- 支持 `thinking` 块（Claude 推理输出）
- 支持 `tool_use` / `tool_result` 转换
- 系统提示词通过 `system` 参数传递（而非消息列表）
- 使用 `anthropic` SDK 的 `AsyncAnthropic` 客户端

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

### create_format 工厂函数

根据 `provider_type` 创建对应的 ChatFormat：

```python
from ghrah.chat.format import create_format

fmt = create_format("openai", model="gpt-4o", api_key="sk-...")
fmt = create_format("anthropic", model="claude-sonnet-4-20250514", api_key="sk-ant-...")
```

## LLMFactory

[`LLMFactory`](../src/ghrah/llm/factory.py) 从 agentconf 配置自动创建 ChatFormat：

```python
from ghrah.llm.factory import LLMFactory
from agentconf import AgentsConfig

resolved = AgentsConfig().resolve_agent("assistant")
fmt = LLMFactory.create(resolved)
# 根据 resolved.provider_type 自动选择 OpenAIFormat 或 AnthropicFormat
```

## 消息序列化

[`serialization.py`](../src/ghrah/chat/serialization.py) 提供 ChatMessage 列表的序列化/反序列化：

```python
from ghrah.chat.serialization import serialize_messages, deserialize_messages

# 序列化
data = serialize_messages(messages)

# 反序列化
messages = deserialize_messages(data)
```

## 响应工具函数

[`response.py`](../src/ghrah/chat/response.py) 提供从 LLMResponse 提取元数据的工具函数：

```python
from ghrah.chat.response import extract_token_usage, extract_reasoning_content, extract_response_metadata

token_usage = extract_token_usage(response)       # TokenUsage | None
reasoning = extract_reasoning_content(response)   # str | None
metadata = extract_response_metadata(response)    # dict
```

## 模块结构

```
src/ghrah/chat/
├── __init__.py          # 公共 API 重导出
├── content.py           # ContentBlock 类型体系和序列化
├── message.py           # ChatMessage 数据类
├── response.py          # LLMResponse 元数据提取工具
├── serialization.py     # 消息序列化/反序列化
└── format/
    ├── __init__.py      # ChatFormat ABC, LLMResponse, TokenUsage, create_format
    ├── openai.py        # OpenAIFormat
    └── anthropic.py     # AnthropicFormat
```

## 与框架层 Message 的关系

ghrah 有两种消息类型，用于不同层次：

| 类型 | 模块 | 用途 |
|------|------|------|
| `Message` | `ghrah.core.message` | Agent 间通信（框架层协议） |
| `ChatMessage` | `ghrah.chat.message` | LLM 交互（chat 层协议） |

`Message` 用于 ActorAgent 之间的消息传递，`ChatMessage` 用于与 LLM 的交互。ActorAgent 内部将 `Message` 转换为 `ChatMessage` 后与 LLM 交互。

## 下一步

- [核心概念](core-concepts.md) — 了解 ChatFormat 在三大支柱中的位置
- [双模式架构](distributed-mode.md) — 了解 ChatFormat 在本地和分布式模式下的使用
- [配置参考](configuration.md) — 了解 LLM 配置管理
