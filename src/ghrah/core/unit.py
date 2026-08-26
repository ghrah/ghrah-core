# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""Core Unit 挂载形态 — 将 ghrah-core 包装为可挂载的 Unit。

ghrah-core 正从「独立 WS 服务器进程」重构为「可挂载的 Unit 形态」。
挂载宿主是 subject 侧的 Ouroboros 运行时，但本模块 **不 import
宿主运行时与 subject 包**：``CoreUnit`` 是纯 duck-typed 对象，
形状与 subject 侧桥 ``mount_unit`` 的契约严格兼容：

- ``unit.meta``：``.name`` / ``.requires`` / ``.provides`` / ``.routes``
  （routes 含 ``commands`` / ``long_running_commands`` / ``events`` 三个
  frozenset[str]，requires/provides 元素含 ``.name`` 属性）
- 生命周期：``await unit.init(ctx)`` → 路由注册 → ``await unit.start()``；
  卸载时 ``await unit.stop()``
- 命令：``await unit.handle_command(command, payload, cmd_ctx) -> dict``
- 事件：``await unit.handle_event(event_type, payload)``（core unit 不消费事件）

ctx 视为 duck-typed ``Any``，仅用到 ``ctx.emit(name, payload)``
（fire-and-forget）与 ``ctx.provide(name, value)``。

事件命名约定：core 域事件经 ``ctx.emit(f"core:{event_type}", payload_dict)``
发送，``core:`` 前缀防止与 subject/observer 域事件冲突。
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from ghrah.abilities.context import AbilityExecutionContext
from ghrah.communication.errors import RegistryError
from ghrah.communication.supervisor import SupervisorActor
from ghrah.core.ability_protocol import AbilityProtocol
from ghrah.core.config.builders import (
    build_context_from_dict,
    build_model_overrides_from_dict,
    build_window_from_dict,
)
from ghrah.core.event_publisher import EventPublisher
from ghrah.core.events import (
    ActionChainUpdatedEvent,
    AgentErrorEvent,
    AgentResponseEvent,
    CoreEvent,
    CoreEventType,
    HITLRequestEvent,
    SessionArchivedEvent,
    SessionCreatedEvent,
    SessionDeletedEvent,
    SessionSwitchedEvent,
)
from ghrah.core.room_protocol import SerialRoomBridge
from ghrah.protocol.types import (
    AbilityResultPayload,
    BroadcastMessagePayload,
    CommandType,
    DelegatePayload,
    EventType,
    ExecuteAbilityPayload,
    GetAgentInfoPayload,
    HITLResponsePayload,
    RegisterAbilityPayload,
    SendMessagePayload,
    SessionArchivePayload,
    SessionCreatePayload,
    SessionDeletePayload,
    SessionListPayload,
    SessionSwitchPayload,
    SpawnAgentPayload,
    TerminateAgentPayload,
    UnregisterAbilityPayload,
    generate_request_id,
)
from ghrah.types.config_types import AgentConfig
from ghrah.types.results import ActionOutcome

logger = logging.getLogger(__name__)

__all__ = [
    "CoreUnitConfig",
    "UnitEventPublisher",
    "CoreUnit",
    "create_core_unit",
]


# ----------------------------------------------------------------
# 配置
# ----------------------------------------------------------------


@dataclass(frozen=True)
class CoreUnitConfig:
    """CoreUnit 配置。

    Attributes:
        cluster_id: SupervisorActor 的集群标识
        default_timeout: Agent 间通信默认超时（秒）
        hitl_timeout: HITL 审批等待超时（秒）。
            AgentBuilder 不透传 hitl_timeout 到 LocalAbilityExecutor，
            CoreUnit 在 spawn 后对 executor 做 best-effort 调整。
        workspace_root: 工作区根目录默认值；AgentConfig 未显式指定时应用
            （None 表示不限制）。
        auto_approve_abilities: HITL 运行时覆盖层——管理员强制放行的能力名
            白名单（覆盖 manifest 的 require_hitl=True；语义平移自 subject
            侧旧 HITLPolicy 的同名覆盖层）。
        require_approval_by_default: 对 manifest 未声明审批要求的能力的兜底
            策略（语义平移自旧 HITLPolicy）。
        command_runner: execute_command 能力的命令执行器注入（per-cluster
            构造期注入，duck-typed ``run_command``；None = standalone 直跑
            subprocess）。Subject 挂载模式下传 SandboxExecutor。
        persistence_factory: per-agent 持久化后端工厂
            （``(AgentConfig) -> PersistenceBackend | None``；None = Core
            内建 sqlite）。新 spawn 生效，存量 agent 不受影响。
    """

    cluster_id: str = "default"
    default_timeout: float = 300.0
    hitl_timeout: float = 300.0
    workspace_root: str | None = None
    auto_approve_abilities: tuple[str, ...] = ()
    require_approval_by_default: bool = True
    command_runner: Any = None
    persistence_factory: Callable[[Any], Any] | None = None


