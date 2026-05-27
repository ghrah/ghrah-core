# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""ReadFileAbility：带工具绑定的文件读取能力。

这是一个"1 Ability = 1 Tool Call"的示例实现，演示如何：
- 通过 bind_tool() 提供原生 Function Calling schema
- 通过 to_prompt_description() 提供 prompt 模式描述（兼容不支持 FC 的模型）
- 从 AbilityExecutionContext.tool_args 获取 LLM 解析的 tool 参数
- 执行实际的文件读取操作
- 集成 FSPermissionChecker 权限检查

执行逻辑：
1. 从 context.tool_args 获取 LLM 解析的参数
2. 权限验证（FSPermissionChecker.check_read_path）
3. 执行文件读取
4. 返回 ActionResult(outcome=SUCCESS/FAILURE, data={"content": ..., "file_path": ...})
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

__all__ = ["ReadFileAbility", "ReadFileInput"]


class ReadFileInput(BaseModel):
    """ReadFile 工具的输入参数。"""

    file_path: str
    encoding: str = "utf-8"


class ReadFileAbility(Ability):
    """文件读取能力 — 一个 Ability 对应一个 tool call。

    特点：
    - bind_tool() 返回 OpenAI function calling 格式的 schema
    - to_prompt_description() 提供 ReAct 模式下的工具描述
    - execute() 从 context.tool_args 获取参数
    - 集成 FSPermissionChecker 权限检查

    注意：实际的 tool 参数来自 LLM 的 function call 响应，
    由 Agent 在调用 execute 前解析并存入 context.accumulated_data。

    用法::

        # 无权限限制
        ability = ReadFileAbility()
        agent.register_ability(ability)

        # 限制只能读取特定目录
        checker = FSPermissionChecker(allowed_paths=["/tmp/data", "/home/user/docs"])
        ability = ReadFileAbility(permission_checker=checker)
        agent.register_ability(ability)

        # 向后兼容：使用 allowed_paths 列表
        ability = ReadFileAbility(allowed_paths=["/tmp/data"])
        agent.register_ability(ability)
    """

    def __init__(
        self,
        hooks: list[Hook] | None = None,
        allowed_paths: list[str] | None = None,
        permission_checker: FSPermissionChecker | None = None,
    ) -> None:
        self._hooks = hooks or []
        # 向后兼容：如果传入了 allowed_paths 但没有 checker，自动创建一个
        if permission_checker is not None:
            self._checker = permission_checker
        elif allowed_paths is not None:
            self._checker = FSPermissionChecker(allowed_paths=allowed_paths)
        else:
            self._checker = None

    @property
    def name(self) -> str:
        return "read_file"

    def bind_tool(self) -> dict[str, Any]:
        """返回 OpenAI function calling 格式的 tool schema。"""
        return {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read the content of a file at the specified path",
                "parameters": ReadFileInput.model_json_schema(),
            },
        }

    def to_prompt_description(self) -> str:
        """用于不支持 function calling 的模型。"""
        return (
            "read_file(file_path: str, encoding: str = 'utf-8') -> str: "
            "Read the content of a file at the specified path"
        )

    def get_hooks(self) -> list[Hook]:
        return list(self._hooks)

    async def execute(self, context: AbilityExecutionContext) -> ActionResult:
        """执行文件读取。

        从 context.tool_args 获取 LLM 解析的参数，
        执行权限验证和文件读取，返回结果。

        Args:
            context: 执行上下文

        Returns:
            ActionResult：
            - SUCCESS: data 包含 "content" 和 "file_path"
            - FAILURE: data 包含 "error"
        """
        tool_args = context.tool_args or context.accumulated_data.get("tool_args", {})
        file_path = tool_args.get("file_path", "")
        encoding = tool_args.get("encoding", "utf-8")

        if not file_path:
            return ActionResult(
                outcome=ActionOutcome.FAILURE,
                data={"error": "file_path is required"},
            )

        # 权限验证（读取权限）
        if self._checker is not None:
            allowed, reason = self._checker.check_read_path(file_path)
            if not allowed:
                return ActionResult(
                    outcome=ActionOutcome.FAILURE,
                    data={"error": reason},
                )

        logger.debug(f"ReadFileAbility: reading {file_path}")

        try:
            with Path(file_path).open(encoding=encoding) as f:
                content = f.read()

            logger.debug(f"ReadFileAbility: read {len(content)} chars from {file_path}")

            return ActionResult(
                outcome=ActionOutcome.SUCCESS,
                data={"content": content, "file_path": file_path},
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
