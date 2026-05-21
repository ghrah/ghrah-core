# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""Ability 层：Agent 能力的接口契约和 Hook 控制流。

核心抽象：
- Ability: 能力基类（= Rust Trait）
- ActionResult / ActionOutcome: 执行结果
- Hook / HookPoint / HookResult: 控制流机制
- AbilityExecutionContext: 执行上下文
- AbilityRegistry: 工厂注册表（类型名 → Ability 类映射）
- AbilityExecutor / LocalAbilityExecutor: 执行器（将执行与 Agent 循环解耦）

内置 Ability（builtin）：
- ConversationAbility: 无 tool call，纯 LLM 问答（内置终止 Hook）
- EndTaskAbility: 终止循环，生成最终回复
- ReadFileAbility: 文件读取（1 Ability = 1 Tool Call）
- WriteFileAbility: 文件写入（创建/覆盖）
- EditFileAbility: 文件编辑（精确字符串替换）
- MoveFileAbility: 文件移动/重命名
- DeleteFileAbility: 文件删除
- ExecuteCommandAbility: 命令执行

集群通信 Ability：
- QueryAgentsAbility: 查询集群中已注册的 Agent 信息
- SendMessageAbility: 向指定 Agent 发送消息
- BroadcastMessageAbility: 向所有 Agent 广播消息
- SpawnAgentAbility: 动态创建平级 Agent

权限模块：
- FSPermissionChecker: 文件系统路径权限检查器
- WriteApprovalHook: 写入操作人工批准 Hook
- CommandSafetyChecker: 命令安全分类器（含子命令路由）
- CommandApprovalHook: 命令执行审批 Hook
"""

from ghrah.abilities.base import Ability, ActionOutcome, ActionResult
from ghrah.abilities.builtin.cluster import (
    BroadcastMessageAbility,
    QueryAgentsAbility,
    SendMessageAbility,
    SpawnAgentAbility,
)
from ghrah.abilities.builtin.command_safety import (
    CommandApprovalHook,
    CommandSafetyCategory,
    CommandSafetyChecker,
)
from ghrah.abilities.builtin.conversation import ConversationAbility
from ghrah.abilities.builtin.delete_file import DeleteFileAbility
from ghrah.abilities.builtin.edit_file import EditFileAbility
from ghrah.abilities.builtin.end_task import EndTaskAbility
from ghrah.abilities.builtin.execute_command import (
    ExecuteCommandAbility,
    ExecuteCommandInput,
)
from ghrah.abilities.builtin.fs_permissions import FSPermissionChecker, WriteApprovalHook
from ghrah.abilities.builtin.list_directory import ListDirectoryAbility
from ghrah.abilities.builtin.move_file import MoveFileAbility
from ghrah.abilities.builtin.read_file import ReadFileAbility
from ghrah.abilities.builtin.write_file import WriteFileAbility
from ghrah.abilities.context import AbilityExecutionContext
from ghrah.abilities.executor import AbilityExecutor, LocalAbilityExecutor, RemoteAbilityExecutor
from ghrah.abilities.hooks import Hook, HookPoint, HookResult
from ghrah.abilities.registry import AbilityRegistry


def _register_builtin_abilities() -> None:
    """注册所有内置 Ability 到 AbilityRegistry。

    在模块加载时自动调用，确保所有内置 Ability 类型名可用。
    显式注册优先于隐式发现。
    """
    AbilityRegistry.register("conversation", ConversationAbility)
    AbilityRegistry.register("end_task", EndTaskAbility)
    AbilityRegistry.register("read_file", ReadFileAbility)
    AbilityRegistry.register("list_directory", ListDirectoryAbility)
    AbilityRegistry.register("write_file", WriteFileAbility)
    AbilityRegistry.register("edit_file", EditFileAbility)
    AbilityRegistry.register("move_file", MoveFileAbility)
    AbilityRegistry.register("delete_file", DeleteFileAbility)
    AbilityRegistry.register("execute_command", ExecuteCommandAbility)
    AbilityRegistry.register("query_agents", QueryAgentsAbility)
    AbilityRegistry.register("send_message", SendMessageAbility)
    AbilityRegistry.register("broadcast_message", BroadcastMessageAbility)
    AbilityRegistry.register("spawn_agent", SpawnAgentAbility)


# 模块加载时自动注册内置 Ability
_register_builtin_abilities()

__all__ = [
    # 核心抽象
    "Ability",
    "ActionOutcome",
    "ActionResult",
    "AbilityExecutionContext",
    "Hook",
    "HookPoint",
    "HookResult",
    # 执行器
    "AbilityExecutor",
    "LocalAbilityExecutor",
    "RemoteAbilityExecutor",
    # 工厂注册表
    "AbilityRegistry",
    # 内置 Ability
    "ConversationAbility",
    "EndTaskAbility",
    "ReadFileAbility",
    "ListDirectoryAbility",
    "WriteFileAbility",
    "EditFileAbility",
    "MoveFileAbility",
    "DeleteFileAbility",
    "ExecuteCommandAbility",
    "ExecuteCommandInput",
    # 集群通信 Ability
    "QueryAgentsAbility",
    "SendMessageAbility",
    "BroadcastMessageAbility",
    "SpawnAgentAbility",
    # 文件系统权限模块
    "FSPermissionChecker",
    "WriteApprovalHook",
    # 命令安全模块
    "CommandSafetyChecker",
    "CommandApprovalHook",
    "CommandSafetyCategory",
]
