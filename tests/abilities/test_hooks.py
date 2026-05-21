# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""Hook 基类、HookPoint 和 HookResult 测试。"""

from __future__ import annotations

import pytest

from ghrah.abilities.base import ActionResult
from ghrah.abilities.context import AbilityExecutionContext
from ghrah.abilities.hooks import Hook, HookPoint, HookResult

# ── 辅助：用于测试的具体 Hook 子类 ──


class StubHook(Hook):
    """测试用 Stub Hook"""

    hook_point = HookPoint.PRE_EXECUTE

    def __init__(
        self,
        should_trigger: bool = True,
        result: HookResult | None = None,
    ) -> None:
        self._should_trigger = should_trigger
        self._result = result or HookResult.continue_()

    async def should_trigger(self, context: AbilityExecutionContext) -> bool:
        return self._should_trigger

    async def execute(
        self, context: AbilityExecutionContext, result: ActionResult | None
    ) -> HookResult:
        return self._result


# ── 测试：HookPoint ──


class TestHookPoint:
    """HookPoint 枚举测试"""

    def test_all_hook_points_exist(self) -> None:
        """验证三层架构的 10 个 HookPoint 都存在"""
        # drive_loop 级
        assert HookPoint.BEFORE_ACTION == "before_action"
        assert HookPoint.AFTER_ACTION == "after_action"
        assert HookPoint.ON_ERROR == "on_error"
        assert HookPoint.ON_MAX_ITERATIONS == "on_max_iterations"
        # action 级
        assert HookPoint.PRE_LLM_CALL == "pre_llm_call"
        assert HookPoint.POST_LLM_CALL == "post_llm_call"
        assert HookPoint.PRE_TOOL_EXECUTE == "pre_tool_execute"
        assert HookPoint.POST_TOOL_EXECUTE == "post_tool_execute"
        # ability 级
        assert HookPoint.PRE_EXECUTE == "pre_execute"
        assert HookPoint.POST_EXECUTE == "post_execute"

    def test_hook_point_count(self) -> None:
        """恰好 10 个 HookPoint"""
        assert len(HookPoint) == 10

    def test_hook_point_is_str(self) -> None:
        """HookPoint 继承 str，可用于字符串比较"""
        assert isinstance(HookPoint.PRE_EXECUTE, str)

    def test_hook_point_ordering(self) -> None:
        """HookPoint 按三层架构排列"""
        points = list(HookPoint)
        # drive_loop 级
        assert points[0] == HookPoint.BEFORE_ACTION
        assert points[1] == HookPoint.AFTER_ACTION
        assert points[2] == HookPoint.ON_ERROR
        assert points[3] == HookPoint.ON_MAX_ITERATIONS
        # action 级
        assert points[4] == HookPoint.PRE_LLM_CALL
        assert points[5] == HookPoint.POST_LLM_CALL
        assert points[6] == HookPoint.PRE_TOOL_EXECUTE
        assert points[7] == HookPoint.POST_TOOL_EXECUTE
        # ability 级
        assert points[8] == HookPoint.PRE_EXECUTE
        assert points[9] == HookPoint.POST_EXECUTE


# ── 测试：HookResult ──


