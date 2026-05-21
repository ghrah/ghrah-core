# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""ExecuteCommandAbility 测试：命令执行能力。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from ghrah.abilities.base import ActionOutcome
from ghrah.abilities.builtin.execute_command import (
    CommandResult,
    ExecuteCommandAbility,
    ExecuteCommandInput,
)
from ghrah.abilities.context import AbilityExecutionContext


def _make_context(**overrides: Any) -> AbilityExecutionContext:
    defaults: dict[str, Any] = {}
    defaults.update(overrides)
    return AbilityExecutionContext(**defaults)


# ── ExecuteCommandInput 测试 ──


class TestExecuteCommandInput:
    def test_schema_has_required_fields(self) -> None:
        schema = ExecuteCommandInput.model_json_schema()
        assert "command" in schema["properties"]
        assert "working_dir" in schema["properties"]
        assert "command" in schema.get("required", [])


# ── ExecuteCommandAbility.bind_tool 测试 ──


class TestBindTool:
    def test_bind_tool_returns_valid_schema(self) -> None:
        ability = ExecuteCommandAbility()
        schema = ability.bind_tool()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "execute_command"
        assert "parameters" in schema["function"]

    def test_name_property(self) -> None:
        ability = ExecuteCommandAbility()
        assert ability.name == "execute_command"

    def test_to_prompt_description(self) -> None:
        ability = ExecuteCommandAbility()
        desc = ability.to_prompt_description()
        assert "execute_command" in desc
        assert "command" in desc


# ── ExecuteCommandAbility.execute 测试（单体模式 subprocess） ──


class TestExecuteSubprocess:
    @pytest.mark.asyncio
    async def test_echo_hello(self) -> None:
        ability = ExecuteCommandAbility()
        context = _make_context(
            current_ability_name="execute_command",
            tool_args={"command": "echo hello"},
        )
        result = await ability.execute(context)
        assert result.outcome == ActionOutcome.SUCCESS
        assert "hello" in result.data["stdout"]
        assert result.data["exit_code"] == 0

    @pytest.mark.asyncio
    async def test_command_failure(self) -> None:
        ability = ExecuteCommandAbility()
        context = _make_context(
            current_ability_name="execute_command",
            tool_args={"command": "false"},
        )
        result = await ability.execute(context)
        assert result.outcome == ActionOutcome.FAILURE
        assert result.data["exit_code"] != 0

    @pytest.mark.asyncio
    async def test_command_with_working_dir(self, tmp_path: Any) -> None:
        ability = ExecuteCommandAbility()
        context = _make_context(
            current_ability_name="execute_command",
            tool_args={"command": "pwd", "working_dir": str(tmp_path)},
        )
        result = await ability.execute(context)
        assert result.outcome == ActionOutcome.SUCCESS
        assert str(tmp_path) in result.data["stdout"]

    @pytest.mark.asyncio
    async def test_empty_command_returns_failure(self) -> None:
        ability = ExecuteCommandAbility()
        context = _make_context(
            current_ability_name="execute_command",
            tool_args={"command": ""},
        )
        result = await ability.execute(context)
        assert result.outcome == ActionOutcome.FAILURE
        assert "command is required" in result.data["error"]

    @pytest.mark.asyncio
    async def test_missing_command_returns_failure(self) -> None:
        ability = ExecuteCommandAbility()
        context = _make_context(
            current_ability_name="execute_command",
            tool_args={},
        )
        result = await ability.execute(context)
        assert result.outcome == ActionOutcome.FAILURE

    @pytest.mark.asyncio
    async def test_dangerous_command_blocked_inline(self) -> None:
        ability = ExecuteCommandAbility()
        context = _make_context(
            current_ability_name="execute_command",
            tool_args={"command": "rm -rf /"},
        )
        result = await ability.execute(context)
        assert result.outcome == ActionOutcome.FAILURE
        assert "Dangerous command" in result.data["error"]

    @pytest.mark.asyncio
    async def test_dangerous_command_sudo_blocked(self) -> None:
        ability = ExecuteCommandAbility()
        context = _make_context(
            current_ability_name="execute_command",
            tool_args={"command": "sudo apt install foo"},
        )
        result = await ability.execute(context)
        assert result.outcome == ActionOutcome.FAILURE


# ── ExecuteCommandAbility.execute 测试（CommandRunner 委托模式） ──


@dataclass
class MockCommandRunnerResult:
    exit_code: int = 0
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False


