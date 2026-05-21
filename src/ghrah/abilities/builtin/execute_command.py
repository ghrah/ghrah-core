# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""ExecuteCommandAbility：命令执行能力。

功能：
- 执行 shell 命令并返回输出
- 支持 SAFE/DANGEROUS/REQUIRE_HITL 三级命令安全分类
- 双模式执行：单体模式（subprocess）和 Subject 模式（SandboxExecutor）

执行模式：
1. 单体模式（command_runner=None）：asyncio.create_subprocess_shell
2. Subject 模式（command_runner=SandboxExecutor）：委托给 command_runner

安全检查：
- inline 硬拒绝：CommandSafetyChecker.category == DANGEROUS → FAILURE
- Hook 层 HITL：CommandApprovalHook 提供 PRE_EXECUTE 拦截
- Subject 端 PermissionChecker 再检查一次
"""

from __future__ import annotations

import asyncio
import logging
import shlex
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from pydantic import BaseModel

from ghrah.abilities.base import Ability, ActionOutcome, ActionResult
from ghrah.abilities.builtin.command_safety import (
    CommandSafetyCategory,
    CommandSafetyChecker,
)

if TYPE_CHECKING:
    from ghrah.abilities.context import AbilityExecutionContext
    from ghrah.abilities.hooks import Hook

logger = logging.getLogger(__name__)

__all__ = [
    "ExecuteCommandAbility",
    "ExecuteCommandInput",
    "CommandResult",
    "CommandRunner",
]

_MAX_OUTPUT_BYTES = 1_000_000


class ExecuteCommandInput(BaseModel):
    command: str
    working_dir: str | None = None


@dataclass
class CommandResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False
    command: str = ""
    working_dir: str = ""

    @property
    def success(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


@runtime_checkable
class CommandRunner(Protocol):
    async def execute_command(
        self,
        command: list[str],
        cwd: str | None = None,
        timeout: float | None = None,
        env: dict[str, str] | None = None,
        stdin_data: str | None = None,
    ) -> CommandResult: ...


class ExecuteCommandAbility(Ability):
    """命令执行能力 — 支持单体和 Subject 双模式。

    用法::

        # 单体模式（本地执行）
        ability = ExecuteCommandAbility()

        # 带命令安全检查
        checker = CommandSafetyChecker()
        hook = CommandApprovalHook(checker)
        ability = ExecuteCommandAbility(command_checker=checker, hooks=[hook])

        # Subject 模式（委托 SandboxExecutor）
        ability = ExecuteCommandAbility(command_runner=sandbox_executor)
    """

    def __init__(
        self,
        hooks: list[Hook] | None = None,
        command_checker: CommandSafetyChecker | None = None,
        command_runner: CommandRunner | None = None,
        timeout: float = 300.0,
    ) -> None:
        self._hooks = hooks or []
        self._checker = command_checker or CommandSafetyChecker()
        self._command_runner = command_runner
        self._timeout = timeout

    @property
    def name(self) -> str:
        return "execute_command"

    def bind_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "execute_command",
                "description": (
                    "Execute a shell command and return its output. "
                    "Use for running tests, linters, build commands, and other development tasks. "
                    "Read-only commands are auto-approved. Dangerous commands are blocked. "
                    "Other commands require human approval."
                ),
                "parameters": ExecuteCommandInput.model_json_schema(),
            },
        }

    def to_prompt_description(self) -> str:
        return (
            "execute_command(command: str, working_dir: str | None = None) -> dict: "
            "Execute a shell command and return exit_code, stdout, stderr"
        )

    def get_hooks(self) -> list[Hook]:
        return list(self._hooks)

    async def execute(self, context: AbilityExecutionContext) -> ActionResult:
        tool_args = context.tool_args or context.accumulated_data.get("tool_args", {})
        command = tool_args.get("command", "")
        working_dir = tool_args.get("working_dir")

        if not command:
            return ActionResult(
                outcome=ActionOutcome.FAILURE,
                data={"error": "command is required"},
            )

        verdict = self._checker.check_command(command)
        if verdict.category == CommandSafetyCategory.DANGEROUS:
            return ActionResult(
                outcome=ActionOutcome.FAILURE,
                data={"error": verdict.reason, "command": command},
            )

        if self._command_runner is not None:
            return await self._execute_via_runner(command, working_dir)
        return await self._execute_subprocess(command, working_dir)

    async def _execute_via_runner(
        self, command: str, working_dir: str | None
    ) -> ActionResult:
        try:
            args = shlex.split(command)
        except ValueError as e:
            return ActionResult(
                outcome=ActionOutcome.FAILURE,
                data={"error": f"Failed to parse command: {e}", "command": command},
            )

        try:
            runner = self._command_runner
            assert runner is not None
            result = await runner.execute_command(
                command=args,
                cwd=working_dir,
                timeout=self._timeout,
            )
        except Exception as e:
            return ActionResult(
                outcome=ActionOutcome.FAILURE,
                data={"error": str(e), "command": command},
            )

        return ActionResult(
            outcome=ActionOutcome.SUCCESS if result.success else ActionOutcome.FAILURE,
            data={
                "exit_code": result.exit_code,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "timed_out": result.timed_out,
                "command": command,
                "working_dir": working_dir or "",
            },
        )

    async def _execute_subprocess(
        self, command: str, working_dir: str | None
    ) -> ActionResult:
        try:
            process = await asyncio.create_subprocess_shell(
                command,
                cwd=working_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(),
                timeout=self._timeout,
            )
            timed_out = False
        except TimeoutError:
            if process.returncode is None:
                process.kill()
                await process.wait()
            timed_out = True
            stdout_bytes = b""
            stderr_bytes = f"Command timed out after {self._timeout}s".encode()
        except Exception as e:
            return ActionResult(
                outcome=ActionOutcome.FAILURE,
                data={"error": str(e), "command": command},
            )

        stdout = self._truncate_output(stdout_bytes)
        stderr = self._truncate_output(stderr_bytes)

        exit_code = process.returncode if process.returncode is not None else -1

        data: dict[str, Any] = {
            "exit_code": exit_code,
            "stdout": stdout,
            "stderr": stderr,
            "timed_out": timed_out,
            "command": command,
            "working_dir": working_dir or "",
        }

        success = exit_code == 0 and not timed_out
        return ActionResult(
            outcome=ActionOutcome.SUCCESS if success else ActionOutcome.FAILURE,
            data=data,
        )

    @staticmethod
    def _truncate_output(data: bytes) -> str:
        try:
            text = data.decode("utf-8", errors="replace")
        except Exception:
            text = str(data)
        if len(data) > _MAX_OUTPUT_BYTES:
            return text[:_MAX_OUTPUT_BYTES] + f"\n[truncated at {_MAX_OUTPUT_BYTES} bytes]"
        return text
