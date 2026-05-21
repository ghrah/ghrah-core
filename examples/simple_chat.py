# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""最小可对话示例

演示最简单的标准用法：
1. 通过 AgentConfig 指定 agent 名称
2. 注册 ConversationAbility（最小必要 Ability）
3. 使用 chat() 接口进行交互式对话

"""

from __future__ import annotations

import asyncio
import logging

from ghrah.abilities.builtin.conversation import ConversationAbility
from ghrah.agents.base import ActorAgent
from ghrah.core.config import AgentConfig

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


async def main() -> None:
    config = AgentConfig(
        name="assistant1",
        description="通用对话助手",
        system_prompt="你是一个友好的 AI 助手，请用中文回答问题。",
    )

    agent = ActorAgent(config)
    agent.register_ability(ConversationAbility())

    print("=" * 60)
    print("ActorAgent 单 Agent 对话示例")
    print("输入 'quit' 退出")
    print("=" * 60)

    while True:
        try:
            user_input = input("\n你: ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not user_input:
            continue
        if user_input.lower() == "quit":
            break

        response = await agent.chat(user_input)
        print(f"\nAI: {response}")

    state = agent.get_state()
    logger.info(f"Final state: {state}")


if __name__ == "__main__":
    asyncio.run(main())
