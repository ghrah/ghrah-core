# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""Hook 机制：Ability 级别的控制流。

Hook 在 Agent 执行循环中的特定触发点执行，用于：
- 条件转移（类似 LangGraph 的路由，但无需图引擎）
- 拦截和修改执行流程（HITL、权限校验等）
- 错误恢复和迭代控制

三层 Hook 架构：
    drive_loop 级（_drive_loop 中触发）:
        BEFORE_ACTION → AFTER_ACTION → ON_ERROR → ON_MAX_ITERATIONS
    action 级（_action 中触发）:
        PRE_LLM_CALL → POST_LLM_CALL → PRE_TOOL_EXECUTE → POST_TOOL_EXECUTE
    ability 级（ability.execute() 前后触发）:
        PRE_EXECUTE → POST_EXECUTE
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ghrah.abilities.base import ActionResult
    from ghrah.abilities.context import AbilityExecutionContext

__all__ = [
    "HookPoint",
    "HookResult",
    "Hook",
]


class HookPoint(str, Enum):
    """Hook 触发点 — 三层架构。

    drive_loop 级（_drive_loop 中触发）:
        BEFORE_ACTION — action 执行前
        AFTER_ACTION — action 执行后
        ON_ERROR — 错误处理
        ON_MAX_ITERATIONS — 达到最大迭代

    action 级（_action 中触发）:
        PRE_LLM_CALL — LLM 调用前
        POST_LLM_CALL — LLM 调用后
        PRE_TOOL_EXECUTE — 工具执行前
        POST_TOOL_EXECUTE — 工具执行后

    ability 级（ability.execute() 前后触发）:
        PRE_EXECUTE — ability 执行前（HITL 批准等）
        POST_EXECUTE — ability 执行后（副作用触发等）
    """

    # drive_loop 级
    BEFORE_ACTION = "before_action"
    AFTER_ACTION = "after_action"
    ON_ERROR = "on_error"
    ON_MAX_ITERATIONS = "on_max_iterations"

    # action 级
    PRE_LLM_CALL = "pre_llm_call"
    POST_LLM_CALL = "post_llm_call"
    PRE_TOOL_EXECUTE = "pre_tool_execute"
    POST_TOOL_EXECUTE = "post_tool_execute"

    # ability 级
    PRE_EXECUTE = "pre_execute"
    POST_EXECUTE = "post_execute"


@dataclass
class HookResult:
    """Hook 返回结果。

    Attributes:
        should_continue: 是否继续当前循环（PRE_EXECUTE 中设为 False 可拦截执行）
        route_to: 路由到其他 ability 名称（如 "end_task"），实现条件转移
        modified_context: Hook 修改的上下文数据，将合并到 AbilityExecutionContext.accumulated_data
        message: 附加信息（如 HITL 提示、错误消息等）
        requires_hitl: 是否需要 HITL 审批（should_continue=False 时，
            requires_hitl=True 表示需要等待人工审批，requires_hitl=False 表示直接拦截）
    """

    should_continue: bool = True
    route_to: str | None = None
    modified_context: dict[str, Any] | None = None
    message: str | None = None
    requires_hitl: bool = False

    @classmethod
    def continue_(cls) -> HookResult:
        """创建一个"继续执行"的结果。"""
        return cls(should_continue=True)

    @classmethod
    def stop(cls, *, message: str | None = None) -> HookResult:
        """创建一个"停止循环"的结果。"""
        return cls(should_continue=False, message=message)

    @classmethod
    def hitl(cls, *, message: str | None = None) -> HookResult:
        """创建一个"需要 HITL 审批"的结果。

        与 stop() 不同，hitl() 表示执行被拦截但需要等待人工审批后才能决定是否继续。
        """
        return cls(should_continue=False, requires_hitl=True, message=message)

    @classmethod
    def route(cls, target: str, *, message: str | None = None) -> HookResult:
        """创建一个"路由到其他 ability"的结果。"""
        return cls(should_continue=True, route_to=target, message=message)

    def merge(self, other: HookResult) -> HookResult:
        """合并两个 HookResult，other 的非默认值覆盖 self。

        合并规则：
        - should_continue: AND 逻辑（任一为 False 则为 False）
        - route_to: other 优先（后者覆盖前者）
        - modified_context: 合并 dict（other 覆盖同名 key）
        - message: other 优先
        - requires_hitl: OR 逻辑（任一需要 HITL 则需要 HITL）
        """
        return HookResult(
            should_continue=self.should_continue and other.should_continue,
            route_to=other.route_to if other.route_to is not None else self.route_to,
            modified_context={
                **(self.modified_context or {}),
                **(other.modified_context or {}),
            }
            if self.modified_context or other.modified_context
            else None,
            message=other.message if other.message is not None else self.message,
            requires_hitl=self.requires_hitl or other.requires_hitl,
        )


class Hook(ABC):
    """Hook 基类：定义在特定触发点执行的控制逻辑。

    子类必须实现：
    - hook_point: 触发点
    - should_trigger(): 判断是否应触发
    - execute(): 执行 Hook 逻辑

    用法示例：
        class MyHook(Hook):
            hook_point = HookPoint.PRE_EXECUTE

            async def should_trigger(self, context):
                return context.current_ability_name == "dangerous_action"

            async def execute(self, context, result):
                return HookResult.stop(message="Blocked!")
    """

    hook_point: HookPoint

    @abstractmethod
    async def should_trigger(self, context: AbilityExecutionContext) -> bool:
        """判断是否应触发此 Hook。

        Args:
            context: 当前执行上下文

        Returns:
            True 表示触发，False 表示跳过
        """
        ...

    @abstractmethod
    async def execute(
        self, context: AbilityExecutionContext, result: ActionResult | None
    ) -> HookResult:
        """执行 Hook 逻辑，返回控制指令。

        Args:
            context: 当前执行上下文
            result: 触发点的结果（PRE_EXECUTE 时为 None，POST_EXECUTE 时为 ActionResult）

        Returns:
            HookResult 控制指令
        """
        ...