class MockCommandRunner:
    """Mock CommandRunner for testing."""

    def __init__(self, results: dict[str, MockCommandRunnerResult] | None = None) -> None:
        self._results = results or {}
        self.calls: list[dict[str, Any]] = []

    async def execute_command(
        self,
        command: list[str],
        cwd: str | None = None,
        timeout: float | None = None,
        env: dict[str, str] | None = None,
        stdin_data: str | None = None,
    ) -> CommandResult:
        self.calls.append({
            "command": command,
            "cwd": cwd,
            "timeout": timeout,
        })
        cmd_str = " ".join(command)
        if cmd_str in self._results:
            r = self._results[cmd_str]
            return CommandResult(
                exit_code=r.exit_code,
                stdout=r.stdout,
                stderr=r.stderr,
                timed_out=r.timed_out,
                command=cmd_str,
                working_dir=cwd or "",
            )
        return CommandResult(
            exit_code=0,
            stdout="mock output",
            stderr="",
            command=cmd_str,
            working_dir=cwd or "",
        )


class TestExecuteViaRunner:
    @pytest.mark.asyncio
    async def test_delegates_to_runner(self) -> None:
        runner = MockCommandRunner()
        ability = ExecuteCommandAbility(command_runner=runner)
        context = _make_context(
            current_ability_name="execute_command",
            tool_args={"command": "ls -la"},
        )
        result = await ability.execute(context)
        assert result.outcome == ActionOutcome.SUCCESS
        assert result.data["stdout"] == "mock output"
        assert len(runner.calls) == 1
        assert runner.calls[0]["command"] == ["ls", "-la"]

    @pytest.mark.asyncio
    async def test_runner_with_working_dir(self) -> None:
        runner = MockCommandRunner()
        ability = ExecuteCommandAbility(command_runner=runner)
        context = _make_context(
            current_ability_name="execute_command",
            tool_args={"command": "ls", "working_dir": "/tmp"},
        )
        result = await ability.execute(context)
        assert result.outcome == ActionOutcome.SUCCESS
        assert runner.calls[0]["cwd"] == "/tmp"

    @pytest.mark.asyncio
    async def test_runner_failure_result(self) -> None:
        runner = MockCommandRunner(results={
            "false": MockCommandRunnerResult(exit_code=1, stderr="error"),
        })
        ability = ExecuteCommandAbility(command_runner=runner)
        context = _make_context(
            current_ability_name="execute_command",
            tool_args={"command": "false"},
        )
        result = await ability.execute(context)
        assert result.outcome == ActionOutcome.FAILURE
        assert result.data["exit_code"] == 1

    @pytest.mark.asyncio
    async def test_runner_timeout_result(self) -> None:
        runner = MockCommandRunner(results={
            "sleep 10": MockCommandRunnerResult(timed_out=True, stderr="Timed out"),
        })
        ability = ExecuteCommandAbility(command_runner=runner)
        context = _make_context(
            current_ability_name="execute_command",
            tool_args={"command": "sleep 10"},
        )
        result = await ability.execute(context)
        assert result.outcome == ActionOutcome.FAILURE
        assert result.data["timed_out"] is True

    @pytest.mark.asyncio
    async def test_runner_exception_handled(self) -> None:
        class FailingRunner:
            async def execute_command(self, **kwargs: Any) -> CommandResult:
                raise RuntimeError("runner crashed")

        ability = ExecuteCommandAbility(command_runner=FailingRunner())
        context = _make_context(
            current_ability_name="execute_command",
            tool_args={"command": "ls"},
        )
        result = await ability.execute(context)
        assert result.outcome == ActionOutcome.FAILURE
        assert "runner crashed" in result.data["error"]

    @pytest.mark.asyncio
    async def test_invalid_command_syntax_handled(self) -> None:
        runner = MockCommandRunner()
        ability = ExecuteCommandAbility(command_runner=runner)
        context = _make_context(
            current_ability_name="execute_command",
            tool_args={"command": "echo 'unterminated string"},
        )
        result = await ability.execute(context)
        assert result.outcome == ActionOutcome.FAILURE
        assert "Failed to parse command" in result.data["error"]


# ── CommandResult 测试 ──


class TestCommandResult:
    def test_success_property(self) -> None:
        result = CommandResult(exit_code=0, stdout="ok", stderr="")
        assert result.success is True

    def test_failure_exit_code(self) -> None:
        result = CommandResult(exit_code=1, stdout="", stderr="error")
        assert result.success is False

    def test_failure_timeout(self) -> None:
        result = CommandResult(exit_code=0, stdout="", stderr="", timed_out=True)
        assert result.success is False
