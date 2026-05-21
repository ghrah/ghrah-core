# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""RemoteAbilityExecutor 测试。

测试 RemoteAbilityExecutor 实现：
- execute_ability: 发送请求到 Subject 并等待结果
- execute_tool_calls: 并行发送多个 tool_calls
- run_hooks: 始终返回 None（Core 端不运行 Hook）
- handle_hitl_hook_result: 始终返回 True（HITL 在 Subject 端处理）
- resolve_ability_result: 遗留兼容接口，始终返回 False
- 超时和异常处理
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from ghrah.protocol.types import CommandType

from ghrah.abilities.base import Ability, ActionOutcome, ActionResult
from ghrah.abilities.context import AbilityExecutionContext
from ghrah.abilities.executor import RemoteAbilityExecutor
from ghrah.abilities.hooks import HookPoint, HookResult
from ghrah.chat.content import ToolCallBlock
from ghrah.core.command_sender import CommandSender

# ─── 测试用 Ability ───


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

    def get_hooks(self) -> list:
        return []


# ─── Fixtures ───


@pytest.fixture
def mock_command_sender():
    """创建 mock CommandSender。"""
    sender = AsyncMock(spec=CommandSender)
    sender.send_command = AsyncMock()
    return sender


@pytest.fixture
def remote_executor(mock_command_sender):
    """创建 RemoteAbilityExecutor 实例。"""
    return RemoteAbilityExecutor(
        command_sender=mock_command_sender,
        agent_name="test_agent",
        timeout=5.0,
    )


@pytest.fixture
def ability_context():
    """创建测试用 AbilityExecutionContext。"""
    return AbilityExecutionContext(
        current_ability_name="mock_ability",
        tool_args={"arg1": "value1"},
        agent_state={},
        context_manager=None,
        accumulated_data={"tool_args": {"arg1": "value1"}},
    )


# ─── execute_ability 测试 ───


class TestRemoteExecuteAbility:
    """RemoteAbilityExecutor.execute_ability 测试。"""

    @pytest.mark.asyncio
    async def test_execute_ability_success(
        self, remote_executor, mock_command_sender, ability_context
    ):
        """测试成功执行 Ability：send_ability_request 返回成功结果。"""
        ability = MockAbility()

        mock_command_sender.send_command.return_value = {
            "success": True,
            "data": {"result": "remote_ok"},
        }

        result = await remote_executor.execute_ability(ability, ability_context)

        assert result.outcome == ActionOutcome.SUCCESS
        assert result.data == {"result": "remote_ok"}
        mock_command_sender.send_command.assert_called_once()

        call_args = mock_command_sender.send_command.call_args
        assert call_args.args[0] == CommandType.EXECUTE_ABILITY.value
        assert call_args.args[1]["agent_name"] == "test_agent"
        assert call_args.args[1]["ability_name"] == "mock_ability"
        assert call_args.args[1]["tool_args"] == {"arg1": "value1"}

    @pytest.mark.asyncio
    async def test_execute_ability_failure_result(
        self, remote_executor, mock_command_sender, ability_context
    ):
        """测试 Subject 返回失败结果。"""
        ability = MockAbility()

        mock_command_sender.send_command.return_value = {
            "success": False,
            "error": "subject error",
        }

        result = await remote_executor.execute_ability(ability, ability_context)

        assert result.outcome == ActionOutcome.FAILURE
        assert result.data == {"error": "subject error"}

    @pytest.mark.asyncio
    async def test_execute_ability_timeout(
        self, remote_executor, mock_command_sender, ability_context
    ):
        """测试执行超时。"""
        ability = MockAbility()

        mock_command_sender.send_command.side_effect = TimeoutError("Request timed out")

        remote_executor._timeout = 0.1

        with pytest.raises(TimeoutError):
            await remote_executor.execute_ability(ability, ability_context)

    @pytest.mark.asyncio
    async def test_execute_ability_sends_correct_request(
        self, remote_executor, mock_command_sender, ability_context
    ):
        """测试发送的请求参数正确。"""
        ability = MockAbility(name="read_file")

        mock_command_sender.send_command.return_value = {
            "success": True,
            "data": {},
        }

        await remote_executor.execute_ability(ability, ability_context)

        call_args = mock_command_sender.send_command.call_args
        assert call_args.args[0] == CommandType.EXECUTE_ABILITY.value
        assert call_args.args[1]["ability_name"] == "read_file"
        assert call_args.args[1]["tool_args"] == {"arg1": "value1"}
        assert len(call_args.args[1]["request_id"]) > 0

    @pytest.mark.asyncio
    async def test_execute_ability_with_result_field(
        self, remote_executor, mock_command_sender, ability_context
    ):
        """测试 send_ability_request 返回 result 字段而非 data 字段。"""
        ability = MockAbility()

        mock_command_sender.send_command.return_value = {
            "success": True,
            "result": {"content": "via result field"},
        }

        result = await remote_executor.execute_ability(ability, ability_context)

        assert result.outcome == ActionOutcome.SUCCESS
        assert result.data == {"content": "via result field"}


