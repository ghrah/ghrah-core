# 安装与快速开始

## 环境要求

- Python >= 3.11
- [uv](https://docs.astral.sh/uv/) 包管理器
- [agentconf](https://github.com/ghrah/agentconf) CLI（用于 LLM 配置管理）

## 安装

克隆仓库并安装依赖：

```bash
git clone https://github.com/ghrah/ghrah-core.git
cd ghrah
uv sync
```

## 配置 LLM

ghrah 使用 [agentconf](https://github.com/ghrah/agentconf) 管理 LLM 配置，采用 Provider → LLM → Agent 三层继承结构。

### 1. 创建 Provider

Provider 定义 LLM 服务提供者的连接信息：

```bash
agentconf provider create openai \
    --type openai \
    --base-url "https://api.openai.com/v1" \
    --api-key "sk-your-api-key"
```

也支持其他兼容 OpenAI API 的服务：

```bash
agentconf provider create deepseek \
    --type openai \
    --base-url "https://api.deepseek.com/v1" \
    --api-key "sk-your-deepseek-key"
```

### 2. 创建 LLM Instance

LLM Instance 绑定到 Provider，指定模型名称：

```bash
agentconf llm create gpt4o \
    --provider openai \
    --model-name "gpt-4o"
```

### 3. 创建 Agent

Agent 绑定到 LLM Instance，可覆盖模型参数：

```bash
agentconf agent create assistant \
    --llm gpt4o \
    --temperature 0.7
```

### 环境变量

可通过 `.env` 文件配置环境变量（参考 [`.env.example`](../.env.example)）：

```bash
# agentconf 数据库路径（默认 ~/.agentconf/config.db）
# AGENTCONF_DB_PATH=~/.agentconf/config.db

# OpenAI API Key（也可以通过 agentconf CLI 配置）
# OPENAI_API_KEY=sk-your-key

# Anthropic API Key
# ANTHROPIC_API_KEY=your-key
```

## 快速开始

### 单 Agent 对话

最简单的使用方式 — 创建一个 Agent，注册 ConversationAbility，并与之对话：

```python
import asyncio
from ghrah.abilities.builtin.conversation import ConversationAbility
from ghrah.agents.base import ActorAgent
from ghrah.core.config import AgentConfig

async def main():
    # 创建 Agent 配置（name 对应 agentconf 中的 agent name）
    config = AgentConfig(
        name="assistant1",
        description="通用对话助手",
        system_prompt="你是一个友好的 AI 助手，请用中文回答问题。",
    )

    # 创建 Agent 并注册至少一个 Ability
    agent = ActorAgent(config)
    agent.register_ability(ConversationAbility())

    # 使用简化接口对话
    response = await agent.chat("你好，请介绍一下你自己。")
    print(f"AI: {response}")

asyncio.run(main())
```

运行：

```bash
uv run python examples/simple_chat.py
```

### 带 Ability 的 Agent

通过注册 Ability 赋予 Agent 具体能力：

```python
from ghrah.abilities.builtin.conversation import ConversationAbility
from ghrah.abilities.builtin.end_task import EndTaskAbility

# 创建 Agent 并注册 Ability
agent = ActorAgent(config)
agent.register_ability(ConversationAbility())
agent.register_ability(EndTaskAbility())
```

运行：

```bash
uv run python examples/ability_agent.py
```

### 多 Agent 协作

使用 `SupervisorActor` 管理多个 Agent 的通信：

```python
from ghrah.communication import SupervisorActor
from ghrah.core.config import AgentConfig

supervisor = SupervisorActor()

# 注册多个 Agent
configs = [
    AgentConfig(name="planner", description="任务规划专家"),
    AgentConfig(name="coder", description="代码编写专家"),
    AgentConfig(name="reviewer", description="代码审查专家"),
]
for config in configs:
    await supervisor.spawn_agent(config)

# 发送消息给指定 Agent
response = await supervisor.send("planner", "设计一个 Web 服务器架构")
```

运行：

```bash
uv run python examples/multi_agent.py
```

### 带文件操作的 Agent

注册文件系统相关 Ability，让 Agent 可以读写文件：

```python
from ghrah.abilities.builtin import (
    ConversationAbility,
    EndTaskAbility,
    ReadFileAbility,
    WriteFileAbility,
    FSPermissionChecker,
)

# 创建带文件权限的 Agent
config = AgentConfig(name="coder", description="代码编写助手")
agent = ActorAgent(config)

# 注册 Ability
agent.register_ability(ConversationAbility())
agent.register_ability(EndTaskAbility())
agent.register_ability(ReadFileAbility(
    permission_checker=FSPermissionChecker(allowed_dirs=["/tmp/workspace"])
))
agent.register_ability(WriteFileAbility(
    permission_checker=FSPermissionChecker(allowed_dirs=["/tmp/workspace"])
))
```

运行：

```bash
uv run python examples/multi_agent_parallel.py
```

## 验证安装

运行测试套件确认安装正确：

```bash
# 运行全部测试
uv run pytest tests/ -v

# 运行特定模块测试
uv run pytest tests/abilities/ -v
uv run pytest tests/agents/ -v

# 代码检查
uv run ruff check src/ tests/
```

## 下一步

- [核心概念](core-concepts.md) — 理解 ActorAgent、Ability、Hook 等核心概念
- [Ability 系统](ability-system.md) — 学习如何开发和注册 Ability
- [多 Agent 通信](multi-agent.md) — 构建多 Agent 协作系统
- [配置参考](configuration.md) — 查看所有配置选项