class TestHookResult:
    """HookResult 数据类测试"""

    def test_default_values(self) -> None:
        result = HookResult()
        assert result.should_continue is True
        assert result.route_to is None
        assert result.modified_context is None
        assert result.message is None
        assert result.requires_hitl is False

    def test_continue_factory(self) -> None:
        result = HookResult.continue_()
        assert result.should_continue is True
        assert result.route_to is None

    def test_stop_factory(self) -> None:
        result = HookResult.stop(message="Blocked")
        assert result.should_continue is False
        assert result.message == "Blocked"
        assert result.route_to is None

    def test_stop_factory_without_message(self) -> None:
        result = HookResult.stop()
        assert result.should_continue is False
        assert result.message is None
        assert result.requires_hitl is False

    def test_hitl_factory(self) -> None:
        result = HookResult.hitl(message="Human approval required")
        assert result.should_continue is False
        assert result.requires_hitl is True
        assert result.message == "Human approval required"

    def test_hitl_factory_without_message(self) -> None:
        result = HookResult.hitl()
        assert result.should_continue is False
        assert result.requires_hitl is True
        assert result.message is None

    def test_route_factory(self) -> None:
        result = HookResult.route("end_task", message="Max iterations")
        assert result.should_continue is True
        assert result.route_to == "end_task"
        assert result.message == "Max iterations"

    def test_route_factory_without_message(self) -> None:
        result = HookResult.route("other_ability")
        assert result.route_to == "other_ability"
        assert result.message is None

    def test_merge_both_continue(self) -> None:
        """两个 continue 的 merge 仍为 continue"""
        a = HookResult.continue_()
        b = HookResult.continue_()
        merged = a.merge(b)
        assert merged.should_continue is True
        assert merged.route_to is None

    def test_merge_one_stops(self) -> None:
        """AND 逻辑：任一 stop 则 stop"""
        a = HookResult.continue_()
        b = HookResult.stop()
        merged = a.merge(b)
        assert merged.should_continue is False

    def test_merge_route_to_override(self) -> None:
        """后者的 route_to 覆盖前者"""
        a = HookResult.route("ability_a")
        b = HookResult.route("ability_b")
        merged = a.merge(b)
        assert merged.route_to == "ability_b"

    def test_merge_route_to_first_wins_if_second_none(self) -> None:
        """后者没有 route_to 时保留前者"""
        a = HookResult.route("ability_a")
        b = HookResult.continue_()
        merged = a.merge(b)
        assert merged.route_to == "ability_a"

    def test_merge_context_combined(self) -> None:
        """modified_context 合并"""
        a = HookResult(should_continue=True, modified_context={"key1": "val1"})
        b = HookResult(should_continue=True, modified_context={"key2": "val2"})
        merged = a.merge(b)
        assert merged.modified_context == {"key1": "val1", "key2": "val2"}

    def test_merge_context_override(self) -> None:
        """后者覆盖同名 key"""
        a = HookResult(should_continue=True, modified_context={"key": "old"})
        b = HookResult(should_continue=True, modified_context={"key": "new"})
        merged = a.merge(b)
        assert merged.modified_context == {"key": "new"}

    def test_merge_message_override(self) -> None:
        """后者的 message 覆盖前者"""
        a = HookResult(should_continue=True, message="first")
        b = HookResult(should_continue=True, message="second")
        merged = a.merge(b)
        assert merged.message == "second"

    def test_merge_message_keeps_first_if_second_none(self) -> None:
        """后者没有 message 时保留前者"""
        a = HookResult(should_continue=True, message="first")
        b = HookResult(should_continue=True)
        merged = a.merge(b)
        assert merged.message == "first"

    def test_merge_none_contexts(self) -> None:
        """两者都没有 modified_context 时结果为 None"""
        a = HookResult.continue_()
        b = HookResult.continue_()
        merged = a.merge(b)
        assert merged.modified_context is None

    def test_merge_requires_hitl_or_logic(self) -> None:
        """requires_hitl: OR 逻辑（任一需要 HITL 则需要 HITL）"""
        a = HookResult.stop(message="blocked")
        b = HookResult.hitl(message="approval needed")
        merged = a.merge(b)
        assert merged.requires_hitl is True

    def test_merge_requires_hitl_both_false(self) -> None:
        """两个都不需要 HITL 时合并后也不需要"""
        a = HookResult.stop(message="blocked")
        b = HookResult.stop(message="also blocked")
        merged = a.merge(b)
        assert merged.requires_hitl is False

    def test_merge_requires_hitl_both_true(self) -> None:
        """两个都需要 HITL 时合并后也需要"""
        a = HookResult.hitl(message="approval 1")
        b = HookResult.hitl(message="approval 2")
        merged = a.merge(b)
        assert merged.requires_hitl is True


# ── 测试：Hook ABC ──


class TestHookABC:
    """Hook 抽象基类测试"""

    def test_cannot_instantiate_directly(self) -> None:
        """Hook 是 ABC，不能直接实例化"""
        with pytest.raises(TypeError):
            Hook()  # type: ignore[abstract]

    def test_stub_hook_point(self) -> None:
        hook = StubHook()
        assert hook.hook_point == HookPoint.PRE_EXECUTE

    async def test_stub_hook_should_trigger_true(self) -> None:
        hook = StubHook(should_trigger=True)
        ctx = self._make_context()
        assert await hook.should_trigger(ctx) is True

    async def test_stub_hook_should_trigger_false(self) -> None:
        hook = StubHook(should_trigger=False)
        ctx = self._make_context()
        assert await hook.should_trigger(ctx) is False

    async def test_stub_hook_execute(self) -> None:
        hook = StubHook(result=HookResult.stop(message="blocked"))
        ctx = self._make_context()
        result = await hook.execute(ctx, None)
        assert result.should_continue is False
        assert result.message == "blocked"

    # ── 辅助 ──

    def _make_context(self) -> AbilityExecutionContext:
        return AbilityExecutionContext()
