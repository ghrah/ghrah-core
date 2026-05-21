# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""文件系统权限模块测试：FSPermissionChecker 和 WriteApprovalHook。"""

from __future__ import annotations

import os
import tempfile
from typing import Any

from ghrah.abilities.builtin.fs_permissions import FSPermissionChecker, WriteApprovalHook
from ghrah.abilities.context import AbilityExecutionContext


def _make_context(**overrides: Any) -> AbilityExecutionContext:
    """创建测试用 AbilityExecutionContext。"""
    defaults: dict[str, Any] = {}
    defaults.update(overrides)
    return AbilityExecutionContext(**defaults)


# ── FSPermissionChecker 测试 ──


class TestFSPermissionChecker:
    """FSPermissionChecker 权限检查测试。"""

    def test_no_restrictions_read(self) -> None:
        """无限制时允许所有读取。"""
        checker = FSPermissionChecker()
        allowed, reason = checker.check_read_path("/any/path/file.txt")
        assert allowed is True
        assert reason == ""

    def test_no_restrictions_write_auto(self) -> None:
        """无限制且不需要批准时允许所有写入。"""
        checker = FSPermissionChecker(require_approval=False)
        allowed, status = checker.check_write_path("/any/path/file.txt")
        assert allowed is True
        assert status is None

    def test_no_restrictions_write_needs_approval(self) -> None:
        """无限制但需要批准时返回 pending。"""
        checker = FSPermissionChecker(require_approval=True)
        allowed, status = checker.check_write_path("/any/path/file.txt")
        assert allowed is True
        assert status == "pending"

    def test_allowed_paths_read_in_list(self) -> None:
        """路径在白名单中允许读取。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            checker = FSPermissionChecker(allowed_paths=[tmpdir])
            allowed, reason = checker.check_read_path(os.path.join(tmpdir, "file.txt"))
            assert allowed is True
            assert reason == ""

    def test_allowed_paths_read_not_in_list(self) -> None:
        """路径不在白名单中拒绝读取。"""
        checker = FSPermissionChecker(allowed_paths=["/tmp/data"])
        allowed, reason = checker.check_read_path("/etc/passwd")
        assert allowed is False
        assert "not in allowed paths" in reason

    def test_workspace_root_read_in_workspace(self) -> None:
        """路径在工作路径下允许读取。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            checker = FSPermissionChecker(workspace_root=tmpdir)
            allowed, reason = checker.check_read_path(os.path.join(tmpdir, "sub/file.txt"))
            assert allowed is True
            assert reason == ""

    def test_workspace_root_read_outside_workspace(self) -> None:
        """路径不在工作路径下拒绝读取。"""
        checker = FSPermissionChecker(workspace_root="/home/user/project")
        allowed, reason = checker.check_read_path("/etc/passwd")
        assert allowed is False

    def test_write_path_auto_approved_in_allowed(self) -> None:
        """白名单内的写入自动批准。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            checker = FSPermissionChecker(allowed_paths=[tmpdir], require_approval=True)
            allowed, status = checker.check_write_path(os.path.join(tmpdir, "file.txt"))
            assert allowed is True
            assert status is None  # 自动批准

    def test_write_path_needs_approval_outside_allowed(self) -> None:
        """白名单外的写入需要人工批准。"""
        checker = FSPermissionChecker(allowed_paths=["/tmp/data"], require_approval=True)
        allowed, status = checker.check_write_path("/etc/config.txt")
        assert allowed is True
        assert status == "pending"

    def test_write_path_rejected_no_approval_no_allowed(self) -> None:
        """白名单外且不需要批准时拒绝。"""
        checker = FSPermissionChecker(allowed_paths=["/tmp/data"], require_approval=False)
        allowed, reason = checker.check_write_path("/etc/config.txt")
        assert allowed is False
        assert "not in allowed paths" in reason

    def test_workspace_root_write_auto_approved(self) -> None:
        """工作路径下的写入自动批准。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            checker = FSPermissionChecker(workspace_root=tmpdir, require_approval=True)
            allowed, status = checker.check_write_path(os.path.join(tmpdir, "output.txt"))
            assert allowed is True
            assert status is None

    def test_allowed_paths_property(self) -> None:
        """allowed_paths 属性返回已配置的路径。"""
        checker = FSPermissionChecker(allowed_paths=["/tmp"])
        assert checker.allowed_paths == ["/tmp"]

    def test_allowed_paths_property_none(self) -> None:
        """未配置时 allowed_paths 返回 None。"""
        checker = FSPermissionChecker()
        assert checker.allowed_paths is None

    def test_workspace_root_property(self) -> None:
        """workspace_root 属性返回已配置的路径。"""
        checker = FSPermissionChecker(workspace_root="/home/user/project")
        assert checker.workspace_root == "/home/user/project"

    def test_workspace_root_property_none(self) -> None:
        """未配置时 workspace_root 返回 None。"""
        checker = FSPermissionChecker()
        assert checker.workspace_root is None

    def test_relative_path_normalization(self) -> None:
        """相对路径被标准化为绝对路径。"""
        checker = FSPermissionChecker(allowed_paths=["./data"])
        # 标准化后应该是绝对路径
        assert all(os.path.isabs(p) for p in checker.allowed_paths or [])


