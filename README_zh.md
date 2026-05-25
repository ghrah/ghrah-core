# 九夏/ghrah

**这是一个Alpha版本的框架，可用于概念验证，并非生产就绪，可能有大量的破坏性更新**

通用分布式智能体集群框架

可以用于构建安全的，可审计的，为各种任务负载，从单智能体到智能体集群系统的运行时核心

## 快速开始

### 安装依赖

```bash
uv sync
```

### (推荐) 配置 Agentconf

使用 Agentconf 的 TUI 配置你的 LLM 供应商、模型、Agent

```bash
uv run agentconf
```

### 直接配置（无需 agentconf）

如果不使用 agentconf，可以直接构造 `ChatFormat` 并注入到 Agent 中：

```python
from ghrah.abilities.builtin.conversation import ConversationAbility
from ghrah.agents.base import ActorAgent
from ghrah.chat.format.openai import OpenAIFormat
from ghrah.core.config import AgentConfig

config = AgentConfig(name="assistant", system_prompt="你是一个 AI 助手。")
agent = ActorAgent(config)
agent.register_ability(ConversationAbility())

# 直接构造 ChatFormat 并注入（跳过 agentconf，这是一种变通，后续会改进）
agent._llm = OpenAIFormat(
    model="gpt-4o",
    api_key="sk-your-api-key",
    base_url="https://api.openai.com/v1",
)

response = await agent.chat("你好！")
```

支持的 `ChatFormat` 子类：`OpenAIFormat`、`AnthropicFormat`、`DeepSeekFormat`。详见 [配置参考](docs/configuration.md)。

### 运行示例

```bash
uv run python examples/simple_chat.py
```

或者运行examples下的其他示例

## 项目结构

```
src/ghrah/
├── core/           # 核心抽象：配置、消息、事件、异常、HITL、CommandSender
├── agents/         # Agent 实现：ActorAgent 基类
├── chat/           # LLM 交互层：ChatMessage、ContentBlock、ChatFormat
│   └── format/     # 格式适配器：OpenAIFormat、AnthropicFormat
├── abilities/      # 能力系统：Ability 接口、Hook、执行器、内置 Ability
│   └── builtin/    # 内置 Ability：对话、文件操作、任务终止、集群操作等
├── context/        # 上下文管理：ActionChain、StateManager、MessageStore、窗口策略
│   └── persistence/# 持久化后端：JSON、SQLite、内存、远程
├── llm/            # LLM 集成：LLMFactory（agentconf → ChatFormat）
└── communication/  # 通信层：Router、Registry、Supervisor
```

## 文档

完整使用说明文档见 [docs/](docs/) 目录：

| 文档 | 中文 | English |
|------|------|---------|
| 安装与快速开始 | [getting-started.md](docs/getting-started.md) | [getting-started_en.md](docs/getting-started_en.md) |
| 核心概念 | [core-concepts.md](docs/core-concepts.md) | [core-concepts_en.md](docs/core-concepts_en.md) |
| Ability 系统 | [ability-system.md](docs/ability-system.md) | [ability-system_en.md](docs/ability-system_en.md) |
| Hook 机制 | [hook-mechanism.md](docs/hook-mechanism.md) | [hook-mechanism_en.md](docs/hook-mechanism_en.md) |
| 上下文管理 | [context-management.md](docs/context-management.md) | [context-management_en.md](docs/context-management_en.md) |
| 多 Agent 通信 | [multi-agent.md](docs/multi-agent.md) | [multi-agent_en.md](docs/multi-agent_en.md) |
| 持久化与窗口管理 | [persistence.md](docs/persistence.md) | [persistence_en.md](docs/persistence_en.md) |
| 内置 Ability 参考 | [builtin-abilities.md](docs/builtin-abilities.md) | [builtin-abilities_en.md](docs/builtin-abilities_en.md) |
| 配置参考 | [configuration.md](docs/configuration.md) | [configuration_en.md](docs/configuration_en.md) |
| 异常处理 | [error-handling.md](docs/error-handling.md) | [error-handling_en.md](docs/error-handling_en.md) |
| 架构图与流程图 | [architecture.md](docs/architecture.md) | [architecture_en.md](docs/architecture_en.md) |
| Chat 交互层 | [chat-module.md](docs/chat-module.md) | [chat-module_en.md](docs/chat-module_en.md) |
| 双模式架构 | [distributed-mode.md](docs/distributed-mode.md) | [distributed-mode_en.md](docs/distributed-mode_en.md) |
| HITL 人在回路 | [hitl.md](docs/hitl.md) | [hitl_en.md](docs/hitl_en.md) |

## 开发

```bash
# 安装开发依赖
uv sync --extra dev

# 运行测试
uv run pytest tests/ -v

# 代码检查
uv run ruff check src/ tests/
```

## License

Apache 2.0
