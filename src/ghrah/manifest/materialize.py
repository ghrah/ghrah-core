# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""Manifest 物化：ResolvedAbility → Ability 实例（对齐独立库 runner 范式）。

将 ``ManifestResolver.resolve`` 产出的 ``ResolvedAgent`` 直接物化为
``Ability`` 列表，不经 wire DTO（``AbilityDefinitionPayload``）往返——
CoreUnit 与 ManifestStore 同进程，无需序列化成 wire 格式再反序列化回来。

行为基准：``ghrah-core/examples/agents_manifest/runner.py`` 的
``_instantiate_ability`` + ``_make_permission_checker``。
``ResolvedAbility.permissions``（``PermissionFlags``）直接喂
``FSPermissionChecker``，无 ``PermissionFlags → params dict → 再重建``
的往返。

非 builtin 能力（``implementation.type != "builtin"`` 或无 ``handler``）
跳过 + warning（保留 subject 侧物化器宽松语义，区别于独立库 runner 的
``raise ValueError``——避免一个非 builtin 中断整个 spawn）。
"""

from __future__ import annotations

import logging
from typing import Any

from ghrah.abilities import (
    FS_ABILITY_TYPES,
    AbilityRegistry,
    CommandApprovalHook,
    CommandSafetyChecker,
    FSPermissionChecker,
    resolve_fs_permission_paths,
)
from ghrah.core.ability_protocol import AbilityProtocol
from ghrah.manifest.resolver import ResolvedAbility

__all__ = ["instantiate_resolved_abilities"]

logger = logging.getLogger(__name__)


def instantiate_resolved_abilities(
    resolved_abilities: list[ResolvedAbility],
    *,
    workspace_root: str | None,
    auto_approve_abilities: tuple[str, ...] = (),
    require_approval_by_default: bool = True,
    command_runner: Any = None,
) -> list[AbilityProtocol]:
    """ResolvedAbility → Ability 实例列表（对齐独立库 runner 范式）。

    权限经 ``resolve_fs_permission_paths`` 解析 ``{{workspace}}`` 模板后
    直接喂 ``FSPermissionChecker``（不经 params dict 往返）。

    HITL 覆盖层（与 ``_create_ability_from_def`` 同语义，平移自 subject
    侧旧 HITLPolicy 覆盖层）：决策优先级
    ``auto_approve > manifest require_hitl > 兜底默认``。

    Args:
        resolved_abilities: ``ManifestResolver.resolve`` 产出的已解析能力列表
        workspace_root: 工作区根目录（模板基准 + 路径解析基准），
            None 表示不限制
        auto_approve_abilities: HITL 运行时覆盖层——强制放行的能力名白名单
        require_approval_by_default: manifest 未声明审批要求时的兜底策略
        command_runner: execute_command 能力的命令执行器注入
            （None = standalone 直跑 subprocess）

    Returns:
        已实例化的 Ability 列表（非 builtin 已跳过 + warning）
    """
    template_vars = {"workspace": workspace_root} if workspace_root else {}
    abilities: list[AbilityProtocol] = []
    for ra in resolved_abilities:
        handler = ra.implementation.handler
        if ra.implementation.type != "builtin" or not handler:
            logger.warning(
                "Skipping non-builtin ability '%s' (type=%s) in manifest spawn",
                ra.ability_name,
                ra.implementation.type,
            )
            continue
        ability = _instantiate_ability(
            ra,
            handler=handler,
            workspace_root=workspace_root,
            template_vars=template_vars,
            auto_approved=handler in auto_approve_abilities,
            require_approval_by_default=require_approval_by_default,
            command_runner=command_runner,
        )
        abilities.append(ability)
    return abilities


def _instantiate_ability(
    ra: ResolvedAbility,
    *,
    handler: str,
    workspace_root: str | None,
    template_vars: dict[str, str],
    auto_approved: bool,
    require_approval_by_default: bool,
    command_runner: Any,
) -> AbilityProtocol:
    """单个 ResolvedAbility → Ability（对齐 runner._instantiate_ability）。"""
    permissions = ra.permissions

    if handler == "conversation":
        return AbilityRegistry.create("conversation")

    if handler == "end_task":
        return AbilityRegistry.create("end_task", mode="toolcall")

    if handler in FS_ABILITY_TYPES or _has_fs_permission_fields(permissions):
        checker = _make_fs_permission_checker(
            permissions,
            workspace_root=workspace_root,
            template_vars=template_vars,
            auto_approved=auto_approved,
            require_approval_by_default=require_approval_by_default,
        )
        return AbilityRegistry.create(handler, permission_checker=checker)

    if handler == "execute_command":
        command_checker, hooks = _make_command_approval(
            permissions,
            auto_approved=auto_approved,
            require_approval_by_default=require_approval_by_default,
            command_runner=command_runner,
        )
        params: dict[str, Any] = {
            "command_checker": command_checker,
            "hooks": hooks,
        }
        if command_runner is not None:
            params["command_runner"] = command_runner
        return AbilityRegistry.create("execute_command", **params)

    return AbilityRegistry.create(handler)


def _has_fs_permission_fields(permissions: Any) -> bool:
    """是否携带 FS 权限字段（对齐 subject 旧 materialize_permission_params 触发条件）。"""
    return bool(
        permissions.fs_read_only
        or permissions.fs_write
        or permissions.allowed_paths
        or permissions.denied_paths
    )


def _make_fs_permission_checker(
    permissions: Any,
    *,
    workspace_root: str | None,
    template_vars: dict[str, str],
    auto_approved: bool,
    require_approval_by_default: bool,
) -> FSPermissionChecker:
    """PermissionFlags → FSPermissionChecker（对齐 runner._make_permission_checker）。

    模板变量 ``{{workspace}}`` 经 ``resolve_fs_permission_paths`` 展开；
    HITL 覆盖层 ``auto_approve > manifest require_hitl > 兜底默认``。
    """
    allowed_paths = permissions.allowed_paths or None
    denied_paths = permissions.denied_paths or None
    if workspace_root:
        allowed_paths, denied_paths = resolve_fs_permission_paths(
            allowed_paths,
            denied_paths,
            template_vars,
            workspace_root,
        )

    if auto_approved:
        require_approval = False
    else:
        # FS 分支已触发即视为 manifest 显式声明 require_hitl（对齐
        # _create_ability_from_def：FS 分支内 require_hitl 作显式值，默认 False）；
        # auto_approve > manifest require_hitl > 兜底默认
        require_approval = bool(permissions.require_hitl)

    return FSPermissionChecker(
        allowed_paths=allowed_paths,
        workspace_root=workspace_root,
        denied_paths=denied_paths,
        require_approval=require_approval,
    )


def _make_command_approval(
    permissions: Any,
    *,
    auto_approved: bool,
    require_approval_by_default: bool,
    command_runner: Any,
) -> tuple[CommandSafetyChecker, list[CommandApprovalHook]]:
    """execute_command 审批构造（对齐 _create_ability_from_def 的 execute_command 分支）。"""
    if auto_approved:
        require_approval = False
    else:
        require_approval = (
            bool(permissions.require_hitl) or require_approval_by_default
        )
    command_checker = CommandSafetyChecker(require_approval=require_approval)
    return command_checker, [CommandApprovalHook(command_checker)]
