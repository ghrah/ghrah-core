# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""文件系统权限检查模块：共享权限逻辑和访问批准 Hook。

提供：
- FSPermissionChecker: 路径权限检查（白名单 + 黑名单 + 工作路径 + 统一审批）
- AccessApprovalHook: PRE_EXECUTE Hook，对读写操作进行人工批准（HITL）
- WriteApprovalHook: AccessApprovalHook 的向后兼容别名

权限模型（统一读写）：
- denied_paths 优先（硬性拒绝，不可覆盖）
- allowed_paths 白名单和 workspace_root 控制自动批准的范围
- 不在白名单且 require_approval=True 时需要人工批准（HITL）
- 不在白名单且 require_approval=False 时直接拒绝
- 未配置白名单且 require_approval=False 时拒绝所有访问（需设置 allowed_paths 或 workspace_root）
- 未配置白名单且 require_approval=True 时所有访问需人工审批
- is_subpath 严格前缀匹配（防止意外的前缀匹配）
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from ghrah.abilities._utils import is_subpath
from ghrah.abilities.hooks import Hook, HookPoint, HookResult

if TYPE_CHECKING:
    from ghrah.abilities.base import ActionResult
    from ghrah.abilities.context import AbilityExecutionContext

__all__ = [
    "FSPermissionChecker",
    "AccessApprovalHook",
    "WriteApprovalHook",
]


class FSPermissionChecker:
    """文件系统路径权限检查器。

    统一管理 allowed_paths 白名单、denied_paths 黑名单和 workspace_root 工作路径，
    为文件系统 Ability 提供一致的权限检查逻辑。

    读写权限模型统一：
    - denied_paths 优先于 allowed_paths（硬性拒绝）
    - 路径前缀匹配使用 is_subpath（严格边界检查）
    - 不在白名单时根据 require_approval 决定是要求 HITL 审批还是直接拒绝
    - 未配置白名单（allowed_paths 和 workspace_root 均为 None）时：
      - require_approval=True：所有路径均需人工审批
      - require_approval=False：所有路径均被拒绝

    用法::

        checker = FSPermissionChecker(
            allowed_paths=["/tmp/data", "/home/user/docs"],
            workspace_root="/home/user/project",
            denied_paths=["/home/user/project/secrets"],
        )

        # 统一访问检查
        allowed, status = checker.check_access("/tmp/data/file.txt", operation="read")
        allowed, status = checker.check_access("/tmp/data/output.txt", operation="write")

        # 兼容接口
        allowed, status = checker.check_read_path("/tmp/data/file.txt")
        allowed, status = checker.check_write_path("/tmp/data/output.txt")
    """

    def __init__(
        self,
        allowed_paths: list[str] | None = None,
        workspace_root: str | None = None,
        denied_paths: list[str] | None = None,
        require_approval: bool = True,
    ) -> None:
        self._allowed_paths = self._normalize_paths(allowed_paths) if allowed_paths else None
        self._workspace_root = Path(workspace_root).resolve() if workspace_root else None
        self._denied_paths = self._normalize_paths(denied_paths) if denied_paths else None
        self._require_approval = require_approval

    @staticmethod
    def _normalize_paths(paths: list[str]) -> list[Path]:
        """将路径列表标准化为绝对路径（解析符号链接）。"""
        return [Path(p).resolve() for p in paths]

    @staticmethod
    def _resolve(path: str | Path) -> Path:
        """将路径解析为绝对路径（解析符号链接）。"""
        return Path(path).resolve()

    def _is_in_allowed_paths(self, resolved: Path) -> bool:
        """检查已解析路径是否在白名单中（严格前缀匹配）。"""
        if self._allowed_paths is None:
            return False
        return any(is_subpath(resolved, allowed) for allowed in self._allowed_paths)

    def _is_in_workspace(self, resolved: Path) -> bool:
        """检查已解析路径是否在工作路径下（严格前缀匹配）。"""
        if self._workspace_root is None:
            return False
        return is_subpath(resolved, self._workspace_root)

    def _is_in_denied_paths(self, resolved: Path) -> bool:
        """检查已解析路径是否在黑名单中（严格前缀匹配）。黑名单优先于白名单。"""
        if self._denied_paths is None:
            return False
        return any(is_subpath(resolved, denied) for denied in self._denied_paths)

    def _is_path_allowed(self, resolved: Path) -> bool:
        """检查已解析路径是否被允许（在白名单或工作路径下，且不在黑名单中）。"""
        if self._is_in_denied_paths(resolved):
            return False
        return self._is_in_allowed_paths(resolved) or self._is_in_workspace(resolved)

    def check_access(self, path: str, operation: str = "read") -> tuple[bool, str | None]:
        """统一访问权限检查。

        Args:
            path: 要检查的文件路径
            operation: 操作类型 "read" 或 "write"

        Returns:
            (allowed, status) 元组：
            - (True, None): 自动批准
            - (True, "pending"): 需要 HITL 审批
            - (False, reason): 拒绝访问
        """
        resolved = self._resolve(path)

        if self._allowed_paths is None and self._workspace_root is None:
            if self._require_approval:
                return True, "pending"
            return False, "Permission denied: no allowed paths configured"

        if self._is_in_denied_paths(resolved):
            return False, f"Permission denied: {path} is in denied paths"

        if self._is_path_allowed(resolved):
            return True, None

        if self._require_approval:
            return True, "pending"

        return False, f"Permission denied: {path} not in allowed paths"

    def check_read_path(self, path: str) -> tuple[bool, str | None]:
        """检查读取路径权限。

        委托给 check_access(operation="read")。

        Args:
            path: 要检查的文件路径

        Returns:
            (allowed, status) 元组：
            - (True, None): 允许访问
            - (True, "pending"): 需要 HITL 审批
            - (False, reason): 拒绝访问
        """
        return self.check_access(path, operation="read")

    def check_write_path(self, path: str) -> tuple[bool, str | None]:
        """检查写入路径权限。

        委托给 check_access(operation="write")。

        Args:
            path: 要检查的文件路径

        Returns:
            (allowed, status) 元组：
            - (True, None): 自动批准
            - (True, "pending"): 需要 HITL 审批
            - (False, reason): 拒绝
        """
        return self.check_access(path, operation="write")

    @property
    def allowed_paths(self) -> list[str] | None:
        """返回已配置的允许路径列表。"""
        if self._allowed_paths is None:
            return None
        return [str(p) for p in self._allowed_paths]

    @property
    def workspace_root(self) -> str | None:
        """返回已配置的工作路径根目录。

        注意：返回值经过 resolve() 解析符号链接，
        可能与传入的原始路径不同。
        """
        return str(self._workspace_root) if self._workspace_root is not None else None

    @property
    def denied_paths(self) -> list[str] | None:
        """返回已配置的拒绝路径列表。"""
        if self._denied_paths is None:
            return None
        return [str(p) for p in self._denied_paths]


