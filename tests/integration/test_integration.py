# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""端到端集成测试。

测试 Supervisor + ActorAgent + Ability 的完整流程。
使用 mock 替代 LLM，专注于验证框架层的集成逻辑。

测试场景：
1. Agent + Ability 完整驱动循环（mock LLM）
2. Agent 手动注册多个 Ability + Tool schema 收集
3. Hook 触发 → 条件转移 → Ability 路由
4. ConversationAbility 内置终止 Hook 验证
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

from ghrah.abilities.base import ActionResult
from ghrah.abilities.builtin.conversation import ConversationAbility
from ghrah.abilities.builtin.end_task import EndTaskAbility
from ghrah.abilities.builtin.read_file import ReadFileAbility
from ghrah.abilities.context import AbilityExecutionContext
from ghrah.abilities.hooks import Hook, HookPoint, HookResult
from ghrah.chat.content import TextBlock
from ghrah.chat.format import LLMResponse
from ghrah.core.config import AgentConfig
from ghrah.core.message import Message, MessageType

# ── Helpers ──


def _create_agent(
    config: AgentConfig | None = None,
    supervisor: Any = None,
) -> Any:
    """创建一个 ActorAgent 实例。"""
    from ghrah.agents.base import ActorAgent

    agent = ActorAgent(config or AgentConfig(name="test-agent"), supervisor)
    return agent


def _make_mock_llm(response_content: str = "Mock LLM response") -> AsyncMock:
    """创建 mock LLM（返回纯文本，无 tool_calls）。"""
    mock_llm = AsyncMock()
    mock_response = LLMResponse(content_blocks=[TextBlock(text=response_content)])
    mock_llm.generate.return_value = mock_response
    mock_llm.configure_tools = MagicMock()
    return mock_llm


def _make_user_message(content: str = "Hello") -> Message:
    """创建用户消息。"""
    return Message(
        sender="user",
        recipient="test-agent",
        content=content,
        type=MessageType.CHAT,
    )


# ── 测试用 Hook ──


class RouteToEndTaskHook(Hook):
    """路由到 end_task。"""

    hook_point = HookPoint.AFTER_ACTION

    async def should_trigger(self, context: AbilityExecutionContext) -> bool:
        return context.current_ability_name == "conversation"

    async def execute(
        self, context: AbilityExecutionContext, result: ActionResult | None
    ) -> HookResult:
        return HookResult.route("end_task", message="Route to end_task")


# ── 测试：Agent + Ability 完整驱动循环 ──


