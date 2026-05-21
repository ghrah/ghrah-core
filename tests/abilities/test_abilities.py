# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""Ability 基类和核心数据结构测试。"""

from __future__ import annotations

from typing import Any

import pytest

from ghrah.abilities.base import Ability, ActionOutcome, ActionResult
from ghrah.abilities.context import AbilityExecutionContext
from ghrah.abilities.hooks import Hook, HookPoint, HookResult

# ── 辅助：用于测试的具体 Ability 子类 ──


class StubAbility(Ability):
    """测试用 Stub Ability"""

    def __init__(
        self,
        name: str = "stub",
        hooks: list[Hook] | None = None,
        tool_schema: dict[str, Any] | None = None,
        prompt_desc: str = "",
        execute_result: ActionResult | None = None,
    ) -> None:
        self._name = name
        self._hooks = hooks or []
        self._tool_schema = tool_schema
        self._prompt_desc = prompt_desc
        self._execute_result = execute_result or ActionResult(outcome=ActionOutcome.SUCCESS)

    @property
    def name(self) -> str:
        return self._name

    async def execute(self, context: AbilityExecutionContext) -> ActionResult:
        return self._execute_result

    def get_hooks(self) -> list[Hook]:
        return self._hooks

    def bind_tool(self) -> dict[str, Any] | None:
        return self._tool_schema

    def to_prompt_description(self) -> str:
        return self._prompt_desc


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


# ── 测试：ActionOutcome ──


class TestActionOutcome:
    """ActionOutcome 枚举测试"""

    def test_outcome_values(self) -> None:
        assert ActionOutcome.SUCCESS == "success"
        assert ActionOutcome.FAILURE == "failure"
        assert ActionOutcome.NEEDS_INPUT == "needs_input"
        assert ActionOutcome.DELEGATE == "delegate"

    def test_outcome_is_str(self) -> None:
        """ActionOutcome 继承 str，可直接用于字符串比较"""
        outcome = ActionOutcome.SUCCESS
        assert isinstance(outcome, str)
        assert outcome == "success"


# ── 测试：ActionResult ──


class TestActionResult:
    """ActionResult 数据类测试"""

    def test_default_values(self) -> None:
        result = ActionResult(outcome=ActionOutcome.SUCCESS)
        assert result.outcome == ActionOutcome.SUCCESS
        assert result.data == {}
        assert result.next_action_hint is None

    def test_with_data(self) -> None:
        result = ActionResult(
            outcome=ActionOutcome.SUCCESS,
            data={"content": "hello", "path": "/tmp/file.txt"},
        )
        assert result.data["content"] == "hello"
        assert result.data["path"] == "/tmp/file.txt"

    def test_with_hint(self) -> None:
        result = ActionResult(
            outcome=ActionOutcome.SUCCESS,
            next_action_hint="read_file",
        )
        assert result.next_action_hint == "read_file"

    def test_failure_result(self) -> None:
        result = ActionResult(
            outcome=ActionOutcome.FAILURE,
            data={"error": "File not found"},
        )
        assert result.outcome == ActionOutcome.FAILURE
        assert "error" in result.data


# ── 测试：Ability ABC ──


class TestAbilityABC:
    """Ability 抽象基类测试"""

    def test_cannot_instantiate_directly(self) -> None:
        """Ability 是 ABC，不能直接实例化"""
        with pytest.raises(TypeError):
            Ability()  # type: ignore[abstract]

    def test_stub_ability_name(self) -> None:
        ability = StubAbility(name="test_ability")
        assert ability.name == "test_ability"

    async def test_stub_ability_execute(self) -> None:
        ability = StubAbility()
        ctx = self._make_context()
        result = await ability.execute(ctx)
        assert result.outcome == ActionOutcome.SUCCESS

    def test_default_bind_tool_returns_none(self) -> None:
        """默认 bind_tool 应返回 None"""
        ability = StubAbility()  # 不传 tool_schema，使用父类默认实现
        # StubAbility 覆盖了 bind_tool，但父类的默认行为是返回 None
        assert ability.bind_tool() is None

    def test_default_to_prompt_returns_empty(self) -> None:
        """默认 to_prompt_description 应返回空字符串"""
        ability = StubAbility()
        assert ability.to_prompt_description() == ""

    def test_bind_tool_with_schema(self) -> None:
        tool_schema = {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read a file",
                "parameters": {"type": "object", "properties": {}},
            },
        }
        ability = StubAbility(tool_schema=tool_schema)
        result = ability.bind_tool()
        assert result is not None
        assert result["function"]["name"] == "read_file"

    def test_to_prompt_with_description(self) -> None:
        ability = StubAbility(prompt_desc="read_file(path) -> str")
        assert ability.to_prompt_description() == "read_file(path) -> str"

    def test_get_hooks_default_empty(self) -> None:
        ability = StubAbility()
        assert ability.get_hooks() == []

    def test_get_hooks_with_hooks(self) -> None:
        hook = StubHook()
        ability = StubAbility(hooks=[hook])
        assert len(ability.get_hooks()) == 1
        assert ability.get_hooks()[0] is hook

    async def test_ability_execute_custom_result(self) -> None:
        custom_result = ActionResult(
            outcome=ActionOutcome.FAILURE,
            data={"error": "timeout"},
            next_action_hint="retry",
        )
        ability = StubAbility(execute_result=custom_result)
        ctx = self._make_context()
        result = await ability.execute(ctx)
        assert result.outcome == ActionOutcome.FAILURE
        assert result.data["error"] == "timeout"
        assert result.next_action_hint == "retry"

    # ── 辅助 ──

    def _make_context(self) -> AbilityExecutionContext:
        return AbilityExecutionContext()
