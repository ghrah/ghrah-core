# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""EditFileAbility：精确字符串替换能力。

功能：
- 在文件中查找唯一匹配的 old_str 并替换为 new_str
- old_str 必须在文件中恰好出现 1 次，否则返回 FAILURE
- 集成 FSPermissionChecker 权限检查

执行逻辑：
1. 从 context.tool_args 获取参数
2. 权限验证
3. 读取文件内容
4. 检查 old_str 匹配次数（0 / 1 / N）
5. 执行替换并写回
6. 返回 ActionResult
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from ghrah.abilities.base import Ability, ActionOutcome, ActionResult
from ghrah.abilities.builtin.fs_permissions import FSPermissionChecker

if TYPE_CHECKING:
    from ghrah.abilities.context import AbilityExecutionContext
    from ghrah.abilities.hooks import Hook

logger = logging.getLogger(__name__)

__all__ = ["EditFileAbility", "EditFileInput"]


class EditFileInput(BaseModel):
    """EditFile 工具的输入参数。"""

    file_path: str
    old_str: str
    new_str: str
    encoding: str = "utf-8"


class EditFileAbility(Ability):
    """文件编辑能力 — 精确字符串替换。

    核心设计：LLM 提供一个在文件中唯一出现的 old_str，将其替换为 new_str。
    如果 old_str 在文件中出现多次，返回 FAILURE 并提示提供更多上下文。

    特点：
    - bind_tool() 返回 OpenAI function calling 格式的 schema
    - old_str 必须精确匹配（包括空白字符和缩进）
    - 替换是原子操作：先读取、验证、替换、再写回
    - 集成 FSPermissionChecker 权限检查

    用法::

        # 无权限限制
        ability = EditFileAbility()

        # 限制写入目录
        checker = FSPermissionChecker(allowed_paths=["/home/user/project"])
        ability = EditFileAbility(permission_checker=checker)
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
        return "edit_file"

    def bind_tool(self) -> dict[str, Any]:
        """返回 OpenAI function calling 格式的 tool schema。"""
        return {
            "type": "function",
            "function": {
                "name": "edit_file",
                "description": (
                    "Edit a file by replacing a unique string. "
                    "The old_str must appear exactly once in the file. "
                    "If it appears multiple times, the operation fails and you should "
                    "provide more surrounding context to make it unique."
                ),
                "parameters": EditFileInput.model_json_schema(),
            },
        }

    def to_prompt_description(self) -> str:
        return (
            "edit_file(file_path: str, old_str: str, new_str: str, "
            "encoding: str = 'utf-8'): Edit a file by replacing old_str with new_str. "
            "old_str must be unique in the file."
        )

    def get_hooks(self) -> list[Hook]:
        return list(self._hooks)

    async def execute(self, context: AbilityExecutionContext) -> ActionResult:
        """执行文件编辑（精确字符串替换）。

        Args:
            context: 执行上下文

        Returns:
            ActionResult：
            - SUCCESS: data 包含 "file_path" 和 "replacements"
            - FAILURE: data 包含 "error"
        """
        tool_args = context.tool_args or context.accumulated_data.get("tool_args", {})
        file_path = tool_args.get("file_path", "")
        old_str = tool_args.get("old_str", "")
        new_str = tool_args.get("new_str", "")
        encoding = tool_args.get("encoding", "utf-8")

        if not file_path:
            return ActionResult(
                outcome=ActionOutcome.FAILURE,
                data={"error": "file_path is required"},
            )

        if not old_str:
            return ActionResult(
                outcome=ActionOutcome.FAILURE,
                data={"error": "old_str is required"},
            )

        # 权限验证
        if self._checker is not None:
            allowed, reason = self._checker.check_write_path(file_path)
            if not allowed:
                return ActionResult(
                    outcome=ActionOutcome.FAILURE,
                    data={"error": reason},
                )

        logger.debug(f"EditFileAbility: editing {file_path}")

        try:
            # 读取文件
            with Path(file_path).open(encoding=encoding) as f:
                content = f.read()

            # 检查 old_str 匹配次数
            count = content.count(old_str)

            if count == 0:
                return ActionResult(
                    outcome=ActionOutcome.FAILURE,
                    data={
                        "error": (
                            f"old_str not found in file: {file_path}. "
                            "Please verify the exact string content including "
                            "whitespace and indentation."
                        ),
                    },
                )

            if count > 1:
                return ActionResult(
                    outcome=ActionOutcome.FAILURE,
                    data={
                        "error": (
                            f"old_str appears {count} times in file: {file_path}, "
                            f"expected exactly 1. Provide more surrounding context "
                            f"to make it unique."
                        ),
                    },
                )

            # 执行替换
            new_content = content.replace(old_str, new_str, 1)

            # 写回文件
            with Path(file_path).open("w", encoding=encoding) as f:
                f.write(new_content)

            logger.debug(f"EditFileAbility: replaced 1 occurrence in {file_path}")

            return ActionResult(
                outcome=ActionOutcome.SUCCESS,
                data={
                    "file_path": file_path,
                    "replacements": 1,
                },
            )
        except FileNotFoundError:
            return ActionResult(
                outcome=ActionOutcome.FAILURE,
                data={"error": f"File not found: {file_path}"},
            )
        except PermissionError:
            return ActionResult(
                outcome=ActionOutcome.FAILURE,
                data={"error": f"Permission denied: {file_path}"},
            )
        except Exception as e:
            return ActionResult(
                outcome=ActionOutcome.FAILURE,
                data={"error": str(e)},
            )