# ----------------------------------------------------------------
# 桥契约形状（本地轻量复刻，不 import subject）
# ----------------------------------------------------------------


@dataclass(frozen=True)
class _ServiceKey:
    """服务键 — 仅需 ``.name`` 属性（bridge 做 ``[key.name for key in ...]``）。"""

    name: str


@dataclass(frozen=True)
class _RouteSpec:
    """路由声明 — 复刻 subject 侧 RouteSpec 三字段形状。"""

    commands: frozenset[str] = frozenset()
    long_running_commands: frozenset[str] = frozenset()
    events: frozenset[str] = frozenset()


@dataclass(frozen=True)
class _UnitMeta:
    """Unit 元数据 — duck-typed 对齐 subject 侧 mount_unit 桥契约。"""

    name: str
    requires: frozenset[_ServiceKey]
    provides: frozenset[_ServiceKey]
    routes: _RouteSpec


# 17 个命令：CommandType 的 .value 字符串
_COMMANDS: frozenset[str] = frozenset(
    {
        CommandType.SPAWN_AGENT.value,
        CommandType.TERMINATE_AGENT.value,
        CommandType.SEND_MESSAGE.value,
        CommandType.BROADCAST_MESSAGE.value,
        CommandType.REGISTER_ABILITY.value,
        CommandType.UNREGISTER_ABILITY.value,
        CommandType.LIST_AGENTS.value,
        CommandType.HEALTH_CHECK.value,
        CommandType.DELEGATE.value,
        CommandType.GET_AGENT_INFO.value,
        CommandType.EXECUTE_ABILITY.value,
        CommandType.HITL_RESPONSE.value,
        CommandType.SESSION_CREATE.value,
        CommandType.SESSION_SWITCH.value,
        CommandType.SESSION_LIST.value,
        CommandType.SESSION_ARCHIVE.value,
        CommandType.SESSION_DELETE.value,
    }
)


# ----------------------------------------------------------------
# 事件发布器：Core → ctx.emit
# ----------------------------------------------------------------


def _core_event_to_dict(event: CoreEvent) -> tuple[str, dict[str, Any]]:
    """将 CoreEvent 转换为 (event_type_str, payload_dict)。

    序列化逻辑对齐原 WS 服务器形态事件消息的 payload
    组装部分，但输出纯 dict，不包 WS Message/Envelope。
    """
    event_type_map: dict[str, str] = {
        CoreEventType.HITL_REQUEST.value: "hitl_request",
        CoreEventType.ACTION_CHAIN_UPDATED.value: "action_chain_updated",
        CoreEventType.AGENT_ERROR.value: "agent_error",
        CoreEventType.AGENT_RESPONSE.value: "agent_response",
        CoreEventType.SESSION_CREATED.value: "session_created",
        CoreEventType.SESSION_SWITCHED.value: "session_switched",
        CoreEventType.SESSION_ARCHIVED.value: "session_archived",
        CoreEventType.SESSION_DELETED.value: "session_deleted",
    }

    payload: dict[str, Any] = {
        "agent_name": event.agent_name,
        "event_type": event_type_map.get(event.event_type.value, event.event_type.value),
    }

    if isinstance(event, HITLRequestEvent):
        payload.update(
            {
                "ability_name": event.ability_name,
                "tool_call": event.tool_call,
                "context": event.context,
            }
        )
    elif isinstance(event, ActionChainUpdatedEvent):
        payload.update({"node": event.node})
    elif isinstance(event, AgentErrorEvent):
        payload.update({"error": event.error})
    elif isinstance(event, AgentResponseEvent):
        payload_update: dict[str, Any] = {
            "content": event.content,
            "message_type": event.message_type,
            "metadata": event.metadata,
        }
        if event.content_blocks is not None:
            payload_update["content_blocks"] = event.content_blocks
        payload.update(payload_update)
    elif isinstance(event, SessionCreatedEvent):
        payload.update(
            {
                "session_id": event.session_id,
                "branch_name": event.branch_name,
                "parent_session_id": event.parent_session_id,
                "fork_point_node_id": event.fork_point_node_id,
            }
        )
    elif isinstance(event, SessionSwitchedEvent):
        payload.update(
            {
                "session_id": event.session_id,
                "branch_name": event.branch_name,
            }
        )
    elif isinstance(event, SessionArchivedEvent):
        payload.update({"session_id": event.session_id})
    elif isinstance(event, SessionDeletedEvent):
        payload.update({"session_id": event.session_id})

    event_type_str = event_type_map.get(event.event_type.value, event.event_type.value)
    return event_type_str, payload


