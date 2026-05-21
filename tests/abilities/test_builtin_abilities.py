# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""内置 Ability 实现测试：ConversationAbility, EndTaskAbility, ReadFileAbility。"""

from __future__ import annotations

import os
import tempfile
from typing import Any
from unittest.mock import MagicMock

import pytest

from ghrah.abilities.base import ActionOutcome, ActionResult
from ghrah.abilities.builtin.conversation import ConversationAbility
from ghrah.abilities.builtin.end_task import EndTaskAbility
from ghrah.abilities.builtin.read_file import ReadFileAbility, ReadFileInput
from ghrah.abilities.context import AbilityExecutionContext
from ghrah.abilities.hooks import Hook

# ── 辅助 ──


def _make_context(
    **overrides: Any,
) -> AbilityExecutionContext:
    """创建测试用 AbilityExecutionContext。"""
    defaults: dict[str, Any] = {}
    defaults.update(overrides)
    return AbilityExecutionContext(**defaults)


# ── ConversationAbility 测试 ──


class TestConversationAbility:
    """ConversationAbility 测试。

    概念修正后，ConversationAbility 不再调用 LLM，
    而是从 context.accumulated_data["llm_response"] 获取 LLM 响应。
    """

    def test_name(self) -> None:
        ability = ConversationAbility()
        assert ability.name == "conversation"

    def test_bind_tool_returns_none(self) -> None:
        """纯对话能力不需要 tool binding。"""
        ability = ConversationAbility()
        assert ability.bind_tool() is None

    def test_to_prompt_description(self) -> None:
        ability = ConversationAbility()
        desc = ability.to_prompt_description()
        assert isinstance(desc, str)
        assert len(desc) > 0

    def test_get_hooks_default_has_done_hook(self) -> None:
        """默认内置 ConversationDoneHook。"""
        from ghrah.abilities.builtin.conversation import ConversationDoneHook

        ability = ConversationAbility()
        hooks = ability.get_hooks()
        assert len(hooks) == 1
        assert isinstance(hooks[0], ConversationDoneHook)

    def test_get_hooks_with_hooks(self) -> None:
        hook = MagicMock(spec=Hook)
        ability = ConversationAbility(hooks=[hook])
        hooks = ability.get_hooks()
        # 内置 ConversationDoneHook + 用户传入的 hook
        assert len(hooks) == 2

    async def test_execute_with_llm_response(self) -> None:
        """从 accumulated_data["llm_response"] 获取 LLM 响应。"""
        ctx = _make_context(accumulated_data={"llm_response": "Hello! How can I help you?"})
        ability = ConversationAbility()
        result = await ability.execute(ctx)

        assert result.outcome == ActionOutcome.SUCCESS
        assert result.data["response"] == "Hello! How can I help you?"
        assert result.next_action_hint is None

    async def test_execute_without_llm_response(self) -> None:
        """没有 llm_response 时返回空的 SUCCESS result。"""
        ctx = _make_context()
        ability = ConversationAbility()
        result = await ability.execute(ctx)

        assert result.outcome == ActionOutcome.SUCCESS
        assert result.data == {}
        assert result.next_action_hint is None

    async def test_execute_with_empty_llm_response(self) -> None:
        """空字符串的 llm_response 也返回空的 SUCCESS result。"""
        ctx = _make_context(accumulated_data={"llm_response": ""})
        ability = ConversationAbility()
        result = await ability.execute(ctx)

        assert result.outcome == ActionOutcome.SUCCESS
        assert result.data == {}


# ── EndTaskAbility 测试 ──


