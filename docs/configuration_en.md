# Configuration Reference

ghrah configuration is divided into two layers: framework configuration (`AgentConfig`, etc.) and LLM configuration (managed through agentconf).

## AgentConfig

[`AgentConfig`](../src/ghrah/core/config.py:102) is the Agent's framework-level configuration:

```python
from ghrah.core.config import AgentConfig

config = AgentConfig(
    name="my-agent",              # Agent runtime name (required, for routing and persistence paths)
    agent_config_name="assistant",  # agentconf configuration name (optional, falls back to name)
    description="General assistant",  # Agent description (for discovery and routing)
    system_prompt="You are an assistant",  # System prompt
    max_iterations=10,            # Maximum reasoning iterations
    resources={"CPU": 2, "GPU": 1},  # Resource requirements
    window=WindowConfig(...),     # Window management configuration
    context=ContextConfig(...),   # Context management configuration
)
```

### Parameter Descriptions

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `name` | `str` | **Required** | Agent runtime unique name, for message routing and persistence paths |
| `agent_config_name` | `str \| None` | `None` | Configuration name in agentconf, falls back to `name` when `None` (backward compatible) |
| `description` | `str` | `""` | Agent capability description, for discovery and routing |
| `system_prompt` | `str` | `""` | System prompt |
| `max_iterations` | `int` | `10` | Maximum reasoning iterations (safety valve against infinite loops) |
| `resources` | `dict[str, Any]` | `{}` | Resource requirements, e.g., `{"CPU": 2, "GPU": 1}` |

| `window` | `WindowConfig \| None` | `None` | Window management configuration, `None` disables window management |
| `context` | `ContextConfig \| None` | `None` | Context management configuration, `None` uses defaults |

### Properties

| Property | Type | Description |
|----------|------|-------------|
| `effective_agent_config_name` | `str` | Effective agentconf lookup name, uses `agent_config_name` if set, falls back to `name` |
| `num_cpus` | `float \| None` | Number of CPUs required |
| `num_gpus` | `float \| None` | Number of GPUs required |

### agent_config_name Usage

When multiple runtime Agents share the same LLM configuration (e.g., Worker pool scenarios), use `agent_config_name` to separate the runtime name from the agentconf configuration name:

```python
# Worker pool: multiple workers share the same agentconf configuration
for i in range(num_workers):
    config = AgentConfig(
        name=f"solve_worker_{i}",        # Runtime unique identifier
        agent_config_name="solve_worker",   # Template name in agentconf
        system_prompt=f"You are solve Worker #{i}",
    )
    # Agent initialization uses "solve_worker" to look up agentconf configuration
    # instead of looking up non-existent "solve_worker_0", "solve_worker_1", etc.
```

When `agent_config_name` is not specified, it automatically falls back to `name`, maintaining backward compatibility:

```python
# Single Agent scenario: name matches agentconf configuration name
config = AgentConfig(
    name="planner",  # agent_config_name not specified, uses "planner" for agentconf lookup
)
```

## WindowConfig

[`WindowConfig`](../src/ghrah/core/config.py:20) controls how conversation history is compressed within the LLM token budget:

```python
from ghrah.core.config import WindowConfig

window_config = WindowConfig(
    max_tokens=4096,                                    # Token budget
    strategies=["tool_call_fold", "truncation"],        # Strategy list
    tool_call_max_length=500,                            # ToolCall fold max length
    sliding_window_size=20,                              # Sliding window size
)
```

### Parameter Descriptions

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `max_tokens` | `int` | `4096` | LLM context window size (token budget) |
| `strategies` | `list[str]` | `["tool_call_fold", "truncation"]` | Strategy name list, in execution order |
| `tool_call_max_length` | `int` | `500` | Max content length for `ToolCallFoldStrategy` |
| `sliding_window_size` | `int` | `20` | Window size for `SlidingWindowStrategy` |

### Available Strategies

| Strategy Name | Class | Description |
|---------------|-------|-------------|
| `"truncation"` | `TruncationStrategy` | Simple truncation from earliest messages |
| `"sliding_window"` | `SlidingWindowStrategy` | Sliding window, keeps most recent N messages |
| `"tool_call_fold"` | `ToolCallFoldStrategy` | Folds long tool_call results |
| `"llm_summary"` | `LLMSummaryStrategy` | Uses LLM to generate summaries (requires LLM injection) |

