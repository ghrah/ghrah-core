# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""集成测试：ActorAgent + ContextManager。

验证 ContextManager 在 ActorAgent 中的完整集成：
- ContextManager 自动创建和初始化
- 迭代生命周期（begin/commit/rollback）
- 消息委托到 ContextManager
- AbilityExecutionContext 包含 context_manager 引用
- 向后兼容 API（_state, get_state, set_state）
- 链式历史记录
- 无 Ability 时抛出 AgentError
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from ghrah.abilities.base import Ability, ActionOutcome, ActionResult
from ghrah.abilities.context import AbilityExecutionContext
from ghrah.abilities.hooks import Hook, HookPoint, HookResult
from ghrah.chat.content import TextBlock, ToolCallBlock
from ghrah.chat.format import LLMResponse
from ghrah.chat.message import ChatMessage
from ghrah.context.manager import ContextManager
from ghrah.core.config import AgentConfig, ContextConfig
from ghrah.core.exceptions import AgentError
from ghrah.core.message import Message, MessageType

# ----------------------------------------------------------------
# 辅助工具
# ----------------------------------------------------------------


class MockAbility(Ability):
    """测试用 Mock Ability。"""

    def __init__(
        self,
        name: str = "test_ability",
        action_result: ActionResult | None = None,
    ) -> None:
        self._name = name
        self._action_result = action_result or ActionResult(
            outcome=ActionOutcome.SUCCESS,
            data={"response": "mock response"},
        )
        self.execute_count = 0

    @property
    def name(self) -> str:
        return self._name

    async def execute(self, context: AbilityExecutionContext) -> ActionResult:
        self.execute_count += 1
        return self._action_result

    def get_hooks(self) -> list[Hook]:
        return []

    def bind_tool(self) -> dict[str, Any] | None:
        return None


class FailingAbility(Ability):
    """执行时抛出异常的 Ability。"""

    def __init__(self, name: str = "failing_ability") -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    async def execute(self, context: AbilityExecutionContext) -> ActionResult:
        raise RuntimeError("Ability execution failed")

    def get_hooks(self) -> list[Hook]:
        return []

    def bind_tool(self) -> dict[str, Any] | None:
        return None


class StateMutatingAbility(Ability):
    """修改 agent 状态的 Ability。"""

    def __init__(self, name: str = "state_ability") -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    async def execute(self, context: AbilityExecutionContext) -> ActionResult:
        if context.context_manager is not None:
            context.context_manager.apply_state_changes({"mutated": True})
        return ActionResult(
            outcome=ActionOutcome.SUCCESS,
            data={"response": "state mutated"},
        )

    def get_hooks(self) -> list[Hook]:
        return []

    def bind_tool(self) -> dict[str, Any] | None:
        return None


def _create_agent(
    config: AgentConfig | None = None,
) -> Any:
    """创建 ActorAgent 实例。"""
    from ghrah.agents.base import ActorAgent

    agent = ActorAgent(config or AgentConfig(name="test-agent"))
    return agent


def _make_message(content: str = "hello") -> Message:
    """创建测试消息。"""
    return Message(
        sender="user",
        recipient="test-agent",
        content=content,
        type=MessageType.CHAT,
    )


def _make_mock_llm(response_content: str = "AI reply") -> MagicMock:
    """创建 mock LLM（返回纯文本，无 tool_calls）。"""
    mock_llm = MagicMock()
    mock_response = LLMResponse(content_blocks=[TextBlock(text=response_content)])
    mock_llm.generate = AsyncMock(return_value=mock_response)
    mock_llm.configure_tools = MagicMock()
    return mock_llm


# ----------------------------------------------------------------
# 测试：ContextManager 自动创建
# ----------------------------------------------------------------


