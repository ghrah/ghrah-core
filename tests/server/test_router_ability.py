# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""MessageRouter._create_ability_from_def 单元测试。

覆盖 Stage 0 修复：
- 文件系统类 ability（含 edit_file/move_file/delete_file）的 permission_checker 注入
- execute_command 的 CommandApprovalHook 注入（HITL 生效）

测试不经过网络层，直接调用 _create_ability_from_def 验证实例化结果。
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from ghrah.protocol.types import AbilityDefinitionPayload

from ghrah.abilities.builtin.command_safety import CommandApprovalHook
from ghrah.abilities.builtin.delete_file import DeleteFileAbility
from ghrah.abilities.builtin.edit_file import EditFileAbility
from ghrah.abilities.builtin.execute_command import ExecuteCommandAbility
from ghrah.abilities.builtin.fs_permissions import FSPermissionChecker
from ghrah.abilities.builtin.move_file import MoveFileAbility
from ghrah.abilities.builtin.write_file import WriteFileAbility
from ghrah.communication.supervisor import SupervisorActor
from ghrah.core.server.connection_manager import ConnectionManager
from ghrah.core.server.event_bus import EventBus
from ghrah.core.server.router import MessageRouter

# ─── Fixtures ───


@pytest.fixture
def mock_supervisor():
    supervisor = MagicMock(spec=SupervisorActor)
    return supervisor


@pytest.fixture
def connection_manager():
    return ConnectionManager()


@pytest.fixture
def event_bus(connection_manager):
    return EventBus(connection_manager)


@pytest.fixture
def router(mock_supervisor, connection_manager, event_bus):
    return MessageRouter(
        connection_manager=connection_manager,
        event_bus=event_bus,
    )


def _make_ability_def(ability_type: str, **params) -> AbilityDefinitionPayload:
    """构造 AbilityDefinitionPayload 辅助函数。"""
    return AbilityDefinitionPayload(
        ability_type=ability_type,
        params=params,
    )


# ─── 文件系统 ability permission_checker 注入 ───


class TestFSAbilityPermissionInjection:
    """文件系统类 ability 的 permission_checker 注入测试。"""

    def test_edit_file_with_permissions_gets_checker(self, router: MessageRouter):
        """edit_file 带权限参数 → FSPermissionChecker 注入。"""
        ability_def = _make_ability_def(
            "edit_file",
            require_hitl=False,
            allowed_paths=["/tmp/workspace"],
            workspace_root="/tmp/workspace",
        )
        ability = router._create_ability_from_def(ability_def)

        assert isinstance(ability, EditFileAbility)
        assert ability._checker is not None
        assert isinstance(ability._checker, FSPermissionChecker)
        assert ability._checker.workspace_root == str(
            __import__("pathlib").Path("/tmp/workspace").resolve()
        )

    def test_edit_file_without_permissions_gets_no_checker(self, router: MessageRouter):
        """edit_file 无权限参数 → checker 为 None（安全降级，现有设计）。"""
        ability_def = _make_ability_def("edit_file")
        ability = router._create_ability_from_def(ability_def)

        assert isinstance(ability, EditFileAbility)
        assert ability._checker is None

    def test_move_file_with_permissions(self, router: MessageRouter):
        """move_file 带权限参数 → FSPermissionChecker 注入。"""
        ability_def = _make_ability_def(
            "move_file",
            require_hitl=True,
            allowed_paths=["/tmp/workspace"],
            denied_paths=["/tmp/workspace/secrets"],
        )
        ability = router._create_ability_from_def(ability_def)

        assert isinstance(ability, MoveFileAbility)
        assert ability._checker is not None
        assert ability._checker.denied_paths is not None

    def test_delete_file_with_permissions(self, router: MessageRouter):
        """delete_file 带权限参数 → FSPermissionChecker 注入。"""
        ability_def = _make_ability_def(
            "delete_file",
            require_hitl=False,
            allowed_paths=["/tmp/workspace"],
        )
        ability = router._create_ability_from_def(ability_def)

        assert isinstance(ability, DeleteFileAbility)
        assert ability._checker is not None

    def test_edit_file_require_hitl_true_when_specified(self, router: MessageRouter):
        """edit_file require_hitl=True → checker.require_approval 为 True。"""
        ability_def = _make_ability_def(
            "edit_file",
            require_hitl=True,
            allowed_paths=["/tmp/workspace"],
        )
        ability = router._create_ability_from_def(ability_def)

        assert isinstance(ability, EditFileAbility)
        assert ability._checker is not None
        # require_hitl=True → checker 内部 require_approval=True
        allowed, status = ability._checker.check_access(
            "/tmp/outside/file.txt", "write"
        )
        # /tmp/outside 不在白名单 → require_approval=True 时返回 (True, "pending")
        assert allowed is True
        assert status == "pending"