class TestEndTaskAbility:
    """EndTaskAbility 测试。"""

    def test_name(self) -> None:
        ability = EndTaskAbility()
        assert ability.name == "end_task"

    def test_bind_tool_returns_none_by_default(self) -> None:
        """默认 auto 模式不暴露给 LLM。"""
        ability = EndTaskAbility()
        assert ability.bind_tool() is None

    def test_bind_tool_returns_schema_in_toolcall_mode(self) -> None:
        """toolcall 模式返回 function calling schema。"""
        ability = EndTaskAbility(mode="toolcall")
        schema = ability.bind_tool()
        assert schema is not None
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "end_task"

    def test_mode_property(self) -> None:
        """mode 属性正确返回。"""
        auto = EndTaskAbility()
        assert auto.mode == "auto"

        toolcall = EndTaskAbility(mode="toolcall")
        assert toolcall.mode == "toolcall"

        verified = EndTaskAbility(mode="verified")
        assert verified.mode == "verified"

    def test_invalid_mode_raises(self) -> None:
        """无效的 mode 抛出 ValueError。"""
        with pytest.raises(ValueError, match="Invalid mode"):
            EndTaskAbility(mode="invalid")

    def test_to_prompt_description(self) -> None:
        ability = EndTaskAbility()
        desc = ability.to_prompt_description()
        assert isinstance(desc, str)
        assert "End" in desc or "end" in desc

    def test_get_hooks_default_empty(self) -> None:
        ability = EndTaskAbility()
        assert ability.get_hooks() == []

    async def test_execute_with_last_action_result_response(self) -> None:
        """优先使用 last_action_result 中的 response。"""
        ctx = _make_context(
            last_action_result=ActionResult(
                outcome=ActionOutcome.SUCCESS,
                data={"response": "Here is the answer"},
            ),
        )
        ability = EndTaskAbility()
        result = await ability.execute(ctx)

        assert result.outcome == ActionOutcome.SUCCESS
        assert result.data["response"] == "Here is the answer"
        assert result.next_action_hint is None

    async def test_execute_with_last_action_result_content(self) -> None:
        """使用 last_action_result 中的 content。"""
        ctx = _make_context(
            last_action_result=ActionResult(
                outcome=ActionOutcome.SUCCESS,
                data={"content": "file content here"},
            ),
        )
        ability = EndTaskAbility()
        result = await ability.execute(ctx)

        assert result.outcome == ActionOutcome.SUCCESS
        assert result.data["response"] == "file content here"

    async def test_execute_with_accumulated_data(self) -> None:
        """从 accumulated_data 中提取 response。"""
        ctx = _make_context(
            accumulated_data={"response": "accumulated response"},
        )
        ability = EndTaskAbility()
        result = await ability.execute(ctx)

        assert result.outcome == ActionOutcome.SUCCESS
        assert result.data["response"] == "accumulated response"

    async def test_execute_default_response(self) -> None:
        """没有数据时返回默认回复。"""
        ctx = _make_context()
        ability = EndTaskAbility()
        result = await ability.execute(ctx)

        assert result.outcome == ActionOutcome.SUCCESS
        assert result.data["response"] == "Task completed"

    async def test_execute_priority_response_over_content(self) -> None:
        """response 优先于 content。"""
        ctx = _make_context(
            last_action_result=ActionResult(
                outcome=ActionOutcome.SUCCESS,
                data={
                    "response": "priority response",
                    "content": "secondary content",
                },
            ),
        )
        ability = EndTaskAbility()
        result = await ability.execute(ctx)

        assert result.data["response"] == "priority response"

    async def test_execute_priority_last_action_over_accumulated(self) -> None:
        """last_action_result 优先于 accumulated_data。"""
        ctx = _make_context(
            last_action_result=ActionResult(
                outcome=ActionOutcome.SUCCESS,
                data={"response": "from last action"},
            ),
            accumulated_data={"response": "from accumulated"},
        )
        ability = EndTaskAbility()
        result = await ability.execute(ctx)

        assert result.data["response"] == "from last action"


# ── ReadFileAbility 测试 ──


