# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""工具调用 Agent 示例 — 展示 bind_tool + Function Calling。

演示如何创建带工具的 Agent：
1. 注册 ReadFileAbility（带 bind_tool → OpenAI function calling schema）
2. 注册 ConversationAbility（纯对话，无 tool binding）
3. 注册 EndTaskAbility（终止循环）
4. 展示 Tool schema 收集
5. 展示通过 Supervisor 管理带工具的 Agent

关键概念：
- bind_tool() 返回 OpenAI FC schema → Agent 自动收集
- 1 Ability = 1 Tool Call（ReadFileAbility 对应 read_file tool）
- 无 tool 的 Ability（ConversationAbility）不暴露给 LLM

前提条件：
    使用 agentconf TUI 或 SDK 预先创建配置（参见 ability_agent.py）

用法：
    uv run python examples/tool_agent.py
"""

from __future__ import annotations

import asyncio
import logging

from ghrah.abilities.base import Ability, ActionOutcome, ActionResult
from ghrah.abilities.builtin.conversation import ConversationAbility
from ghrah.abilities.builtin.end_task import EndTaskAbility
from ghrah.abilities.builtin.read_file import ReadFileAbility
from ghrah.abilities.context import AbilityExecutionContext
from ghrah.agents.base import ActorAgent
from ghrah.communication import SupervisorActor
from ghrah.core.config import AgentConfig

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


async def demo_manual_registration() -> None:
    """演示手动注册 Ability + Tool binding。"""
    print("\n" + "=" * 60)
    print("Demo 1: 手动注册 Ability + Tool Binding")
    print("=" * 60)

    config = AgentConfig(
        name="tool-agent",
        description="带文件读取能力的 Agent",
        system_prompt="你是一个文件助手。用户可以让你读取文件内容。",
    )

    agent = ActorAgent(config)

    # 手动注册 Ability（组合模式 — 按需注册）
    read_file = ReadFileAbility()
    conversation = ConversationAbility()
    end_task = EndTaskAbility()

    agent.register_ability(read_file)
    agent.register_ability(conversation)
    agent.register_ability(end_task)

    # 查看注册结果
    abilities = agent.get_abilities()
    state = agent.get_state()

    print(f"  已注册 Ability: {abilities}")
    print(f"  Bound tools (FC schema): {state['bound_tools']} 个")

    # 展示 tool schema
    tool_schema = read_file.bind_tool()
    print(f"  read_file schema: {tool_schema}")
    print()


async def demo_custom_ability() -> None:
    """演示自定义 Ability 注册。"""
    print("\n" + "=" * 60)
    print("Demo 2: 自定义 Ability")
    print("=" * 60)

    class CodeReviewAbility(Ability):
        """示例：自定义代码审查 Ability。"""

        @property
        def name(self) -> str:
            return "code_review"

        async def execute(self, context: AbilityExecutionContext) -> ActionResult:
            return ActionResult(
                outcome=ActionOutcome.SUCCESS,
                data={"response": "Code review completed"},
            )

        def get_hooks(self) -> list:
            return []

    config = AgentConfig(
        name="review-agent",
        description="代码审查 Agent",
    )

    agent = ActorAgent(config)

    # 注册自定义 Ability
    agent.register_ability(CodeReviewAbility())
    agent.register_ability(ConversationAbility())
    agent.register_ability(EndTaskAbility())

    abilities = agent.get_abilities()
    print(f"  已注册 Ability: {abilities}")
    print()


async def demo_supervisor_integration() -> None:
    """演示 Supervisor + 显式 Ability 注册。"""
    print("\n" + "=" * 60)
    print("Demo 3: Supervisor + 显式 Ability 注册")
    print("=" * 60)

    supervisor = SupervisorActor()

    # 注册带自定义 Ability 的 Agent
    config = AgentConfig(
        name="file-assistant",
        description="文件助手",
        system_prompt="你是一个文件助手。",
    )
    await supervisor.spawn_agent(
        config,
        abilities=[ReadFileAbility(), ConversationAbility(), EndTaskAbility()],
    )

    # 注册使用默认 Ability 的 Agent
    default_config = AgentConfig(
        name="default-agent",
        description="默认对话 Agent",
    )
    await supervisor.spawn_agent(default_config)

    # 检查 Agent 状态
    agents = await supervisor.list_agents()
    for agent_info in agents:
        print(f"  Agent: {agent_info['name']} — {agent_info['description']}")

    # 清理
    for agent_info in agents:
        await supervisor.terminate_agent(agent_info["name"])

    print("\n  清理完成")
    print()


def main() -> None:
    # Demo 1: 手动注册
    asyncio.run(demo_manual_registration())

    # Demo 2: 自定义 Ability
    asyncio.run(demo_custom_ability())

    # Demo 3: Supervisor 集成
    asyncio.run(demo_supervisor_integration())

    print("所有示例运行完成！")


if __name__ == "__main__":
    main()
