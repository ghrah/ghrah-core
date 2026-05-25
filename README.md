# Jiuxia/ghrah

[简体中文](./README_zh.md)

**This is an Alpha version framework that can be used for proof of concept, it is not production-ready and may have numerous breaking updates**

A general-purpose distributed agent cluster framework

Can be used to build a secure, auditable runtime core for various workloads, ranging from single agents to agent cluster systems

## Quick Start

### Install Dependencies

```bash
uv sync
```

### Configure Agentconf (Recommended)

Use the Agentconf TUI to configure your LLM provider, model, and Agent

```bash
uv run agentconf
```

### Direct Configuration (Without agentconf)

If you prefer not to use agentconf, you can directly construct a `ChatFormat` and inject it into the Agent:

```python
from ghrah.abilities.builtin.conversation import ConversationAbility
from ghrah.agents.base import ActorAgent
from ghrah.chat.format.openai import OpenAIFormat
from ghrah.core.config import AgentConfig

config = AgentConfig(name="assistant", system_prompt="You are an AI assistant.")
agent = ActorAgent(config)
agent.register_ability(ConversationAbility())

# Directly construct ChatFormat and inject (bypasses agentconf， This is a workaround, and it will be improved later)
agent._llm = OpenAIFormat(
    model="gpt-4o",
    api_key="sk-your-api-key",
    base_url="https://api.openai.com/v1",
)

response = await agent.chat("Hello!")
```

Available `ChatFormat` subclasses: `OpenAIFormat`, `AnthropicFormat`, `DeepSeekFormat`. See [Configuration Reference](docs/configuration_en.md) for details.

### Run Examples

```bash
uv run python examples/simple_chat.py
```

Or run other examples under the `examples` directory

## Project Structure

```
src/ghrah/
├── core/           # Core abstractions: config, messages, events, exceptions, HITL, CommandSender
├── agents/         # Agent implementations: ActorAgent base class
├── chat/           # LLM interaction layer: ChatMessage, ContentBlock, ChatFormat
│   └── format/     # Format adapters: OpenAIFormat, AnthropicFormat
├── abilities/      # Ability system: Ability interface, hooks, executors, built-in abilities
│   └── builtin/    # Built-in abilities: conversation, file operations, task termination, cluster operations, etc.
├── context/        # Context management: ActionChain, StateManager, MessageStore, window policies
│   └── persistence/# Persistence backends: JSON, SQLite, in-memory, remote
├── llm/            # LLM integration: LLMFactory (agentconf → ChatFormat)
└── communication/  # Communication layer: Router, Registry, Supervisor
```

## Documentation

For full usage documentation, see the [docs/](docs/) directory:

| Document | 中文 | English |
|----------|------|---------|
| Installation & Quick Start | [getting-started.md](docs/getting-started.md) | [getting-started_en.md](docs/getting-started_en.md) |
| Core Concepts | [core-concepts.md](docs/core-concepts.md) | [core-concepts_en.md](docs/core-concepts_en.md) |
| Ability System | [ability-system.md](docs/ability-system.md) | [ability-system_en.md](docs/ability-system_en.md) |
| Hook Mechanism | [hook-mechanism.md](docs/hook-mechanism.md) | [hook-mechanism_en.md](docs/hook-mechanism_en.md) |
| Context Management | [context-management.md](docs/context-management.md) | [context-management_en.md](docs/context-management_en.md) |
| Multi-Agent Communication | [multi-agent.md](docs/multi-agent.md) | [multi-agent_en.md](docs/multi-agent_en.md) |
| Persistence & Window Management | [persistence.md](docs/persistence.md) | [persistence_en.md](docs/persistence_en.md) |
| Built-in Ability Reference | [builtin-abilities.md](docs/builtin-abilities.md) | [builtin-abilities_en.md](docs/builtin-abilities_en.md) |
| Configuration Reference | [configuration.md](docs/configuration.md) | [configuration_en.md](docs/configuration_en.md) |
| Error Handling | [error-handling.md](docs/error-handling.md) | [error-handling_en.md](docs/error-handling_en.md) |
| Architecture & Flow Diagrams | [architecture.md](docs/architecture.md) | [architecture_en.md](docs/architecture_en.md) |
| Chat Interaction Layer | [chat-module.md](docs/chat-module.md) | [chat-module_en.md](docs/chat-module_en.md) |
| Dual-Mode Architecture | [distributed-mode.md](docs/distributed-mode.md) | [distributed-mode_en.md](docs/distributed-mode_en.md) |
| HITL Human-in-the-Loop | [hitl.md](docs/hitl.md) | [hitl_en.md](docs/hitl_en.md) |

## Development

```bash
# Install optional-dependencies
uv sync --extra dev

# Run tests
uv run pytest tests/ -v

# Lint
uv run ruff check src/ tests/
```

## License

Apache 2.0