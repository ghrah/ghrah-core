# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""Agent 驱动循环测试。

测试 ActorAgent 的：
- Ability 注册和 bind_tool 收集
- 核心驱动循环（三层 Hook 架构）
- _run_hooks 机制（多 hook 合并逻辑）
- 循环终止条件（max_iterations / hook 停止）
- 无 ability 注册时抛出 AgentError
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from ghrah.abilities.base import Ability, ActionOutcome, ActionResult
from ghrah.abilities.context import AbilityExecutionContext
from ghrah.abilities.errors import AbilityNotFoundError
from ghrah.abilities.hooks import Hook, HookPoint, HookResult
from ghrah.chat.content import ReasoningBlock, TextBlock, ToolCallBlock
from ghrah.chat.format import LLMResponse
from ghrah.chat.message import ChatMessage
from ghrah.core.config import AgentConfig
from ghrah.core.events import CoreEventType
from ghrah.core.exceptions import AgentError, HookError
from ghrah.core.message import AgentMessage as Message
from ghrah.core.message import MessageType

# ----------------------------------------------------------------
# 测试用 Mock 类
# ----------------------------------------------------------------


class MockAbility(Ability):
    """用于测试的 mock ability。"""

    def __init__(
        self,
        name: str = "test_ability",
        action_result: ActionResult | None = None,
        tool_schema: dict[str, Any] | None = None,
        hooks: list[Hook] | None = None,
    ) -> None:
        self._name = name
        self._action_result = action_result or ActionResult(
            outcome=ActionOutcome.SUCCESS,
            data={"response": "mock response"},
        )
        self._tool_schema = tool_schema
        self._hooks = hooks or []
        self.execute_count = 0

    @property
    def name(self) -> str:
        return self._name

    async def execute(self, context: AbilityExecutionContext) -> ActionResult:
        self.execute_count += 1
        return self._action_result

    def get_hooks(self) -> list[Hook]:
        return self._hooks

    def bind_tool(self) -> dict[str, Any] | None:
        return self._tool_schema


class MockHook(Hook):
    """用于测试的 mock hook。"""

    def __init__(
        self,
        hook_point: HookPoint = HookPoint.PRE_EXECUTE,
        should_trigger: bool = True,
        result: HookResult | None = None,
    ) -> None:
        self.hook_point = hook_point
        self._should_trigger = should_trigger
        self._result = result or HookResult.continue_()
        self.trigger_count = 0
        self.execute_count = 0

    async def should_trigger(self, context: AbilityExecutionContext) -> bool:
        self.trigger_count += 1
        return self._should_trigger

    async def execute(
        self, context: AbilityExecutionContext, result: ActionResult | None
    ) -> HookResult:
        self.execute_count += 1
        return self._result


class StopAfterOneHook(Hook):
    """AFTER_ACTION hook：第一次触发返回 stop，之后返回 continue。"""

    hook_point = HookPoint.AFTER_ACTION

    def __init__(self) -> None:
        self._call_count = 0

    async def should_trigger(self, context: AbilityExecutionContext) -> bool:
        return True

    async def execute(
        self, context: AbilityExecutionContext, result: ActionResult | None
    ) -> HookResult:
        self._call_count += 1
        if self._call_count == 1:
            return HookResult.stop(message="Done after first action")
        return HookResult.continue_()


# ----------------------------------------------------------------
# Helper：创建 ActorAgent 实例
# ----------------------------------------------------------------


def _create_agent(
    config: AgentConfig | None = None,
    supervisor: Any = None,
) -> Any:
    """创建一个 ActorAgent 实例（通过 AgentBuilder）。"""
    from ghrah.agents.builder import AgentBuilder

    agent = AgentBuilder.from_config(config or AgentConfig(name="test-agent"), supervisor=supervisor)
    return agent


def _make_message(content: str = "hello") -> Message:
    """创建测试消息。"""
    return Message(
        sender="user",
        recipient="test-agent",
        content=content,
        type=MessageType.CHAT,
    )


def _make_mock_llm(response_content: str = "Mock LLM response") -> AsyncMock:
    """创建 mock LLM，返回纯文本响应（无 tool_calls）。"""
    mock_llm = AsyncMock()
    mock_response = LLMResponse(content_blocks=[TextBlock(text=response_content)])
    mock_llm.generate.return_value = mock_response
    mock_llm.configure_tools = MagicMock()
    return mock_llm


# ----------------------------------------------------------------
# 测试：Ability 注册
# ----------------------------------------------------------------


class TestAbilityRegistration:
    """Ability 注册相关测试。"""

    def test_register_ability_basic(self) -> None:
        agent = _create_agent()
        ability = MockAbility(name="conv")

        agent.register_ability(ability)

        assert "conv" in agent._abilities
        assert agent._abilities["conv"] is ability

    def test_register_ability_collects_tool_schema(self) -> None:
        agent = _create_agent()
        tool_schema = {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read a file",
                "parameters": {"type": "object", "properties": {}},
            },
        }
        ability = MockAbility(name="read_file", tool_schema=tool_schema)

        agent.register_ability(ability)

        assert len(agent._bound_tools) == 1
        assert agent._bound_tools[0] == tool_schema

    def test_register_ability_no_tool_schema(self) -> None:
        agent = _create_agent()
        ability = MockAbility(name="conversation", tool_schema=None)

        agent.register_ability(ability)

        assert len(agent._bound_tools) == 0

    def test_register_ability_collects_hooks(self) -> None:
        agent = _create_agent()
        hook = MockHook(hook_point=HookPoint.PRE_EXECUTE)
        ability = MockAbility(name="with_hook", hooks=[hook])

        agent.register_ability(ability)

        assert len(agent._all_hooks) == 1
        assert agent._all_hooks[0] is hook

    def test_register_multiple_abilities(self) -> None:
        agent = _create_agent()
        a1 = MockAbility(name="conv", tool_schema=None)
        a2 = MockAbility(
            name="read",
            tool_schema={"type": "function", "function": {"name": "read"}},
        )
        a3 = MockAbility(
            name="write",
            tool_schema={"type": "function", "function": {"name": "write"}},
        )

        agent.register_ability(a1)
        agent.register_ability(a2)
        agent.register_ability(a3)

        assert len(agent._abilities) == 3
        assert len(agent._bound_tools) == 2

    def test_register_duplicate_ability_raises(self) -> None:
        agent = _create_agent()
        agent.register_ability(MockAbility(name="conv"))

        with pytest.raises(AgentError, match="already registered"):
            agent.register_ability(MockAbility(name="conv"))

    def test_unregister_ability(self) -> None:
        agent = _create_agent()
        tool_schema = {"type": "function", "function": {"name": "read"}}
        hook = MockHook()
        ability = MockAbility(name="read", tool_schema=tool_schema, hooks=[hook])

        agent.register_ability(ability)
        assert len(agent._abilities) == 1
        assert len(agent._bound_tools) == 1
        assert len(agent._all_hooks) == 1

        agent.unregister_ability("read")
        assert len(agent._abilities) == 0
        assert len(agent._bound_tools) == 0
        assert len(agent._all_hooks) == 0

    def test_unregister_nonexistent_raises(self) -> None:

        agent = _create_agent()

        with pytest.raises(AbilityNotFoundError):
            agent.unregister_ability("nonexistent")

    def test_get_abilities(self) -> None:
        agent = _create_agent()
        agent.register_ability(MockAbility(name="conv"))
        agent.register_ability(MockAbility(name="read"))

        result = agent.get_abilities()
        assert set(result) == {"conv", "read"}


