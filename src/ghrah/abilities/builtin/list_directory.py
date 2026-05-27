# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""ListDirectoryAbility：目录列表能力。

功能：
- 列出指定目录下的文件和子目录
- 返回每个条目的名称、类型（file/dir）、大小等信息
- 支持递归列出
- 集成 FSPermissionChecker 读取权限检查

执行逻辑：
1. 从 context.tool_args 获取参数
2. 权限验证（读取权限）
3. 列出目录内容
4. 返回 ActionResult，data 包含 entries 列表
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from ghrah.abilities.base import Ability, ActionOutcome, ActionResult
from ghrah.abilities.builtin.fs_permissions import FSPermissionChecker

if TYPE_CHECKING:
    from ghrah.abilities.context import AbilityExecutionContext
    from ghrah.abilities.hooks import Hook

logger = logging.getLogger(__name__)

__all__ = ["ListDirectoryAbility", "ListDirectoryInput"]


class ListDirectoryInput(BaseModel):
    """ListDirectory 工具的输入参数。"""

    dir_path: str
    recursive: bool = False


class ListDirectoryAbility(Ability):
    """目录列表能力 — 列出目录内容。

    特点：
    - bind_tool() 返回 OpenAI function calling 格式的 schema
    - 返回每个条目的名称、类型（file/dir）、大小
    - 支持递归列出子目录
    - 集成 FSPermissionChecker 读取权限检查

    用法::

        # 无权限限制
        ability = ListDirectoryAbility()

        # 限制可列出的目录
        checker = FSPermissionChecker(allowed_paths=["/home/user/project"])
        ability = ListDirectoryAbility(permission_checker=checker)
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
        """返回 OpenAI function calling 格式的 tool schema。"""
        return {
            "type": "function",
            "function": {
                "name": "list_directory",
                "description": (
                    "List files and directories at the specified path. "
                    "Returns entry names, types (file/directory), and sizes. "
                    "Use recursive=true to list all nested contents."
                ),
                "parameters": ListDirectoryInput.model_json_schema(),
            },
        }

    def to_prompt_description(self) -> str:
        return (
            "list_directory(dir_path: str, recursive: bool = False): "
            "List files and directories at the specified path"
        )

    def get_hooks(self) -> list[Hook]:
        return list(self._hooks)

    async def execute(self, context: AbilityExecutionContext) -> ActionResult:
        """执行目录列表。

        Args:
            context: 执行上下文

        Returns:
            ActionResult：
            - SUCCESS: data 包含 "dir_path" 和 "entries" 列表
            - FAILURE: data 包含 "error"
        """
        tool_args = context.tool_args or context.accumulated_data.get("tool_args", {})
        dir_path = tool_args.get("dir_path", "")
        recursive = tool_args.get("recursive", False)

        if not dir_path:
            return ActionResult(
                outcome=ActionOutcome.FAILURE,
                data={"error": "dir_path is required"},
            )

        # 权限验证（读取权限）
        if self._checker is not None:
            allowed, reason = self._checker.check_read_path(dir_path)
            if not allowed:
                return ActionResult(
                    outcome=ActionOutcome.FAILURE,
                    data={"error": reason},
                )

        logger.debug(f"ListDirectoryAbility: listing {dir_path} (recursive={recursive})")

        try:
            if not Path(dir_path).exists():
                return ActionResult(
                    outcome=ActionOutcome.FAILURE,
                    data={"error": f"Directory not found: {dir_path}"},
                )

            if not Path(dir_path).is_dir():
                return ActionResult(
                    outcome=ActionOutcome.FAILURE,
                    data={"error": f"Not a directory: {dir_path}"},
                )

            entries = self._list_entries(dir_path, recursive)

            logger.debug(f"ListDirectoryAbility: found {len(entries)} entries in {dir_path}")

            return ActionResult(
                outcome=ActionOutcome.SUCCESS,
                data={
                    "dir_path": dir_path,
                    "entries": entries,
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
    def _list_entries(dir_path: str, recursive: bool) -> list[dict[str, Any]]:
        """列出目录条目。

        Args:
            dir_path: 目录路径
            recursive: 是否递归列出

        Returns:
            条目列表，每个条目包含 name, type, size, path
        """
        entries: list[dict[str, Any]] = []

        if recursive:
            dir_path_obj = Path(dir_path)
            for root, dirs, files in os.walk(dir_path):
                root_path = Path(root)
                for d in sorted(dirs):
                    full_path = root_path / d
                    entries.append(
                        {
                            "name": d,
                            "type": "directory",
                            "path": str(full_path.relative_to(dir_path_obj)),
                        }
                    )
                for f in sorted(files):
                    full_path = root_path / f
                    try:
                        size = full_path.stat().st_size
                    except OSError:
                        size = -1
                    entries.append(
                        {
                            "name": f,
                            "type": "file",
                            "size": size,
                            "path": str(full_path.relative_to(dir_path_obj)),
                        }
                    )
        else:
            for entry_path in sorted(Path(dir_path).iterdir()):
                is_dir = entry_path.is_dir()
                entry_info: dict[str, Any] = {
                    "name": entry_path.name,
                    "type": "directory" if is_dir else "file",
                }
                if not is_dir:
                    try:
                        entry_info["size"] = entry_path.stat().st_size
                    except OSError:
                        entry_info["size"] = -1
                entries.append(entry_info)

        return entries
