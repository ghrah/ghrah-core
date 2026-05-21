# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""Ability 基类：Agent 能力的接口契约（= Rust Trait）。

核心设计：
- 一个 Ability = 一个 tool call（或无 tool call 的纯 LLM 调用）
- Ability 是最小的能力单元，Agent 通过组合多个 Ability 获得完整行为
- bind_tool() 提供原生 Function Calling 绑定（高优先级）
- to_prompt_description() 提供 prompt 模式的描述（低优先级，兼容不支持 FC 的模型）
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ghrah.abilities.context import AbilityExecutionContext
    from ghrah.abilities.hooks import Hook

__all__ = [
    "ActionOutcome",
    "ActionResult",
    "Ability",
]


class ActionOutcome(str, Enum):
    """Action 执行结果类型。"""

    SUCCESS = "success"
    FAILURE = "failure"
    NEEDS_INPUT = "needs_input"  # 需要人工输入（HITL）
    DELEGATE = "delegate"  # 需要委托给其他 Agent


@dataclass
class ActionResult:
    """Action 执行结果。

    Attributes:
        outcome: 执行结果类型
        data: 结果数据（如工具返回的内容、错误信息等）
        next_action_hint: 建议的下一个 action 名称，为 None 表示任务完成
    """

    outcome: ActionOutcome
    data: dict[str, Any] = field(default_factory=dict)
    next_action_hint: str | None = None


class Ability(ABC):
    """能力基类（= Rust Trait）。

    定义 Agent 能力的接口契约。不同的 Agent 可以对同类型 Ability 有不同的 impl。

    子类必须实现：
    - name: 能力名称（唯一标识）
    - execute(): 执行该能力的动作
    - get_hooks(): 返回该能力注册的所有 hooks

    可选覆盖：
    - bind_tool(): 返回原生 Function Calling 的 tool schema
    - to_prompt_description(): 返回 LLM 可理解的能力描述(TODO)
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """能力名称（唯一标识）。"""
        ...

    @abstractmethod
    async def execute(self, context: AbilityExecutionContext) -> ActionResult:
        """执行该能力的动作。

        Args:
            context: 执行上下文（含消息历史、当前状态、LLM 客户端等）

        Returns:
            执行结果
        """
        ...

    @abstractmethod
    def get_hooks(self) -> list[Hook]:
        """返回该能力注册的所有 hooks。"""
        ...

    def bind_tool(self) -> dict[str, Any] | None:
        """绑定原生 Function Calling 的 tool schema（高优先级）。

        返回 OpenAI function calling 格式的 tool definition，
        或 None 表示该 Ability 没有对应的 tool call。

        优先使用此方法进行 tool 绑定，现代 LLM 基本都支持 function calling。

        Returns:
            OpenAI function calling tool schema dict，或 None
        """
        return None

    def to_prompt_description(self) -> str:
        """转换为 LLM 可理解的能力描述
        TODO:
        用于不支持 function calling 的模型的 system prompt 注入
        (目前已经没有新的模型不支持原生工具调用了）
        如 ReAct 模式下的工具描述。

        Returns:
            工具描述文本
        """
        return ""

    def get_default_state(self) -> dict[str, Any]:
        """返回该 ability 的默认状态（用于初始化作用域）。

        子类可选覆盖。返回的字典将成为该 ability 在 StateManager 中的初始状态。
        """
        return {}
