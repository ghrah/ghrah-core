# 配置参考

ghrah 的配置分为两层：框架层配置（`AgentConfig` 等）和 LLM 配置（通过 agentconf 管理）。

## AgentConfig

[`AgentConfig`](../src/ghrah/core/config.py:102) 是 Agent 的框架层配置：

```python
from ghrah.core.config import AgentConfig

config = AgentConfig(
    name="my-agent",              # Agent 运行时名称（必填，用于消息路由和持久化路径）
    agent_config_name="assistant",  # agentconf 中的配置名称（可选，None 时回退到 name）
    description="通用助手",        # Agent 描述（用于发现和路由）
    system_prompt="你是一个助手",   # 系统提示词
    max_iterations=10,            # 最大推理迭代次数
    resources={"CPU": 2, "GPU": 1},  # 资源需求
    window=WindowConfig(...),     # 窗口管理配置
    context=ContextConfig(...),   # 上下文管理配置
)
```

### 参数说明

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `name` | `str` | **必填** | Agent 运行时唯一名称，用于消息路由和持久化路径 |
| `agent_config_name` | `str \| None` | `None` | agentconf 中的配置名称，`None` 时回退到 `name`（向后兼容） |
| `description` | `str` | `""` | Agent 能力描述，用于 Agent 发现和路由 |
| `system_prompt` | `str` | `""` | 系统提示词 |
| `max_iterations` | `int` | `10` | 最大推理迭代次数（防止死循环的安全阀） |
| `resources` | `dict[str, Any]` | `{}` | 资源需求，如 `{"CPU": 2, "GPU": 1}` |

| `window` | `WindowConfig \| None` | `None` | 窗口管理配置，`None` 表示不启用 |
| `context` | `ContextConfig \| None` | `None` | 上下文管理配置，`None` 表示使用默认值 |

### 属性

| 属性 | 类型 | 说明 |
|------|------|------|
| `effective_agent_config_name` | `str` | 有效的 agentconf 查找名称，优先使用 `agent_config_name`，未指定时回退到 `name` |
| `num_cpus` | `float \| None` | 需要的 CPU 资源数 |
| `num_gpus` | `float \| None` | 需要的 GPU 资源数 |

### agent_config_name 使用场景

当多个运行时 Agent 共享同一份 LLM 配置时（如 Worker 池场景），可以通过 `agent_config_name` 将运行时名称与 agentconf 配置名称分离：

```python
# Worker 池：多个 worker 共享同一份 agentconf 配置
for i in range(num_workers):
    config = AgentConfig(
        name=f"solve_worker_{i}",        # 运行时唯一标识
        agent_config_name="solve_worker",   # agentconf 中的模板名称
        system_prompt=f"你是解题 Worker #{i}",
    )
    # Agent 初始化时会使用 "solve_worker" 查找 agentconf 配置
    # 而不是查找不存在的 "solve_worker_0", "solve_worker_1" 等
```

当 `agent_config_name` 未指定时，自动回退到 `name`，保持向后兼容：

```python
# 单 Agent 场景：name 与 agentconf 配置名称一致
config = AgentConfig(
    name="planner",  # agent_config_name 未指定，自动使用 "planner" 查找 agentconf
)
```

## WindowConfig

[`WindowConfig`](../src/ghrah/core/config.py:20) 控制如何将对话历史压缩到 LLM 的 token 预算内：

```python
from ghrah.core.config import WindowConfig

window_config = WindowConfig(
    max_tokens=4096,                                    # token 预算
    strategies=["tool_call_fold", "truncation"],        # 策略列表
    tool_call_max_length=500,                            # ToolCall 折叠最大长度
    sliding_window_size=20,                              # 滑动窗口大小
)
```

### 参数说明

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `max_tokens` | `int` | `4096` | LLM 上下文窗口大小（token 预算） |
| `strategies` | `list[str]` | `["tool_call_fold", "truncation"]` | 策略名称列表，按执行顺序排列 |
| `tool_call_max_length` | `int` | `500` | `ToolCallFoldStrategy` 的最大 content 长度 |
| `sliding_window_size` | `int` | `20` | `SlidingWindowStrategy` 的窗口大小 |

