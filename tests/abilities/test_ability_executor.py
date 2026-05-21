# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""AbilityExecutor 测试。

测试 AbilityExecutor 接口和 LocalAbilityExecutor 实现：
- execute_ability: 单个 Ability 执行（含 PRE/POST_EXECUTE Hook）
- execute_tool_calls: 多个 tool_calls 并行执行
- run_hooks: Hook 运行机制
- handle_hitl_hook_result: HITL 审批流程
- receive_hitl_response: 外部 HITL 结果接收
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from ghrah.abilities.base import Ability, ActionOutcome, ActionResult
from ghrah.abilities.context import AbilityExecutionContext
from ghrah.abilities.executor import AbilityExecutor, LocalAbilityExecutor
from ghrah.abilities.hooks import Hook, HookPoint, HookResult
from ghrah.chat.content import ToolCallBlock
from ghrah.core.event_publisher import EventPublisher, NullEventPublisher
from ghrah.core.events import HITLRequestEvent

# ─── 测试用 Ability 和 Hook ───


class MockAbility(Ability):
    """测试用 Ability。"""

    def __init__(self, name: str = "mock_ability", action_result: ActionResult | None = None):
        self._name = name
        self._action_result = action_result or ActionResult(
            outcome=ActionOutcome.SUCCESS, data={"result": "ok"}
        )

    @property
    def name(self) -> str:
        return self._name

    async def execute(self, context: AbilityExecutionContext) -> ActionResult:
        return self._action_result

    def get_hooks(self) -> list[Hook]:
        return []

    def bind_tool(self) -> dict | None:
        return {
            "type": "function",
            "function": {
                "name": self._name,
                "description": f"Mock ability: {self._name}",
                "parameters": {"type": "object", "properties": {}},
            },
        }


class FailingAbility(Ability):
    """执行失败的 Ability。"""

    @property
    def name(self) -> str:
        return "failing_ability"

    async def execute(self, context: AbilityExecutionContext) -> ActionResult:
        return ActionResult(outcome=ActionOutcome.FAILURE, data={"error": "intentional failure"})

    def get_hooks(self) -> list[Hook]:
        return []


class BlockingHook(Hook):
    """返回 should_continue=False 的 Hook（直接拦截，不触发 HITL）。"""

    hook_point = HookPoint.PRE_EXECUTE

    def __init__(self, target_ability: str = "mock_ability", message: str = "Blocked by hook"):
        self._target_ability = target_ability
        self._message = message

    async def should_trigger(self, context: AbilityExecutionContext) -> bool:
        return context.current_ability_name == self._target_ability

    async def execute(
        self, context: AbilityExecutionContext, result: ActionResult | None
    ) -> HookResult:
        return HookResult(should_continue=False, message=self._message)


class HITLBlockingHook(Hook):
    """返回 should_continue=False 且 requires_hitl=True 的 Hook（模拟 HITL 拦截）。"""

    hook_point = HookPoint.PRE_EXECUTE

    def __init__(
        self, target_ability: str = "mock_ability", message: str = "Human approval required"
    ):
        self._target_ability = target_ability
        self._message = message

    async def should_trigger(self, context: AbilityExecutionContext) -> bool:
        return context.current_ability_name == self._target_ability

    async def execute(
        self, context: AbilityExecutionContext, result: ActionResult | None
    ) -> HookResult:
        return HookResult.hitl(message=self._message)


class ModifyingHook(Hook):
    """修改上下文的 Hook。"""

    hook_point = HookPoint.PRE_EXECUTE

    def __init__(self, target_ability: str = "mock_ability"):
        self._target_ability = target_ability

    async def should_trigger(self, context: AbilityExecutionContext) -> bool:
        return context.current_ability_name == self._target_ability

    async def execute(
        self, context: AbilityExecutionContext, result: ActionResult | None
    ) -> HookResult:
        return HookResult(
            should_continue=True,
            modified_context={"hook_modified": True},
        )


class PostExecuteHook(Hook):
    """POST_EXECUTE Hook。"""

    hook_point = HookPoint.POST_EXECUTE

    async def should_trigger(self, context: AbilityExecutionContext) -> bool:
        return True

    async def execute(
        self, context: AbilityExecutionContext, result: ActionResult | None
    ) -> HookResult:
        return HookResult(should_continue=True, message="post_execute hook ran")


