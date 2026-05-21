# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""WriteFileAbility：文件写入能力。

功能：
- 创建新文件或覆盖写入已有文件
- 支持自动创建父目录
- 集成 FSPermissionChecker 权限检查

执行逻辑：
1. 从 context.tool_args 获取 LLM 解析的参数
2. 权限验证（FSPermissionChecker.check_write_path）
3. 如果 create_dirs=True，自动创建父目录
4. 写入文件内容
5. 返回 ActionResult(outcome=SUCCESS/FAILURE)
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

__all__ = ["WriteFileAbility", "WriteFileInput"]


class WriteFileInput(BaseModel):
    """WriteFile 工具的输入参数。"""

    file_path: str
    content: str
    create_dirs: bool = True
    encoding: str = "utf-8"


class WriteFileAbility(Ability):
    """文件写入能力 — 创建或覆盖文件。

    特点：
    - bind_tool() 返回 OpenAI function calling 格式的 schema
    - 集成 FSPermissionChecker 权限检查
    - 支持自动创建父目录

    用法::

        # 无权限限制
        ability = WriteFileAbility()

        # 限制写入目录
        checker = FSPermissionChecker(allowed_paths=["/tmp/data"])
        ability = WriteFileAbility(permission_checker=checker)

        # 带人工批准 Hook
        from ghrah.abilities.builtin.fs_permissions import WriteApprovalHook
        hook = WriteApprovalHook(checker)
        ability = WriteFileAbility(
            permission_checker=checker,
            hooks=[hook],
        )
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
        return "write_file"

    def bind_tool(self) -> dict[str, Any]:
        """返回 OpenAI function calling 格式的 tool schema。"""
        return {
            "type": "function",
            "function": {
                "name": "write_file",
                "description": (
                    "Write content to a file. Creates the file and parent directories "
                    "if they do not exist. Overwrites existing content."
                ),
                "parameters": WriteFileInput.model_json_schema(),
            },
        }

    def to_prompt_description(self) -> str:
        return (
            "write_file(file_path: str, content: str, create_dirs: bool = True, "
            "encoding: str = 'utf-8'): Write content to a file"
        )

    def get_hooks(self) -> list[Hook]:
        return list(self._hooks)

    async def execute(self, context: AbilityExecutionContext) -> ActionResult:
        """执行文件写入。

        Args:
            context: 执行上下文

        Returns:
            ActionResult：
            - SUCCESS: data 包含 "file_path" 和 "bytes_written"
            - FAILURE: data 包含 "error"
        """
        tool_args = context.tool_args or context.accumulated_data.get("tool_args", {})
        file_path = tool_args.get("file_path", "")
        content = tool_args.get("content", "")
        create_dirs = tool_args.get("create_dirs", True)
        encoding = tool_args.get("encoding", "utf-8")

        if not file_path:
            return ActionResult(
                outcome=ActionOutcome.FAILURE,
                data={"error": "file_path is required"},
            )

        # 权限验证
        if self._checker is not None:
            allowed, reason = self._checker.check_write_path(file_path)
            if not allowed:
                return ActionResult(
                    outcome=ActionOutcome.FAILURE,
                    data={"error": reason},
                )

        logger.debug(f"WriteFileAbility: writing to {file_path}")

        try:
            # 创建父目录
            if create_dirs:
                parent = os.path.dirname(os.path.abspath(file_path))
                if parent:
                    os.makedirs(parent, exist_ok=True)

            # 写入文件
            with open(file_path, "w", encoding=encoding) as f:
                f.write(content)

            bytes_written = len(content.encode(encoding))
            logger.debug(f"WriteFileAbility: wrote {bytes_written} bytes to {file_path}")

            return ActionResult(
                outcome=ActionOutcome.SUCCESS,
                data={
                    "file_path": file_path,
                    "bytes_written": bytes_written,
                },
            )
        except PermissionError:
            return ActionResult(
                outcome=ActionOutcome.FAILURE,
                data={"error": f"Permission denied: {file_path}"},
            )
        except OSError as e:
            return ActionResult(
                outcome=ActionOutcome.FAILURE,
                data={"error": f"Failed to write file: {e}"},
            )
        except Exception as e:
            return ActionResult(
                outcome=ActionOutcome.FAILURE,
                data={"error": str(e)},
            )