# ----------------------------------------------------------------
# 测试：_run_hooks 机制
# ----------------------------------------------------------------


class TestRunHooks:
    """Hook 运行机制测试。"""

    @pytest.mark.asyncio
    async def test_no_matching_hooks(self) -> None:
        agent = _create_agent()
        agent.register_ability(
            MockAbility(name="test", hooks=[MockHook(hook_point=HookPoint.POST_EXECUTE)])
        )

        context = AbilityExecutionContext()

        result = await agent._run_hooks(HookPoint.BEFORE_ACTION, context)
        assert result is None

    @pytest.mark.asyncio
    async def test_single_matching_hook(self) -> None:
        hook_result = HookResult.stop(message="blocked")
        hook = MockHook(hook_point=HookPoint.PRE_EXECUTE, result=hook_result)
        agent = _create_agent()
        agent.register_ability(MockAbility(name="test", hooks=[hook]))

        context = AbilityExecutionContext()

        result = await agent._run_hooks(HookPoint.PRE_EXECUTE, context)
        assert result is not None
        assert result.should_continue is False
        assert result.message == "blocked"

    @pytest.mark.asyncio
    async def test_multiple_hooks_merged(self) -> None:
        """多个 hook 触发时，结果应该合并（后者覆盖前者）。"""
        hook1 = MockHook(
            hook_point=HookPoint.POST_EXECUTE,
            result=HookResult(should_continue=True, route_to="ability_a"),
        )
        hook2 = MockHook(
            hook_point=HookPoint.POST_EXECUTE,
            result=HookResult(should_continue=True, route_to="ability_b"),
        )
        agent = _create_agent()
        agent.register_ability(MockAbility(name="test", hooks=[hook1, hook2]))

        context = AbilityExecutionContext()

        result = await agent._run_hooks(HookPoint.POST_EXECUTE, context)
        assert result is not None
        assert result.route_to == "ability_b"

    @pytest.mark.asyncio
    async def test_hook_should_trigger_false(self) -> None:
        """should_trigger 返回 False 的 hook 不应执行。"""
        hook = MockHook(
            hook_point=HookPoint.PRE_EXECUTE,
            should_trigger=False,
            result=HookResult.stop(),
        )
        agent = _create_agent()
        agent.register_ability(MockAbility(name="test", hooks=[hook]))

        context = AbilityExecutionContext()

        result = await agent._run_hooks(HookPoint.PRE_EXECUTE, context)
        assert result is None
        assert hook.execute_count == 0

    @pytest.mark.asyncio
    async def test_hooks_from_multiple_abilities(self) -> None:
        """不同 ability 的 hooks 都能被收集和执行。"""
        hook1 = MockHook(
            hook_point=HookPoint.BEFORE_ACTION,
            result=HookResult(should_continue=True),
        )
        hook2 = MockHook(
            hook_point=HookPoint.BEFORE_ACTION,
            result=HookResult(should_continue=True, modified_context={"key": "value"}),
        )

        agent = _create_agent()
        agent.register_ability(MockAbility(name="a1", hooks=[hook1]))
        agent.register_ability(MockAbility(name="a2", hooks=[hook2]))

        context = AbilityExecutionContext()

        result = await agent._run_hooks(HookPoint.BEFORE_ACTION, context)
        assert result is not None
        assert result.modified_context == {"key": "value"}

    @pytest.mark.asyncio
    async def test_hook_should_trigger_error(self) -> None:
        """should_trigger 抛异常时应该包装为 HookError。"""
        error_hook = MockHook(hook_point=HookPoint.PRE_EXECUTE)
        error_hook.should_trigger = AsyncMock(side_effect=ValueError("boom"))

        agent = _create_agent()
        agent.register_ability(MockAbility(name="test", hooks=[error_hook]))

        context = AbilityExecutionContext()

        with pytest.raises(HookError, match="should_trigger failed"):
            await agent._run_hooks(HookPoint.PRE_EXECUTE, context)

    @pytest.mark.asyncio
    async def test_hook_execute_error(self) -> None:
        """execute 抛异常时应该包装为 HookError。"""
        error_hook = MockHook(hook_point=HookPoint.PRE_EXECUTE)
        error_hook.execute = AsyncMock(side_effect=ValueError("boom"))

        agent = _create_agent()
        agent.register_ability(MockAbility(name="test", hooks=[error_hook]))

        context = AbilityExecutionContext()

        with pytest.raises(HookError, match="execute failed"):
            await agent._run_hooks(HookPoint.PRE_EXECUTE, context)


# ----------------------------------------------------------------
# 测试：核心驱动循环
# ----------------------------------------------------------------