# ─── execute_tool_calls 测试 ───


class TestRemoteExecuteToolCalls:
    """RemoteAbilityExecutor.execute_tool_calls 测试。"""

    @pytest.mark.asyncio
    async def test_execute_tool_calls_single(self, remote_executor, mock_command_sender):
        """测试执行单个 tool_call。"""
        ability = MockAbility(name="read_file")
        abilities = {"read_file": ability}
        tool_calls = [
            ToolCallBlock(name="read_file", arguments={"path": "/tmp/test.txt"}, id="call_1")
        ]

        mock_command_sender.send_command.return_value = {
            "success": True,
            "data": {"content": "file content"},
        }

        results = await remote_executor.execute_tool_calls(tool_calls, abilities, {}, None)

        assert len(results) == 1
        assert results[0]["ability_name"] == "read_file"
        assert results[0]["action_result"].outcome == ActionOutcome.SUCCESS
        assert results[0]["tool_call_id"] == "call_1"

    @pytest.mark.asyncio
    async def test_execute_tool_calls_multiple(self, remote_executor, mock_command_sender):
        """测试并行执行多个 tool_calls。"""
        ability1 = MockAbility(name="read_file")
        ability2 = MockAbility(name="write_file")
        abilities = {"read_file": ability1, "write_file": ability2}
        tool_calls = [
            ToolCallBlock(name="read_file", arguments={"path": "/tmp/a.txt"}, id="call_1"),
            ToolCallBlock(name="write_file", arguments={"path": "/tmp/b.txt"}, id="call_2"),
        ]

        mock_command_sender.send_command.return_value = {
            "success": True,
            "data": {"done": True},
        }

        results = await remote_executor.execute_tool_calls(tool_calls, abilities, {}, None)

        assert len(results) == 2
        assert all(r["action_result"].outcome == ActionOutcome.SUCCESS for r in results)

    @pytest.mark.asyncio
    async def test_execute_tool_calls_unknown_ability(self, remote_executor, mock_command_sender):
        """测试未知 ability 直接返回失败结果。"""
        abilities = {}
        tool_calls = [ToolCallBlock(name="unknown_ability", arguments={}, id="call_1")]

        results = await remote_executor.execute_tool_calls(tool_calls, abilities, {}, None)

        assert len(results) == 1
        assert results[0]["ability_name"] == "unknown_ability"
        assert results[0]["action_result"].outcome == ActionOutcome.FAILURE
        assert "Unknown ability" in results[0]["action_result"].data["error"]
        assert results[0]["tool_call_id"] == "call_1"

    @pytest.mark.asyncio
    async def test_execute_tool_calls_string_args(self, remote_executor, mock_command_sender):
        """测试 tool_call 中 arguments 为 dict 的正常情况。"""
        ability = MockAbility(name="read_file")
        abilities = {"read_file": ability}
        tool_calls = [
            ToolCallBlock(name="read_file", arguments={"path": "/tmp/test.txt"}, id="call_1"),
        ]

        mock_command_sender.send_command.return_value = {
            "success": True,
            "data": {},
        }

        results = await remote_executor.execute_tool_calls(tool_calls, abilities, {}, None)

        assert len(results) == 1
        assert results[0]["ability_name"] == "read_file"

    @pytest.mark.asyncio
    async def test_execute_tool_calls_failure_result(self, remote_executor, mock_command_sender):
        """测试 Subject 返回失败结果。"""
        ability = MockAbility(name="write_file")
        abilities = {"write_file": ability}
        tool_calls = [
            ToolCallBlock(name="write_file", arguments={"path": "/tmp/test.txt"}, id="call_1")
        ]

        mock_command_sender.send_command.return_value = {
            "success": False,
            "error": "Permission denied",
        }

        results = await remote_executor.execute_tool_calls(tool_calls, abilities, {}, None)

        assert len(results) == 1
        assert results[0]["action_result"].outcome == ActionOutcome.FAILURE

    @pytest.mark.asyncio
    async def test_execute_tool_calls_timeout(self, remote_executor, mock_command_sender):
        """测试 tool_call 执行超时返回失败结果。"""
        ability = MockAbility(name="slow_ability")
        abilities = {"slow_ability": ability}
        tool_calls = [ToolCallBlock(name="slow_ability", arguments={}, id="call_1")]

        mock_command_sender.send_command.side_effect = TimeoutError("Timed out")

        remote_executor._timeout = 0.1

        results = await remote_executor.execute_tool_calls(tool_calls, abilities, {}, None)

        assert len(results) == 1
        assert results[0]["action_result"].outcome == ActionOutcome.FAILURE
        assert "timed out" in results[0]["action_result"].data["error"].lower()


