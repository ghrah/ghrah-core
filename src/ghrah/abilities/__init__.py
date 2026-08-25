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
- SendMessageAbility: 向指定 Agent 发送消息（支持同步/异步模式）
- BroadcastMessageAbility: 向所有 Agent 广播消息
- SpawnAgentAbility: 动态创建平级 Agent
- TerminateAgentAbility: 终止集群中的 Agent

权限模块：
- FSPermissionChecker: 文件系统路径权限检查器
- AccessApprovalHook: 读写操作人工批准 Hook
- WriteApprovalHook: AccessApprovalHook 的向后兼容别名
- CommandSafetyChecker: 命令安全分类器（含子命令路由）
- CommandApprovalHook: 命令执行审批 Hook
"""

from ghrah.abilities.base import Ability
from ghrah.abilities.builtin.broadcast_message import BroadcastMessageAbility
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
from ghrah.abilities.context import AbilityExecutionContext
from ghrah.abilities.errors import AbilityError, AbilityNotFoundError
from ghrah.abilities.execution_data import (
    COT_CONTENT,
    CUMULATIVE_TOKEN_USAGE,
    FINAL_RESPONSE,
    LLM_RESPONSE,
    TOOL_ARGS,
    DataKey,
    ExecutionData,
)
from ghrah.abilities.execution_frame import ExecutionFrame
from ghrah.abilities.execution_services import (
    AGENT_NAME,
    CONTEXT_MANAGER,
    SUPERVISOR,
    ExecutionServices,
    ServiceKey,
)
from ghrah.abilities.executor import AbilityExecutor, LocalAbilityExecutor
from ghrah.abilities.hook_context import HookContext
from ghrah.abilities.hook_runner import HookRunner
from ghrah.abilities.hook_store import HookStore
from ghrah.abilities.hooks import Hook, HookPoint, HookResult, HookScope
from ghrah.abilities.invocation import AbilityInvocation
from ghrah.abilities.paths import (
    ABILITY_PATH_SPECS,
    AbilityPathSpec,
    extract_paths,
    is_subpath,
    resolve_fs_permission_paths,
)
from ghrah.abilities.registry import AbilityRegistry
from ghrah.types.results import ActionOutcome, ActionResult

FS_ABILITY_TYPES: frozenset[str] = frozenset(
    {
        "read_file",
        "write_file",
        "list_directory",
        "edit_file",
        "move_file",
        "delete_file",
    }
)
"""文件系统类 Ability 的 handler 类型集合（单一真源）。

runner（本地实例化）与 router（分布式实例化）共用此集合，
避免 `_fs_handler_types` / `_fs_ability_types` 两份副本漂移。
"""

CLUSTER_ABILITY_TYPES: frozenset[str] = frozenset(
    {
        "query_agents",
        "send_message",
        "broadcast_message",
        "spawn_agent",
        "terminate_agent",
    }
)
"""集群通信类 Ability 的 handler 类型集合（单一真源）。"""


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
    AbilityRegistry.register("terminate_agent", TerminateAgentAbility)


# 模块加载时自动注册内置 Ability
_register_builtin_abilities()

__all__ = [
    # 共享常量（单一真源）
    "FS_ABILITY_TYPES",
    "CLUSTER_ABILITY_TYPES",
    # 核心抽象
    "Ability",
    "ActionOutcome",
    "ActionResult",
    "AbilityError",
    "AbilityNotFoundError",
    "AbilityExecutionContext",
    "AbilityInvocation",
    "DataKey",
    "ExecutionData",
    "TOOL_ARGS",
    "LLM_RESPONSE",
    "COT_CONTENT",
    "CUMULATIVE_TOKEN_USAGE",
    "FINAL_RESPONSE",
    "ServiceKey",
    "ExecutionServices",
    "CONTEXT_MANAGER",
    "SUPERVISOR",
    "AGENT_NAME",
    "ExecutionFrame",
    "HookContext",
    "HookStore",
    "HookRunner",
    "HookScope",
    "Hook",
    "HookPoint",
    "HookResult",
    # 执行器
    "AbilityExecutor",
    "LocalAbilityExecutor",
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
    "TerminateAgentAbility",
    # 文件系统权限模块
    "FSPermissionChecker",
    "AccessApprovalHook",
    "WriteApprovalHook",
    # 命令安全模块
    "CommandSafetyChecker",
    "CommandApprovalHook",
    "CommandSafetyCategory",
    # 路径工具模块
    "is_subpath",
    "AbilityPathSpec",
    "ABILITY_PATH_SPECS",
    "extract_paths",
    "resolve_fs_permission_paths",
]