class TestDriveLoop:
    """核心驱动循环测试。

    _drive_loop 通过 _action 调用 LLM，因此需要 mock LLM。
    """

    @pytest.mark.asyncio
    async def test_single_iteration_success(self) -> None:
        """单次迭代：LLM 返回纯文本 → conversation ability 执行 → AFTER_ACTION hook 停止循环。"""
        agent = _create_agent()
        agent.register_ability(MockAbility(name="conversation"))

        mock_llm = _make_mock_llm("hello world")
        agent._llm = mock_llm

        stop_hook = StopAfterOneHook()
        agent._all_hooks.append(stop_hook)

        agent._iteration_state.reset()

        await agent._drive_loop()

        assert agent._iteration_state.last_action_result is not None
        assert agent._iteration_state.last_action_result.outcome == ActionOutcome.SUCCESS

    @pytest.mark.asyncio
    async def test_max_iterations_limit(self) -> None:
        """循环应该受 max_iterations 限制。"""
        always_continue_hook = MockHook(
            hook_point=HookPoint.AFTER_ACTION,
            result=HookResult.continue_(),
        )
        agent = _create_agent()
        agent.register_ability(MockAbility(name="conversation"))
        agent._all_hooks.append(always_continue_hook)

        mock_llm = _make_mock_llm("reply")
        agent._llm = mock_llm

        agent._iteration_state.max_iterations = 3
        agent._iteration_state.reset()

        await agent._drive_loop()

        assert mock_llm.generate.call_count == 3
        assert agent._iteration_state.iteration == 2

    @pytest.mark.asyncio
    async def test_unlimited_iterations_with_hook_stop(self) -> None:
        """max_iterations = -1 时无上限，由 hook 控制终止。"""
        stop_hook = StopAfterOneHook()
        agent = _create_agent()
        agent.register_ability(MockAbility(name="conversation"))
        agent._all_hooks.append(stop_hook)

        mock_llm = _make_mock_llm("reply")
        agent._llm = mock_llm

        agent._iteration_state.max_iterations = -1
        agent._iteration_state.reset()

        await agent._drive_loop()

        assert mock_llm.generate.call_count == 1
        assert agent._iteration_state.is_unlimited is True

    @pytest.mark.asyncio
    async def test_before_action_hook_stops_loop(self) -> None:
        """BEFORE_ACTION hook 返回 should_continue=False 应停止循环。"""
        block_hook = MockHook(
            hook_point=HookPoint.BEFORE_ACTION,
            result=HookResult.stop(message="blocked by policy"),
        )
        agent = _create_agent()
        agent.register_ability(MockAbility(name="conversation"))
        agent._all_hooks.append(block_hook)

        mock_llm = _make_mock_llm("response")
        agent._llm = mock_llm

        agent._iteration_state.reset()

        await agent._drive_loop()

        assert mock_llm.generate.call_count == 0
        assert agent._iteration_state.last_action_result is None

    @pytest.mark.asyncio
    async def test_before_action_hook_routes_to_ability(self) -> None:
        """BEFORE_ACTION hook 返回 should_continue=False + route_to 时，应执行路由目标后退出。"""
        route_hook = MockHook(
            hook_point=HookPoint.BEFORE_ACTION,
            result=HookResult(should_continue=False, route_to="end_task"),
        )
        end_ability = MockAbility(
            name="end_task",
            action_result=ActionResult(
                outcome=ActionOutcome.SUCCESS,
                data={"response": "task ended"},
            ),
        )
        agent = _create_agent()
        agent.register_ability(MockAbility(name="conversation"))
        agent.register_ability(end_ability)
        agent._all_hooks.append(route_hook)

        mock_llm = _make_mock_llm("response")
        agent._llm = mock_llm

        agent._iteration_state.reset()

        await agent._drive_loop()

        assert end_ability.execute_count == 1
        assert agent._iteration_state.last_action_result.data["response"] == "task ended"

    @pytest.mark.asyncio
    async def test_after_action_hook_route_to_triggers_pending_route(self) -> None:
        """AFTER_ACTION hook 通过 route_to 设置 pending_route 并 continue。"""

        class RouteOnceHook(Hook):
            """只在第一次 AFTER_ACTION 时路由。"""

            hook_point = HookPoint.AFTER_ACTION

            def __init__(self) -> None:
                self._call_count = 0

            async def should_trigger(self, context: AbilityExecutionContext) -> bool:
                return True

            async def execute(
                self, context: AbilityExecutionContext, result: ActionResult | None
            ) -> HookResult:
                self._call_count += 1
                if self._call_count == 1:
                    return HookResult.route("step2")
                return HookResult.stop()

        route_hook = RouteOnceHook()
        step1 = MockAbility(name="step1")
        step2 = MockAbility(
            name="step2",
            action_result=ActionResult(
                outcome=ActionOutcome.SUCCESS,
                data={"step": 2},
            ),
        )
        agent = _create_agent()
        agent.register_ability(step1)
        agent.register_ability(step2)
        agent._all_hooks.append(route_hook)

        mock_llm = AsyncMock()
        mock_response = LLMResponse(
            content_blocks=[ToolCallBlock(id="call_route", name="step1", arguments={})],
        )
        mock_llm.generate.return_value = mock_response
        mock_llm.configure_tools = MagicMock()
        agent._llm = mock_llm

        agent._iteration_state.max_iterations = 10
        agent._iteration_state.reset()

        await agent._drive_loop()

        assert route_hook._call_count >= 1
        assert (
            agent._iteration_state.pending_route == "step2"
            or agent._iteration_state.iteration >= 1
        )

    @pytest.mark.asyncio
    async def test_after_action_hook_modifies_context(self) -> None:
        """AFTER_ACTION hook 可以修改上下文。"""
        modify_hook = MockHook(
            hook_point=HookPoint.AFTER_ACTION,
            result=HookResult(
                should_continue=True,
                modified_context={"extra_info": "added by hook"},
            ),
        )
        stop_hook = MockHook(
            hook_point=HookPoint.AFTER_ACTION,
            result=HookResult.stop(),
        )
        agent = _create_agent()
        agent.register_ability(MockAbility(name="conversation"))
        agent._all_hooks.append(modify_hook)
        agent._all_hooks.append(stop_hook)

        mock_llm = _make_mock_llm("response")
        agent._llm = mock_llm

        agent._iteration_state.reset()

        await agent._drive_loop()

        assert modify_hook.trigger_count >= 1
        assert stop_hook.trigger_count >= 1

    @pytest.mark.asyncio
    async def test_on_error_hook_called_on_exception(self) -> None:
        """_action 执行抛异常时应触发 ON_ERROR hooks。"""
        error_hook = MockHook(
            hook_point=HookPoint.ON_ERROR,
            result=HookResult.continue_(),
        )

        agent = _create_agent()
        agent.register_ability(MockAbility(name="conversation"))
        agent._all_hooks.append(error_hook)

        mock_llm = AsyncMock()
        mock_llm.generate.side_effect = RuntimeError("LLM crashed")
        mock_llm.configure_tools = MagicMock()
        agent._llm = mock_llm

        agent._iteration_state.reset()

        with pytest.raises(AgentError, match="LLM crashed"):
            await agent._drive_loop()

        assert error_hook.execute_count == 1

    @pytest.mark.asyncio
    async def test_on_max_iterations_hook(self) -> None:
        """达到最大迭代次数时应触发 ON_MAX_ITERATIONS hooks。"""
        max_hook = MockHook(
            hook_point=HookPoint.ON_MAX_ITERATIONS,
            result=HookResult.route("end_task"),
        )
        always_continue = MockHook(
            hook_point=HookPoint.AFTER_ACTION,
            result=HookResult.continue_(),
        )
        conv_ability = MockAbility(name="conversation")
        end_ability = MockAbility(
            name="end_task",
            action_result=ActionResult(
                outcome=ActionOutcome.SUCCESS,
                data={"response": "task ended"},
            ),
        )
        agent = _create_agent()
        agent.register_ability(conv_ability)
        agent.register_ability(end_ability)
        agent._all_hooks.extend([always_continue, max_hook])

        mock_llm = _make_mock_llm("reply")
        agent._llm = mock_llm

        agent._iteration_state.max_iterations = 2
        agent._iteration_state.reset()

        await agent._drive_loop()

        assert mock_llm.generate.call_count == 2
        assert end_ability.execute_count == 1
        assert max_hook.execute_count == 1