class TestAgentDriveLoop:
    """测试 Agent 的完整驱动循环集成。"""

    async def test_single_ability_execution(self) -> None:
        """ConversationAbility 执行 → LLM 调用 → 回复。"""
        config = AgentConfig(
            name="test-agent",
            max_iterations=10,
        )
        agent = _create_agent(config)

        conv = ConversationAbility()
        agent.register_ability(conv)

        mock_llm = _make_mock_llm("Hello! How can I help?")
        agent._llm = mock_llm

        msg = _make_user_message()
        reply = await agent.receive(msg)

        assert reply.content == "Hello! How can I help?"
        assert reply.type == MessageType.RESULT
        assert mock_llm.generate.call_count == 1

    async def test_tool_schema_collection(self) -> None:
        """注册 ReadFileAbility 后检查 tool schema 收集。"""
        config = AgentConfig(name="tool-agent")
        agent = _create_agent(config)

        read_file = ReadFileAbility()
        agent.register_ability(read_file)

        assert len(agent._bound_tools) == 1
        schema = agent._bound_tools[0]
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "read_file"

        conv = ConversationAbility()
        agent.register_ability(conv)
        assert len(agent._bound_tools) == 1

    async def test_ability_route_via_hook(self) -> None:
        """Hook 路由：conversation → end_task。"""
        config = AgentConfig(name="route-agent")
        agent = _create_agent(config)

        route_hook = RouteToEndTaskHook()
        conv = ConversationAbility(hooks=[route_hook])
        end_task = EndTaskAbility()

        agent.register_ability(conv)
        agent.register_ability(end_task)

        mock_llm = _make_mock_llm("I'll help with that")
        agent._llm = mock_llm

        msg = _make_user_message()
        reply = await agent.receive(msg)

        assert reply.type == MessageType.RESULT

    async def test_conversation_stops_after_one_iteration(self) -> None:
        """ConversationAbility 内置 Hook 确保只执行一次。"""
        config = AgentConfig(name="stop-test", max_iterations=10)
        agent = _create_agent(config)

        conv = ConversationAbility()
        agent.register_ability(conv)

        mock_llm = _make_mock_llm("Response")
        agent._llm = mock_llm

        msg = _make_user_message()
        reply = await agent.receive(msg)

        assert reply.content == "Response"
        assert mock_llm.generate.call_count == 1

    async def test_sequential_receive_calls(self) -> None:
        """连续多次 receive() 调用都正常工作。"""
        config = AgentConfig(name="multi-msg-agent", max_iterations=10)
        agent = _create_agent(config)

        conv = ConversationAbility()
        agent.register_ability(conv)

        mock_llm = _make_mock_llm("Response")
        agent._llm = mock_llm

        msg1 = _make_user_message("Message 1")
        reply1 = await agent.receive(msg1)
        assert reply1.content == "Response"

        mock_llm.generate.return_value = LLMResponse(content_blocks=[TextBlock(text="Response 2")])
        msg2 = _make_user_message("Message 2")
        reply2 = await agent.receive(msg2)
        assert reply2.content == "Response 2"


class TestManualRegistration:
    """测试手动 Ability 注册 + Tool schema 收集。"""

    def test_register_read_file_and_conversation(self) -> None:
        """注册 ReadFileAbility + ConversationAbility → tool schema 收集。"""
        config = AgentConfig(name="tool-agent")
        agent = _create_agent(config)

        agent.register_ability(ReadFileAbility())
        agent.register_ability(ConversationAbility())
        agent.register_ability(EndTaskAbility())

        ability_names = agent.get_abilities()
        assert "read_file" in ability_names
        assert "conversation" in ability_names
        assert "end_task" in ability_names
        assert len(agent._bound_tools) == 1

    async def test_full_manual_registration_message_flow(self) -> None:
        """完整流程：手动注册 → 消息收发。"""
        config = AgentConfig(
            name="full-flow-agent",
            max_iterations=10,
        )
        agent = _create_agent(config)

        agent.register_ability(ConversationAbility())
        agent.register_ability(EndTaskAbility())

        mock_llm = _make_mock_llm("Full flow response")
        agent._llm = mock_llm

        msg = _make_user_message("Test full flow")
        reply = await agent.receive(msg)

        assert reply.content == "Full flow response"
        assert reply.type == MessageType.RESULT


class TestMaxIterationsIntegration:
    """测试 max_iterations 与驱动循环的集成。"""

    async def test_max_iterations_1_executes_once(self) -> None:
        """max_iterations=1 时只执行一次。"""
        config = AgentConfig(
            name="limited-agent",
            max_iterations=1,
        )
        agent = _create_agent(config)

        conv = ConversationAbility()
        agent.register_ability(conv)

        mock_llm = _make_mock_llm("Response")
        agent._llm = mock_llm

        msg = _make_user_message()
        reply = await agent.receive(msg)

        assert reply.content == "Response"
        assert mock_llm.generate.call_count == 1

    async def test_unlimited_iterations_stops_via_hook(self) -> None:
        """max_iterations=-1 无上限，但内置 Hook 可以停止。"""
        config = AgentConfig(
            name="unlimited-agent",
            max_iterations=-1,
        )
        agent = _create_agent(config)

        conv = ConversationAbility()
        agent.register_ability(conv)

        mock_llm = _make_mock_llm("Unlimited response")
        agent._llm = mock_llm

        msg = _make_user_message()
        reply = await agent.receive(msg)

        assert reply.content == "Unlimited response"
        assert mock_llm.generate.call_count == 1