class AccessApprovalHook(Hook):
    """访问操作的人工批准 Hook。

    在 PRE_EXECUTE 触发点拦截需要审批的 Ability（读取和写入类），
    根据 FSPermissionChecker.check_access() 判断是否需要人工批准。

    审批流程：
    1. 从 tool_args 中提取目标路径
    2. 根据 Ability 类型判断操作类型（读/写）
    3. 通过 FSPermissionChecker 检查权限
    4. 如果需要人工批准 → 返回 HITL（暂停执行）
    5. 如果自动批准 → 放行
    6. 如果拒绝 → 返回 stop

    用法::

        checker = FSPermissionChecker(
            allowed_paths=["/tmp"],
            require_approval=True,
        )
        hook = AccessApprovalHook(checker)
        ability = ReadFileAbility(hooks=[hook])
    """

    hook_point = HookPoint.PRE_EXECUTE

    WRITE_ABILITIES = {"write_file", "edit_file", "move_file", "delete_file"}
    READ_ABILITIES = {"read_file", "list_directory"}

    def __init__(self, checker: FSPermissionChecker) -> None:
        self._checker = checker

    async def should_trigger(self, context: AbilityExecutionContext) -> bool:
        """在读写类 Ability 时触发检查。"""
        name = context.current_ability_name
        return name in self.WRITE_ABILITIES or name in self.READ_ABILITIES

    async def execute(
        self, context: AbilityExecutionContext, result: ActionResult | None
    ) -> HookResult:
        """检查访问路径权限，决定是否需要人工批准。"""
        tool_args = context.tool_args or context.accumulated_data.get("tool_args", {})
        target_path = self._extract_target_path(context.current_ability_name, tool_args)

        if not target_path:
            return HookResult.continue_()

        operation = "write" if context.current_ability_name in self.WRITE_ABILITIES else "read"
        allowed, status = self._checker.check_access(target_path, operation)

        if not allowed:
            return HookResult.stop(message=status or f"Permission denied: {target_path}")

        if status == "pending":
            return HookResult.hitl(
                message=f"Human approval required for {operation} operation on: {target_path}",
            )

        return HookResult.continue_()

    @staticmethod
    def _extract_target_path(ability_name: str, tool_args: dict[str, Any]) -> str | None:
        """根据 ability 类型提取目标路径。"""
        if ability_name == "move_file":
            return tool_args.get("destination_path")
        return tool_args.get("file_path") or tool_args.get("dir_path")


WriteApprovalHook = AccessApprovalHook
