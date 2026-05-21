# Installation & Quick Start

## Prerequisites

- Python >= 3.11
- [uv](https://docs.astral.sh/uv/) package manager
- [agentconf](https://github.com/ghrah/agentconf) CLI (for LLM configuration management)

## Installation

Clone the repository and install dependencies:

```bash
git clone https://github.com/ghrah/python-actor.git
cd python-actor
uv sync
```

## LLM Configuration

ghrah uses [agentconf](https://github.com/ghrah/agentconf) to manage LLM configurations with a Provider → LLM → Agent three-tier inheritance structure.

### 1. Create a Provider

A Provider defines the LLM service provider's connection information:

```bash
agentconf provider create openai \
    --type openai \
    --base-url "https://api.openai.com/v1" \
    --api-key "sk-your-api-key"
```

Also supports other OpenAI API-compatible services:

```bash
agentconf provider create deepseek \
    --type openai \
    --base-url "https://api.deepseek.com/v1" \
    --api-key "sk-your-deepseek-key"
```

### 2. Create an LLM Instance

An LLM Instance binds to a Provider and specifies the model name:

```bash
agentconf llm create gpt4o \
    --provider openai \
    --model-name "gpt-4o"
```

### 3. Create an Agent

An Agent binds to an LLM Instance and can override model parameters:

```bash
agentconf agent create assistant \
    --llm gpt4o \
    --temperature 0.7
```

### Environment Variables

Configure environment variables via `.env` file (see [`.env.example`](../.env.example)):

```bash
# agentconf database path (default: ~/.agentconf/config.db)
# AGENTCONF_DB_PATH=~/.agentconf/config.db

# OpenAI API Key (can also be configured via agentconf CLI)
# OPENAI_API_KEY=sk-your-key

# Anthropic API Key
# ANTHROPIC_API_KEY=your-key
```

## Quick Start

### Single Agent Chat

The simplest usage — create an Agent, register ConversationAbility, and chat with it:

```python
import asyncio
from ghrah.abilities.builtin.conversation import ConversationAbility
from ghrah.agents.base import ActorAgent
from ghrah.core.config import AgentConfig

async def main():
    # Create Agent config (name corresponds to agentconf agent name)
    config = AgentConfig(
        name="assistant1",
        description="General chat assistant",
        system_prompt="You are a friendly AI assistant.",
    )

    # Create Agent and register at least one Ability
    agent = ActorAgent(config)
    agent.register_ability(ConversationAbility())

    # Chat using the simplified interface
    response = await agent.chat("Hello, please introduce yourself.")
    print(f"AI: {response}")

asyncio.run(main())
```

Run:

```bash
uv run python examples/simple_chat.py
```

### Agent with Abilities

Register Abilities to give the Agent specific capabilities:

```python
from ghrah.abilities.builtin.conversation import ConversationAbility
from ghrah.abilities.builtin.end_task import EndTaskAbility

# Create Agent and register Abilities
agent = ActorAgent(config)
agent.register_ability(ConversationAbility())
agent.register_ability(EndTaskAbility())
```

Run:

```bash
uv run python examples/ability_agent.py
```

### Multi-Agent Collaboration

Use `SupervisorActor` to manage communication between multiple Agents:

```python
from ghrah.communication import SupervisorActor
from ghrah.core.config import AgentConfig

supervisor = SupervisorActor()

# Register multiple Agents
configs = [
    AgentConfig(name="planner", description="Task planning expert"),
    AgentConfig(name="coder", description="Code writing expert"),
    AgentConfig(name="reviewer", description="Code review expert"),
]
for config in configs:
    await supervisor.spawn_agent(config)

# Send message to a specific Agent
response = await supervisor.send("planner", "Design a web server architecture")
```

Run:

```bash
uv run python examples/multi_agent.py
```

### Agent with File Operations

Register file system Abilities to enable the Agent to read and write files:

```python
from ghrah.abilities.builtin import (
    ConversationAbility,
    EndTaskAbility,
    ReadFileAbility,
    WriteFileAbility,
    FSPermissionChecker,
)

# Create Agent with file permissions
config = AgentConfig(name="coder", description="Code writing assistant")
agent = ActorAgent(config)

# Register Abilities
agent.register_ability(ConversationAbility())
agent.register_ability(EndTaskAbility())
agent.register_ability(ReadFileAbility(
    permission_checker=FSPermissionChecker(allowed_dirs=["/tmp/workspace"])
))
agent.register_ability(WriteFileAbility(
    permission_checker=FSPermissionChecker(allowed_dirs=["/tmp/workspace"])
))
```

Run:

```bash
uv run python examples/multi_agent_parallel.py
```

## Verify Installation

Run the test suite to confirm installation:

```bash
# Run all tests
uv run pytest tests/ -v

# Run specific module tests
uv run pytest tests/abilities/ -v
uv run pytest tests/agents/ -v

# Lint check
uv run ruff check src/ tests/
```

## Next Steps

- [Core Concepts](core-concepts_en.md) — Understand ActorAgent, Ability, Hook, and other core concepts
- [Ability System](ability-system_en.md) — Learn how to develop and register Abilities
- [Multi-Agent Communication](multi-agent_en.md) — Build multi-agent collaboration systems
- [Configuration Reference](configuration_en.md) — View all configuration options