# ─── run_hooks 测试 ───


class TestRemoteRunHooks:
    """RemoteAbilityExecutor.run_hooks 测试。"""

    @pytest.mark.asyncio
    async def test_run_hooks_returns_none(self, remote_executor, ability_context):
        """测试分布式模式下 run_hooks 始终返回 None。"""
        result = await remote_executor.run_hooks(HookPoint.PRE_EXECUTE, ability_context)
        assert result is None

    @pytest.mark.asyncio
    async def test_run_hooks_post_execute_returns_none(self, remote_executor, ability_context):
        """测试 POST_EXECUTE Hook 也返回 None。"""
        action_result = ActionResult(outcome=ActionOutcome.SUCCESS, data={})
        result = await remote_executor.run_hooks(
            HookPoint.POST_EXECUTE, ability_context, action_result
        )
        assert result is None


# ─── handle_hitl_hook_result 测试 ───


class TestRemoteHandleHITLHookResult:
    """RemoteAbilityExecutor.handle_hitl_hook_result 测试。"""

    @pytest.mark.asyncio
    async def test_handle_hitl_returns_true(self, remote_executor, ability_context):
        """测试分布式模式下 HITL 处理始终返回 True。"""
        hook_result = HookResult.hitl(message="Human approval required")
        result = await remote_executor.handle_hitl_hook_result(hook_result, ability_context)
        assert result is True

    @pytest.mark.asyncio
    async def test_handle_hitl_blocking_returns_true(self, remote_executor, ability_context):
        """测试即使 Hook 拦截也返回 True（HITL 在 Subject 端处理）。"""
        hook_result = HookResult.stop(message="Blocked")
        result = await remote_executor.handle_hitl_hook_result(hook_result, ability_context)
        assert result is True


# ─── update_hooks / update_event_publisher 测试 ───


class TestRemoteNoOpMethods:
    """RemoteAbilityExecutor 空操作方法测试。"""

    def test_update_hooks_is_noop(self, remote_executor):
        """测试 update_hooks 为空操作。"""
        remote_executor.update_hooks([MagicMock()])
        # 不应抛出异常，也不应有任何效果

    def test_update_event_publisher_is_noop(self, remote_executor):
        """测试 update_event_publisher 为空操作。"""
        remote_executor.update_event_publisher(MagicMock())
        # 不应抛出异常

    def test_receive_hitl_response_returns_false(self, remote_executor):
        """测试 receive_hitl_response 始终返回 False。"""
        result = remote_executor.receive_hitl_response(
            ability_name="test_ability",
            tool_call_id="call_123",
            approved=True,
        )
        assert result is False


# ─── resolve_ability_result 测试（遗留兼容） ───


class TestResolveAbilityResult:
    """RemoteAbilityExecutor.resolve_ability_result 遗留兼容测试。"""

    def test_resolve_ability_result_returns_false(self, remote_executor):
        """测试 resolve_ability_result 始终返回 False。"""
        from ghrah.abilities.base import ActionResult

        result = remote_executor.resolve_ability_result(
            request_id="test_req",
            action_result=ActionResult(outcome=ActionOutcome.SUCCESS, data={}),
        )
        assert result is False
