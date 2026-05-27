# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""MoveFileAbility：文件移动/重命名能力。

功能：
- 移动或重命名文件，支持跨目录移动
- 源路径和目标路径双重权限检查
- 支持自动创建目标目录
- 支持覆盖已存在的目标文件

执行逻辑：
1. 从 context.tool_args 获取参数
2. 源路径读取权限检查 + 目标路径写入权限检查
3. 验证源文件存在
4. 检查目标文件是否已存在
5. 执行 shutil.move()
6. 返回 ActionResult
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from ghrah.abilities.base import Ability, ActionOutcome, ActionResult
from ghrah.abilities.builtin.fs_permissions import FSPermissionChecker

if TYPE_CHECKING:
    from ghrah.abilities.context import AbilityExecutionContext
    from ghrah.abilities.hooks import Hook

logger = logging.getLogger(__name__)

__all__ = ["MoveFileAbility", "MoveFileInput"]


class MoveFileInput(BaseModel):
    """MoveFile 工具的输入参数。"""

    source_path: str
    destination_path: str
    create_dirs: bool = True
    overwrite: bool = False


class MoveFileAbility(Ability):
    """文件移动/重命名能力。

    特点：
    - 支持跨目录移动
    - 源路径和目标路径双重权限检查
    - 支持自动创建目标目录
    - 可选覆盖已存在的目标文件

    用法::

        # 无权限限制
        ability = MoveFileAbility()

        # 限制路径
        checker = FSPermissionChecker(allowed_paths=["/home/user/project"])
        ability = MoveFileAbility(permission_checker=checker)
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
        return "move_file"

    def bind_tool(self) -> dict[str, Any]:
        """返回 OpenAI function calling 格式的 tool schema。"""
        return {
            "type": "function",
            "function": {
                "name": "move_file",
                "description": (
                    "Move or rename a file. Supports cross-directory moves. "
                    "The source and destination paths are both subject to permission checks."
                ),
                "parameters": MoveFileInput.model_json_schema(),
            },
        }

    def to_prompt_description(self) -> str:
        return (
            "move_file(source_path: str, destination_path: str, "
            "create_dirs: bool = True, overwrite: bool = False): "
            "Move or rename a file"
        )

    def get_hooks(self) -> list[Hook]:
        return list(self._hooks)

    async def execute(self, context: AbilityExecutionContext) -> ActionResult:
        """执行文件移动/重命名。

        Args:
            context: 执行上下文

        Returns:
            ActionResult：
            - SUCCESS: data 包含 "source_path" 和 "destination_path"
            - FAILURE: data 包含 "error"
        """
        tool_args = context.tool_args or context.accumulated_data.get("tool_args", {})
        source_path = tool_args.get("source_path", "")
        destination_path = tool_args.get("destination_path", "")
        create_dirs = tool_args.get("create_dirs", True)
        overwrite = tool_args.get("overwrite", False)

        if not source_path:
            return ActionResult(
                outcome=ActionOutcome.FAILURE,
                data={"error": "source_path is required"},
            )

        if not destination_path:
            return ActionResult(
                outcome=ActionOutcome.FAILURE,
                data={"error": "destination_path is required"},
            )

        # 权限验证：源路径（读取）+ 目标路径（写入）
        if self._checker is not None:
            # 源路径读取权限
            read_allowed, read_reason = self._checker.check_read_path(source_path)
            if not read_allowed:
                return ActionResult(
                    outcome=ActionOutcome.FAILURE,
                    data={"error": read_reason},
                )

            # 目标路径写入权限
            write_allowed, write_reason = self._checker.check_write_path(destination_path)
            if not write_allowed:
                return ActionResult(
                    outcome=ActionOutcome.FAILURE,
                    data={"error": write_reason},
                )

        logger.debug(f"MoveFileAbility: moving {source_path} -> {destination_path}")

        try:
            # 验证源文件存在
            if not Path(source_path).exists():
                return ActionResult(
                    outcome=ActionOutcome.FAILURE,
                    data={"error": f"Source file not found: {source_path}"},
                )

            # 检查目标文件是否已存在
            if Path(destination_path).exists() and not overwrite:
                return ActionResult(
                    outcome=ActionOutcome.FAILURE,
                    data={
                        "error": (
                            f"Destination already exists: {destination_path}. "
                            "Set overwrite=True to replace it."
                        ),
                    },
                )

            # 创建目标目录
            if create_dirs:
                parent = Path(destination_path).resolve().parent
                parent.mkdir(parents=True, exist_ok=True)

            # 执行移动
            shutil.move(source_path, destination_path)

            logger.debug(f"MoveFileAbility: moved {source_path} -> {destination_path}")

            return ActionResult(
                outcome=ActionOutcome.SUCCESS,
                data={
                    "source_path": source_path,
                    "destination_path": destination_path,
                },
            )
        except PermissionError:
            return ActionResult(
                outcome=ActionOutcome.FAILURE,
                data={"error": "Permission denied during move operation"},
            )
        except OSError as e:
            return ActionResult(
                outcome=ActionOutcome.FAILURE,
                data={"error": f"Failed to move file: {e}"},
            )
        except Exception as e:
            return ActionResult(
                outcome=ActionOutcome.FAILURE,
                data={"error": str(e)},
            )