# ─── execute_command CommandApprovalHook 注入 ───


class TestExecuteCommandHookInjection:
    """execute_command 的 CommandApprovalHook 注入测试。"""

    def test_execute_command_with_require_approval_has_hook(self, router: MessageRouter):
        """execute_command + require_approval=True → 挂载 CommandApprovalHook。"""
        ability_def = _make_ability_def("execute_command", require_approval=True)
        ability = router._create_ability_from_def(ability_def)

        assert isinstance(ability, ExecuteCommandAbility)
        hooks = ability.get_hooks()
        assert len(hooks) == 1
        assert isinstance(hooks[0], CommandApprovalHook)
        # command_checker 已注入
        assert ability._checker is not None

    def test_execute_command_default_require_approval_true(self, router: MessageRouter):
        """execute_command 无 params → 默认 require_approval=True（保守）。"""
        ability_def = _make_ability_def("execute_command")
        ability = router._create_ability_from_def(ability_def)

        assert isinstance(ability, ExecuteCommandAbility)
        hooks = ability.get_hooks()
        assert len(hooks) == 1
        assert isinstance(hooks[0], CommandApprovalHook)

    def test_execute_command_require_approval_false(self, router: MessageRouter):
        """execute_command + require_approval=False → 关闭审批。"""
        ability_def = _make_ability_def("execute_command", require_approval=False)
        ability = router._create_ability_from_def(ability_def)

        assert isinstance(ability, ExecuteCommandAbility)
        hooks = ability.get_hooks()
        assert len(hooks) == 1
        # hook 始终挂载（显式注入策略），但 checker 的 require_approval=False
        assert ability._checker._require_approval is False

    def test_execute_command_require_approval_not_passed_to_constructor(
        self, router: MessageRouter
    ):
        """require_approval 标记不应透传给 ExecuteCommandAbility 构造函数。

        ExecuteCommandAbility 构造函数不接受 require_approval 参数，
        若未 pop 会抛 TypeError。
        """
        ability_def = _make_ability_def("execute_command", require_approval=True)
        # 不应抛 TypeError
        ability = router._create_ability_from_def(ability_def)
        assert isinstance(ability, ExecuteCommandAbility)


# ─── 回归：原有 fs ability 不受影响 ───


class TestRegressionFSAbilities:
    """回归测试：read_file/write_file/list_directory 行为不变。"""

    def test_read_file_with_permissions(self, router: MessageRouter):
        """read_file 带权限参数 → FSPermissionChecker 注入（原有行为）。"""
        ability_def = _make_ability_def(
            "read_file",
            require_hitl=False,
            allowed_paths=["/tmp/workspace"],
        )
        ability = router._create_ability_from_def(ability_def)

        assert ability._checker is not None
        assert isinstance(ability._checker, FSPermissionChecker)

    def test_write_file_with_permissions(self, router: MessageRouter):
        """write_file 带权限参数 → FSPermissionChecker 注入（原有行为）。"""
        ability_def = _make_ability_def(
            "write_file",
            require_hitl=False,
            allowed_paths=["/tmp/workspace"],
        )
        ability = router._create_ability_from_def(ability_def)

        assert isinstance(ability, WriteFileAbility)
        assert ability._checker is not None