## ContextConfig

[`ContextConfig`](../src/ghrah/core/config.py:40) controls the ActorAgent's context management behavior:

```python
from ghrah.core.config import ContextConfig

context_config = ContextConfig(
    snapshot_interval=5,                # Snapshot interval
    auto_persist=False,                  # Auto-persist
    persistence_type="json_file",       # Persistence backend type
    persistence_root_dir="/tmp/data",    # Storage root directory
    persistence_compress=True,           # gzip compression
    persistence_run_id="my_session", # Session ID
)
```

### Parameter Descriptions

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `snapshot_interval` | `int` | `5` | Message snapshot interval (full snapshot every N iterations) |
| `auto_persist` | `bool` | `False` | Whether to auto-persist after each commit/rollback |
| `persistence_type` | `str \| None` | `None` | Persistence backend type: `"json_file"` / `"memory"` / `"sqlite"` / `"remote"` / `None` |
| `persistence_root_dir` | `str \| None` | `None` | Persistence storage root directory path (for json_file/sqlite backends) |
| `persistence_compress` | `bool` | `True` | Whether to enable gzip compression for persistence files |
| `persistence_run_id` | `str \| None` | `None` | Persistence run ID, `None` means auto-generated |


### Persistence Backend Types

| Type | Class | Description |
|------|-------|-------------|
| `"json_file"` | `JsonFileBackend` | JSON file-based, supports gzip compression |
| `"memory"` | `InMemoryBackend` | Pure in-memory, no disk persistence |
| `"sqlite"` | `SqliteBackend` | SQLite database-based, WAL mode for concurrent reads |
| `"remote"` | `RemoteBackend` | Delegates persistence to Subject via CommandSender |
| `None` | — | Persistence disabled |

### create_persistence() Factory Method

`ContextConfig.create_persistence()` creates the corresponding persistence backend instance based on `persistence_type`:

```python
context_config = ContextConfig(persistence_type="json_file", persistence_root_dir="/tmp/data")
backend = context_config.create_persistence()  # Returns JsonFileBackend instance
```

## agentconf Configuration

