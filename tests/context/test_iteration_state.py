# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""IterationState 单元测试。

独立测试 IterationState，不依赖 ContextManager。
"""

from __future__ import annotations

from ghrah.abilities.base import ActionOutcome, ActionResult
from ghrah.context import IterationState


class TestIterationStateDefaults:
    """默认值测试。"""

    def test_defaults(self) -> None:
        """默认值正确。"""
        state = IterationState()
        assert state.iteration == 0
        assert state.max_iterations == 10
        assert state.last_action_result is None
        assert state.pending_route is None

    def test_custom_max_iterations(self) -> None:
        """自定义 max_iterations。"""
        state = IterationState(max_iterations=5)
        assert state.max_iterations == 5
        assert state.is_unlimited is False


class TestIterationStateIsUnlimited:
    """is_unlimited 测试。"""

    def test_negative_means_unlimited(self) -> None:
        """max_iterations < 0 代表无上限。"""
        state = IterationState(max_iterations=-1)
        assert state.is_unlimited is True

    def test_zero_not_unlimited(self) -> None:
        """max_iterations=0 不是无上限。"""
        state = IterationState(max_iterations=0)
        assert state.is_unlimited is False


class TestIterationStateShouldContinue:
    """should_continue 测试。"""

    def test_unlimited_always_continues(self) -> None:
        """无上限时始终应该继续。"""
        state = IterationState(max_iterations=-1)
        state.iteration = 1000
        assert state.should_continue is True

    def test_below_max(self) -> None:
        """iteration < max_iterations 时应继续。"""
        state = IterationState(max_iterations=3)
        state.iteration = 0
        assert state.should_continue is True
        state.iteration = 1
        assert state.should_continue is True
        state.iteration = 2
        assert state.should_continue is True

    def test_reaches_max(self) -> None:
        """iteration == max_iterations 时不应继续。"""
        state = IterationState(max_iterations=3)
        state.iteration = 3
        assert state.should_continue is False

    def test_exceeds_max(self) -> None:
        """iteration > max_iterations 时不应继续。"""
        state = IterationState(max_iterations=3)
        state.iteration = 5
        assert state.should_continue is False


class TestIterationStateAdvance:
    """advance() 测试。"""

    def test_advance_increments(self) -> None:
        """advance() 推进迭代计数。"""
        state = IterationState()
        assert state.iteration == 0
        state.advance()
        assert state.iteration == 1
        state.advance()
        assert state.iteration == 2

    def test_advance_multiple_times(self) -> None:
        """多次 advance 累加。"""
        state = IterationState(max_iterations=10)
        for _ in range(5):
            state.advance()
        assert state.iteration == 5


class TestIterationStateReset:
    """reset() 测试。"""

    def test_reset_zeroes_iteration(self) -> None:
        """reset() 清零迭代计数。"""
        state = IterationState()
        state.advance()
        state.advance()
        assert state.iteration == 2
        state.reset()
        assert state.iteration == 0

    def test_reset_clears_last_action_result(self) -> None:
        """reset() 清空 last_action_result。"""
        state = IterationState()
        state.last_action_result = ActionResult(
            outcome=ActionOutcome.SUCCESS,
            data={"response": "ok"},
        )
        state.reset()
        assert state.last_action_result is None

    def test_reset_clears_pending_route(self) -> None:
        """reset() 清空 pending_route。"""
        state = IterationState()
        state.pending_route = "step2"
        state.reset()
        assert state.pending_route is None

    def test_reset_preserves_max_iterations(self) -> None:
        """reset() 不影响 max_iterations。"""
        state = IterationState(max_iterations=42)
        state.advance()
        state.reset()
        assert state.max_iterations == 42


class TestIterationStateLastActionResult:
    """last_action_result 测试。"""

    def test_set_and_get(self) -> None:
        """设置和读取 last_action_result。"""
        state = IterationState()
        ar = ActionResult(
            outcome=ActionOutcome.SUCCESS,
            data={"response": "hello"},
        )
        state.last_action_result = ar
        assert state.last_action_result is ar
        assert state.last_action_result.data == {"response": "hello"}

    def test_set_none(self) -> None:
        """显式设置为 None。"""
        state = IterationState()
        state.last_action_result = None
        assert state.last_action_result is None


class TestIterationStateLoopSimulation:
    """模拟驱动循环的集成测试。"""

    def test_full_loop_lifecycle(self) -> None:
        """完整的循环生命周期。"""
        state = IterationState(max_iterations=3)
        state.reset()

        # 第 1 次迭代
        assert state.should_continue is True
        state.last_action_result = ActionResult(
            outcome=ActionOutcome.SUCCESS, data={"step": 1}
        )
        state.advance()

        # 第 2 次迭代
        assert state.should_continue is True
        state.last_action_result = ActionResult(
            outcome=ActionOutcome.SUCCESS, data={"step": 2}
        )
        state.advance()

        # 第 3 次迭代
        assert state.should_continue is True
        state.last_action_result = ActionResult(
            outcome=ActionOutcome.SUCCESS, data={"step": 3}
        )
        state.advance()

        # 第 4 次迭代 — 应该停止
        assert state.should_continue is False
        assert state.iteration == 3

    def test_unlimited_loop_with_hook_stop(self) -> None:
        """无上限循环，由 hook 控制（这里模拟计数达到 10 时停止）。"""
        state = IterationState(max_iterations=-1)
        state.reset()

        assert state.is_unlimited is True

        count = 0
        while state.should_continue and count < 10:
            state.advance()
            count += 1

        # 循环在 count=10 时由外部条件停止
        assert count == 10
        assert state.should_continue is True  # 仍然可以继续