class UnitEventPublisher(EventPublisher):
    """Core → ctx.emit 事件发布器（Unit 挂载模式）。

    将 CoreEvent 序列化为纯 dict，经宿主 ctx.emit 以
    ``core:{event_type}`` 名称发送（fire-and-forget）。
    emit 为 None 时退化为 Null 行为（仅日志），用于 standalone 场景。
    """

    def __init__(self, emit: Callable[[str, dict[str, Any]], None] | None = None) -> None:
        """初始化 UnitEventPublisher。

        Args:
            emit: 宿主事件发射回调（通常为 ``ctx.emit``），None 表示 Null 模式
        """
        self._emit = emit

    async def publish(self, event: CoreEvent) -> None:
        """发布事件到宿主 ctx。"""
        event_type, payload = _core_event_to_dict(event)
        if self._emit is None:
            logger.debug(f"Event published (unit-null): {event_type} for agent {event.agent_name}")
            return
        try:
            self._emit(f"core:{event_type}", payload)
            logger.debug(f"Event published (unit): core:{event_type} for agent {event.agent_name}")
        except Exception:
            # fire-and-forget：emit 失败不阻断驱动循环
            logger.exception(f"Failed to emit core:{event_type} for agent {event.agent_name}")


# ----------------------------------------------------------------
# Ability 实例化（移植自旧 WS 服务器形态的 router::_create_ability_from_def）
# ----------------------------------------------------------------


def _create_ability_from_def(
    ability_def: Any,
    *,
    command_runner: Any = None,
    auto_approve_abilities: tuple[str, ...] = (),
    require_approval_by_default: bool = True,
) -> AbilityProtocol:
    """将 AbilityDefinitionPayload 转换为 Ability 实例。

    与原 server/router.py 的 ``_create_ability_from_def`` 共享同一套常量与
    AbilityRegistry.create 工厂：
    1. 文件系统类（FS_ABILITY_TYPES）：将 require_hitl/allowed_paths/
       denied_paths/workspace_root 原始字段转换为 FSPermissionChecker。
    2. execute_command：将 require_approval 标记转换为
       CommandSafetyChecker + CommandApprovalHook 注入构造函数。
    3. end_task：统一 mode="toolcall"。

    HITL 运行时覆盖层（语义平移自 subject 侧旧 HITLPolicy）：
    - ``auto_approve_abilities`` 白名单 → 强制免审批（覆盖 manifest
      require_hitl=True）；
    - manifest 未声明审批字段时 → ``require_approval_by_default`` 兜底。
    决策优先级：auto_approve > manifest 显式声明 > 兜底默认。

    ``command_runner`` 非 None 时注入 execute_command（Subject 挂载模式的
    SandboxExecutor；None = standalone 直跑 subprocess）。
    """
    from ghrah.abilities import (
        FS_ABILITY_TYPES,
        AbilityRegistry,
        CommandApprovalHook,
        CommandSafetyChecker,
        FSPermissionChecker,
    )

    params = dict(ability_def.params) if ability_def.params else {}
    ability_type = ability_def.ability_type
    auto_approved = ability_type in auto_approve_abilities

    _fs_permission_keys = {"require_hitl", "allowed_paths", "denied_paths", "workspace_root"}

    if ability_type in FS_ABILITY_TYPES and _fs_permission_keys & set(params.keys()):
        fs_params = {k: params.pop(k) for k in _fs_permission_keys if k in params}
        allowed_paths = fs_params.get("allowed_paths")
        denied_paths = fs_params.get("denied_paths")
        workspace_root = fs_params.get("workspace_root")
        # HITL 覆盖层：auto_approve > manifest require_hitl > 兜底默认
        if auto_approved:
            require_approval = False
        elif "require_hitl" in fs_params and isinstance(fs_params["require_hitl"], bool):
            require_approval = fs_params["require_hitl"]
        else:
            require_approval = require_approval_by_default
        checker = FSPermissionChecker(
            allowed_paths=allowed_paths,
            workspace_root=workspace_root,
            denied_paths=denied_paths,
            require_approval=require_approval,
        )
        params["permission_checker"] = checker

    if ability_type == "execute_command":
        # HITL 覆盖层：auto_approve > manifest require_approval > 兜底默认
        manifest_requirement = params.pop("require_approval", None)
        if auto_approved:
            require_approval = False
        elif manifest_requirement is not None:
            require_approval = bool(manifest_requirement)
        else:
            require_approval = require_approval_by_default
        command_checker = CommandSafetyChecker(require_approval=require_approval)
        params["command_checker"] = command_checker
        params["hooks"] = [CommandApprovalHook(command_checker)]
        if command_runner is not None:
            params["command_runner"] = command_runner

    if ability_type == "end_task":
        params["mode"] = "toolcall"

    return AbilityRegistry.create(ability_type, **params)


