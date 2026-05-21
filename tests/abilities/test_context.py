# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""AbilityExecutionContext 测试。

重构后 AbilityExecutionContext 只保留 Ability 执行所需的最少字段：
- current_ability_name: 当前 ability 名称
- tool_args: 工具调用参数
- agent_state: Agent 完整状态（只读视图）
- context_manager: ContextManager 引用
- accumulated_data: 兼容旧代码
- last_action_result: 兼容旧代码

驱动循环控制状态（iteration, max_iterations, should_continue, pending_route）
已迁移到 ContextManager，由 ContextManager 相关测试覆盖。
"""

from __future__ import annotations

from ghrah.abilities.base import ActionOutcome, ActionResult
from ghrah.abilities.context import AbilityExecutionContext


def _make_context(**overrides) -> AbilityExecutionContext:
    """创建测试用 AbilityExecutionContext。

    接受可选的 kwargs 覆盖默认值。
    """
    return AbilityExecutionContext(**overrides)


class TestAbilityExecutionContext:
    """AbilityExecutionContext 数据类测试。"""

    def test_default_values(self) -> None:
        ctx = _make_context()
        assert ctx.current_ability_name == ""
        assert ctx.tool_args == {}
        assert ctx.accumulated_data == {}
        assert ctx.last_action_result is None
        assert ctx.agent_state == {}
        assert ctx.context_manager is None
        assert ctx.current_node_id is None

    def test_custom_values(self) -> None:
        ctx = _make_context(
            current_ability_name="read_file",
            tool_args={"file_path": "/tmp/a.txt"},
        )
        assert ctx.current_ability_name == "read_file"
        assert ctx.tool_args == {"file_path": "/tmp/a.txt"}

    def test_accumulated_data_independent(self) -> None:
        """不同实例的 accumulated_data 是独立的。"""
        ctx1 = _make_context()
        ctx2 = _make_context()
        ctx1.accumulated_data["key"] = "value"
        assert "key" not in ctx2.accumulated_data

    def test_agent_state_independent(self) -> None:
        """不同实例的 agent_state 是独立的。"""
        ctx1 = _make_context()
        ctx2 = _make_context()
        ctx1.agent_state["status"] = "running"
        assert "status" not in ctx2.agent_state

    def test_last_action_result(self) -> None:
        result = ActionResult(
            outcome=ActionOutcome.SUCCESS,
            data={"content": "file content"},
        )
        ctx = _make_context()
        ctx.last_action_result = result
        assert ctx.last_action_result.outcome == ActionOutcome.SUCCESS
        assert ctx.last_action_result.data["content"] == "file content"

    def test_current_ability_name(self) -> None:
        ctx = _make_context()
        assert ctx.current_ability_name == ""
        ctx.current_ability_name = "read_file"
        assert ctx.current_ability_name == "read_file"

    def test_tool_args_default_empty(self) -> None:
        """tool_args 默认为空字典。"""
        ctx = _make_context()
        assert ctx.tool_args == {}

    def test_tool_args_custom(self) -> None:
        """tool_args 可自定义。"""
        ctx = _make_context(tool_args={"path": "/tmp/test.txt", "encoding": "utf-8"})
        assert ctx.tool_args["path"] == "/tmp/test.txt"
        assert ctx.tool_args["encoding"] == "utf-8"


class TestAbilityStateAPI:
    """测试 AbilityExecutionContext 上的状态 API 方法。"""

    def test_get_ability_state_no_name(self) -> None:
        """current_ability_name 为空时返回空字典。"""
        ctx = _make_context()
        assert ctx.get_ability_state() == {}

    def test_get_ability_state_returns_deepcopy(self) -> None:
        """get_ability_state 返回深拷贝，不影响原始状态。"""
        ctx = _make_context(
            current_ability_name="test_ability",
            agent_state={"test_ability": {"count": 0}},
        )
        state = ctx.get_ability_state()
        assert state == {"count": 0}

        # 修改返回值不影响原始
        state["count"] = 999
        assert ctx.agent_state["test_ability"]["count"] == 0

    def test_get_ability_state_missing_scope(self) -> None:
        """agent_state 中没有对应作用域时返回空字典。"""
        ctx = _make_context(
            current_ability_name="other_ability",
            agent_state={"test_ability": {"count": 0}},
        )
        assert ctx.get_ability_state() == {}
