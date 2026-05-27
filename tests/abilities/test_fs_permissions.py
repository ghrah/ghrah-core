# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""文件系统权限模块测试：FSPermissionChecker 和 AccessApprovalHook。"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from ghrah.abilities.builtin.fs_permissions import AccessApprovalHook, FSPermissionChecker
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
        allowed, status = checker.check_read_path("/any/path/file.txt")
        assert allowed is True
        assert status == "pending"

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
            allowed, status = checker.check_read_path(str(Path(tmpdir) / "file.txt"))
            assert allowed is True
            assert status is None

    def test_allowed_paths_read_not_in_list(self) -> None:
        """路径不在白名单中需要审批（require_approval=True）。"""
        checker = FSPermissionChecker(allowed_paths=["/tmp/data"])
        allowed, status = checker.check_read_path("/etc/passwd")
        assert allowed is True
        assert status == "pending"

    def test_allowed_paths_read_not_in_list_no_approval(self) -> None:
        """路径不在白名单中且不需要审批时拒绝读取。"""
        checker = FSPermissionChecker(allowed_paths=["/tmp/data"], require_approval=False)
        allowed, status = checker.check_read_path("/etc/passwd")
        assert allowed is False
        assert "not in allowed paths" in (status or "")

    def test_workspace_root_read_in_workspace(self) -> None:
        """路径在工作路径下允许读取。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            checker = FSPermissionChecker(workspace_root=tmpdir)
            allowed, status = checker.check_read_path(str(Path(tmpdir) / "sub/file.txt"))
            assert allowed is True
            assert status is None

    def test_workspace_root_read_outside_workspace(self) -> None:
        """路径不在工作路径下需要审批（require_approval=True）。"""
        checker = FSPermissionChecker(workspace_root="/home/user/project")
        allowed, status = checker.check_read_path("/etc/passwd")
        assert allowed is True
        assert status == "pending"

    def test_workspace_root_read_outside_workspace_no_approval(self) -> None:
        """路径不在工作路径下且不需要审批时拒绝读取。"""
        checker = FSPermissionChecker(workspace_root="/home/user/project", require_approval=False)
        allowed, status = checker.check_read_path("/etc/passwd")
        assert allowed is False

    def test_write_path_auto_approved_in_allowed(self) -> None:
        """白名单内的写入自动批准。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            checker = FSPermissionChecker(allowed_paths=[tmpdir], require_approval=True)
            allowed, status = checker.check_write_path(str(Path(tmpdir) / "file.txt"))
            assert allowed is True
            assert status is None

    def test_write_path_needs_approval_outside_allowed(self) -> None:
        """白名单外的写入需要人工批准。"""
        checker = FSPermissionChecker(allowed_paths=["/tmp/data"], require_approval=True)
        allowed, status = checker.check_write_path("/etc/config.txt")
        assert allowed is True
        assert status == "pending"

    def test_write_path_rejected_no_approval_no_allowed(self) -> None:
        """白名单外且不需要批准时拒绝。"""
        checker = FSPermissionChecker(allowed_paths=["/tmp/data"], require_approval=False)
        allowed, status = checker.check_write_path("/etc/config.txt")
        assert allowed is False
        assert "not in allowed paths" in (status or "")

    def test_workspace_root_write_auto_approved(self) -> None:
        """工作路径下的写入自动批准。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            checker = FSPermissionChecker(workspace_root=tmpdir, require_approval=True)
            allowed, status = checker.check_write_path(str(Path(tmpdir) / "output.txt"))
            assert allowed is True
            assert status is None

    def test_allowed_paths_property(self) -> None:
        """allowed_paths 属性返回已配置的路径。"""
        checker = FSPermissionChecker(allowed_paths=["/tmp"])
        assert checker.allowed_paths == [str(Path("/tmp").resolve())]

    def test_allowed_paths_property_none(self) -> None:
        """未配置时 allowed_paths 返回 None。"""
        checker = FSPermissionChecker()
        assert checker.allowed_paths is None

    def test_workspace_root_property(self) -> None:
        """workspace_root 属性返回已配置的路径。"""
        checker = FSPermissionChecker(workspace_root="/home/user/project")
        assert checker.workspace_root == str(Path("/home/user/project").resolve())

    def test_workspace_root_property_none(self) -> None:
        """未配置时 workspace_root 返回 None。"""
        checker = FSPermissionChecker()
        assert checker.workspace_root is None

    def test_relative_path_normalization(self) -> None:
        """相对路径被标准化为绝对路径。"""
        checker = FSPermissionChecker(allowed_paths=["./data"])
        assert all(Path(p).is_absolute() for p in checker.allowed_paths or [])


# ── denied_paths 测试 ──


class TestDeniedPaths:
    """denied_paths 黑名单优先级测试。"""

    def test_denied_overrides_allowed_read(self) -> None:
        """denied_paths 优先于 allowed_paths：读取被拒绝。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            secret = Path(tmpdir) / "secret"
            secret.mkdir()
            checker = FSPermissionChecker(
                allowed_paths=[tmpdir],
                denied_paths=[str(secret)],
            )
            allowed, status = checker.check_read_path(str(secret / "file.txt"))
            assert allowed is False
            assert "denied paths" in (status or "")

    def test_denied_overrides_allowed_write(self) -> None:
        """denied_paths 优先于 allowed_paths：写入被拒绝。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            secret = Path(tmpdir) / "secret"
            secret.mkdir()
            checker = FSPermissionChecker(
                allowed_paths=[tmpdir],
                denied_paths=[str(secret)],
            )
            allowed, status = checker.check_write_path(str(secret / "file.txt"))
            assert allowed is False
            assert "denied paths" in (status or "")

    def test_denied_overrides_workspace_read(self) -> None:
        """denied_paths 优先于 workspace_root：读取被拒绝。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            secret = Path(tmpdir) / "secret"
            secret.mkdir()
            checker = FSPermissionChecker(
                workspace_root=tmpdir,
                denied_paths=[str(secret)],
            )
            allowed, status = checker.check_read_path(str(secret / "file.txt"))
            assert allowed is False
            assert "denied paths" in (status or "")

    def test_denied_overrides_workspace_write(self) -> None:
        """denied_paths 优先于 workspace_root：写入被拒绝。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            secret = Path(tmpdir) / "secret"
            secret.mkdir()
            checker = FSPermissionChecker(
                workspace_root=tmpdir,
                denied_paths=[str(secret)],
            )
            allowed, status = checker.check_write_path(str(secret / "file.txt"))
            assert allowed is False
            assert "denied paths" in (status or "")

    def test_denied_paths_property(self) -> None:
        """denied_paths 属性返回已配置的路径。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            checker = FSPermissionChecker(denied_paths=[tmpdir])
            assert checker.denied_paths is not None
            assert all(Path(p).is_absolute() for p in checker.denied_paths)

    def test_denied_paths_property_none(self) -> None:
        """未配置时 denied_paths 返回 None。"""
        checker = FSPermissionChecker()
        assert checker.denied_paths is None

    def test_non_denied_path_still_allowed(self) -> None:
        """非 denied 路径仍然受 allowed 和 workspace 控制。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            secret = Path(tmpdir) / "secret"
            secret.mkdir()
            data = Path(tmpdir) / "data"
            data.mkdir()
            checker = FSPermissionChecker(
                allowed_paths=[str(data)],
                denied_paths=[str(secret)],
            )
            allowed, status = checker.check_read_path(str(data / "file.txt"))
            assert allowed is True
            assert status is None
            allowed, status = checker.check_read_path(str(secret / "file.txt"))
            assert allowed is False

    def test_denied_path_no_approval_bypass(self) -> None:
        """denied_paths 路径即使 require_approval=True 也不进入 pending，直接拒绝。"""
        checker = FSPermissionChecker(
            allowed_paths=["/tmp"],
            denied_paths=["/tmp/secret"],
            require_approval=True,
        )
        allowed, status = checker.check_write_path("/tmp/secret/diary.txt")
        assert allowed is False
        assert "denied paths" in (status or "")

    def test_denied_path_boundary(self) -> None:
        """denied_paths 使用严格前缀匹配（防止 /tmp/data 匹配 /tmp/database）。"""
        checker = FSPermissionChecker(
            allowed_paths=["/tmp"],
            denied_paths=["/tmp/data"],
        )
        # /tmp/database 不应被 denied 路径 /tmp/data 拒绝
        allowed, status = checker.check_read_path("/tmp/database/file.txt")
        assert allowed is True
        assert status is None


# ── check_access 统一审批模型测试 ──


class TestCheckAccess:
    """check_access 统一审批模型测试。"""

    def test_read_needs_approval_outside_allowed(self) -> None:
        """不在白名单的读取路径需要审批。"""
        checker = FSPermissionChecker(
            allowed_paths=["/tmp/data"],
            require_approval=True,
        )
        allowed, status = checker.check_access("/etc/config.txt", operation="read")
        assert allowed is True
        assert status == "pending"

    def test_read_auto_approved_in_allowed(self) -> None:
        """白名单内的读取路径自动批准。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            checker = FSPermissionChecker(allowed_paths=[tmpdir], require_approval=True)
            allowed, status = checker.check_access(str(Path(tmpdir) / "file.txt"), operation="read")
            assert allowed is True
            assert status is None

    def test_read_auto_approved_no_restrictions(self) -> None:
        """无限制且不需要批准时读取自动批准。"""
        checker = FSPermissionChecker(require_approval=False)
        allowed, status = checker.check_access("/any/path", operation="read")
        assert allowed is True
        assert status is None

    def test_read_needs_approval_no_restrictions(self) -> None:
        """无限制但需要批准时读取返回 pending。"""
        checker = FSPermissionChecker(require_approval=True)
        allowed, status = checker.check_access("/any/path", operation="read")
        assert allowed is True
        assert status == "pending"

    def test_read_denied_outside_allowed_no_approval(self) -> None:
        """非白名单且不需要批准时读取被拒绝。"""
        checker = FSPermissionChecker(
            allowed_paths=["/tmp/data"],
            require_approval=False,
        )
        allowed, status = checker.check_access("/etc/passwd", operation="read")
        assert allowed is False
        assert "not in allowed paths" in (status or "")

    def test_write_needs_approval_outside_allowed(self) -> None:
        """不在白名单的写入路径需要审批。"""
        checker = FSPermissionChecker(
            allowed_paths=["/tmp/data"],
            require_approval=True,
        )
        allowed, status = checker.check_access("/etc/config.txt", operation="write")
        assert allowed is True
        assert status == "pending"

    def test_write_auto_approved_in_allowed(self) -> None:
        """白名单内的写入路径自动批准。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            checker = FSPermissionChecker(allowed_paths=[tmpdir], require_approval=True)
            allowed, status = checker.check_access(str(Path(tmpdir) / "file.txt"), operation="write")
            assert allowed is True
            assert status is None

    def test_denied_overrides_allowed_in_check_access(self) -> None:
        """check_access 中 denied_paths 优先于 allowed_paths。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            secret = Path(tmpdir) / "secret"
            secret.mkdir()
            checker = FSPermissionChecker(
                allowed_paths=[tmpdir],
                denied_paths=[str(secret)],
            )
            allowed, status = checker.check_access(str(secret / "file.txt"), operation="read")
            assert allowed is False
            assert "denied paths" in (status or "")

    def test_check_read_path_delegates_to_check_access(self) -> None:
        """check_read_path 委托给 check_access。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            checker = FSPermissionChecker(allowed_paths=[tmpdir])
            allowed, status = checker.check_read_path(str(Path(tmpdir) / "file.txt"))
            assert allowed is True
            assert status is None

    def test_check_write_path_delegates_to_check_access(self) -> None:
        """check_write_path 委托给 check_access。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            checker = FSPermissionChecker(allowed_paths=[tmpdir])
            allowed, status = checker.check_write_path(str(Path(tmpdir) / "file.txt"))
            assert allowed is True
            assert status is None