LLM-related configuration is managed through [agentconf](https://github.com/ghrah/agentconf) with a three-tier inheritance structure:

```
Provider (service provider)
├── base_url: API endpoint
├── api_key: Authentication key
└── type: Provider type (openai / anthropic)
    │
    └── LLM Instance (model instance)
        ├── model_name: Model identifier
        ├── temperature: Temperature parameter (overridable)
        ├── top_p: Top-P parameter (overridable)
        └── max_tokens: Max token count (overridable)
            │
            └── Agent (agent)
                ├── temperature: Temperature parameter (overrides LLM level)
                ├── top_p: Top-P parameter (overrides LLM level)
                └── max_tokens: Max token count (overrides LLM level)
```

### CLI Commands

```bash
# Create Provider
agentconf provider create openai \
    --type openai \
    --base-url "https://api.openai.com/v1" \
    --api-key "sk-your-api-key"

# Create LLM Instance
agentconf llm create gpt4o \
    --provider openai \
    --model-name "gpt-4o"

# Create Agent
agentconf agent create assistant \
    --llm gpt4o \
    --temperature 0.7
```

### SDK Usage

```python
from agentconf import AgentsConfig

config_client = AgentsConfig()

# Resolve Agent configuration (includes full Provider → LLM → Agent inheritance chain)
resolved = config_client.resolve_agent("assistant")

# resolved contains:
# - provider_type: ProviderType
# - base_url: str
# - api_key: SecretStr
# - model_name: str
# - temperature: float | None
# - top_p: float | None
# - max_tokens: int | None
```

## Direct ChatFormat Construction (Fallback)

When you don't want to use agentconf, you can directly construct a `ChatFormat` subclass and inject it into the Agent via `agent._llm`. This approach bypasses the agentconf Provider → LLM → Agent inheritance chain, giving the caller full control over LLM parameter management.

> **How it works**: `ActorAgent._ensure_llm()` checks `self._llm` on first invocation. If already set, it returns immediately without going through agentconf resolution. Simply assign the ChatFormat before calling `receive()` / `chat()`.


## Environment Variables

Configure via `.env` file or environment variables (see [`.env.example`](../.env.example)):

| Variable | Description | Default |
|----------|-------------|---------|
| `AGENTCONF_DB_PATH` | agentconf database path | `~/.agentconf/config.db` |
| `OPENAI_API_KEY` | OpenAI API Key | — |
| `ANTHROPIC_API_KEY` | Anthropic API Key | — |

## Complete Configuration Examples

### Minimal Configuration

```python
from ghrah.core.config import AgentConfig

config = AgentConfig(
    name="assistant",
    system_prompt="You are a friendly AI assistant.",
)
```

### Full Configuration

```python
from ghrah.core.config import AgentConfig, WindowConfig, ContextConfig

config = AgentConfig(
    name="coder",
    description="Code writing assistant",
    system_prompt="You are a code writing expert. Write high-quality code based on requirements.",
    max_iterations=15,
    resources={"CPU": 2},
    
    # Window management
    window=WindowConfig(
        max_tokens=8192,
        strategies=["tool_call_fold", "sliding_window", "truncation"],
        tool_call_max_length=500,
        sliding_window_size=30,
    ),
    
    # Context management
    context=ContextConfig(
        snapshot_interval=10,
        auto_persist=True,
        persistence_type="json_file",
        persistence_root_dir="/tmp/agent_data",
        persistence_compress=True,
        persistence_run_id="session_20260422",
    ),
)
```

### Multi-Agent Configuration

```python
from ghrah.core.config import AgentConfig, ContextConfig

# Planner — lightweight configuration
planner_config = AgentConfig(
    name="planner",
    description="Task planning expert",
    system_prompt="You are a task planning expert. Break down complex tasks into clear steps.",
    max_iterations=5,
)

# Coder — full configuration
coder_config = AgentConfig(
    name="coder",
    description="Code writing expert",
    system_prompt="You are a code writing expert.",
    max_iterations=15,
    context=ContextConfig(
        persistence_type="json_file",
        persistence_root_dir="/tmp/coder_data",
    ),
)

# Reviewer — medium configuration
reviewer_config = AgentConfig(
    name="reviewer",
    description="Code review expert",
    system_prompt="You are a code review expert.",
    max_iterations=10,
)
```

### Worker Pool Configuration (agent_config_name)

When multiple Agents share the same LLM configuration (e.g., Worker pool scenarios), use `agent_config_name` to separate the runtime name from the agentconf configuration name:

```python
from ghrah.core.config import AgentConfig

# Worker pool: multiple workers share the same agentconf configuration
# Only need to create one "solve_worker" configuration in agentconf
worker_configs = [
    AgentConfig(
        name=f"solve_worker_{i}",        # Runtime unique identifier
        agent_config_name="solve_worker",   # Template name in agentconf
        description=f"Solve Worker #{i}",
        system_prompt=f"You are solve Worker #{i}.",
    )
    for i in range(3)
]

# Role alias: different runtime name, shared LLM configuration
reviewer_config = AgentConfig(
    name="code_reviewer_v2",     # New version runtime identifier
    agent_config_name="reviewer",   # Reuse reviewer's LLM configuration
    description="Code review expert v2",
    system_prompt="You are a code review expert.",
)
```

See [Worker Pool Example](../examples/worker_pool.py) for details.

### Distributed Mode Configuration

In distributed mode, Core communicates with Subject via CommandSender:

```python
from ghrah.core.config import AgentConfig, ContextConfig

config = AgentConfig(
    name="coder",
    system_prompt="You are a code writing expert.",
    context=ContextConfig(
        persistence_type="remote",
    ),
)
```

See [Dual-Mode Architecture](distributed-mode_en.md) for details.

## Next Steps

- [Quick Start](getting-started_en.md) — Create Agents using configuration
- [Persistence & Window Management](persistence_en.md) — Deep dive into persistence and window strategy configuration
- [Built-in Ability Reference](builtin-abilities_en.md) — View FSPermissionChecker configuration