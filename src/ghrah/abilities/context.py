# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""AbilityExecutionContext：Ability 执行所需的最小上下文。

重构后的设计原则：只包含 Ability 执行所需的信息，不混入驱动循环控制状态。
驱动循环的控制状态（iteration, max_iterations, should_continue 等）由 ContextManager 管理。
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ghrah.abilities.base import ActionResult
    from ghrah.context.manager import ContextManager

__all__ = ["AbilityExecutionContext"]


@dataclass
class AbilityExecutionContext:
    """Ability 执行所需的最小上下文。

    在 Agent 驱动循环中为每个 Ability 创建，提供执行所需的信息和状态 API。

    Attributes:
        current_ability_name: 当前 ability 名称，用于状态作用域隔离
        tool_args: 工具调用参数（从 LLM tool call 解析）
        agent_state: Agent 完整状态的只读视图
        context_manager: ContextManager 引用（用于状态回写）
        current_node_id: 当前链节点 ID
    """

    # Ability 身份
    current_ability_name: str = ""

    # 工具参数（从 tool call 解析）
    tool_args: dict[str, Any] = field(default_factory=dict)

    # Agent 状态引用（只读完整视图）
    agent_state: dict[str, Any] = field(default_factory=dict)

    # ContextManager 集成
    context_manager: ContextManager | None = None
    current_node_id: str | None = None

    # 集群通信支持
    supervisor: Any = None
    agent_name: str = ""

    # ---- 兼容旧代码的临时属性 ----
    # Hook 和内置 Ability 可能通过这些属性读取数据
    accumulated_data: dict[str, Any] = field(default_factory=dict)
    last_action_result: ActionResult | None = None

    # ---- 状态 API ----

    def get_ability_state(self) -> dict[str, Any]:
        """获取当前 ability 作用域的状态（只读快照）。

        从 agent_state 中按 current_ability_name 提取对应作用域。
        """
        if not self.current_ability_name:
            return {}
        return copy.deepcopy(self.agent_state.get(self.current_ability_name, {}))

    def update_state(self, changes: dict[str, Any]) -> None:
        """更新当前 ability 作用域的状态。

        变更通过 ContextManager 写入事务的 pending 区，
        commit_iteration 时才真正生效。

        Args:
            changes: 要应用的状态变更（支持嵌套 dict 递归合并）
        """
        if self.context_manager is None:
            raise RuntimeError(
                "Cannot update state: context_manager is not set. "
                "This context may have been created outside the drive loop."
            )
        scoped_changes = {self.current_ability_name: changes}
        self.context_manager.apply_state_changes(scoped_changes)
        # 同时更新本地 agent_state 视图
        if self.current_ability_name in self.agent_state:
            self._merge_dict(self.agent_state[self.current_ability_name], changes)
        else:
            self.agent_state[self.current_ability_name] = copy.deepcopy(changes)

    def update_global_state(self, changes: dict[str, Any]) -> None:
        """更新全局状态（非作用域）。

        仅限 Agent 级别的代码使用，Ability 不应调用此方法。
        """
        if self.context_manager is None:
            raise RuntimeError("Cannot update state: context_manager is not set.")
        self.context_manager.apply_state_changes(changes)
        self._merge_dict(self.agent_state, changes)

    @staticmethod
    def _merge_dict(base: dict, override: dict) -> None:
        """就地递归合并 override 到 base。"""
        for key, value in override.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                AbilityExecutionContext._merge_dict(base[key], value)
            else:
                base[key] = value