### 可用策略

| 策略名称 | 类 | 说明 |
|----------|-----|------|
| `"truncation"` | `TruncationStrategy` | 简单截断，从最早的消息开始 |
| `"sliding_window"` | `SlidingWindowStrategy` | 滑动窗口，保留最近 N 条消息 |
| `"tool_call_fold"` | `ToolCallFoldStrategy` | 折叠长的 tool_call 结果 |
| `"llm_summary"` | `LLMSummaryStrategy` | 使用 LLM 生成摘要（需注入 LLM） |

## ContextConfig

[`ContextConfig`](../src/ghrah/core/config.py:40) 控制 ActorAgent 的上下文管理行为：

```python
from ghrah.core.config import ContextConfig

context_config = ContextConfig(
    snapshot_interval=5,                # 快照间隔
    auto_persist=False,                  # 自动持久化
    persistence_type="json_file",       # 持久化后端类型
    persistence_root_dir="/tmp/data",    # 存储根目录
    persistence_compress=True,           # gzip 压缩
    persistence_run_id="my_session", # 会话 ID
)
```

### 参数说明

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `snapshot_interval` | `int` | `5` | 消息快照间隔（每 N 次迭代存储一次完整快照） |
| `auto_persist` | `bool` | `False` | 是否在每次 commit/rollback 后自动持久化节点 |
| `persistence_type` | `str \| None` | `None` | 持久化后端类型：`"json_file"` / `"memory"` / `"sqlite"` / `"remote"` / `None` |
| `persistence_root_dir` | `str \| None` | `None` | 持久化存储根目录路径（json_file/sqlite 后端使用） |
| `persistence_compress` | `bool` | `True` | 是否启用 gzip 压缩持久化文件 |
| `persistence_run_id` | `str \| None` | `None` | 持久化运行 ID，`None` 表示自动生成 |


### 持久化后端类型

| 类型 | 类 | 说明 |
|------|-----|------|
| `"json_file"` | `JsonFileBackend` | 基于 JSON 文件，支持 gzip 压缩 |
| `"memory"` | `InMemoryBackend` | 纯内存，不持久化到磁盘 |
| `"sqlite"` | `SqliteBackend` | 基于 SQLite 数据库，WAL 模式支持并发读 |
| `"remote"` | `RemoteBackend` | 通过 CommandSender 将持久化操作委托给 Subject |
| `None` | — | 不启用持久化 |

### create_persistence() 工厂方法

`ContextConfig.create_persistence()` 根据 `persistence_type` 创建对应的持久化后端实例：

```python
context_config = ContextConfig(persistence_type="json_file", persistence_root_dir="/tmp/data")
backend = context_config.create_persistence()  # 返回 JsonFileBackend 实例
```

## agentconf 配置

