# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""命令安全检查模块：分类和审批逻辑。

提供：
- CommandSafetyCategory: 命令安全分类枚举（SAFE / DANGEROUS / REQUIRE_HITL）
- CommandSafetyVerdict: 分类裁定结果
- CommandSafetyChecker: 命令安全分类器（含子命令路由）
- CommandApprovalHook: PRE_EXECUTE Hook，拦截 execute_command Ability

分类模型：
- SAFE: 只读命令，自动通过（ls, cat, git status 等）
- DANGEROUS: 不可逆破坏命令，自动拒绝（rm, chmod, kill 等）
- REQUIRE_HITL: 有副作用但不一定危险的命令，需人工审批（curl, git commit 等）

多面性命令（git, npm, pip 等）支持子命令级分类：
- git status → SAFE
- git clean → DANGEROUS
- git commit → REQUIRE_HITL
"""

from __future__ import annotations

import logging
import shlex
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from ghrah.abilities.hooks import Hook, HookPoint, HookResult

if TYPE_CHECKING:
    from ghrah.abilities.base import ActionResult
    from ghrah.abilities.context import AbilityExecutionContext

logger = logging.getLogger(__name__)

__all__ = [
    "CommandSafetyCategory",
    "CommandSafetyVerdict",
    "CommandSafetyChecker",
    "CommandApprovalHook",
    "DEFAULT_SAFE_COMMANDS",
    "DEFAULT_DANGEROUS_COMMANDS",
    "DEFAULT_SAFE_SUB_COMMANDS",
    "DEFAULT_DANGEROUS_SUB_COMMANDS",
]


class CommandSafetyCategory(StrEnum):
    SAFE = "safe"
    DANGEROUS = "dangerous"
    REQUIRE_HITL = "require_hitl"


@dataclass
class CommandSafetyVerdict:
    category: CommandSafetyCategory
    base_command: str
    sub_command: str | None = None
    reason: str = ""


DEFAULT_SAFE_COMMANDS: set[str] = {
    "cat", "head", "tail", "less", "more", "file", "stat", "wc",
    "ls", "find", "tree", "pwd", "du", "df",
    "grep", "egrep", "fgrep", "sort", "uniq", "cut", "paste",
    "tr", "diff", "comm", "tee",
    "uname", "hostname", "whoami", "id", "date", "uptime",
    "which", "whereis", "type",
    "ps", "jobs",
    "pytest", "ruff", "mypy", "eslint", "tsc",
    "echo", "true", "false", "test", "env", "printenv", "seq",
    "dirname", "basename", "realpath", "readlink", "xargs",
}

DEFAULT_DANGEROUS_COMMANDS: set[str] = {
    "rm", "rmdir", "chmod", "chown", "chgrp",
    "mkfs", "dd", "format", "fdisk", "parted",
    "shutdown", "reboot", "halt", "poweroff",
    "kill", "killall", "pkill",
    "useradd", "userdel", "usermod", "groupadd", "groupdel", "passwd",
    "su", "sudo", "doas",
}

DEFAULT_SAFE_SUB_COMMANDS: dict[str, set[str]] = {
    "git": {
        "status", "log", "diff", "show", "blame",
        "rev-parse", "describe", "name-rev", "shortlog", "whatchanged",
        "remote", "ls-remote", "ls-files",
        "branch", "tag", "stash",
        "config", "var",
    },
    "npm": {
        "run", "test", "list", "ls", "view", "info", "outdated", "audit", "pack",
    },
    "pip": {
        "list", "show", "freeze", "search",
    },
    "uv": {
        "run", "list", "tree",
    },
    "docker": {
        "ps", "images", "logs", "inspect", "version", "info", "diff", "top",
    },
    "kubectl": {
        "get", "describe", "logs", "top", "explain", "api-resources", "api-versions",
    },
    "cargo": {
        "check", "test", "build", "run", "doc", "search", "metadata", "tree",
        "clippy",
    },
}

DEFAULT_DANGEROUS_SUB_COMMANDS: dict[str, set[str]] = {
    "git": {
        "clean",
    },
    "npm": {
        "publish",
    },
    "docker": {
        "rmi",
    },
    "kubectl": {
        "delete",
    },
}


class CommandSafetyChecker:
    """命令安全分类器，含子命令路由。

    分类优先级：
    1. 基础命令在 DANGEROUS_COMMANDS → DANGEROUS（不考虑子命令）
    2. 基础命令有子命令路由表：
       a. 子命令在 DANGEROUS_SUB_COMMANDS → DANGEROUS
       b. 子命令在 SAFE_SUB_COMMANDS → SAFE
       c. 其他子命令 → REQUIRE_HITL
    3. 基础命令在 SAFE_COMMANDS → SAFE
    4. 默认 → REQUIRE_HITL（当 require_approval=True）
    """

    def __init__(
        self,
        safe_commands: set[str] | None = None,
        dangerous_commands: set[str] | None = None,
        safe_sub_commands: dict[str, set[str]] | None = None,
        dangerous_sub_commands: dict[str, set[str]] | None = None,
        require_approval: bool = True,
    ) -> None:
        self._safe_commands = safe_commands if safe_commands is not None else DEFAULT_SAFE_COMMANDS
        self._dangerous_commands = (
            dangerous_commands
            if dangerous_commands is not None
            else DEFAULT_DANGEROUS_COMMANDS
        )
        self._safe_sub_commands = (
            safe_sub_commands if safe_sub_commands is not None else DEFAULT_SAFE_SUB_COMMANDS
        )
        self._dangerous_sub_commands = (
            dangerous_sub_commands
            if dangerous_sub_commands is not None
            else DEFAULT_DANGEROUS_SUB_COMMANDS
        )
        self._require_approval = require_approval

    def check_command(self, command: str) -> CommandSafetyVerdict:
        """检查命令安全性。

        Args:
            command: 命令字符串（如 "git status -s"）

        Returns:
            CommandSafetyVerdict 包含分类结果和原因
        """
        if not command or not command.strip():
            return CommandSafetyVerdict(
                category=CommandSafetyCategory.DANGEROUS,
                base_command="",
                reason="Empty command",
            )

        base_cmd, sub_cmd = self.parse_command(command)

        base_cmd_lower = base_cmd.lower()

        if base_cmd_lower in self._dangerous_commands:
            return CommandSafetyVerdict(
                category=CommandSafetyCategory.DANGEROUS,
                base_command=base_cmd_lower,
                sub_command=sub_cmd,
                reason=f"Dangerous command: {base_cmd_lower}",
            )

        has_sub_routing = (
            base_cmd_lower in self._safe_sub_commands
            or base_cmd_lower in self._dangerous_sub_commands
        )
        if has_sub_routing:
            if sub_cmd:
                sub_cmd_lower = sub_cmd.lower()
                dangerous_subs = self._dangerous_sub_commands.get(base_cmd_lower, set())
                if sub_cmd_lower in dangerous_subs:
                    return CommandSafetyVerdict(
                        category=CommandSafetyCategory.DANGEROUS,
                        base_command=base_cmd_lower,
                        sub_command=sub_cmd_lower,
                        reason=f"Dangerous sub-command: {base_cmd_lower} {sub_cmd_lower}",
                    )
                safe_subs = self._safe_sub_commands.get(base_cmd_lower, set())
                if sub_cmd_lower in safe_subs:
                    return CommandSafetyVerdict(
                        category=CommandSafetyCategory.SAFE,
                        base_command=base_cmd_lower,
                        sub_command=sub_cmd_lower,
                        reason=f"Safe sub-command: {base_cmd_lower} {sub_cmd_lower}",
                    )
            else:
                all_safe_subs = self._safe_sub_commands.get(base_cmd_lower, set())
                all_dangerous_subs = self._dangerous_sub_commands.get(base_cmd_lower, set())
                if not all_safe_subs and not all_dangerous_subs:
                    pass
            return CommandSafetyVerdict(
                category=CommandSafetyCategory.REQUIRE_HITL,
                base_command=base_cmd_lower,
                sub_command=sub_cmd,
                reason=(
                    f"Command requires approval: {command}"
                    if sub_cmd
                    else f"Command requires approval: {base_cmd_lower}"
                ),
            )

        if base_cmd_lower in self._safe_commands:
            return CommandSafetyVerdict(
                category=CommandSafetyCategory.SAFE,
                base_command=base_cmd_lower,
                sub_command=sub_cmd,
                reason=f"Safe command: {base_cmd_lower}",
            )

        if not self._require_approval:
            return CommandSafetyVerdict(
                category=CommandSafetyCategory.SAFE,
                base_command=base_cmd_lower,
                sub_command=sub_cmd,
                reason=f"Approval not required: {base_cmd_lower}",
            )

        return CommandSafetyVerdict(
            category=CommandSafetyCategory.REQUIRE_HITL,
            base_command=base_cmd_lower,
            sub_command=sub_cmd,
            reason=f"Command requires approval: {command}",
        )

    @staticmethod
    def parse_command(command: str) -> tuple[str, str | None]:
        """解析命令字符串，提取 (基础命令, 子命令)。

        处理：
        - "rm -rf /" → ("rm", None)
        - "git status" → ("git", "status")
        - "git log --oneline" → ("git", "log")
        - "npm run build" → ("npm", "run")
        - "/usr/bin/python script.py" → ("python", None)
        - "" → ("", None)

        Args:
            command: 命令字符串

        Returns:
            (基础命令, 子命令或None) 元组
        """
        if not command or not command.strip():
            return "", None

        try:
            parts = shlex.split(command)
        except ValueError:
            parts = command.split()

        if not parts:
            return "", None

        base = Path(parts[0]).name

        sub_cmd: str | None = None
        for i in range(1, len(parts)):
            part = parts[i]
            if part.startswith("-"):
                continue
            if "/" in part:
                continue
            if "." in part and not part.startswith("."):
                continue
            sub_cmd = part
            break

        return base, sub_cmd


class CommandApprovalHook(Hook):
    """命令执行审批 Hook。

    在 PRE_EXECUTE 触发点拦截 execute_command Ability，
    通过 CommandSafetyChecker 检查命令安全性（含子命令路由）：
    - SAFE → HookResult.continue_()
    - DANGEROUS → HookResult.stop(message=...)
    - REQUIRE_HITL → HookResult.hitl(message=...)
    """

    hook_point = HookPoint.PRE_EXECUTE

    def __init__(self, checker: CommandSafetyChecker) -> None:
        self._checker = checker

    async def should_trigger(self, context: AbilityExecutionContext) -> bool:
        return context.current_ability_name == "execute_command"

    async def execute(
        self, context: AbilityExecutionContext, result: ActionResult | None
    ) -> HookResult:
        tool_args = context.tool_args or context.accumulated_data.get("tool_args", {})
        command = tool_args.get("command", "")
        verdict = self._checker.check_command(command)

        if verdict.category == CommandSafetyCategory.SAFE:
            return HookResult.continue_()

        if verdict.category == CommandSafetyCategory.DANGEROUS:
            return HookResult.stop(message=verdict.reason)

        return HookResult.hitl(message=verdict.reason)