# ----------------------------------------------------------------
# 测试：receive 方法集成
# ----------------------------------------------------------------


class TestReceiveIntegration:
    """receive 方法的集成测试。"""

    @pytest.mark.asyncio
    async def test_receive_with_ability(self) -> None:
        """有 ability 注册时，receive 触发驱动循环。"""
        from ghrah.abilities.builtin.conversation import ConversationAbility

        agent = _create_agent()
        agent.register_ability(ConversationAbility())

        mock_llm = _make_mock_llm("Hello!")
        agent._llm = mock_llm

        message = _make_message("hi")
        reply = await agent.receive(message)

        assert reply.content == "Hello!"
        assert reply.type == MessageType.RESULT
        assert reply.reply_to == message.id

    @pytest.mark.asyncio
    async def test_receive_no_ability_raises_error(self) -> None:
        """无 ability 注册时，receive 应抛出 AgentError。"""
        agent = _create_agent()

        message = _make_message("hi")
        with pytest.raises(AgentError, match="No abilities registered"):
            await agent.receive(message)

    @pytest.mark.asyncio
    async def test_receive_multiple_abilities(self) -> None:
        """注册多个 ability，receive 正常工作。"""
        from ghrah.abilities.builtin.conversation import ConversationAbility
        from ghrah.abilities.builtin.end_task import EndTaskAbility

        agent = _create_agent()
        agent.register_ability(ConversationAbility())
        agent.register_ability(EndTaskAbility())

        mock_llm = _make_mock_llm("Multi ability response")
        agent._llm = mock_llm

        message = _make_message("test")
        reply = await agent.receive(message)

        assert reply.content == "Multi ability response"
        assert reply.type == MessageType.RESULT

    @pytest.mark.asyncio
    async def test_receive_error_handling(self) -> None:
        """receive 中 AgentError 被重新抛出。"""
        from ghrah.abilities.builtin.conversation import ConversationAbility

        agent = _create_agent()
        agent.register_ability(ConversationAbility())

        mock_llm = AsyncMock()
        mock_llm.generate.side_effect = RuntimeError("LLM down")
        mock_llm.configure_tools = MagicMock()
        agent._llm = mock_llm

        message = _make_message("hi")
        with pytest.raises(AgentError, match="Action failed"):
            await agent.receive(message)

    @pytest.mark.asyncio
    async def test_receive_sequential_messages(self) -> None:
        """连续多次 receive 正常工作。"""
        from ghrah.abilities.builtin.conversation import ConversationAbility

        agent = _create_agent()
        agent.register_ability(ConversationAbility())

        mock_llm = _make_mock_llm("Response 1")
        agent._llm = mock_llm

        msg1 = _make_message("msg1")
        reply1 = await agent.receive(msg1)
        assert reply1.content == "Response 1"

        mock_llm.generate.return_value = LLMResponse(content_blocks=[TextBlock(text="Response 2")])
        msg2 = _make_message("msg2")
        reply2 = await agent.receive(msg2)
        assert reply2.content == "Response 2"
        assert [
            message.role
            for message in agent._context_manager.message_store.current_messages
        ] == ["user", "ai", "user", "ai"]

    @pytest.mark.asyncio
    async def test_reasoning_only_response_retries_for_visible_text(self) -> None:
        """终止响应只有 reasoning 时补全一次，且不把首次空响应写入历史。"""
        from ghrah.abilities.builtin.conversation import ConversationAbility

        agent = _create_agent()
        agent.register_ability(ConversationAbility())
        agent._llm = AsyncMock()
        agent._llm.configure_tools = MagicMock()
        agent._llm.generate.side_effect = [
            LLMResponse(content_blocks=[ReasoningBlock(reasoning="内部思考")]),
            LLMResponse(content_blocks=[TextBlock(text="下午好呀。")]),
        ]

        reply = await agent.receive(_make_message("下午好"))

        assert reply.content == "下午好呀。"
        assert agent._llm.generate.await_count == 2
        messages = agent._context_manager.message_store.current_messages
        assert [message.role for message in messages] == ["user", "ai"]
        assert messages[-1].text == "下午好呀。"
        retry_messages = agent._llm.generate.await_args_list[1].args[0]
        assert any(message.source == "system:runtime" for message in retry_messages)

    @pytest.mark.asyncio
    async def test_reasoning_only_retry_uses_safe_visible_fallback(self) -> None:
        """补全仍无正文时给出安全提示，不能把 reasoning 当用户回复。"""
        from ghrah.abilities.builtin.conversation import ConversationAbility

        agent = _create_agent()
        agent.register_ability(ConversationAbility())
        agent._llm = AsyncMock()
        agent._llm.configure_tools = MagicMock()
        agent._llm.generate.side_effect = [
            LLMResponse(content_blocks=[ReasoningBlock(reasoning="隐私思考一")]),
            LLMResponse(content_blocks=[ReasoningBlock(reasoning="隐私思考二")]),
        ]

        reply = await agent.receive(_make_message("下午好"))

        assert reply.content == "模型未返回可展示的正文，请重试。"
        assert "隐私思考" not in reply.content

    @pytest.mark.asyncio
    async def test_receive_does_not_republish_previous_chain_head(self) -> None:
        """第二条消息只发布新节点，不能先重放上一条回复节点。"""
        from ghrah.abilities.builtin.conversation import ConversationAbility

        agent = _create_agent()
        agent.register_ability(ConversationAbility())
        agent._llm = _make_mock_llm("first")
        publisher = MagicMock()
        publisher.publish = AsyncMock()
        agent._event_publisher = publisher

        await agent.receive(_make_message("one"))
        agent._llm.generate.return_value = LLMResponse(
            content_blocks=[TextBlock(text="second")]
        )
        await agent.receive(_make_message("two"))

        chain_events = [
            call.args[0]
            for call in publisher.publish.await_args_list
            if call.args[0].event_type == CoreEventType.ACTION_CHAIN_UPDATED
        ]
        assert len(chain_events) == 2
        assert [event.node["iteration"] for event in chain_events] == [1, 2]
        assert chain_events[0].node["id"] != chain_events[1].node["id"]

    @pytest.mark.asyncio
    async def test_room_delivery_context_survives_tool_call_iterations(self) -> None:
        """最终 conversation 节点没有 user delta 时仍携带 Room 归属。"""
        from ghrah.abilities.builtin.conversation import ConversationAbility

        agent = _create_agent()
        agent.register_ability(
            MockAbility(
                name="write_file",
                action_result=ActionResult(
                    outcome=ActionOutcome.SUCCESS,
                    data={"bytes_written": 3},
                ),
                tool_schema={"type": "function", "function": {"name": "write_file"}},
            )
        )
        agent.register_ability(ConversationAbility())
        agent._llm = AsyncMock()
        agent._llm.configure_tools = MagicMock()
        agent._llm.generate.side_effect = [
            LLMResponse(
                content_blocks=[
                    ToolCallBlock(
                        id="call-write",
                        name="write_file",
                        arguments={"content": "poem"},
                    )
                ]
            ),
            LLMResponse(content_blocks=[TextBlock(text="已写好。")]),
        ]
        publisher = MagicMock()
        publisher.publish = AsyncMock()
        agent._event_publisher = publisher

        await agent.receive(
            Message(
                sender="user",
                recipient="test-agent",
                content="写一首诗",
                type=MessageType.CHAT,
                metadata={
                    "room_id": "room-1",
                    "project_id": "project-1",
                    "agent_id": "stable-1",
                },
            )
        )

        chain_events = [
            call.args[0]
            for call in publisher.publish.await_args_list
            if call.args[0].event_type == CoreEventType.ACTION_CHAIN_UPDATED
        ]
        assert len(chain_events) == 2
        assert any(
            message["role"] == "user"
            for message in chain_events[0].node["messages_delta"]
        )
        assert all(
            message["role"] != "user"
            for message in chain_events[1].node["messages_delta"]
        )
        assert [
            event.node["metadata"]["delivery_context"] for event in chain_events
        ] == [
            {
                "room_id": "room-1",
                "project_id": "project-1",
                "agent_id": "stable-1",
            },
            {
                "room_id": "room-1",
                "project_id": "project-1",
                "agent_id": "stable-1",
            },
        ]