# ── WriteApprovalHook 测试 ──


class TestWriteApprovalHook:
    """WriteApprovalHook 人工批准 Hook 测试。"""

    def test_hook_point_is_pre_execute(self) -> None:
        """Hook 触发点是 PRE_EXECUTE。"""
        hook = WriteApprovalHook(FSPermissionChecker())
        assert hook.hook_point.value == "pre_execute"

    async def test_should_trigger_write_ability(self) -> None:
        """写入类 Ability 触发检查。"""
        hook = WriteApprovalHook(FSPermissionChecker())
        for name in ["write_file", "edit_file", "move_file", "delete_file"]:
            ctx = _make_context(current_ability_name=name)
            assert await hook.should_trigger(ctx) is True

    async def test_should_not_trigger_read_ability(self) -> None:
        """读取类 Ability 不触发检查。"""
        hook = WriteApprovalHook(FSPermissionChecker())
        ctx = _make_context(current_ability_name="read_file")
        assert await hook.should_trigger(ctx) is False

    async def test_should_not_trigger_other_ability(self) -> None:
        """其他 Ability 不触发检查。"""
        hook = WriteApprovalHook(FSPermissionChecker())
        ctx = _make_context(current_ability_name="conversation")
        assert await hook.should_trigger(ctx) is False

    async def test_execute_auto_approved(self) -> None:
        """白名单内路径自动批准。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            checker = FSPermissionChecker(allowed_paths=[tmpdir])
            hook = WriteApprovalHook(checker)
            ctx = _make_context(
                current_ability_name="write_file",
                tool_args={"file_path": os.path.join(tmpdir, "file.txt")},
            )
            result = await hook.execute(ctx, None)
            assert result.should_continue is True

    async def test_execute_needs_approval(self) -> None:
        """白名单外路径需要人工批准。"""
        checker = FSPermissionChecker(require_approval=True)
        hook = WriteApprovalHook(checker)
        ctx = _make_context(
            current_ability_name="write_file",
            tool_args={"file_path": "/etc/config.txt"},
        )
        result = await hook.execute(ctx, None)
        assert result.should_continue is False
        assert result.requires_hitl is True
        assert "approval required" in (result.message or "").lower()

    async def test_execute_denied(self) -> None:
        """白名单外且不需要批准时拒绝。"""
        checker = FSPermissionChecker(allowed_paths=["/tmp/data"], require_approval=False)
        hook = WriteApprovalHook(checker)
        ctx = _make_context(
            current_ability_name="write_file",
            tool_args={"file_path": "/etc/config.txt"},
        )
        result = await hook.execute(ctx, None)
        assert result.should_continue is False
        assert "denied" in (result.message or "").lower()

    async def test_execute_no_file_path_continues(self) -> None:
        """没有 file_path 时放行（由 Ability 自身做参数验证）。"""
        hook = WriteApprovalHook(FSPermissionChecker())
        ctx = _make_context(
            current_ability_name="write_file",
            tool_args={},
        )
        result = await hook.execute(ctx, None)
        assert result.should_continue is True

    async def test_execute_move_file_uses_destination_path(self) -> None:
        """move_file 使用 destination_path 检查权限。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            checker = FSPermissionChecker(allowed_paths=[tmpdir])
            hook = WriteApprovalHook(checker)
            ctx = _make_context(
                current_ability_name="move_file",
                tool_args={
                    "source_path": "/tmp/source.txt",
                    "destination_path": os.path.join(tmpdir, "dest.txt"),
                },
            )
            result = await hook.execute(ctx, None)
            assert result.should_continue is True

    async def test_execute_uses_accumulated_data_fallback(self) -> None:
        """tool_args 为空时从 accumulated_data 获取。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            checker = FSPermissionChecker(allowed_paths=[tmpdir])
            hook = WriteApprovalHook(checker)
            ctx = _make_context(
                current_ability_name="write_file",
                tool_args=None,
                accumulated_data={"tool_args": {"file_path": os.path.join(tmpdir, "file.txt")}},
            )
            result = await hook.execute(ctx, None)
            assert result.should_continue is True