# ----------------------------------------------------------------
# CoreUnit
# ----------------------------------------------------------------

_CommandHandler = Callable[[dict[str, Any], Any], Awaitable[dict[str, Any]]]


class CoreUnit:
    """ghrah-core 的 Unit 挂载形态。

    纯 duck-typed 对象：不 import 宿主运行时/subject 包，形状与 subject 侧
    ``mount_unit`` 桥契约严格兼容。内部持有 SupervisorActor 与
    UnitEventPublisher，将 17 个 core 命令分发到 Supervisor/Agent 层。

    用法:
        unit = create_core_unit(CoreUnitConfig())
        await unit.init(ctx)   # ctx.provide("supervisor"/"core_registry")
        await unit.start()
        result = await unit.handle_command("list_agents", {}, cmd_ctx)
        await unit.stop()
    """

    def __init__(self, config: CoreUnitConfig) -> None:
        """初始化 CoreUnit（不触碰宿主，init(ctx) 时才接管）。

        Args:
            config: Unit 配置
        """
        self._config = config
        self._meta = _UnitMeta(
            name="core",
            requires=frozenset(),
            provides=frozenset({_ServiceKey("supervisor"), _ServiceKey("core_registry")}),
            routes=_RouteSpec(commands=_COMMANDS),
        )
        self._supervisor: SupervisorActor | None = None
        self._publisher: UnitEventPublisher | None = None
        self._emit: Callable[[str, dict[str, Any]], None] | None = None
        self._stopped = False

        self._handlers: dict[str, _CommandHandler] = {
            CommandType.SPAWN_AGENT.value: self._handle_spawn_agent,
            CommandType.TERMINATE_AGENT.value: self._handle_terminate_agent,
            CommandType.SEND_MESSAGE.value: self._handle_send_message,
            CommandType.BROADCAST_MESSAGE.value: self._handle_broadcast_message,
            CommandType.REGISTER_ABILITY.value: self._handle_register_ability,
            CommandType.UNREGISTER_ABILITY.value: self._handle_unregister_ability,
            CommandType.LIST_AGENTS.value: self._handle_list_agents,
            CommandType.HEALTH_CHECK.value: self._handle_health_check,
            CommandType.DELEGATE.value: self._handle_delegate,
            CommandType.GET_AGENT_INFO.value: self._handle_get_agent_info,
            CommandType.EXECUTE_ABILITY.value: self._handle_execute_ability,
            CommandType.HITL_RESPONSE.value: self._handle_hitl_response,
            CommandType.SESSION_CREATE.value: self._handle_session_create,
            CommandType.SESSION_SWITCH.value: self._handle_session_switch,
            CommandType.SESSION_LIST.value: self._handle_session_list,
            CommandType.SESSION_ARCHIVE.value: self._handle_session_archive,
            CommandType.SESSION_DELETE.value: self._handle_session_delete,
        }

    @property
    def meta(self) -> _UnitMeta:
        """Unit 元数据（bridge 契约）。"""
        return self._meta

    @property
    def supervisor(self) -> SupervisorActor | None:
        """内部 SupervisorActor（init 前为 None）。"""
        return self._supervisor

    # ----------------------------------------------------------------
    # 生命周期
    # ----------------------------------------------------------------

    async def init(self, ctx: Any) -> None:
        """初始化 Unit：构造 Supervisor 并向宿主提供核心服务。

        Args:
            ctx: 宿主上下文（duck-typed），用到 ``ctx.emit`` 与 ``ctx.provide``
        """
        emit = getattr(ctx, "emit", None)
        self._emit = emit if callable(emit) else None
        self._publisher = UnitEventPublisher(emit=self._emit)

        # Room bridge（send 工具回路）：宿主 ctx 有 serial 时桥接 Subject RoomUnit
        # （duck-typed；standalone 场景无 serial → bridge 为 None，send 工具明确报错）
        serial = getattr(ctx, "serial", None)
        room_bridge = (
            SerialRoomBridge(serial) if callable(serial) else None
        )

        supervisor = SupervisorActor(
            default_timeout=self._config.default_timeout,
            cluster_id=self._config.cluster_id,
            event_publisher=self._publisher,
            room_bridge=room_bridge,
        )
        self._supervisor = supervisor

        provide = getattr(ctx, "provide", None)
        if callable(provide):
            provide("supervisor", supervisor)
            provide("core_registry", getattr(supervisor, "_registry", None))
        else:
            logger.warning("CoreUnit.init: ctx 无 provide 方法，跳过服务注册")

        logger.info(f"CoreUnit initialized (cluster_id={self._config.cluster_id})")

    async def start(self) -> None:
        """启动 Unit（幂等空实现 — 路由注册由 bridge 完成）。"""
        logger.debug("CoreUnit started")

    async def stop(self) -> None:
        """停止 Unit：清理 pending HITL futures 并终止所有 Agent（幂等）。"""
        if self._stopped:
            return
        self._stopped = True

        supervisor = self._supervisor
        if supervisor is None:
            return

        # 先清理 executor 层 pending HITL futures，再终止 agents
        try:
            for agent_info in await supervisor.list_agents():
                name = agent_info.get("name", "")
                if not name:
                    continue
                try:
                    handle = await supervisor.get_agent_handle(name)
                    executor = getattr(handle, "_ability_executor", None)
                    hitl_store = getattr(executor, "hitl_store", None)
                    if hitl_store is not None:
                        hitl_store.cancel_all()
                except Exception:
                    logger.warning(f"CoreUnit.stop: 清理 agent '{name}' HITL futures 失败")
        except Exception:
            logger.warning("CoreUnit.stop: 枚举 agents 失败")

        await supervisor.shutdown()
        logger.info("CoreUnit stopped")

    # ----------------------------------------------------------------
    # 命令/事件分发（bridge 契约）
    # ----------------------------------------------------------------

    async def handle_command(
        self, command: str, payload: dict[str, Any], cmd_ctx: Any
    ) -> dict[str, Any]:
        """分发命令到对应 handler。

        Args:
            command: 命令名（CommandType 的 .value 字符串）
            payload: 命令载荷
            cmd_ctx: 命令上下文（subject 侧占位对象，视为 Any）

        Returns:
            回执字典 ``{"success": bool, "data": ..., "error": ...}``
        """
        handler = self._handlers.get(command)
        if handler is None:
            return {"success": False, "error": f"Unknown command: {command}"}
        try:
            return await handler(payload, cmd_ctx)
        except Exception as e:
            logger.exception(f"CoreUnit: error handling {command}: {e}")
            return {"success": False, "error": str(e)}

    async def handle_event(self, event_type: str, payload: dict[str, Any]) -> None:
        """消费宿主事件（core unit 不消费事件，空实现）。"""
        logger.debug(f"CoreUnit.handle_event ignored: {event_type}")

    # ----------------------------------------------------------------
    # 内部工具
    # ----------------------------------------------------------------

    def _require_supervisor(self) -> SupervisorActor:
        """取 Supervisor，未 init 时抛错（由 handle_command 统一捕获）。"""
        if self._supervisor is None:
            raise RuntimeError("CoreUnit not initialized (init(ctx) first)")
        return self._supervisor

    def _emit_event(self, event_type: str, payload: dict[str, Any]) -> None:
        """经宿主 emit 发送 core 域事件（``core:{event_type}``，fire-and-forget）。"""
        if self._emit is None:
            logger.debug(f"Event emitted (unit-null): core:{event_type}")
            return
        try:
            self._emit(f"core:{event_type}", payload)
        except Exception:
            logger.exception(f"Failed to emit core:{event_type}")

    @staticmethod
    def _ok(data: Any = None) -> dict[str, Any]:
        return {"success": True, "data": data}

    @staticmethod
    def _err(error: str) -> dict[str, Any]:
        return {"success": False, "error": error}

    # ----------------------------------------------------------------
    # Agent 生命周期命令
    # ----------------------------------------------------------------

    async def _handle_spawn_agent(self, payload: dict[str, Any], cmd_ctx: Any) -> dict[str, Any]:
        """spawn_agent — 接收已物化的 SpawnAgentPayload（移植自 router:577-708）。

        manifest 展开/权限物化在 subject 侧完成，本 handler 直接消费
        AgentConfigPayload 与 AbilityDefinitionPayload 列表。
        """
        supervisor = self._require_supervisor()
        sp = SpawnAgentPayload.model_validate(payload)
        logger.info(f"CoreUnit.spawn_agent: name={sp.config.name}")

        core_config = AgentConfig(
            name=sp.config.name,
            agent_config_name=sp.config.agent_config_name,
            description=sp.config.description,
            system_prompt=sp.config.system_prompt,
            max_iterations=sp.config.max_iterations,
            communication_timeout=sp.config.communication_timeout,
            window=(build_window_from_dict(sp.config.window) if sp.config.window else None),
            context=(build_context_from_dict(sp.config.context) if sp.config.context else None),
            model_overrides=(
                build_model_overrides_from_dict(sp.config.model_overrides)
                if sp.config.model_overrides
                else None
            ),
            workspace_root=self._config.workspace_root,
        )

        ability_instances = None
        if sp.abilities:
            ability_instances = []
            for ability_def in sp.abilities:
                try:
                    ability = _create_ability_from_def(
                        ability_def,
                        command_runner=self._config.command_runner,
                        auto_approve_abilities=self._config.auto_approve_abilities,
                        require_approval_by_default=(self._config.require_approval_by_default),
                    )
                    ability_instances.append(ability)
                except KeyError as e:
                    return self._err(
                        f"Unknown ability type '{ability_def.ability_type}' "
                        f"for agent '{sp.config.name}': {e}"
                    )
                except (TypeError, ValueError) as e:
                    return self._err(
                        f"Invalid params for ability '{ability_def.ability_type}' "
                        f"for agent '{sp.config.name}': {e}"
                    )

        try:
            agent_name = await supervisor.spawn_agent(
                core_config,
                abilities=ability_instances,
                persistence_factory=self._config.persistence_factory,
            )
        except RegistryError as e:
            return self._err(str(e))

        self._apply_hitl_timeout(agent_name)

        config_dict = sp.config.model_dump()
        self._emit_event(
            EventType.AGENT_SPAWNED.value,
            {"name": agent_name, "config": config_dict},
        )
        return self._ok({"name": agent_name})

    def _apply_hitl_timeout(self, agent_name: str) -> None:
        """best-effort 将 config.hitl_timeout 应用到 agent 的本地 executor。

        AgentBuilder 不透传 hitl_timeout 到 LocalAbilityExecutor，
        故在 spawn 后直接调整（防御式：找不到 executor 时仅记日志）。
        """
        if self._supervisor is None:
            return
        try:
            info = self._supervisor._registry.get_info(agent_name)
            executor = getattr(info.actor_handle, "_ability_executor", None)
            if executor is not None and hasattr(executor, "_hitl_timeout"):
                executor._hitl_timeout = self._config.hitl_timeout
        except Exception:
            logger.warning(f"CoreUnit: 应用 hitl_timeout 到 agent '{agent_name}' 失败")

    async def _handle_terminate_agent(
        self, payload: dict[str, Any], cmd_ctx: Any
    ) -> dict[str, Any]:
        supervisor = self._require_supervisor()
        tp = TerminateAgentPayload.model_validate(payload)
        await supervisor.terminate_agent(tp.name)
        self._emit_event(EventType.AGENT_TERMINATED.value, {"name": tp.name})
        return self._ok({"name": tp.name, "terminated": True})

    # ----------------------------------------------------------------
    # 消息路由命令
    # ----------------------------------------------------------------

    async def _handle_send_message(self, payload: dict[str, Any], cmd_ctx: Any) -> dict[str, Any]:
        supervisor = self._require_supervisor()
        sp = SendMessagePayload.model_validate(payload)
        result = await supervisor.send(
            target=sp.target,
            content=sp.content,
            sender=sp.sender,
            timeout=sp.timeout,
        )
        return self._ok({"content": result})

    async def _handle_broadcast_message(
        self, payload: dict[str, Any], cmd_ctx: Any
    ) -> dict[str, Any]:
        supervisor = self._require_supervisor()
        bp = BroadcastMessagePayload.model_validate(payload)
        results = await supervisor.broadcast(content=bp.content, sender=bp.sender)
        return self._ok({"responses": results})

    async def _handle_delegate(self, payload: dict[str, Any], cmd_ctx: Any) -> dict[str, Any]:
        supervisor = self._require_supervisor()
        dp = DelegatePayload.model_validate(payload)
        result = await supervisor.delegate(
            from_agent=dp.from_agent,
            to_agent=dp.to_agent,
            content=dp.content,
            timeout=dp.timeout,
        )
        return self._ok({"content": result})

    # ----------------------------------------------------------------
    # Ability 注册命令
    # ----------------------------------------------------------------

    async def _handle_register_ability(
        self, payload: dict[str, Any], cmd_ctx: Any
    ) -> dict[str, Any]:
        supervisor = self._require_supervisor()
        rp = RegisterAbilityPayload.model_validate(payload)
        result = await supervisor.register_ability_for_agent(
            agent_name=rp.agent_name,
            ability_type=rp.ability.ability_type,
            ability_params=rp.ability.params,
        )
        return self._ok({"agent_name": rp.agent_name, "ability": result, "registered": True})

    async def _handle_unregister_ability(
        self, payload: dict[str, Any], cmd_ctx: Any
    ) -> dict[str, Any]:
        supervisor = self._require_supervisor()
        up = UnregisterAbilityPayload.model_validate(payload)
        agent_handle = await supervisor.get_agent_handle(up.agent_name)
        await agent_handle.unregister_ability(up.ability_name)
        return self._ok(
            {
                "agent_name": up.agent_name,
                "ability": up.ability_name,
                "unregistered": True,
            }
        )

    # ----------------------------------------------------------------
    # 查询命令
    # ----------------------------------------------------------------

    async def _handle_list_agents(self, payload: dict[str, Any], cmd_ctx: Any) -> dict[str, Any]:
        supervisor = self._require_supervisor()
        result = await supervisor.list_agents()
        return self._ok({"agents": result})

    async def _handle_health_check(self, payload: dict[str, Any], cmd_ctx: Any) -> dict[str, Any]:
        supervisor = self._require_supervisor()
        result = await supervisor.health_check()
        return self._ok(result)

    async def _handle_get_agent_info(self, payload: dict[str, Any], cmd_ctx: Any) -> dict[str, Any]:
        supervisor = self._require_supervisor()
        gp = GetAgentInfoPayload.model_validate(payload)
        agent_handle = await supervisor.get_agent_handle(gp.name)
        state = agent_handle.get_state()
        abilities = agent_handle.get_abilities()
        return self._ok({"name": gp.name, "state": state, "abilities": abilities})

    # ----------------------------------------------------------------
    # execute_ability（本地执行 + ability_result 事件）
    # ----------------------------------------------------------------

    async def _handle_execute_ability(
        self, payload: dict[str, Any], cmd_ctx: Any
    ) -> dict[str, Any]:
        """execute_ability — 单体模式本地执行（移植自 router:555 + :393-460）。

        WS 模式下 router 将 execute_ability 转发到 Subject 执行；Unit 形态下
        core 与 subject 同进程，直接经 agent 的 LocalAbilityExecutor 本地执行，
        再把结果转译为 AbilityResultPayload 经 ``core:ability_result`` 事件上抛。

        request_id 关联：优先 ExecuteAbilityPayload.request_id，
        兜底 cmd_ctx.request_id，再兜底自动生成。
        """
        supervisor = self._require_supervisor()
        ep = ExecuteAbilityPayload.model_validate(payload)
        request_id = ep.request_id or getattr(cmd_ctx, "request_id", None) or generate_request_id()
        logger.info(
            "CoreUnit.execute_ability: agent=%s ability=%s request_id=%s",
            ep.agent_name,
            ep.ability_name,
            request_id,
        )

        agent_handle = await supervisor.get_agent_handle(ep.agent_name)
        abilities = getattr(agent_handle, "_abilities", {})
        ability = abilities.get(ep.ability_name)
        if ability is None:
            return self._err(f"Ability '{ep.ability_name}' not found on agent '{ep.agent_name}'")
        executor = getattr(agent_handle, "_ability_executor", None)
        if executor is None:
            return self._err(f"Agent '{ep.agent_name}' has no ability executor")

        try:
            context = AbilityExecutionContext(
                current_ability_name=ep.ability_name,
                tool_args=ep.tool_args,
                context_manager=getattr(agent_handle, "_context_manager", None),
                supervisor=supervisor,
                agent_name=ep.agent_name,
            )
            action_result = await executor.execute_ability(ability, context)
            success = action_result.outcome == ActionOutcome.SUCCESS
            error = None if success else str(action_result.data.get("error", "unknown error"))
            result_payload = AbilityResultPayload(
                request_id=request_id,
                agent_name=ep.agent_name,
                ability_name=ep.ability_name,
                success=success,
                result=action_result.data,
                error=error,
            )
        except Exception as e:
            # 对齐 router:457-460 语义：执行异常仅记日志，转译为失败回执
            logger.exception(
                "CoreUnit.execute_ability failed: agent=%s ability=%s request_id=%s",
                ep.agent_name,
                ep.ability_name,
                request_id,
            )
            result_payload = AbilityResultPayload(
                request_id=request_id,
                agent_name=ep.agent_name,
                ability_name=ep.ability_name,
                success=False,
                result=None,
                error=str(e),
            )

        self._emit_event(EventType.ABILITY_RESULT.value, result_payload.model_dump())
        return self._ok(result_payload.model_dump())

    # ----------------------------------------------------------------
    # HITL 命令
    # ----------------------------------------------------------------

    async def _handle_hitl_response(self, payload: dict[str, Any], cmd_ctx: Any) -> dict[str, Any]:
        """hitl_response — 单体字段集路径（移植自 router:1044-1077）。

        经 supervisor 找到 agent，向其 executor 投递审批结果，resolve
        进程内 HITL future。优先走 executor 层（返回 resolved bool）；
        无 executor 时回退 ActorAgent.receive_hitl_response。
        """
        supervisor = self._require_supervisor()
        hp = HITLResponsePayload.model_validate(payload)
        agent_handle = await supervisor.get_agent_handle(hp.agent_name)

        executor = getattr(agent_handle, "_ability_executor", None)
        if executor is not None and hasattr(executor, "receive_hitl_response"):
            resolved = executor.receive_hitl_response(
                ability_name=hp.ability_name,
                tool_call_id=hp.tool_call_id,
                approved=hp.approved,
                result=hp.result,
            )
        else:
            await agent_handle.receive_hitl_response(
                ability_name=hp.ability_name,
                tool_call_id=hp.tool_call_id,
                approved=hp.approved,
                result=hp.result,
            )
            resolved = True

        return self._ok({"resolved": bool(resolved)})

    # ----------------------------------------------------------------
    # Session 命令
    # ----------------------------------------------------------------

    async def _handle_session_create(self, payload: dict[str, Any], cmd_ctx: Any) -> dict[str, Any]:
        supervisor = self._require_supervisor()
        sp = SessionCreatePayload.model_validate(payload)
        data = await supervisor.create_session(
            agent_name=sp.agent_name,
            session_name=sp.session_name,
            from_node_id=sp.from_node_id,
            system_prompt=sp.system_prompt,
        )
        return self._ok(data)

    async def _handle_session_switch(self, payload: dict[str, Any], cmd_ctx: Any) -> dict[str, Any]:
        supervisor = self._require_supervisor()
        sp = SessionSwitchPayload.model_validate(payload)
        data = await supervisor.switch_session(agent_name=sp.agent_name, session_id=sp.session_id)
        return self._ok(data)

    async def _handle_session_list(self, payload: dict[str, Any], cmd_ctx: Any) -> dict[str, Any]:
        supervisor = self._require_supervisor()
        sp = SessionListPayload.model_validate(payload)
        sessions = await supervisor.list_sessions(sp.agent_name)
        return self._ok({"sessions": sessions})

    async def _handle_session_archive(
        self, payload: dict[str, Any], cmd_ctx: Any
    ) -> dict[str, Any]:
        supervisor = self._require_supervisor()
        sp = SessionArchivePayload.model_validate(payload)
        await supervisor.archive_session(agent_name=sp.agent_name, session_id=sp.session_id)
        return self._ok({"session_id": sp.session_id, "archived": True})

    async def _handle_session_delete(self, payload: dict[str, Any], cmd_ctx: Any) -> dict[str, Any]:
        supervisor = self._require_supervisor()
        sp = SessionDeletePayload.model_validate(payload)
        await supervisor.delete_session(agent_name=sp.agent_name, session_id=sp.session_id)
        return self._ok({"session_id": sp.session_id, "deleted": True})


def create_core_unit(config: CoreUnitConfig) -> CoreUnit:
    """创建 CoreUnit 实例（工厂函数）。

    Args:
        config: Unit 配置

    Returns:
        CoreUnit 实例（尚未 init）
    """
    return CoreUnit(config)
