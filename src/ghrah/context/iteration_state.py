# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""IterationState：ActorAgent 驱动循环的迭代控制状态。

将驱动循环控制状态（iteration/max_iterations/last_action_result/pending_route）
从 ContextManager 中提取，归 ActorAgent（驱动者）所有。

这解决了 ContextManager 职责过载问题——ContextManager 只管上下文数据
（消息/状态/链/会话），循环控制状态由驱动者持有。

注：pending_route 当前为死状态（仅写入无读取），保留待路由功能启用。
"""

from __future__ import annotations

import dataclasses

from ghrah.types.results import ActionResult

__all__ = ["IterationState"]


@dataclasses.dataclass
class IterationState:
    """ActorAgent 驱动循环的迭代控制状态。

    持有循环执行所需的全部控制状态：
    - iteration: 当前迭代计数（0-indexed）
    - max_iterations: 最大迭代次数（-1 代表无上限）
    - last_action_result: 上一次 action 的结果
    - pending_route: Hook 设置的路由目标（当前为死状态，仅写入无读取）

    用法:
        state = IterationState()
        state.max_iterations = 5
        state.reset()
        while state.should_continue:
            ...
            state.advance()
    """

    iteration: int = 0
    max_iterations: int = 10
    last_action_result: ActionResult | None = None
    pending_route: str | None = None

    @property
    def is_unlimited(self) -> bool:
        """是否无上限迭代。"""
        return self.max_iterations < 0

    @property
    def should_continue(self) -> bool:
        """是否应该继续循环。"""
        return self.is_unlimited or self.iteration < self.max_iterations

    def advance(self) -> None:
        """推进迭代计数。"""
        self.iteration += 1

    def reset(self) -> None:
        """重置迭代控制状态。

        清零迭代计数、清空 last_action_result 和 pending_route。
        max_iterations 不受影响（需在调用前显式设置）。
        """
        self.iteration = 0
        self.last_action_result = None
        self.pending_route = None