class TestReadFileAbility:
    """ReadFileAbility 测试。"""

    def test_name(self) -> None:
        ability = ReadFileAbility()
        assert ability.name == "read_file"

    def test_bind_tool_returns_schema(self) -> None:
        """返回 OpenAI function calling 格式的 schema。"""
        ability = ReadFileAbility()
        schema = ability.bind_tool()

        assert schema is not None
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "read_file"
        assert "description" in schema["function"]
        assert "parameters" in schema["function"]

    def test_bind_tool_schema_has_file_path(self) -> None:
        """schema 包含 file_path 参数。"""
        ability = ReadFileAbility()
        schema = ability.bind_tool()

        params = schema["function"]["parameters"]
        assert "file_path" in params.get("properties", {})

    def test_to_prompt_description(self) -> None:
        ability = ReadFileAbility()
        desc = ability.to_prompt_description()
        assert "read_file" in desc
        assert "file_path" in desc

    def test_get_hooks_default_empty(self) -> None:
        ability = ReadFileAbility()
        assert ability.get_hooks() == []

    async def test_execute_read_file_success(self) -> None:
        """成功读取文件。"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("Hello, World!")
            temp_path = f.name

        try:
            ctx = _make_context(
                accumulated_data={"tool_args": {"file_path": temp_path}},
            )
            ability = ReadFileAbility()
            result = await ability.execute(ctx)

            assert result.outcome == ActionOutcome.SUCCESS
            assert result.data["content"] == "Hello, World!"
            assert result.data["file_path"] == temp_path
        finally:
            os.unlink(temp_path)

    async def test_execute_read_file_with_encoding(self) -> None:
        """使用指定编码读取文件。"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", encoding="utf-8", delete=False
        ) as f:
            f.write("你好世界")
            temp_path = f.name

        try:
            ctx = _make_context(
                accumulated_data={
                    "tool_args": {
                        "file_path": temp_path,
                        "encoding": "utf-8",
                    },
                },
            )
            ability = ReadFileAbility()
            result = await ability.execute(ctx)

            assert result.outcome == ActionOutcome.SUCCESS
            assert result.data["content"] == "你好世界"
        finally:
            os.unlink(temp_path)

    async def test_execute_file_not_found(self) -> None:
        """文件不存在时返回 FAILURE。"""
        ctx = _make_context(
            accumulated_data={
                "tool_args": {"file_path": "/nonexistent/file.txt"},
            },
        )
        ability = ReadFileAbility()
        result = await ability.execute(ctx)

        assert result.outcome == ActionOutcome.FAILURE
        assert (
            "not found" in result.data["error"].lower() or "File not found" in result.data["error"]
        )

    async def test_execute_no_file_path(self) -> None:
        """没有 file_path 参数时返回 FAILURE。"""
        ctx = _make_context(
            accumulated_data={"tool_args": {}},
        )
        ability = ReadFileAbility()
        result = await ability.execute(ctx)

        assert result.outcome == ActionOutcome.FAILURE
        assert "file_path" in result.data["error"]

    async def test_execute_no_tool_args(self) -> None:
        """没有 tool_args 时返回 FAILURE。"""
        ctx = _make_context()
        ability = ReadFileAbility()
        result = await ability.execute(ctx)

        assert result.outcome == ActionOutcome.FAILURE
        assert "file_path" in result.data["error"]

    async def test_execute_allowed_paths_granted(self) -> None:
        """文件路径在 allowed_paths 内，允许读取。"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("allowed content")
            temp_path = f.name

        try:
            # 使用文件所在目录作为 allowed_path
            allowed_dir = os.path.dirname(temp_path)
            ctx = _make_context(
                accumulated_data={"tool_args": {"file_path": temp_path}},
            )
            ability = ReadFileAbility(allowed_paths=[allowed_dir])
            result = await ability.execute(ctx)

            assert result.outcome == ActionOutcome.SUCCESS
            assert result.data["content"] == "allowed content"
        finally:
            os.unlink(temp_path)

    async def test_execute_allowed_paths_denied(self) -> None:
        """文件路径不在 allowed_paths 内，拒绝读取。"""
        ctx = _make_context(
            accumulated_data={"tool_args": {"file_path": "/etc/passwd"}},
        )
        ability = ReadFileAbility(allowed_paths=["/tmp/data", "/home/user/docs"])
        result = await ability.execute(ctx)

        assert result.outcome == ActionOutcome.FAILURE
        assert "Permission denied" in result.data["error"]
        assert "/etc/passwd" in result.data["error"]

    async def test_execute_allowed_paths_none_allows_all(self) -> None:
        """allowed_paths 为 None 时，不做权限检查。"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("no restriction")
            temp_path = f.name

        try:
            ctx = _make_context(
                accumulated_data={"tool_args": {"file_path": temp_path}},
            )
            ability = ReadFileAbility(allowed_paths=None)
            result = await ability.execute(ctx)

            assert result.outcome == ActionOutcome.SUCCESS
            assert result.data["content"] == "no restriction"
        finally:
            os.unlink(temp_path)

    async def test_execute_allowed_paths_multiple(self) -> None:
        """多个 allowed_paths，匹配任一即可。"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("multi path")
            temp_path = f.name

        try:
            allowed_dir = os.path.dirname(temp_path)
            ctx = _make_context(
                accumulated_data={"tool_args": {"file_path": temp_path}},
            )
            ability = ReadFileAbility(allowed_paths=["/nonexistent", allowed_dir])
            result = await ability.execute(ctx)

            assert result.outcome == ActionOutcome.SUCCESS
            assert result.data["content"] == "multi path"
        finally:
            os.unlink(temp_path)


# ── ReadFileInput 测试 ──


class TestReadFileInput:
    """ReadFileInput pydantic model 测试。"""

    def test_default_encoding(self) -> None:
        inp = ReadFileInput(file_path="/tmp/test.txt")
        assert inp.encoding == "utf-8"

    def test_custom_encoding(self) -> None:
        inp = ReadFileInput(file_path="/tmp/test.txt", encoding="latin-1")
        assert inp.encoding == "latin-1"

    def test_json_schema(self) -> None:
        schema = ReadFileInput.model_json_schema()
        assert "file_path" in schema.get("properties", {})
        assert "encoding" in schema.get("properties", {})