class TestContextManagerCreation:
    """验证 ActorAgent 初始化时自动创建 ContextManager。"""

    def test_context_manager_created_on_init(self) -> None:
        """Agent 初始化时应自动创建 ContextManager 实例。"""
        agent = _create_agent()
        assert hasattr(agent, "_context_manager")
        assert isinstance(agent._context_manager, ContextManager)

    def test_context_manager_with_agent_name(self) -> None:
        """ContextManager 应使用 AgentConfig.name 作为 agent_name。"""
        agent = _create_agent(AgentConfig(name="my-agent"))
        assert agent._context_manager._agent_name == "my-agent"

    def test_context_manager_with_system_prompt(self) -> None:
        """ContextManager 应接收 system_prompt 配置。"""
        agent = _create_agent(AgentConfig(name="prompt-agent", system_prompt="You are helpful"))
        assert agent._context_manager._system_prompt == "You are helpful"

    def test_context_manager_with_context_config(self) -> None:
        """应支持 ContextConfig 中的配置项。"""
        config = AgentConfig(
            name="config-agent",
            context=ContextConfig(snapshot_interval=10, auto_persist=True),
        )
        agent = _create_agent(config)
        assert agent._context_manager._message_store.snapshot_interval == 10
        assert agent._context_manager._auto_persist is True

    def test_context_manager_default_config(self) -> None:
        """没有 ContextConfig 时使用默认值。"""
        agent = _create_agent()
        assert agent._context_manager._message_store.snapshot_interval == 5
        assert agent._context_manager._auto_persist is False

    def test_initial_state_empty(self) -> None:
        """初始状态应为空字典。"""
        agent = _create_agent()
        assert agent._context_manager.get_current_state() == {}


# ----------------------------------------------------------------
# 测试：AbilityExecutionContext 包含 context_manager 引用
# ----------------------------------------------------------------


class TestAbilityExecutionContextIntegration:
    """验证 AbilityExecutionContext 中的 context_manager 引用。"""

    def test_build_context_includes_context_manager(self) -> None:
        """_build_hook_context 返回的 AbilityExecutionContext 应包含 context_manager。"""
        agent = _create_agent()

        context = agent._build_hook_context({})

        assert context.context_manager is agent._context_manager

    def test_build_hook_context_agent_state_from_cm(self) -> None:
        """agent_state 应来自 ContextManager。"""
        agent = _create_agent()
        agent.set_state("test_key", "test_value")

        context = agent._build_hook_context({})

        assert context.agent_state == {"test_key": "test_value"}

    def test_build_ability_context_agent_state(self) -> None:
        """_build_ability_context 的 agent_state 应来自 ContextManager。"""
        agent = _create_agent()
        agent.set_state("key", "value")

        context = agent._build_ability_context("test_ability", {}, {})

        assert context.agent_state == {"key": "value"}
        assert context.current_ability_name == "test_ability"
        assert context.tool_args == {}


# ----------------------------------------------------------------
# 测试：迭代生命周期集成
# ----------------------------------------------------------------


class TestIterationLifecycle:
    """验证 _drive_loop 中的迭代生命周期管理。"""

    @pytest.mark.asyncio
    async def test_drive_loop_commits_iteration(self) -> None:
        """成功执行 ability 后应提交迭代。"""
        agent = _create_agent(AgentConfig(name="test-agent", max_iterations=1))
        agent.register_ability(MockAbility(name="conversation"))

        mock_llm = _make_mock_llm()
        agent._llm = mock_llm
        msg = _make_message()
        agent._message_history.append(msg)

        cm = agent._context_manager
        cm.reset_iteration()

        await agent._drive_loop()

        chain = cm._chain
        assert chain.head is not None
        assert chain.head.ability_names == ["conversation"]

    @pytest.mark.asyncio
    async def test_drive_loop_captures_ability_failure(self) -> None:
        """ability 执行异常时应被 asyncio.gather 捕获为 FAILURE，迭代正常 commit。"""
        agent = _create_agent(AgentConfig(name="test-agent", max_iterations=1))
        agent.register_ability(FailingAbility())

        mock_response = LLMResponse(
            content_blocks=[ToolCallBlock(id="call_1", name="failing_ability", arguments={})],
        )
        mock_llm = MagicMock()
        mock_llm.generate = AsyncMock(return_value=mock_response)
        mock_llm.configure_tools = MagicMock()
        agent._llm = mock_llm

        msg = _make_message()
        agent._message_history.append(msg)

        cm = agent._context_manager
        cm.reset_iteration()

        await agent._drive_loop()

        head = cm.chain.head
        assert head is not None
        assert head.ability_names == ["failing_ability"]
        action_result = head.action_results
        assert isinstance(action_result, list)
        assert action_result[0]["action_result"].outcome == ActionOutcome.FAILURE

    @pytest.mark.asyncio
    async def test_multiple_iterations_create_chain(self) -> None:
        """多次迭代应在链上创建多个节点。"""
        agent = _create_agent(AgentConfig(name="test-agent", max_iterations=3))
        agent.register_ability(MockAbility(name="conversation"))

        class StopAfterTwoHook(Hook):
            hook_point = HookPoint.AFTER_ACTION
            count = 0

            async def should_trigger(self, context: AbilityExecutionContext) -> bool:
                return True

            async def execute(
                self, context: AbilityExecutionContext, result: ActionResult | None
            ) -> HookResult:
                self.count += 1
                if self.count >= 2:
                    return HookResult.stop(message="Done after two")
                return HookResult.continue_()

        agent._all_hooks.append(StopAfterTwoHook())

        mock_llm = _make_mock_llm()
        agent._llm = mock_llm
        msg = _make_message()
        agent._message_history.append(msg)

        cm = agent._context_manager
        cm.reset_iteration()

        await agent._drive_loop()

        chain = cm._chain
        assert chain.head is not None
        nodes = chain.get_history()
        assert len(nodes) >= 2

    @pytest.mark.asyncio
    async def test_state_changes_persisted_through_iteration(self) -> None:
        """迭代中的状态变更应被持久化。"""
        agent = _create_agent(AgentConfig(name="test-agent", max_iterations=1))
        agent.register_ability(StateMutatingAbility())

        mock_response = LLMResponse(
            content_blocks=[ToolCallBlock(id="call_1", name="state_ability", arguments={})],
        )
        mock_llm = MagicMock()
        mock_llm.generate = AsyncMock(return_value=mock_response)
        mock_llm.configure_tools = MagicMock()
        agent._llm = mock_llm

        msg = _make_message()
        agent._message_history.append(msg)

        cm = agent._context_manager
        cm.reset_iteration()

        await agent._drive_loop()

        state = cm.get_current_state()
        assert state.get("mutated") is True


