# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""ConversationAbility：无 tool call 的最简对话能力。

- 这是「无 tool_call 的最简实例」
- 当 LLM 返回纯文本时，框架自动标记为使用了 conversation 能力
- execute() 方法不再调用 LLM（LLM 调用将在 Phase 1 移到 _drive_loop 的 action 层）
- 从 context.accumulated_data["llm_response"] 获取 LLM 已返回的纯文本响应

内置 Hook：
    ConversationDoneHook：POST_EXECUTE 触发，执行后终止循环。
    纯对话场景下 ConversationAbility 只需执行一次，无需继续循环。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from ghrah.abilities.base import Ability, ActionOutcome, ActionResult
from ghrah.abilities.hooks import Hook, HookPoint, HookResult

if TYPE_CHECKING:
    from ghrah.abilities.context import AbilityExecutionContext

logger = logging.getLogger(__name__)

__all__ = ["ConversationAbility", "ConversationDoneHook"]


class ConversationDoneHook(Hook):
    """ConversationAbility 执行完成后终止循环。

    纯对话 Ability 只需执行一次 LLM 调用即可，无需继续循环。
    AFTER_ACTION hook（drive_loop 级），
    这样可以在 _drive_loop 层面终止循环。
    """

    hook_point = HookPoint.AFTER_ACTION

    async def should_trigger(self, context: AbilityExecutionContext) -> bool:
        """只在当前 ability 是 conversation 且有 LLM 响应时触发。"""
        return context.current_ability_name == "conversation"

    async def execute(
        self, context: AbilityExecutionContext, result: ActionResult | None
    ) -> HookResult:
        """终止循环。"""
        return HookResult.stop()


class ConversationAbility(Ability):
    """对话能力 — 无 tool call，纯文本响应。

    - bind_tool() 返回 None（不注册 function calling schema）
    - execute() 不再调用 LLM，从 context.accumulated_data["llm_response"] 获取 LLM 响应
    - 内置 ConversationDoneHook：AFTER_ACTION 终止循环（drive_loop 级）

    用法::

        ability = ConversationAbility()
        agent.register_ability(ability)
    """

    def __init__(self, hooks: list[Hook] | None = None) -> None:
        self._hooks: list[Hook] = [ConversationDoneHook()]
        if hooks:
            self._hooks.extend(hooks)

    @property
    def name(self) -> str:
        return "conversation"

    def bind_tool(self) -> dict[str, Any] | None:
        """纯对话能力不需要 tool binding。"""
        return None

    def to_prompt_description(self) -> str:
        return "Direct conversation with the LLM without tool usage"

    def get_hooks(self) -> list[Hook]:
        return list(self._hooks)

    async def execute(self, context: AbilityExecutionContext) -> ActionResult:
        """执行对话响应处理。

        从 context.accumulated_data["llm_response"] 获取 LLM 已经返回的纯文本响应，
        包装为 ActionResult 返回。如果不存在这个 key，返回一个空的 SUCCESS result。


        Args:
            context: 执行上下文

        Returns:
            ActionResult，data 中包含 "response" 字段
        """
        response = context.accumulated_data.get("llm_response", "")

        if response:
            logger.debug(f"ConversationAbility: got LLM response ({len(response)} chars)")
            return ActionResult(
                outcome=ActionOutcome.SUCCESS,
                data={"response": response},
                next_action_hint=None,  # 对话完成，无需继续循环
            )

        logger.debug(
            "ConversationAbility: no llm_response in accumulated_data, returning empty success"
        )
        return ActionResult(
            outcome=ActionOutcome.SUCCESS,
            data={},
            next_action_hint=None,
        )