# ── AccessApprovalHook 测试 ──


class TestAccessApprovalHook:
    """AccessApprovalHook 人工批准 Hook 测试。"""

    def test_hook_point_is_pre_execute(self) -> None:
        """Hook 触发点是 PRE_EXECUTE。"""
        hook = AccessApprovalHook(FSPermissionChecker())
        assert hook.hook_point.value == "pre_execute"

    async def test_should_trigger_write_ability(self) -> None:
        """写入类 Ability 触发检查。"""
        hook = AccessApprovalHook(FSPermissionChecker())
        for name in AccessApprovalHook.WRITE_ABILITIES:
            ctx = _make_context(current_ability_name=name)
            assert await hook.should_trigger(ctx) is True

    async def test_should_trigger_read_ability(self) -> None:
        """读取类 Ability 触发检查。"""
        hook = AccessApprovalHook(FSPermissionChecker())
        for name in AccessApprovalHook.READ_ABILITIES:
            ctx = _make_context(current_ability_name=name)
            assert await hook.should_trigger(ctx) is True

    async def test_should_not_trigger_other_ability(self) -> None:
        """其他 Ability 不触发检查。"""
        hook = AccessApprovalHook(FSPermissionChecker())
        ctx = _make_context(current_ability_name="conversation")
        assert await hook.should_trigger(ctx) is False

    async def test_execute_auto_approved(self) -> None:
        """白名单内路径自动批准。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            checker = FSPermissionChecker(allowed_paths=[tmpdir])
            hook = AccessApprovalHook(checker)
            ctx = _make_context(
                current_ability_name="write_file",
                tool_args={"file_path": str(Path(tmpdir) / "file.txt")},
            )
            result = await hook.execute(ctx, None)
            assert result.should_continue is True

    async def test_execute_needs_approval(self) -> None:
        """白名单外路径需要人工批准。"""
        checker = FSPermissionChecker(require_approval=True)
        hook = AccessApprovalHook(checker)
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
        hook = AccessApprovalHook(checker)
        ctx = _make_context(
            current_ability_name="write_file",
            tool_args={"file_path": "/etc/config.txt"},
        )
        result = await hook.execute(ctx, None)
        assert result.should_continue is False
        assert "denied" in (result.message or "").lower()

    async def test_execute_no_file_path_continues(self) -> None:
        """没有 file_path 时放行（由 Ability 自身做参数验证）。"""
        hook = AccessApprovalHook(FSPermissionChecker())
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
            hook = AccessApprovalHook(checker)
            ctx = _make_context(
                current_ability_name="move_file",
                tool_args={
                    "source_path": "/tmp/source.txt",
                    "destination_path": str(Path(tmpdir) / "dest.txt"),
                },
            )
            result = await hook.execute(ctx, None)
            assert result.should_continue is True

    async def test_execute_uses_accumulated_data_fallback(self) -> None:
        """tool_args 为空时从 accumulated_data 获取。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            checker = FSPermissionChecker(allowed_paths=[tmpdir])
            hook = AccessApprovalHook(checker)
            ctx = _make_context(
                current_ability_name="write_file",
                tool_args=None,
                accumulated_data={"tool_args": {"file_path": str(Path(tmpdir) / "file.txt")}},
            )
            result = await hook.execute(ctx, None)
            assert result.should_continue is True

    async def test_execute_read_ability_uses_dir_path(self) -> None:
        """list_directory 使用 dir_path 检查权限。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            checker = FSPermissionChecker(allowed_paths=[tmpdir])
            hook = AccessApprovalHook(checker)
            ctx = _make_context(
                current_ability_name="list_directory",
                tool_args={"dir_path": tmpdir},
            )
            result = await hook.execute(ctx, None)
            assert result.should_continue is True

    async def test_execute_read_needs_approval(self) -> None:
        """读取操作也需要审批。"""
        checker = FSPermissionChecker(require_approval=True)
        hook = AccessApprovalHook(checker)
        ctx = _make_context(
            current_ability_name="read_file",
            tool_args={"file_path": "/etc/passwd"},
        )
        result = await hook.execute(ctx, None)
        assert result.should_continue is False
        assert result.requires_hitl is True
        assert "read" in (result.message or "").lower()

    async def test_execute_write_needs_approval_message(self) -> None:
        """写入操作审批消息包含 write。"""
        checker = FSPermissionChecker(require_approval=True)
        hook = AccessApprovalHook(checker)
        ctx = _make_context(
            current_ability_name="write_file",
            tool_args={"file_path": "/etc/config.txt"},
        )
        result = await hook.execute(ctx, None)
        assert result.should_continue is False
        assert "write" in (result.message or "").lower()

    async def test_execute_denied_path(self) -> None:
        """denied_paths 路径被拒绝。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            secret = Path(tmpdir) / "secret"
            secret.mkdir()
            checker = FSPermissionChecker(
                allowed_paths=[tmpdir],
                denied_paths=[str(secret)],
            )
            hook = AccessApprovalHook(checker)
            ctx = _make_context(
                current_ability_name="read_file",
                tool_args={"file_path": str(secret / "file.txt")},
            )
            result = await hook.execute(ctx, None)
            assert result.should_continue is False
            assert "denied" in (result.message or "").lower()