# ----------------------------------------------------------------
# 测试：消息委托
# ----------------------------------------------------------------


class TestMessageDelegation:
    """验证消息通过 ContextManager 管理。"""

    def test_messages_via_context_manager(self) -> None:
        """消息应通过 ContextManager.message_store 管理。"""
        agent = _create_agent()
        assert agent._context_manager.message_store.current_messages == []

        agent._context_manager.message_store.append(ChatMessage.user(text_or_blocks="test"))
        assert len(agent._context_manager.message_store.current_messages) == 1

    def test_messages_replace_via_message_store(self) -> None:
        """可以直接替换 MessageStore 的消息。"""
        agent = _create_agent()
        new_messages = [ChatMessage.system(text="sys"), ChatMessage.user(text_or_blocks="hi")]
        for msg in new_messages:
            agent._context_manager.message_store.append(msg)
        assert len(agent._context_manager.message_store.current_messages) == 2
        assert agent._context_manager.message_store.current_messages[0].role == "system"


# ----------------------------------------------------------------
# 测试：向后兼容 API
# ----------------------------------------------------------------


class TestBackwardCompatibility:
    """验证旧 API 通过 property 代理保持兼容。"""

    def test_state_read_via_context_manager(self) -> None:
        """状态应通过 ContextManager.state_manager 读取。"""
        agent = _create_agent()
        agent.set_state("foo", "bar")
        assert agent._context_manager.get_current_state() == {"foo": "bar"}

    def test_state_write_via_context_manager(self) -> None:
        """状态应通过 set_state() 或 ContextManager 写入。"""
        agent = _create_agent()
        agent.set_state("new", "state")
        assert agent._context_manager.state_manager.current == {"new": "state"}

    def test_get_state(self) -> None:
        """get_state() 应返回包含 ContextManager 状态的完整信息。"""
        agent = _create_agent()
        agent.set_state("x", 1)
        state = agent.get_state()
        assert state["state"] == {"x": 1}
        assert state["name"] == "test-agent"
        assert "abilities" in state

    def test_set_state(self) -> None:
        """set_state(key, value) 应更新 ContextManager 的状态。"""
        agent = _create_agent()
        agent.set_state("y", 2)
        assert agent._context_manager.state_manager.current.get("y") == 2

    def test_get_history(self) -> None:
        """get_history() 应返回 _message_history 的内容。"""
        agent = _create_agent()
        msg = _make_message()
        agent._message_history.append(msg)
        history = agent.get_history()
        assert len(history) == 1
        assert history[0]["content"] == "hello"

    @pytest.mark.asyncio
    async def test_reset(self) -> None:
        """reset() 应重建 ContextManager。"""
        agent = _create_agent()
        agent.set_state("z", 3)
        agent._message_history.append(_make_message())

        await agent.reset()

        assert agent._context_manager.get_current_state() == {}
        assert len(agent._message_history) == 0
        assert agent._context_manager.message_store.current_messages == []


