# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""StudentGradeListDirectoryAbility：带默认排除的目录列表能力。

在 builtin ListDirectoryAbility 的基础上增加了目录排除功能：
- 默认排除 .git / .venv / node_modules / __pycache__ 等噪音目录
- 支持 recursive 模式下对 os.walk 的 dirs 剪枝，避免遍历排除目录
- 支持 exclude_dirs 参数追加额外排除项（与默认列表合并）

执行逻辑：
1. 从 context.tool_args 获取参数
2. 权限验证（读取权限）
3. 合并默认排除列表与用户传入的 exclude_dirs
4. 列出目录内容（排除指定目录）
5. 返回 ActionResult，data 包含 entries 列表
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from ghrah.abilities.base import Ability, ActionOutcome, ActionResult
from ghrah.abilities.builtin.fs_permissions import FSPermissionChecker

if TYPE_CHECKING:
    from ghrah.abilities.context import AbilityExecutionContext
    from ghrah.abilities.hooks import Hook

logger = logging.getLogger(__name__)

__all__ = ["StudentGradeListDirectoryAbility", "StudentGradeListDirectoryInput"]

DEFAULT_EXCLUDE_DIRS: frozenset[str] = frozenset({
    ".git",
    ".venv",
    "node_modules",
    "__pycache__",
    ".idea",
    ".vscode",
    "dist",
    "build",
    ".next",
    ".DS_Store",
    ".eggs",
})


class StudentGradeListDirectoryInput(BaseModel):
    dir_path: str
    recursive: bool = False
    exclude_dirs: list[str] | None = None


class StudentGradeListDirectoryAbility(Ability):
    """带默认排除的目录列表能力。

    与 builtin ListDirectoryAbility 相比：
    - 默认排除常见噪音目录（.git, node_modules 等）
    - 支持 exclude_dirs 参数追加额外排除项
    - recursive 模式下通过 os.walk dirs 剪枝避免遍历排除目录
    """

    def __init__(
        self,
        hooks: list[Hook] | None = None,
        permission_checker: FSPermissionChecker | None = None,
    ) -> None:
        self._hooks = hooks or []
        self._checker = permission_checker

    @property
    def name(self) -> str:
        return "list_directory"

    def bind_tool(self) -> dict[str, Any]:
        schema = StudentGradeListDirectoryInput.model_json_schema()
        if "properties" in schema and "exclude_dirs" in schema["properties"]:
            schema["properties"]["exclude_dirs"]["description"] = (
                "Additional directory names to exclude from listing (merged with "
                "the built-in exclusion list). Pass an empty array to use defaults only."
            )
        return {
            "type": "function",
            "function": {
                "name": "list_directory",
                "description": (
                    "List files and directories at the specified path. Automatically "
                    "excludes common noise directories (.git, .venv, node_modules, "
                    "__pycache__, .idea, .vscode, dist, build, .next, .DS_Store, .eggs). "
                    "Returns entry names, types, and sizes. Use recursive=true to list "
                    "all nested contents. Use exclude_dirs to add extra directory names "
                    "to exclude (merged with the defaults)."
                ),
                "parameters": schema,
            },
        }

    def to_prompt_description(self) -> str:
        return (
            "list_directory(dir_path: str, recursive: bool = False, "
            "exclude_dirs: list[str] | None = None): "
            "List files and directories, excluding .git, node_modules, "
            "__pycache__, .venv, etc."
        )

    def get_hooks(self) -> list[Hook]:
        return list(self._hooks)

    async def execute(self, context: AbilityExecutionContext) -> ActionResult:
        tool_args = context.tool_args or context.accumulated_data.get("tool_args", {})
        dir_path = tool_args.get("dir_path", "")
        recursive = tool_args.get("recursive", False)
        extra_exclude = tool_args.get("exclude_dirs") or []

        if not dir_path:
            return ActionResult(
                outcome=ActionOutcome.FAILURE,
                data={"error": "dir_path is required"},
            )

        if self._checker is not None:
            allowed, reason = self._checker.check_read_path(dir_path)
            if not allowed:
                return ActionResult(
                    outcome=ActionOutcome.FAILURE,
                    data={"error": reason},
                )

        exclude_dirs = DEFAULT_EXCLUDE_DIRS | frozenset(extra_exclude)

        logger.debug(
            "StudentGradeListDirectoryAbility: listing %s (recursive=%s, exclude=%s)",
            dir_path,
            recursive,
            exclude_dirs,
        )

        try:
            if not os.path.exists(dir_path):
                return ActionResult(
                    outcome=ActionOutcome.FAILURE,
                    data={"error": f"Directory not found: {dir_path}"},
                )

            if not os.path.isdir(dir_path):
                return ActionResult(
                    outcome=ActionOutcome.FAILURE,
                    data={"error": f"Not a directory: {dir_path}"},
                )

            entries = self._list_entries(dir_path, recursive, exclude_dirs)

            logger.debug(
                "StudentGradeListDirectoryAbility: found %d entries in %s",
                len(entries),
                dir_path,
            )

            return ActionResult(
                outcome=ActionOutcome.SUCCESS,
                data={
                    "dir_path": dir_path,
                    "entries": entries,
                    "excluded_dirs": sorted(exclude_dirs),
                },
            )
        except PermissionError:
            return ActionResult(
                outcome=ActionOutcome.FAILURE,
                data={"error": f"Permission denied: {dir_path}"},
            )
        except Exception as e:
            return ActionResult(
                outcome=ActionOutcome.FAILURE,
                data={"error": str(e)},
            )

    @staticmethod
    def _list_entries(
        dir_path: str,
        recursive: bool,
        exclude_dirs: frozenset[str],
    ) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []

        if recursive:
            for root, dirs, files in os.walk(dir_path):
                dirs[:] = sorted(d for d in dirs if d not in exclude_dirs)

                for d in sorted(dirs):
                    full_path = os.path.join(root, d)
                    entries.append(
                        {
                            "name": d,
                            "type": "directory",
                            "path": os.path.relpath(full_path, dir_path),
                        }
                    )
                for f in sorted(files):
                    full_path = os.path.join(root, f)
                    try:
                        size = os.path.getsize(full_path)
                    except OSError:
                        size = -1
                    entries.append(
                        {
                            "name": f,
                            "type": "file",
                            "size": size,
                            "path": os.path.relpath(full_path, dir_path),
                        }
                    )
        else:
            for entry in sorted(os.listdir(dir_path)):
                if entry in exclude_dirs:
                    continue
                full_path = os.path.join(dir_path, entry)
                is_dir = os.path.isdir(full_path)
                entry_info: dict[str, Any] = {
                    "name": entry,
                    "type": "directory" if is_dir else "file",
                }
                if not is_dir:
                    try:
                        entry_info["size"] = os.path.getsize(full_path)
                    except OSError:
                        entry_info["size"] = -1
                entries.append(entry_info)

        return entries