LLM 相关配置通过 [agentconf](https://github.com/ghrah/agentconf) 管理，采用三层继承结构：

```
Provider（服务提供者）
├── base_url: API 端点
├── api_key: 认证密钥
└── type: 提供者类型（openai / anthropic）
    │
    └── LLM Instance（模型实例）
        ├── model_name: 模型标识
        ├── temperature: 温度参数（可覆盖）
        ├── top_p: Top-P 参数（可覆盖）
        └── max_tokens: 最大 token 数（可覆盖）
            │
            └── Agent（智能体）
                ├── temperature: 温度参数（覆盖 LLM 级）
                ├── top_p: Top-P 参数（覆盖 LLM 级）
                └── max_tokens: 最大 token 数（覆盖 LLM 级）
```

### CLI 命令

```bash
# 创建 Provider
agentconf provider create openai \
    --type openai \
    --base-url "https://api.openai.com/v1" \
    --api-key "sk-your-api-key"

# 创建 LLM Instance
agentconf llm create gpt4o \
    --provider openai \
    --model-name "gpt-4o"

# 创建 Agent
agentconf agent create assistant \
    --llm gpt4o \
    --temperature 0.7
```

### SDK 使用

```python
from agentconf import AgentsConfig

config_client = AgentsConfig()

# 解析 Agent 配置（包含 Provider → LLM → Agent 的完整继承链）
resolved = config_client.resolve_agent("assistant")

# resolved 包含：
# - provider_type: ProviderType
# - base_url: str
# - api_key: SecretStr
# - model_name: str
# - temperature: float | None
# - top_p: float | None
# - max_tokens: int | None
```

## 环境变量

通过 `.env` 文件或环境变量配置（参考 [`.env.example`](../.env.example)）：

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `AGENTCONF_DB_PATH` | agentconf 数据库路径 | `~/.agentconf/config.db` |
| `OPENAI_API_KEY` | OpenAI API Key | — |
| `ANTHROPIC_API_KEY` | Anthropic API Key | — |

## 完整配置示例

### 最小配置

```python
from ghrah.core.config import AgentConfig

config = AgentConfig(
    name="assistant",
    system_prompt="你是一个友好的 AI 助手。",
)
```

### 完整配置

```python
from ghrah.core.config import AgentConfig, WindowConfig, ContextConfig

config = AgentConfig(
    name="coder",
    description="代码编写助手",
    system_prompt="你是一个代码编写专家。请根据需求编写高质量的代码。",
    max_iterations=15,
    resources={"CPU": 2},
    
    # 窗口管理
    window=WindowConfig(
        max_tokens=8192,
        strategies=["tool_call_fold", "sliding_window", "truncation"],
        tool_call_max_length=500,
        sliding_window_size=30,
    ),
    
    # 上下文管理
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

### 多 Agent 配置

```python
from ghrah.core.config import AgentConfig, ContextConfig

# 规划者 — 轻量配置
planner_config = AgentConfig(
    name="planner",
    description="任务规划专家",
    system_prompt="你是一个任务规划专家。请将复杂任务分解为清晰的步骤。",
    max_iterations=5,
)

# 编码者 — 完整配置
coder_config = AgentConfig(
    name="coder",
    description="代码编写专家",
    system_prompt="你是一个代码编写专家。",
    max_iterations=15,
    context=ContextConfig(
        persistence_type="json_file",
        persistence_root_dir="/tmp/coder_data",
    ),
)

# 审查者 — 中等配置
reviewer_config = AgentConfig(
    name="reviewer",
    description="代码审查专家",
    system_prompt="你是一个代码审查专家。",
    max_iterations=10,
)
```

### Worker 池配置（agent_config_name）

当多个 Agent 共享同一份 LLM 配置时（如 Worker 池场景），使用 `agent_config_name` 将运行时名称与 agentconf 配置名称分离：

```python
from ghrah.core.config import AgentConfig

# Worker 池：多个 worker 共享同一份 agentconf 配置
# agentconf 中只需创建一个 "solve_worker" 配置
worker_configs = [
    AgentConfig(
        name=f"solve_worker_{i}",        # 运行时唯一标识
        agent_config_name="solve_worker",   # agentconf 中的模板名称
        description=f"解题 Worker #{i}",
        system_prompt=f"你是解题 Worker #{i}。",
    )
    for i in range(3)
]

# 角色别名：不同运行时名称，共享同一份 LLM 配置
reviewer_config = AgentConfig(
    name="code_reviewer_v2",     # 新版本运行时标识
    agent_config_name="reviewer",   # 复用 reviewer 的 LLM 配置
    description="代码审查专家 v2",
    system_prompt="你是一个代码审查专家。",
)
```

详见 [Worker 池示例](../examples/worker_pool.py)。

### 分布式模式配置

分布式模式下 Core 通过 CommandSender 与 Subject 通信：

```python
from ghrah.core.config import AgentConfig, ContextConfig

config = AgentConfig(
    name="coder",
    system_prompt="你是一个代码编写专家。",
    context=ContextConfig(
        persistence_type="remote",
    ),
)
```

详见 [双模式架构](distributed-mode.md)。

## 下一步

- [快速开始](getting-started.md) — 使用配置创建 Agent
- [持久化与窗口管理](persistence.md) — 深入了解持久化和窗口策略配置
- [内置 Ability 参考](builtin-abilities.md) — 查看 FSPermissionChecker 配置