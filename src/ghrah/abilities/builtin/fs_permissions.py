# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""文件系统权限检查模块：共享权限逻辑和写入操作批准 Hook。

提供：
- FSPermissionChecker: 路径权限检查（白名单 + 工作路径自动批准）
- WriteApprovalHook: PRE_EXECUTE Hook，对写入操作进行人工批准（HITL）

权限模型：
- 读取操作：allowed_paths 白名单控制
- 写入操作：双重授权机制
  - 自动批准：路径在 allowed_paths 或 workspace_root 下
  - 人工批准（HITL）：路径不在白名单时暂停执行，等待人工确认
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

from ghrah.abilities.hooks import Hook, HookPoint, HookResult

if TYPE_CHECKING:
    from ghrah.abilities.base import ActionResult
    from ghrah.abilities.context import AbilityExecutionContext

__all__ = [
    "FSPermissionChecker",
    "WriteApprovalHook",
]


class FSPermissionChecker:
    """文件系统路径权限检查器。

    统一管理 allowed_paths 白名单和 workspace_root 工作路径，
    为文件系统 Ability 提供一致的权限检查逻辑。

    用法::

        checker = FSPermissionChecker(
            allowed_paths=["/tmp/data", "/home/user/docs"],
            workspace_root="/home/user/project",
        )

        # 读取权限
        allowed, reason = checker.check_read_path("/tmp/data/file.txt")

        # 写入权限
        allowed, approval = checker.check_write_path("/tmp/data/output.txt")
    """

    def __init__(
        self,
        allowed_paths: list[str] | None = None,
        workspace_root: str | None = None,
        require_approval: bool = True,
    ) -> None:
        self._allowed_paths = self._normalize_paths(allowed_paths) if allowed_paths else None
        self._workspace_root = os.path.abspath(workspace_root) if workspace_root else None
        self._require_approval = require_approval

    @staticmethod
    def _normalize_paths(paths: list[str]) -> list[str]:
        """将路径列表标准化为绝对路径。"""
        return [os.path.abspath(p) for p in paths]

    def _is_in_allowed_paths(self, path: str) -> bool:
        """检查路径是否在白名单中。"""
        abs_path = os.path.abspath(path)
        if self._allowed_paths is None:
            return False
        return any(abs_path.startswith(allowed) for allowed in self._allowed_paths)

    def _is_in_workspace(self, path: str) -> bool:
        """检查路径是否在工作路径下。"""
        if self._workspace_root is None:
            return False
        abs_path = os.path.abspath(path)
        return abs_path.startswith(self._workspace_root)

    def check_read_path(self, path: str) -> tuple[bool, str]:
        """检查读取路径权限。

        Args:
            path: 要检查的文件路径

        Returns:
            (allowed, reason) 元组：
            - (True, ""): 允许访问
            - (False, reason): 拒绝访问并给出原因
        """
        abs_path = os.path.abspath(path)

        # 如果没有配置任何限制，默认允许
        if self._allowed_paths is None and self._workspace_root is None:
            return True, ""

        if self._is_in_allowed_paths(abs_path) or self._is_in_workspace(abs_path):
            return True, ""

        return False, f"Permission denied: {path} not in allowed paths"

    def check_write_path(self, path: str) -> tuple[bool, str | None]:
        """检查写入路径权限。

        Args:
            path: 要检查的文件路径

        Returns:
            (allowed, approval_status) 元组：
            - (True, None): 自动批准
            - (True, "pending"): 需要人工批准
            - (False, reason): 拒绝
        """
        abs_path = os.path.abspath(path)

        # 如果没有配置白名单，检查是否需要人工批准
        if self._allowed_paths is None and self._workspace_root is None:
            if self._require_approval:
                return True, "pending"
            return True, None

        # 白名单或工作路径下 → 自动批准
        if self._is_in_allowed_paths(abs_path) or self._is_in_workspace(abs_path):
            return True, None

        # 不在白名单 → 需要人工批准
        if self._require_approval:
            return True, "pending"

        # 不需要批准但也不在白名单 → 拒绝
        return False, f"Permission denied: {path} not in allowed paths"

    @property
    def allowed_paths(self) -> list[str] | None:
        """返回已配置的允许路径列表。"""
        return self._allowed_paths

    @property
    def workspace_root(self) -> str | None:
        """返回已配置的工作路径根目录。"""
        return self._workspace_root


class WriteApprovalHook(Hook):
    """写入操作的人工批准 Hook。

    在 PRE_EXECUTE 触发点拦截写入类 Ability（write_file, edit_file, move_file, delete_file），
    检查操作路径是否需要人工批准。

    审批流程：
    1. 从 tool_args 中提取目标路径
    2. 通过 FSPermissionChecker 检查权限
    3. 如果需要人工批准 → 返回 NEEDS_INPUT（暂停执行）
    4. 如果自动批准 → 放行
    5. 如果拒绝 → 返回 stop

    用法::

        checker = FSPermissionChecker(
            allowed_paths=["/tmp"],
            require_approval=True,
        )
        hook = WriteApprovalHook(checker)
        ability = WriteFileAbility(hooks=[hook])
    """

    hook_point = HookPoint.PRE_EXECUTE

    # 需要写入批准的 ability 名称集合
    WRITE_ABILITIES = {"write_file", "edit_file", "move_file", "delete_file"}

    def __init__(self, checker: FSPermissionChecker) -> None:
        self._checker = checker

    async def should_trigger(self, context: AbilityExecutionContext) -> bool:
        """只在写入类 Ability 时触发检查。"""
        return context.current_ability_name in self.WRITE_ABILITIES

    async def execute(
        self, context: AbilityExecutionContext, result: ActionResult | None
    ) -> HookResult:
        """检查写入路径权限，决定是否需要人工批准。"""
        # 从 tool_args 中提取目标路径
        tool_args = context.tool_args or context.accumulated_data.get("tool_args", {})
        target_path = self._extract_target_path(context.current_ability_name, tool_args)

        if not target_path:
            return HookResult.continue_()

        allowed, approval_status = self._checker.check_write_path(target_path)

        if not allowed:
            return HookResult.stop(message=f"Permission denied: {target_path} not in allowed paths")

        if approval_status == "pending":
            return HookResult.hitl(
                message=f"Human approval required for write operation on: {target_path}",
            )

        return HookResult.continue_()

    @staticmethod
    def _extract_target_path(ability_name: str, tool_args: dict[str, Any]) -> str | None:
        """根据 ability 类型提取目标路径。"""
        if ability_name == "move_file":
            return tool_args.get("destination_path")
        return tool_args.get("file_path")
