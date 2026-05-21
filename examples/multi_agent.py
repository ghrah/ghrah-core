# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""多 Agent 协作示例。

展示如何使用 SupervisorActor 管理多个 Agent，进行消息路由和广播。

前置条件：
    1. 已配置 agentconf（运行 `agentconf --help` 查看配置方法）
    2. 至少配置了以下 Agent：
       - planner（任务规划）
       - coder（代码编写）
       - reviewer（代码审查）

    可以使用以下命令快速配置：
        agentconf provider create openai \\
            --type openai \\
            --base-url "https://api.openai.com/v1" \\
            --api-key "sk-your-key"

        agentconf model create gpt4o --provider openai --model-name "gpt-4o"

        agentconf agent create planner --model gpt4o --temperature 0.3
        agentconf agent create coder --model gpt4o --temperature 0.2
        agentconf agent create reviewer --model gpt4o --temperature 0.1

用法：
    uv run python examples/multi_agent.py
"""

from __future__ import annotations

import asyncio

from ghrah.communication import SupervisorActor
from ghrah.core.config import AgentConfig


async def main() -> None:
    # 创建 Supervisor
    supervisor = SupervisorActor()

    # 定义 Agent 配置（不再使用 AgentType，行为由 Ability 组合决定）
    agents_config = [
        AgentConfig(
            name="planner",
            description="任务规划专家，负责分解复杂任务",
            system_prompt="你是一个任务规划专家。请将复杂任务分解为清晰的步骤。",
        ),
        AgentConfig(
            name="coder",
            description="代码编写专家",
            system_prompt="你是一个代码编写专家。请根据需求编写高质量的代码。",
        ),
        AgentConfig(
            name="reviewer",
            description="代码审查专家",
            system_prompt="你是一个代码审查专家。请审查代码并提供改进建议。",
        ),
    ]

    # 注册所有 Agent（默认注册 ConversationAbility + EndTaskAbility）
    print("=" * 60)
    print("注册 Agent...")
    for config in agents_config:
        name = await supervisor.spawn_agent(config)
        print(f"  ✓ Agent 注册成功: {name}")

    # 列出所有 Agent
    print("\n" + "=" * 60)
    print("已注册 Agent 列表:")
    agents = await supervisor.list_agents()
    for agent in agents:
        print(f"  - {agent['name']}: {agent['description']}")

    # 健康检查
    print("\n" + "=" * 60)
    print("健康检查:")
    health = await supervisor.health_check()
    for name, is_healthy in health.items():
        status = "✓ 健康" if is_healthy else "✗ 不健康"
        print(f"  - {name}: {status}")

    # 发送消息到单个 Agent
    print("\n" + "=" * 60)
    print("发送消息到 planner...")
    response_design = await supervisor.send(
        "planner",
        "请设计一个Python的猜数字小游戏，带有CLI界面的模块，以文件为单位描述设计，描述保持简洁。你的设计将发送给Coder实现，所以你不需要实现具体的代码",
    )
    print(f"  Planner 回复:\n{response_design}...")

    # 广播消息
    print("\n" + "=" * 60)
    print("广播消息到所有 Agent...")
    responses = await supervisor.broadcast("请简要介绍你的专长和职责, 保持在100字以内")
    for i, resp in enumerate(responses):
        print(f"  Agent {i + 1} 回复: {resp}...")

    # Agent 间委托（planner 委托 coder 写代码）
    print("\n" + "=" * 60)
    print("委托任务: planner → coder...")
    delegate_response = await supervisor.delegate(
        from_agent="planner",
        to_agent="coder",
        content=response_design,
    )
    print(f"  Coder 回复:\n{delegate_response}...")

    # 清理
    print("\n" + "=" * 60)
    print("清理资源...")
    for agent in agents:
        await supervisor.terminate_agent(agent["name"])
        print(f"  ✓ Agent 已终止: {agent['name']}")

    print("\n示例运行完成！")


if __name__ == "__main__":
    asyncio.run(main())