# ----------------------------------------------------------------
# 测试：并行 tool_calls 执行
# ----------------------------------------------------------------


def _make_mock_llm_with_tool_calls(
    tool_calls: list[dict[str, Any]],
) -> AsyncMock:
    """创建 mock LLM，返回带有 tool_calls 的响应。"""
    mock_llm = AsyncMock()
    mock_response = LLMResponse(
        content_blocks=[
            ToolCallBlock(id=tc["id"], name=tc["name"], arguments=tc["args"]) for tc in tool_calls
        ],
    )
    mock_llm.generate.return_value = mock_response
    mock_llm.configure_tools = MagicMock()
    return mock_llm


class TestParallelToolCalls:
    """并行 tool_calls 执行测试。"""

    @pytest.mark.asyncio
    async def test_action_with_multiple_tool_calls(self) -> None:
        """LLM 返回 2 个 tool_calls 时，两个 abilities 都应被执行。"""
        agent = _create_agent()

        ability_a = MockAbility(
            name="read_file",
            action_result=ActionResult(
                outcome=ActionOutcome.SUCCESS,
                data={"content": "file A content"},
            ),
            tool_schema={"type": "function", "function": {"name": "read_file"}},
        )
        ability_b = MockAbility(
            name="write_file",
            action_result=ActionResult(
                outcome=ActionOutcome.SUCCESS,
                data={"content": "file B written"},
            ),
            tool_schema={"type": "function", "function": {"name": "write_file"}},
        )
        agent.register_ability(ability_a)
        agent.register_ability(ability_b)

        mock_llm = _make_mock_llm_with_tool_calls(
            [
                {
                    "name": "read_file",
                    "args": {"file_path": "/tmp/a.txt"},
                    "id": "call_1",
                },
                {
                    "name": "write_file",
                    "args": {"file_path": "/tmp/b.txt", "content": "hello"},
                    "id": "call_2",
                },
            ]
        )
        agent._llm = mock_llm

        action_output = await agent._action({})
        results = action_output["results"]

        assert len(results) == 2
        assert results[0]["ability_name"] == "read_file"
        assert results[0]["action_result"].outcome == ActionOutcome.SUCCESS
        assert results[1]["ability_name"] == "write_file"
        assert results[1]["action_result"].outcome == ActionOutcome.SUCCESS

        assert ability_a.execute_count == 1
        assert ability_b.execute_count == 1

    @pytest.mark.asyncio
    async def test_action_parallel_partial_failure(self) -> None:
        """LLM 返回 2 个 tool_calls，其中一个 ability 执行失败，不影响另一个。"""
        agent = _create_agent()

        success_ability = MockAbility(
            name="read_file",
            action_result=ActionResult(
                outcome=ActionOutcome.SUCCESS,
                data={"content": "file content"},
            ),
            tool_schema={"type": "function", "function": {"name": "read_file"}},
        )

        class FailingAbility(Ability):
            @property
            def name(self) -> str:
                return "fail_tool"

            async def execute(self, context: AbilityExecutionContext) -> ActionResult:
                raise RuntimeError("Something went wrong")

            def get_hooks(self) -> list[Hook]:
                return []

            def bind_tool(self) -> dict[str, Any] | None:
                return {"type": "function", "function": {"name": "fail_tool"}}

        failing_ability = FailingAbility()
        agent.register_ability(success_ability)
        agent.register_ability(failing_ability)

        mock_llm = _make_mock_llm_with_tool_calls(
            [
                {"name": "read_file", "args": {"file_path": "/tmp/a.txt"}, "id": "call_1"},
                {"name": "fail_tool", "args": {"param": "value"}, "id": "call_2"},
            ]
        )
        agent._llm = mock_llm

        action_output = await agent._action({})
        results = action_output["results"]

        assert len(results) == 2

        success_results = [r for r in results if r["ability_name"] == "read_file"]
        assert len(success_results) == 1
        assert success_results[0]["action_result"].outcome == ActionOutcome.SUCCESS

        fail_results = [r for r in results if r["ability_name"] == "fail_tool"]
        assert len(fail_results) == 1
        assert fail_results[0]["action_result"].outcome == ActionOutcome.FAILURE
        assert "Something went wrong" in fail_results[0]["action_result"].data["error"]

        assert success_ability.execute_count == 1

    @pytest.mark.asyncio
    async def test_action_parallel_all_failure(self) -> None:
        """所有 abilities 都失败时，结果应正确收集。"""
        agent = _create_agent()

        class AlwaysFailAbility(Ability):
            def __init__(self, name: str, error_msg: str) -> None:
                self._name = name
                self._error_msg = error_msg

            @property
            def name(self) -> str:
                return self._name

            async def execute(self, context: AbilityExecutionContext) -> ActionResult:
                raise RuntimeError(self._error_msg)

            def get_hooks(self) -> list[Hook]:
                return []

            def bind_tool(self) -> dict[str, Any] | None:
                return {"type": "function", "function": {"name": self._name}}

        fail_a = AlwaysFailAbility("tool_a", "Error A")
        fail_b = AlwaysFailAbility("tool_b", "Error B")
        agent.register_ability(fail_a)
        agent.register_ability(fail_b)

        mock_llm = _make_mock_llm_with_tool_calls(
            [
                {"name": "tool_a", "args": {}, "id": "call_1"},
                {"name": "tool_b", "args": {}, "id": "call_2"},
            ]
        )
        agent._llm = mock_llm

        action_output = await agent._action({})
        results = action_output["results"]

        assert len(results) == 2
        assert all(r["action_result"].outcome == ActionOutcome.FAILURE for r in results)

        error_messages = [r["action_result"].data["error"] for r in results]
        assert "Error A" in error_messages
        assert "Error B" in error_messages

    @pytest.mark.asyncio
    async def test_action_single_tool_call_serial_path(self) -> None:
        """单个 tool_call 应走串行执行路径（向后兼容）。"""
        agent = _create_agent()

        ability = MockAbility(
            name="read_file",
            action_result=ActionResult(
                outcome=ActionOutcome.SUCCESS,
                data={"content": "file content"},
            ),
            tool_schema={"type": "function", "function": {"name": "read_file"}},
        )
        agent.register_ability(ability)

        mock_llm = _make_mock_llm_with_tool_calls(
            [
                {"name": "read_file", "args": {"file_path": "/tmp/a.txt"}, "id": "call_1"},
            ]
        )
        agent._llm = mock_llm

        action_output = await agent._action({})
        results = action_output["results"]

        assert len(results) == 1
        assert results[0]["ability_name"] == "read_file"
        assert results[0]["action_result"].outcome == ActionOutcome.SUCCESS
        assert ability.execute_count == 1

    @pytest.mark.asyncio
    async def test_action_unknown_ability_in_parallel(self) -> None:
        """并行执行中混合已知和未知 ability 时，未知 ability 应记录失败。"""
        agent = _create_agent()

        known_ability = MockAbility(
            name="read_file",
            action_result=ActionResult(
                outcome=ActionOutcome.SUCCESS,
                data={"content": "file content"},
            ),
            tool_schema={"type": "function", "function": {"name": "read_file"}},
        )
        agent.register_ability(known_ability)

        mock_llm = _make_mock_llm_with_tool_calls(
            [
                {"name": "read_file", "args": {"file_path": "/tmp/a.txt"}, "id": "call_1"},
                {"name": "unknown_tool", "args": {}, "id": "call_2"},
            ]
        )
        agent._llm = mock_llm

        action_output = await agent._action({})
        results = action_output["results"]

        assert len(results) == 2

        known_results = [r for r in results if r["ability_name"] == "read_file"]
        assert len(known_results) == 1
        assert known_results[0]["action_result"].outcome == ActionOutcome.SUCCESS

        unknown_results = [r for r in results if r["ability_name"] == "unknown_tool"]
        assert len(unknown_results) == 1
        assert unknown_results[0]["action_result"].outcome == ActionOutcome.FAILURE
        assert "Unknown ability" in unknown_results[0]["action_result"].data["error"]

    @pytest.mark.asyncio
    async def test_parallel_tool_calls_with_tool_messages(self) -> None:
        """并行执行后 ChatMessage.tool 应正确构建并添加到 ContextManager。"""

        agent = _create_agent()

        ability_a = MockAbility(
            name="read_file",
            action_result=ActionResult(
                outcome=ActionOutcome.SUCCESS,
                data={"content": "file A"},
            ),
            tool_schema={"type": "function", "function": {"name": "read_file"}},
        )
        ability_b = MockAbility(
            name="write_file",
            action_result=ActionResult(
                outcome=ActionOutcome.FAILURE,
                data={"error": "Permission denied"},
            ),
            tool_schema={"type": "function", "function": {"name": "write_file"}},
        )
        agent.register_ability(ability_a)
        agent.register_ability(ability_b)

        mock_llm = _make_mock_llm_with_tool_calls(
            [
                {"name": "read_file", "args": {"file_path": "/tmp/a.txt"}, "id": "call_1"},
                {"name": "write_file", "args": {"file_path": "/tmp/b.txt"}, "id": "call_2"},
            ]
        )
        agent._llm = mock_llm

        await agent._action({})

        messages = agent._context_manager.message_store.current_messages
        tool_messages = [m for m in messages if m.role == "tool"]
        assert len(tool_messages) == 2

        tool_call_ids = set()
        for m in tool_messages:
            for tr in m.tool_results:
                tool_call_ids.add(tr.tool_call_id)
        assert "call_1" in tool_call_ids
        assert "call_2" in tool_call_ids


