# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""内置 Ability 实现。

提供框架核心 Ability：
- ConversationAbility: 无 tool call，纯 LLM 问答
- EndTaskAbility: 终止循环，生成最终回复
- ReadFileAbility: 文件读取
- ListDirectoryAbility: 目录列表
- WriteFileAbility: 文件写入（创建/覆盖）
- EditFileAbility: 文件编辑（精确字符串替换）
- MoveFileAbility: 文件移动/重命名
- DeleteFileAbility: 文件删除
- ExecuteCommandAbility: 命令执行

集群通信 Ability：
- QueryAgentsAbility: 查询集群中已注册的 Agent 信息
- SendMessageAbility: 向指定 Agent 发送消息（支持同步/异步模式）
- BroadcastMessageAbility: 向所有 Agent 广播消息
- SpawnAgentAbility: 动态创建 Agent
- TerminateAgentAbility: 终止集群中的 Agent

权限模块：
- FSPermissionChecker: 文件系统路径权限检查器
- AccessApprovalHook: 读写操作人工批准 Hook
- WriteApprovalHook: AccessApprovalHook 的向后兼容别名
- CommandSafetyChecker: 命令安全分类器（含子命令路由）
- CommandApprovalHook: 命令执行审批 Hook
"""

from ghrah.abilities.builtin.broadcast_message import BroadcastMessageAbility
from ghrah.abilities.builtin.command_safety import (
    CommandApprovalHook,
    CommandSafetyCategory,
    CommandSafetyChecker,
)
from ghrah.abilities.builtin.conversation import (
    ConversationAbility,
    ConversationDoneHook,
)
from ghrah.abilities.builtin.delete_file import DeleteFileAbility
from ghrah.abilities.builtin.edit_file import EditFileAbility
from ghrah.abilities.builtin.end_task import EndTaskAbility
from ghrah.abilities.builtin.execute_command import (
    ExecuteCommandAbility,
    ExecuteCommandInput,
)
from ghrah.abilities.builtin.fs_permissions import (
    AccessApprovalHook,
    FSPermissionChecker,
    WriteApprovalHook,
)
from ghrah.abilities.builtin.list_directory import ListDirectoryAbility
from ghrah.abilities.builtin.move_file import MoveFileAbility
from ghrah.abilities.builtin.query_agents import QueryAgentsAbility
from ghrah.abilities.builtin.read_file import ReadFileAbility
from ghrah.abilities.builtin.send_message import SendMessageAbility
from ghrah.abilities.builtin.spawn_agent import SpawnAgentAbility
from ghrah.abilities.builtin.terminate_agent import TerminateAgentAbility
from ghrah.abilities.builtin.write_file import WriteFileAbility

__all__ = [
    # 核心 Ability
    "ConversationAbility",
    "EndTaskAbility",
    "ReadFileAbility",
    # 文件系统 Ability
    "ListDirectoryAbility",
    "WriteFileAbility",
    "EditFileAbility",
    "MoveFileAbility",
    "DeleteFileAbility",
    # 命令执行 Ability
    "ExecuteCommandAbility",
    "ExecuteCommandInput",
    # 集群通信 Ability
    "QueryAgentsAbility",
    "SendMessageAbility",
    "BroadcastMessageAbility",
    "SpawnAgentAbility",
    "TerminateAgentAbility",
    # 文件系统权限模块
    "FSPermissionChecker",
    "AccessApprovalHook",
    "WriteApprovalHook",
    # 命令安全模块
    "CommandSafetyChecker",
    "CommandApprovalHook",
    "CommandSafetyCategory",
    # 内建 Hook
    "ConversationDoneHook",
]


def _register_builtin_hooks() -> None:
    """注册内建 Hook 到 BuiltinHookRegistry。

    此函数在模块加载时执行（本文件末尾），将内建 Hook 类注册到
    BuiltinHookRegistry 的进程级注册表。属于模块级副作用：
    仅 import ghrah.abilities.builtin 即会触发注册。
    """
    from ghrah.abilities.hook_registry import BuiltinHookRegistry

    BuiltinHookRegistry.register("conversation_done", ConversationDoneHook)
    BuiltinHookRegistry.register("write_approval", WriteApprovalHook)
    BuiltinHookRegistry.register("command_approval", CommandApprovalHook)


_register_builtin_hooks()