# ----------------------------------------------------------------
# 测试：完整流程集成
# ----------------------------------------------------------------


class TestFullFlow:
    """验证完整的 receive → drive_loop → response 流程。"""

    @pytest.mark.asyncio
    async def test_receive_with_ability(self) -> None:
        """完整的 receive 流程应正常工作。"""
        agent = _create_agent(AgentConfig(name="test-agent", max_iterations=1))
        ability = MockAbility()
        agent.register_ability(ability)

        mock_response = LLMResponse(
            content_blocks=[ToolCallBlock(id="call_1", name="test_ability", arguments={})],
        )
        mock_llm = MagicMock()
        mock_llm.generate = AsyncMock(return_value=mock_response)
        mock_llm.configure_tools = MagicMock()
        agent._llm = mock_llm
        agent._initialized = True

        msg = _make_message()
        reply = await agent.receive(msg)

        assert reply.type == MessageType.RESULT
        assert reply.content == "mock response"
        assert ability.execute_count == 1

        chain = agent._context_manager._chain
        assert chain.head is not None

    @pytest.mark.asyncio
    async def test_receive_without_ability_raises_error(self) -> None:
        """无 ability 注册时，receive 应抛出 AgentError。"""
        agent = _create_agent()

        msg = _make_message()
        with pytest.raises(AgentError, match="No abilities registered"):
            await agent.receive(msg)

    @pytest.mark.asyncio
    async def test_receive_captures_ability_failure(self) -> None:
        """ability 执行异常时被捕获为 FAILURE，receive 正常返回。"""
        agent = _create_agent(AgentConfig(name="test-agent", max_iterations=1))
        agent.register_ability(FailingAbility())

        mock_response = LLMResponse(
            content_blocks=[ToolCallBlock(id="call_1", name="failing_ability", arguments={})],
        )
        mock_llm = MagicMock()
        mock_llm.generate = AsyncMock(return_value=mock_response)
        mock_llm.configure_tools = MagicMock()
        agent._llm = mock_llm
        agent._initialized = True

        msg = _make_message()
        reply = await agent.receive(msg)
        assert reply is not None

    @pytest.mark.asyncio
    async def test_message_history_preserved(self) -> None:
        """多轮对话后消息历史应正确保留。"""
        agent = _create_agent()
        ability = MockAbility()
        agent.register_ability(ability)

        mock_llm = _make_mock_llm(response_content="Reply")
        agent._llm = mock_llm
        agent._initialized = True

        msg1 = _make_message("first")
        await agent.receive(msg1)

        msg2 = _make_message("second")
        await agent.receive(msg2)

        assert len(agent._message_history) == 4
        assert agent._message_history[0].content == "first"
        assert agent._message_history[2].content == "second"


# ----------------------------------------------------------------
# 测试：ContextManager fork_for_sub_agent
# ----------------------------------------------------------------


class TestSubAgentFork:
    """验证 fork_for_sub_agent 功能。"""

    def test_fork_creates_independent_context(self) -> None:
        """fork 应创建独立的 ContextManager。"""
        agent = _create_agent()
        agent.set_state("shared", "value")

        forked = agent._context_manager.fork_for_sub_agent("sub-agent")

        assert forked._agent_name == "sub-agent"
        assert forked.get_current_state() == {"shared": "value"}

        forked.state_manager.reset(new_state={**forked.state_manager.current, "new": "data"})
        assert "new" not in agent._context_manager.state_manager.current

    def test_fork_with_state_filter(self) -> None:
        """fork 时应支持状态过滤。"""
        agent = _create_agent()
        agent.set_state("public", "yes")
        agent.set_state("private", "no")

        forked = agent._context_manager.fork_for_sub_agent(
            "sub-agent",
            state_filter=lambda s: {k: v for k, v in s.items() if k == "public"},
        )

        state = forked.get_current_state()
        assert state == {"public": "yes"}