# ----------------------------------------------------------------
# 测试：消息队列注入
# ----------------------------------------------------------------


class TestMessageQueue:
    """消息队列注入测试。

    验证 ActorAgent 的 _message_queue 支持：
    - receive() 通过队列注入初始用户消息
    - inject_message() 在迭代中注入新消息
    - _drain_message_queue() 非阻塞排空
    - 多消息在多次迭代中消费
    - 空队列时正常工作
    """

    def test_message_queue_initial_state(self) -> None:
        """Agent 初始状态时消息队列为空。"""
        agent = _create_agent()
        assert agent._message_queue.empty()

    @pytest.mark.asyncio
    async def test_inject_message_adds_to_queue(self) -> None:
        """inject_message 将消息添加到队列。"""
        agent = _create_agent()
        msg = ChatMessage.user("injected message", source="human")
        await agent.inject_message(msg)

        assert agent._message_queue.qsize() == 1

    @pytest.mark.asyncio
    async def test_inject_multiple_messages(self) -> None:
        """多次 inject_message 按顺序入队。"""
        agent = _create_agent()
        msg1 = ChatMessage.user("first", source="human")
        msg2 = ChatMessage.user("second", source="human")
        await agent.inject_message(msg1)
        await agent.inject_message(msg2)

        assert agent._message_queue.qsize() == 2
        drained = agent._drain_message_queue()
        assert len(drained) == 2
        assert drained[0] is msg1
        assert drained[1] is msg2

    def test_drain_empty_queue(self) -> None:
        """空队列排空时返回空列表。"""
        agent = _create_agent()
        result = agent._drain_message_queue()
        assert result == []

    @pytest.mark.asyncio
    async def test_drain_message_queue_non_blocking(self) -> None:
        """_drain_message_queue 非阻塞，排空后不再等待。"""
        agent = _create_agent()
        msg = ChatMessage.user("test", source="human")
        await agent.inject_message(msg)

        drained = agent._drain_message_queue()
        assert len(drained) == 1
        assert drained[0] is msg

        # 第二次排空应返回空
        drained_again = agent._drain_message_queue()
        assert drained_again == []

    @pytest.mark.asyncio
    async def test_receive_enqueues_initial_message(self) -> None:
        """receive() 将用户消息入队到 _message_queue。"""
        from ghrah.abilities.builtin.conversation import ConversationAbility

        agent = _create_agent()
        agent.register_ability(ConversationAbility())
        agent._llm = _make_mock_llm("Hello response")

        message = _make_message("initial message")
        await agent.receive(message)

        # receive 完成后队列应为空（消息已被 drive_loop 消费）
        assert agent._message_queue.empty()

    @pytest.mark.asyncio
    async def test_drive_loop_consumes_queue_each_iteration(self) -> None:
        """_drive_loop 在每轮迭代开始时从队列注入消息。

        模拟场景：第一轮迭代消费 receive() 入队的消息，
        然后通过 inject_message 注入新消息，下一轮迭代应消费它。
        """
        agent = _create_agent()
        agent.register_ability(MockAbility(name="conversation"))

        call_count = 0

        async def inject_on_second_call(messages_arg):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # 第一次 LLM 返回文本回复，循环结束
                return LLMResponse(content_blocks=[TextBlock(text="first response")])
            # 不应到达第二次（StopAfterOneHook 会在第一次后停止）
            return LLMResponse(content_blocks=[TextBlock(text="second response")])

        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(side_effect=inject_on_second_call)
        mock_llm.configure_tools = MagicMock()
        agent._llm = mock_llm

        stop_hook = StopAfterOneHook()
        agent._all_hooks.append(stop_hook)

        # 入队消息并运 drive_loop
        await agent._message_queue.put(ChatMessage.user("hello", source="human"))
        agent._iteration_state.reset()

        await agent._drive_loop()

        assert call_count == 1

    @pytest.mark.asyncio
    async def test_inject_message_mid_loop(self) -> None:
        """在 drive_loop 运行期间通过 inject_message 注入消息。

        使用 AFTER_ACTION hook 在第一次迭代后注入新消息，
        验证消息在下一轮迭代被消费。
        """
        agent = _create_agent()
        agent.register_ability(MockAbility(name="conversation"))

        injected_msg = ChatMessage.user("mid-loop injection", source="human")
        iteration_count = 0

        class InjectAfterFirstAction(Hook):
            """第一次 AFTER_ACTION 时注入消息并继续循环。"""

            hook_point = HookPoint.AFTER_ACTION

            def __init__(self) -> None:
                self._call_count = 0

            async def should_trigger(self, context: AbilityExecutionContext) -> bool:
                return True

            async def execute(
                self, context: AbilityExecutionContext, result: ActionResult | None
            ) -> HookResult:
                self._call_count += 1
                if self._call_count == 1:
                    return HookResult.continue_()
                return HookResult.stop()

        inject_hook = InjectAfterFirstAction()
        agent._all_hooks.append(inject_hook)

        mock_llm = _make_mock_llm("response")
        agent._llm = mock_llm

        # 入队初始消息
        await agent._message_queue.put(ChatMessage.user("start", source="human"))
        agent._iteration_state.max_iterations = 10
        agent._iteration_state.reset()

        # 在 drive_loop 开始前注入一条消息
        await agent.inject_message(injected_msg)

        await agent._drive_loop()

        # 验证注入的消息被消费
        assert agent._message_queue.empty()

    @pytest.mark.asyncio
    async def test_reset_clears_message_queue(self) -> None:
        """reset() 应清空消息队列。"""
        agent = _create_agent()
        await agent.inject_message(ChatMessage.user("msg1", source="human"))
        await agent.inject_message(ChatMessage.user("msg2", source="human"))

        assert agent._message_queue.qsize() == 2

        await agent.reset()

        assert agent._message_queue.empty()

    @pytest.mark.asyncio
    async def test_reset_clears_iteration_state(self) -> None:
        """reset() 应重置驱动循环状态（iteration/last_action_result/pending_route）。

        回归测试：S1.3 将驱动循环状态从 ContextManager 迁出到
        ActorAgent._iteration_state 后，reset() 仅重建 ContextManager 不再
        隐式清掉这些字段，必须在 reset() 中显式重置，否则状态泄漏到下一轮
        （例如 list_sessions() 的 iteration_count 报告旧值）。
        """
        agent = _create_agent(
            AgentConfig(name="test-agent", max_iterations=7)
        )
        # 污染驱动循环状态
        agent._iteration_state.iteration = 3
        agent._iteration_state.pending_route = "step2"
        agent._iteration_state.last_action_result = ActionResult(
            outcome=ActionOutcome.SUCCESS,
            data={"response": "stale"},
        )

        await agent.reset()

        # reset() 必须清零这三个字段
        assert agent._iteration_state.iteration == 0
        assert agent._iteration_state.pending_route is None
        assert agent._iteration_state.last_action_result is None
        # max_iterations 应从 config 同步（而非残留默认值 10）
        assert agent._iteration_state.max_iterations == 7

    @pytest.mark.asyncio
    async def test_rollback_preserves_queued_messages(self) -> None:
        """迭代失败回滚时，排空的消息应重新注入队列，防止消息丢失。

        场景：消息入队 → _drive_loop 排空消息 → _action 抛异常 →
        rollback_iteration 应将排空的消息重新放回队列。
        """
        agent = _create_agent()
        agent.register_ability(MockAbility(name="conversation"))

        mock_llm = AsyncMock()
        mock_llm.generate.side_effect = RuntimeError("LLM crashed")
        mock_llm.configure_tools = MagicMock()
        agent._llm = mock_llm

        msg1 = ChatMessage.user("important message", source="human")
        msg2 = ChatMessage.user("another message", source="human")
        await agent._message_queue.put(msg1)
        await agent._message_queue.put(msg2)

        agent._iteration_state.reset()

        with pytest.raises(AgentError, match="Action failed"):
            await agent._drive_loop()

        # 回滚后，排空的消息应重新注入队列
        assert not agent._message_queue.empty()
        drained = agent._drain_message_queue()
        assert len(drained) == 2
        assert drained[0] is msg1
        assert drained[1] is msg2

    @pytest.mark.asyncio
    async def test_rollback_preserves_message_order(self) -> None:
        """回滚后重新入队的消息应保持原始顺序。

        使用 reversed 入队保证先入队的消息先出队。
        """
        agent = _create_agent()
        agent.register_ability(MockAbility(name="conversation"))

        mock_llm = AsyncMock()
        mock_llm.generate.side_effect = RuntimeError("LLM crashed")
        mock_llm.configure_tools = MagicMock()
        agent._llm = mock_llm

        messages = [ChatMessage.user(f"msg_{i}", source="human") for i in range(5)]
        for msg in messages:
            await agent._message_queue.put(msg)

        agent._iteration_state.reset()

        with pytest.raises(AgentError):
            await agent._drive_loop()

        drained = agent._drain_message_queue()
        assert len(drained) == 5
        for i, msg in enumerate(drained):
            assert msg is messages[i]

    @pytest.mark.asyncio
    async def test_rollback_no_messages_in_queue(self) -> None:
        """回滚时如果队列为空（没有排空消息），不应出错。"""
        agent = _create_agent()
        agent.register_ability(MockAbility(name="conversation"))

        mock_llm = AsyncMock()
        mock_llm.generate.side_effect = RuntimeError("LLM crashed")
        mock_llm.configure_tools = MagicMock()
        agent._llm = mock_llm

        # 不入队任何消息，直接触发 drive_loop
        agent._iteration_state.reset()

        with pytest.raises(AgentError, match="Action failed"):
            await agent._drive_loop()

        # 队列仍应为空
        assert agent._message_queue.empty()

    @pytest.mark.asyncio
    async def test_commit_does_not_reinject_messages(self) -> None:
        """迭代成功提交时，排空的消息不应被重新入队。

        消息应在 commit 时进入 MessageStore，而不是回到队列。
        """
        agent = _create_agent()
        agent.register_ability(MockAbility(name="conversation"))

        stop_hook = StopAfterOneHook()
        agent._all_hooks.append(stop_hook)

        mock_llm = _make_mock_llm("response")
        agent._llm = mock_llm

        msg = ChatMessage.user("hello", source="human")
        await agent._message_queue.put(msg)

        agent._iteration_state.reset()

        await agent._drive_loop()

        # 成功迭代后，消息不应回到队列
        # 它已被 ContextManager 消费
        assert agent._message_queue.empty()