# ─── 测试 LocalAbilityExecutor ───


class TestLocalAbilityExecutor:
    """LocalAbilityExecutor 测试。"""

    def test_init_default(self):
        """测试默认初始化。"""
        executor = LocalAbilityExecutor(agent_name="test-agent")
        assert executor._agent_name == "test-agent"
        assert executor._hooks == []
        assert isinstance(executor._event_publisher, NullEventPublisher)
        assert executor._hitl_timeout == 300.0

    def test_init_with_hooks(self):
        """测试带 hooks 初始化。"""
        hook = BlockingHook()
        executor = LocalAbilityExecutor(agent_name="test-agent", hooks=[hook])
        assert len(executor._hooks) == 1

    def test_update_hooks(self):
        """测试 update_hooks 方法。"""
        executor = LocalAbilityExecutor(agent_name="test-agent")
        assert executor._hooks == []

        hook = BlockingHook()
        executor.update_hooks([hook])
        assert len(executor._hooks) == 1

    def test_update_event_publisher(self):
        """测试 update_event_publisher 方法。"""
        executor = LocalAbilityExecutor(agent_name="test-agent")
        assert isinstance(executor._event_publisher, NullEventPublisher)

        mock_publisher = MagicMock(spec=EventPublisher)
        executor.update_event_publisher(mock_publisher)
        assert executor._event_publisher is mock_publisher

    @pytest.mark.asyncio
    async def test_execute_ability_simple(self):
        """测试简单 Ability 执行。"""
        ability = MockAbility()
        executor = LocalAbilityExecutor(agent_name="test-agent")

        context = AbilityExecutionContext(
            current_ability_name="mock_ability",
            tool_args={},
            agent_state={},
        )

        result = await executor.execute_ability(ability, context)
        assert result.outcome == ActionOutcome.SUCCESS
        assert result.data == {"result": "ok"}

    @pytest.mark.asyncio
    async def test_execute_ability_with_pre_execute_hook(self):
        """测试 PRE_EXECUTE Hook 修改上下文。"""
        ability = MockAbility()
        hook = ModifyingHook()
        executor = LocalAbilityExecutor(agent_name="test-agent", hooks=[hook])

        context = AbilityExecutionContext(
            current_ability_name="mock_ability",
            tool_args={},
            agent_state={},
            accumulated_data={},
        )

        result = await executor.execute_ability(ability, context)
        assert result.outcome == ActionOutcome.SUCCESS
        # Hook 修改的上下文应该被合并
        assert context.accumulated_data.get("hook_modified") is True

    @pytest.mark.asyncio
    async def test_execute_ability_with_blocking_hook(self):
        """测试 PRE_EXECUTE Hook 直接拦截执行（非 HITL 场景，不等待审批）。"""
        ability = MockAbility()
        hook = BlockingHook(message="Permission denied")
        executor = LocalAbilityExecutor(agent_name="test-agent", hooks=[hook])

        context = AbilityExecutionContext(
            current_ability_name="mock_ability",
            tool_args={},
            agent_state={},
            accumulated_data={},
        )

        # BlockingHook 返回 should_continue=False 且 requires_hitl=False
        # 应直接返回 FAILURE，不进入 HITL 等待流程
        result = await executor.execute_ability(ability, context)
        assert result.outcome == ActionOutcome.FAILURE
        assert result.data.get("error") == "Permission denied"
        assert "hitl_rejected" not in result.data  # 非 HITL 拦截不应包含 hitl_rejected

    @pytest.mark.asyncio
    async def test_execute_ability_with_hitl_blocking_hook_rejected(self):
        """测试 HITL Hook 拦截且审批被拒绝的场景。"""
        ability = MockAbility()
        hook = HITLBlockingHook(message="Human approval required")
        executor = LocalAbilityExecutor(
            agent_name="test-agent",
            hooks=[hook],
            hitl_timeout=5.0,
        )

        context = AbilityExecutionContext(
            current_ability_name="mock_ability",
            tool_args={"call_id": "call_hitl_reject"},
            agent_state={},
            accumulated_data={},
        )

        # 模拟审批拒绝
        async def reject():
            await asyncio.sleep(0.1)
            executor.receive_hitl_response(
                ability_name="mock_ability",
                tool_call_id="call_hitl_reject",
                approved=False,
            )

        asyncio.create_task(reject())

        result = await executor.execute_ability(ability, context)
        # HITL 拒绝后应返回 FAILURE 且包含 hitl_rejected 标记
        assert result.outcome == ActionOutcome.FAILURE
        assert result.data.get("hitl_rejected") is True

    @pytest.mark.asyncio
    async def test_execute_ability_with_post_execute_hook(self):
        """测试 POST_EXECUTE Hook。"""
        ability = MockAbility()
        hook = PostExecuteHook()
        executor = LocalAbilityExecutor(agent_name="test-agent", hooks=[hook])

        context = AbilityExecutionContext(
            current_ability_name="mock_ability",
            tool_args={},
            agent_state={},
            accumulated_data={},
        )

        result = await executor.execute_ability(ability, context)
        assert result.outcome == ActionOutcome.SUCCESS

    @pytest.mark.asyncio
    async def test_execute_ability_failing(self):
        """测试执行失败的 Ability。"""
        ability = FailingAbility()
        executor = LocalAbilityExecutor(agent_name="test-agent")

        context = AbilityExecutionContext(
            current_ability_name="failing_ability",
            tool_args={},
            agent_state={},
        )

        result = await executor.execute_ability(ability, context)
        assert result.outcome == ActionOutcome.FAILURE
        assert result.data == {"error": "intentional failure"}

    @pytest.mark.asyncio
    async def test_execute_tool_calls_simple(self):
        """测试简单 tool_calls 执行。"""
        ability = MockAbility()
        executor = LocalAbilityExecutor(agent_name="test-agent")

        # 创建 mock ContextManager
        mock_cm = MagicMock()
        mock_cm.get_current_state.return_value = {}
        mock_cm.last_action_result = None

        tool_calls = [
            ToolCallBlock(name="mock_ability", arguments={"key": "value"}, id="call_123"),
        ]

        results = await executor.execute_tool_calls(
            tool_calls=tool_calls,
            abilities={"mock_ability": ability},
            accumulated_data={},
            context_manager=mock_cm,
        )

        assert len(results) == 1
        assert results[0]["ability_name"] == "mock_ability"
        assert results[0]["action_result"].outcome == ActionOutcome.SUCCESS
        assert results[0]["tool_call_id"] == "call_123"

    @pytest.mark.asyncio
    async def test_execute_tool_calls_unknown_ability(self):
        """测试未知 ability 的 tool_call。"""
        executor = LocalAbilityExecutor(agent_name="test-agent")

        mock_cm = MagicMock()
        mock_cm.get_current_state.return_value = {}
        mock_cm.last_action_result = None

        tool_calls = [
            ToolCallBlock(name="unknown_ability", arguments={}, id="call_456"),
        ]

        results = await executor.execute_tool_calls(
            tool_calls=tool_calls,
            abilities={},
            accumulated_data={},
            context_manager=mock_cm,
        )

        assert len(results) == 1
        assert results[0]["ability_name"] == "unknown_ability"
        assert results[0]["action_result"].outcome == ActionOutcome.FAILURE
        assert "Unknown ability" in results[0]["action_result"].data["error"]

    @pytest.mark.asyncio
    async def test_execute_tool_calls_multiple(self):
        """测试多个 tool_calls 并行执行。"""
        ability1 = MockAbility(name="ability_a")
        ability2 = MockAbility(name="ability_b")
        executor = LocalAbilityExecutor(agent_name="test-agent")

        mock_cm = MagicMock()
        mock_cm.get_current_state.return_value = {}
        mock_cm.last_action_result = None

        tool_calls = [
            ToolCallBlock(name="ability_a", arguments={}, id="call_1"),
            ToolCallBlock(name="ability_b", arguments={}, id="call_2"),
        ]

        results = await executor.execute_tool_calls(
            tool_calls=tool_calls,
            abilities={"ability_a": ability1, "ability_b": ability2},
            accumulated_data={},
            context_manager=mock_cm,
        )

        assert len(results) == 2
        ability_names = {r["ability_name"] for r in results}
        assert ability_names == {"ability_a", "ability_b"}

    @pytest.mark.asyncio
    async def test_run_hooks_no_hooks(self):
        """测试没有 Hook 时的 run_hooks。"""
        executor = LocalAbilityExecutor(agent_name="test-agent")

        context = AbilityExecutionContext(
            current_ability_name="test",
            tool_args={},
            agent_state={},
        )

        result = await executor.run_hooks(HookPoint.PRE_EXECUTE, context)
        assert result is None

    @pytest.mark.asyncio
    async def test_run_hooks_with_matching_hook(self):
        """测试匹配触发点的 Hook。"""
        hook = ModifyingHook()
        executor = LocalAbilityExecutor(agent_name="test-agent", hooks=[hook])

        context = AbilityExecutionContext(
            current_ability_name="mock_ability",
            tool_args={},
            agent_state={},
            accumulated_data={},
        )

        result = await executor.run_hooks(HookPoint.PRE_EXECUTE, context)
        assert result is not None
        assert result.modified_context == {"hook_modified": True}

    @pytest.mark.asyncio
    async def test_run_hooks_with_non_matching_point(self):
        """测试不匹配触发点的 Hook 不执行。"""
        hook = ModifyingHook()  # PRE_EXECUTE
        executor = LocalAbilityExecutor(agent_name="test-agent", hooks=[hook])

        context = AbilityExecutionContext(
            current_ability_name="mock_ability",
            tool_args={},
            agent_state={},
            accumulated_data={},
        )

        result = await executor.run_hooks(HookPoint.POST_EXECUTE, context)
        assert result is None  # PRE_EXECUTE hook 不应在 POST_EXECUTE 触发

    @pytest.mark.asyncio
    async def test_run_hooks_merge_multiple(self):
        """测试多个 Hook 结果合并。"""
        hook1 = ModifyingHook()
        hook2 = PostExecuteHook()
        executor = LocalAbilityExecutor(agent_name="test-agent", hooks=[hook1, hook2])

        context = AbilityExecutionContext(
            current_ability_name="mock_ability",
            tool_args={},
            agent_state={},
            accumulated_data={},
        )

        # 两个 PRE_EXECUTE Hook 应该合并结果
        # 但 PostExecuteHook 的 hook_point 是 POST_EXECUTE，不会触发
        result = await executor.run_hooks(HookPoint.PRE_EXECUTE, context)
        assert result is not None
        assert result.modified_context == {"hook_modified": True}

    @pytest.mark.asyncio
    async def test_handle_hitl_hook_result_with_approval(self):
        """测试 HITL 审批通过流程。"""
        executor = LocalAbilityExecutor(agent_name="test-agent")

        context = AbilityExecutionContext(
            current_ability_name="write_file",
            tool_args={"file_path": "/tmp/test.txt", "call_id": "call_789"},
            agent_state={},
            accumulated_data={},
        )

        hook_result = HookResult.hitl(
            message="Human approval required for write operation on: /tmp/test.txt",
        )

        # 在另一个任务中模拟外部审批
        async def approve_after_delay():
            await asyncio.sleep(0.1)
            executor.receive_hitl_response(
                ability_name="write_file",
                tool_call_id="call_789",
                approved=True,
            )

        asyncio.create_task(approve_after_delay())

        result = await executor.handle_hitl_hook_result(hook_result, context)
        assert result is True  # 审批通过

    @pytest.mark.asyncio
    async def test_handle_hitl_hook_result_with_rejection(self):
        """测试 HITL 审批拒绝流程。"""
        executor = LocalAbilityExecutor(agent_name="test-agent")

        context = AbilityExecutionContext(
            current_ability_name="write_file",
            tool_args={"file_path": "/tmp/test.txt", "call_id": "call_101"},
            agent_state={},
            accumulated_data={},
        )

        hook_result = HookResult.hitl(
            message="Human approval required for write operation on: /tmp/test.txt",
        )

        # 模拟拒绝
        async def reject_after_delay():
            await asyncio.sleep(0.1)
            executor.receive_hitl_response(
                ability_name="write_file",
                tool_call_id="call_101",
                approved=False,
            )

        asyncio.create_task(reject_after_delay())

        result = await executor.handle_hitl_hook_result(hook_result, context)
        assert result is False  # 审批拒绝

    @pytest.mark.asyncio
    async def test_handle_hitl_hook_result_timeout(self):
        """测试 HITL 审批超时。"""
        executor = LocalAbilityExecutor(agent_name="test-agent", hitl_timeout=0.1)

        context = AbilityExecutionContext(
            current_ability_name="write_file",
            tool_args={"file_path": "/tmp/test.txt"},
            agent_state={},
            accumulated_data={},
        )

        hook_result = HookResult.hitl(
            message="Human approval required for write operation on: /tmp/test.txt",
        )

        # 不 resolve Future，等待超时
        result = await executor.handle_hitl_hook_result(hook_result, context)
        assert result is False  # 超时

    def test_receive_hitl_response_no_pending_future(self):
        """测试没有等待中的 Future 时接收 HITL 响应。"""
        executor = LocalAbilityExecutor(agent_name="test-agent")

        # 没有创建 Future，直接调用 receive_hitl_response
        resolved = executor.receive_hitl_response(
            ability_name="write_file",
            tool_call_id="nonexistent",
            approved=True,
        )
        assert resolved is False  # 没有 pending Future

    @pytest.mark.asyncio
    async def test_hitl_request_event_published(self):
        """测试 HITL 请求事件被发布。"""
        mock_publisher = AsyncMock(spec=EventPublisher)
        executor = LocalAbilityExecutor(
            agent_name="test-agent",
            event_publisher=mock_publisher,
            hitl_timeout=0.1,
        )

        context = AbilityExecutionContext(
            current_ability_name="write_file",
            tool_args={"file_path": "/tmp/test.txt"},
            agent_state={},
            accumulated_data={},
        )

        hook_result = HookResult.hitl(
            message="Human approval required for write operation on: /tmp/test.txt",
        )

        # 触发 HITL 流程（会超时）
        await executor.handle_hitl_hook_result(hook_result, context)

        # 验证事件被发布
        mock_publisher.publish.assert_called_once()
        event = mock_publisher.publish.call_args[0][0]
        assert isinstance(event, HITLRequestEvent)
        assert event.agent_name == "test-agent"
        assert event.ability_name == "write_file"

    @pytest.mark.asyncio
    async def test_execute_ability_with_hitl_approval(self):
        """测试完整的 HITL 审批流程：Hook 拦截 → 等待审批 → 继续执行。"""
        ability = MockAbility()
        # 创建一个 HITL 拦截 Hook（requires_hitl=True）
        hitl_hook = HITLBlockingHook(message="Human approval required for write operation")
        executor = LocalAbilityExecutor(
            agent_name="test-agent",
            hooks=[hitl_hook],
            hitl_timeout=5.0,
        )

        context = AbilityExecutionContext(
            current_ability_name="mock_ability",
            tool_args={"call_id": "call_hitl_1"},
            agent_state={},
            accumulated_data={},
        )

        # 模拟外部审批通过
        async def approve():
            await asyncio.sleep(0.1)
            executor.receive_hitl_response(
                ability_name="mock_ability",
                tool_call_id="call_hitl_1",
                approved=True,
            )

        asyncio.create_task(approve())

        result = await executor.execute_ability(ability, context)
        # HITL 审批通过后，Ability 应该正常执行
        assert result.outcome == ActionOutcome.SUCCESS


# ─── 测试 AbilityExecutor 接口 ───


class TestAbilityExecutorInterface:
    """AbilityExecutor 抽象接口测试。"""

    def test_cannot_instantiate_abstract(self):
        """测试不能直接实例化抽象类。"""
        with pytest.raises(TypeError):
            AbilityExecutor()

    def test_local_ability_executor_is_ability_executor(self):
        """测试 LocalAbilityExecutor 是 AbilityExecutor 的子类。"""
        executor = LocalAbilityExecutor(agent_name="test-agent")
        assert isinstance(executor, AbilityExecutor)
