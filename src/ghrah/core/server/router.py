# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import asyncio
import logging
from typing import Any

from ghrah.abilities.registry import AbilityRegistry
from ghrah.communication.supervisor import SupervisorActor
from ghrah.core.config import (
    AgentConfig,
    ContextConfig,
    ModelOverrides,
    WindowConfig,
)
from ghrah.core.server.connection_manager import ConnectionManager
from ghrah.core.server.event_bus import EventBus
from ghrah.protocol.types import (
    CORE_COMMANDS,
    PERSIST_COMMANDS,
    CommandType,
    Message,
    SpawnAgentPayload,
    create_command_result,
    create_error,
    generate_request_id,
)

logger = logging.getLogger(__name__)


def _build_window(data: dict[str, Any]) -> WindowConfig:
    return WindowConfig(
        max_tokens=data.get("max_tokens", 4096),
        strategies=data.get("strategies", ["tool_call_fold", "truncation"]),
        tool_call_max_length=data.get("tool_call_max_length", 500),
        sliding_window_size=data.get("sliding_window_size", 20),
    )


def _build_context(data: dict[str, Any]) -> ContextConfig:
    return ContextConfig(
        persistence_type=data.get("persistence_type"),
        persistence_root_dir=data.get("persistence_root_dir"),
        persistence_compress=data.get("persistence_compress", True),
        auto_persist=data.get("auto_persist", False),
        snapshot_interval=data.get("snapshot_interval", 5),
        persistence_run_id=data.get("persistence_run_id"),
    )


def _build_model_overrides(data: dict[str, Any]) -> ModelOverrides:
    return ModelOverrides(
        temperature=data.get("temperature"),
        max_tokens=data.get("max_tokens"),
        top_p=data.get("top_p"),
        top_k=data.get("top_k"),
    )


class MessageRouter:
    def __init__(
        self,
        supervisor: SupervisorActor,
        connection_manager: ConnectionManager,
        event_bus: EventBus,
        ability_timeout: float = 120.0,
        default_timeout: float = 30.0,
    ) -> None:
        self._supervisor = supervisor
        self._connection_manager = connection_manager
        self._event_bus = event_bus
        self._ability_timeout = ability_timeout
        self._default_timeout = default_timeout

        self._pending_requests: dict[str, asyncio.Future[Message]] = {}
        self._request_sessions: dict[str, str] = {}

    async def send_command(
        self,
        command_type: str,
        payload: dict[str, Any],
        request_id: str | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """实现 CommandSender 协议 — 供内部组件（RemoteBackend、RemoteAbilityExecutor）调用。

        通过 ConnectionManager 将命令转发到 Subject，等待 command_result 响应。

        Args:
            command_type: 命令类型
            payload: 命令载荷
            request_id: 请求 ID（自动生成如果未提供）
            timeout: 超时时间（秒），None 使用默认值

        Returns:
            命令响应载荷字典

        Raises:
            ConnectionError: 没有可用的 Subject 连接
            asyncio.TimeoutError: 等待响应超时
        """
        if request_id is None:
            request_id = generate_request_id()
        if timeout is None:
            timeout = self._default_timeout

        message = Message(
            type=command_type,
            payload=payload,
            request_id=request_id,
        )

        result = await self._forward_to_subject(
            message,
            session_id="<internal>",
            request_id=request_id,
            command_label=command_type,
            timeout=timeout,
        )

        if isinstance(result, dict):
            return result

        if hasattr(result, "payload"):
            return result.payload if result.payload else {"success": False}

        return {"success": False}

    async def handle_command(
        self,
        message: Message,
        session_id: str,
    ) -> Message | None:
        request_id = message.request_id or generate_request_id()

        if message.type in PERSIST_COMMANDS:
            return await self._forward_to_subject(
                message, session_id, request_id, command_label="persist command"
            )

        if message.type == CommandType.EXECUTE_ABILITY.value:
            return await self._handle_execute_ability(message, session_id, request_id)

        if message.type not in CORE_COMMANDS and message.type not in (
            CommandType.SUBSCRIBE.value,
            CommandType.UNSUBSCRIBE.value,
        ):
            return create_error(
                code="UNKNOWN_COMMAND",
                message=f"Unknown command type: {message.type}",
                request_id=request_id,
            )

        try:
            command_type = CommandType(message.type)
        except ValueError:
            return create_error(
                code="UNKNOWN_COMMAND",
                message=f"Unknown command type: {message.type}",
                request_id=request_id,
            )

        handler_map: dict[CommandType, Any] = {
            CommandType.SPAWN_AGENT: self._handle_spawn_agent,
            CommandType.TERMINATE_AGENT: self._handle_terminate_agent,
            CommandType.SEND_MESSAGE: self._handle_send_message,
            CommandType.BROADCAST_MESSAGE: self._handle_broadcast_message,
            CommandType.REGISTER_ABILITY: self._handle_register_ability,
            CommandType.UNREGISTER_ABILITY: self._handle_unregister_ability,
            CommandType.LIST_AGENTS: self._handle_list_agents,
            CommandType.HEALTH_CHECK: self._handle_health_check,
            CommandType.DELEGATE: self._handle_delegate,
            CommandType.GET_AGENT_INFO: self._handle_get_agent_info,
            CommandType.INIT_CLUSTER: self._handle_init_cluster,
            CommandType.SHUTDOWN_CLUSTER: self._handle_shutdown_cluster,
            CommandType.CLUSTER_STATUS: self._handle_cluster_status,
            CommandType.SUBSCRIBE: self._handle_subscribe,
            CommandType.UNSUBSCRIBE: self._handle_unsubscribe,
            CommandType.HITL_RESPONSE: self._handle_hitl_response,
        }

        handler = handler_map.get(command_type)
        if handler is None:
            return create_error(
                code="UNSUPPORTED_COMMAND",
                message=f"Command not implemented: {command_type.value}",
                request_id=request_id,
            )

        try:
            return await handler(message, session_id, request_id)
        except Exception as e:
            logger.exception(f"Unexpected error handling {command_type.value}: {e}")
            return create_command_result(
                request_id=request_id,
                success=False,
                error=f"Internal error: {e}",
            )

    async def handle_event(
        self,
        message: Message,
        session_id: str,
    ) -> None:
        await self._event_bus.publish(message)

    async def resolve_command_result(
        self,
        message: Message,
        session_id: str,
    ) -> bool:
        request_id = message.request_id or message.payload.get("request_id")
        if not request_id:
            logger.warning("command_result missing request_id, ignoring")
            return False

        future = self._pending_requests.pop(request_id, None)
        self._request_sessions.pop(request_id, None)

        if future is None:
            logger.debug(
                f"command_result with request_id={request_id} "
                f"has no pending request, ignoring"
            )
            return False

        if not future.done():
            future.set_result(message)
            logger.info(
                f"Resolved pending request {request_id} "
                f"from session {session_id}"
            )
        else:
            logger.warning(
                f"Pending request {request_id} already resolved, discarding"
            )

        return True

    async def resolve_ability_result(
        self,
        message: Message,
        session_id: str,
    ) -> bool:
        request_id = message.request_id or message.payload.get("request_id")
        if not request_id:
            logger.warning("ability_result missing request_id, ignoring")
            return False

        future = self._pending_requests.pop(request_id, None)
        self._request_sessions.pop(request_id, None)

        if future is None:
            logger.debug(
                f"ability_result with request_id={request_id} "
                f"has no pending execute_ability request, ignoring"
            )
            return False

        if not future.done():
            ability_payload = message.payload
            result_msg = create_command_result(
                request_id=request_id,
                success=ability_payload.get("success", False),
                data=ability_payload.get("result"),
                error=ability_payload.get("error"),
            )
            future.set_result(result_msg)
            logger.info(
                f"Resolved ability_result for execute_ability request {request_id} "
                f"from session {session_id}"
            )
        else:
            logger.warning(
                f"Pending execute_ability request {request_id} already resolved"
            )

        return True

    async def _forward_to_subject(
        self,
        message: Message,
        session_id: str,
        request_id: str,
        command_label: str = "command",
        timeout: float | None = None,
    ) -> Message:
        if timeout is None:
            timeout = 30.0

        subject_sessions = self._connection_manager.active_sessions
        subject_sessions = [s for s in subject_sessions if s != session_id]

        if not subject_sessions:
            logger.warning(
                f"No Subject session available for {command_label} "
                f"{message.type} (request_id={request_id})"
            )
            return create_command_result(
                request_id=request_id,
                success=False,
                error=f"No Subject connected to handle {command_label}",
            )

        message_dict = message.model_dump_with_timestamp()
        target_session = subject_sessions[0]
        if not await self._connection_manager.send_to(target_session, message_dict):
            return create_command_result(
                request_id=request_id,
                success=False,
                error=f"Failed to send {command_label} to Subject session",
            )

        logger.info(
            f"Forwarded {message.type} {command_label} to Subject "
            f"session {target_session} (request_id={request_id})"
        )

        future: asyncio.Future[Message] = (
            asyncio.get_running_loop().create_future()
        )
        self._pending_requests[request_id] = future
        self._request_sessions[request_id] = session_id

        try:
            result = await asyncio.wait_for(future, timeout=timeout)
            return result
        except TimeoutError:
            logger.warning(
                f"{command_label} {message.type} timed out "
                f"(request_id={request_id}, timeout={timeout}s)"
            )
            return create_command_result(
                request_id=request_id,
                success=False,
                error=f"{command_label} timed out waiting for Subject response",
            )
        except Exception as e:
            logger.error(f"Error waiting for {command_label} response: {e}")
            return create_command_result(
                request_id=request_id,
                success=False,
                error=f"{command_label} failed: {e}",
            )
        finally:
            self._pending_requests.pop(request_id, None)
            self._request_sessions.pop(request_id, None)

    async def _handle_execute_ability(
        self, message: Message, session_id: str, request_id: str
    ) -> Message:
        from ghrah.protocol.types import ExecuteAbilityPayload

        payload = ExecuteAbilityPayload(**message.payload)
        logger.info(
            "_handle_execute_ability: agent=%s ability=%s request_id=%s "
            "from_session=%s",
            payload.agent_name, payload.ability_name, payload.request_id, session_id,
        )

        subject_sessions = self._connection_manager.active_sessions

        if not subject_sessions:
            logger.warning(
                f"No Subject session available for execute ability "
                f"(request_id={request_id})"
            )
            return create_command_result(
                request_id=request_id,
                success=False,
                error="No Subject connected to execute ability",
            )

        message_dict = message.model_dump_with_timestamp()
        target_session = subject_sessions[0]
        if not await self._connection_manager.send_to(target_session, message_dict):
            return create_command_result(
                request_id=request_id,
                success=False,
                error="Failed to send execute ability to Subject session",
            )

        logger.info(
            f"Forwarded execute ability to Subject session {target_session} "
            f"(request_id={request_id})"
        )

        future: asyncio.Future[Message] = (
            asyncio.get_running_loop().create_future()
        )
        self._pending_requests[request_id] = future
        self._request_sessions[request_id] = session_id

        try:
            result = await asyncio.wait_for(future, timeout=self._ability_timeout)
            return result
        except TimeoutError:
            logger.warning(
                f"Execute ability request timed out "
                f"(request_id={request_id}, timeout={self._ability_timeout}s)"
            )
            return create_command_result(
                request_id=request_id,
                success=False,
                error="Execute ability timed out waiting for Subject response",
            )
        except Exception as e:
            logger.error(f"Error waiting for execute ability response: {e}")
            return create_command_result(
                request_id=request_id,
                success=False,
                error=f"Execute ability failed: {e}",
            )
        finally:
            self._pending_requests.pop(request_id, None)
            self._request_sessions.pop(request_id, None)

    async def _handle_spawn_agent(
        self, message: Message, session_id: str, request_id: str
    ) -> Message:
        payload = SpawnAgentPayload(**message.payload)
        logger.info(
            "_handle_spawn_agent: name=%s agent_config=%s request_id=%s",
            payload.config.name, payload.config.agent_config_name, request_id,
        )

        core_config = AgentConfig(
            name=payload.config.name,
            agent_config_name=payload.config.agent_config_name,
            description=payload.config.description,
            system_prompt=payload.config.system_prompt,
            max_iterations=payload.config.max_iterations,
            communication_timeout=payload.config.communication_timeout,
            window=_build_window(payload.config.window) if payload.config.window else None,
            context=_build_context(payload.config.context) if payload.config.context else None,
            model_overrides=(
                _build_model_overrides(payload.config.model_overrides)
                if payload.config.model_overrides
                else None
            ),
        )

        ability_instances = None
        if payload.abilities:
            ability_instances = []
            for ability_def in payload.abilities:
                try:
                    ability = AbilityRegistry.create(
                        ability_def.ability_type, **ability_def.params
                    )
                    ability_instances.append(ability)
                except KeyError as e:
                    return create_command_result(
                        request_id=request_id,
                        success=False,
                        error=f"Unknown ability type '{ability_def.ability_type}' "
                              f"for agent '{payload.config.name}': {e}",
                    )

        result = await self._supervisor.spawn_agent(core_config, abilities=ability_instances)
        agent_name = result

        if agent_name:
            config_dict = (
                payload.config.model_dump()
                if hasattr(payload.config, "model_dump")
                else {}
            )
            await self._event_bus.emit_agent_spawned(
                agent_name=agent_name,
                config=config_dict,
            )

        return create_command_result(
            request_id=request_id,
            success=True,
            data={"name": agent_name},
        )

    async def _handle_terminate_agent(
        self, message: Message, session_id: str, request_id: str
    ) -> Message:
        from ghrah.protocol.types import TerminateAgentPayload

        payload = TerminateAgentPayload(**message.payload)
        await self._supervisor.terminate_agent(payload.name)

        await self._event_bus.emit_agent_terminated(agent_name=payload.name)

        return create_command_result(
            request_id=request_id,
            success=True,
            data={"name": payload.name, "terminated": True},
        )

    async def _handle_send_message(
        self, message: Message, session_id: str, request_id: str
    ) -> Message:
        from ghrah.protocol.types import SendMessagePayload

        payload = SendMessagePayload(**message.payload)
        result = await self._supervisor.send(
            target=payload.target,
            content=payload.content,
            sender=payload.sender,
            timeout=payload.timeout,
        )
        return create_command_result(
            request_id=request_id,
            success=True,
            data={"content": result},
        )

    async def _handle_broadcast_message(
        self, message: Message, session_id: str, request_id: str
    ) -> Message:
        from ghrah.protocol.types import BroadcastMessagePayload

        payload = BroadcastMessagePayload(**message.payload)
        results = await self._supervisor.broadcast(
            content=payload.content,
            sender=payload.sender,
        )
        return create_command_result(
            request_id=request_id,
            success=True,
            data={"responses": results},
        )

    async def _handle_register_ability(
        self, message: Message, session_id: str, request_id: str
    ) -> Message:
        from ghrah.protocol.types import RegisterAbilityPayload

        payload = RegisterAbilityPayload(**message.payload)
        result = await self._supervisor.register_ability_for_agent(
            agent_name=payload.agent_name,
            ability_type=payload.ability.ability_type,
            ability_params=payload.ability.params,
        )
        return create_command_result(
            request_id=request_id,
            success=True,
            data={"agent_name": payload.agent_name, "ability": result, "registered": True},
        )

    async def _handle_unregister_ability(
        self, message: Message, session_id: str, request_id: str
    ) -> Message:
        from ghrah.protocol.types import UnregisterAbilityPayload

        payload = UnregisterAbilityPayload(**message.payload)
        try:
            agent_handle = await self._supervisor.get_agent_handle(payload.agent_name)
            if agent_handle is None:
                return create_command_result(
                    request_id=request_id,
                    success=False,
                    error=f"Agent '{payload.agent_name}' not found",
                )
            await agent_handle.unregister_ability(payload.ability_name)
            return create_command_result(
                request_id=request_id,
                success=True,
                data={
                    "agent_name": payload.agent_name,
                    "ability": payload.ability_name,
                    "unregistered": True,
                },
            )
        except Exception as e:
            return create_command_result(
                request_id=request_id,
                success=False,
                error=str(e),
            )

    async def _handle_get_agent_info(
        self, message: Message, session_id: str, request_id: str
    ) -> Message:
        agent_handle = await self._supervisor.get_agent_handle(
            name=message.payload.get("name", ""),
        )
        if agent_handle is None:
            return create_command_result(
                request_id=request_id,
                success=False,
                error=f"Agent '{message.payload.get('name', '')}' not found",
            )
        state = agent_handle.get_state()
        abilities = agent_handle.get_abilities()
        return create_command_result(
            request_id=request_id,
            success=True,
            data={
                "name": message.payload.get("name", ""),
                "state": state,
                "abilities": abilities,
            },
        )

    async def _handle_init_cluster(
        self, message: Message, session_id: str, request_id: str
    ) -> Message:
        agents = await self._supervisor.list_agents()
        return create_command_result(
            request_id=request_id,
            success=True,
            data={
                "initialized": True,
                "active_agents": len(agents),
                "config": message.payload.get("config", {}),
            },
        )

    async def _handle_shutdown_cluster(
        self, message: Message, session_id: str, request_id: str
    ) -> Message:
        agents = await self._supervisor.list_agents()
        for agent_info in agents:
            name = agent_info.get("name", "")
            if name:
                try:
                    await self._supervisor.terminate_agent(name)
                except Exception:
                    logger.warning(f"Failed to terminate agent '{name}' during shutdown")
        return create_command_result(
            request_id=request_id,
            success=True,
            data={"shutdown": True, "terminated_agents": len(agents)},
        )

    async def _handle_cluster_status(
        self, message: Message, session_id: str, request_id: str
    ) -> Message:
        agents = await self._supervisor.list_agents()
        health = await self._supervisor.health_check()
        return create_command_result(
            request_id=request_id,
            success=True,
            data={
                "active_agents": len(agents),
                "health": health,
                "status": "running",
            },
        )

    async def _handle_list_agents(
        self, message: Message, session_id: str, request_id: str
    ) -> Message:
        result = await self._supervisor.list_agents()
        return create_command_result(
            request_id=request_id,
            success=True,
            data=result,
        )

    async def _handle_health_check(
        self, message: Message, session_id: str, request_id: str
    ) -> Message:
        result = await self._supervisor.health_check()
        return create_command_result(
            request_id=request_id,
            success=True,
            data=result,
        )

    async def _handle_delegate(
        self, message: Message, session_id: str, request_id: str
    ) -> Message:
        from ghrah.protocol.types import DelegatePayload

        payload = DelegatePayload(**message.payload)
        result = await self._supervisor.delegate(
            from_agent=payload.from_agent,
            to_agent=payload.to_agent,
            content=payload.content,
            timeout=payload.timeout,
        )
        return create_command_result(
            request_id=request_id,
            success=True,
            data={"content": result},
        )

    async def _handle_subscribe(
        self, message: Message, session_id: str, request_id: str
    ) -> Message:
        from ghrah.protocol.types import SubscribePayload

        payload = SubscribePayload(**message.payload)
        self._connection_manager.subscribe(
            session_id=session_id,
            agent_names=payload.agent_names,
            event_types=payload.event_types,
        )
        sub_info = self._connection_manager.get_subscription_info(session_id)
        return create_command_result(
            request_id=request_id,
            success=True,
            data=sub_info,
        )

    async def _handle_unsubscribe(
        self, message: Message, session_id: str, request_id: str
    ) -> Message:
        from ghrah.protocol.types import UnsubscribePayload

        payload = UnsubscribePayload(**message.payload)
        self._connection_manager.unsubscribe(
            session_id=session_id,
            agent_names=payload.agent_names,
            event_types=payload.event_types,
        )
        sub_info = self._connection_manager.get_subscription_info(session_id)
        return create_command_result(
            request_id=request_id,
            success=True,
            data=sub_info,
        )

    async def _handle_hitl_response(
        self, message: Message, session_id: str, request_id: str
    ) -> Message:
        """将 HITL 审批结果路由到对应的 Agent。"""
        payload = message.payload
        agent_name = payload.get("agent_name", "")
        ability_name = payload.get("ability_name", "")
        tool_call_id = payload.get("tool_call_id", "")
        approved = payload.get("approved", False)
        result = payload.get("result")

        agent_handle = await self._supervisor.get_agent_handle(agent_name)
        if agent_handle is None:
            return create_command_result(
                request_id=request_id,
                success=False,
                error=f"Agent '{agent_name}' not found",
            )

        resolved = agent_handle.receive_hitl_response(
            ability_name=ability_name,
            tool_call_id=tool_call_id,
            approved=approved,
            result=result,
        )

        return create_command_result(
            request_id=request_id,
            success=True,
            data={"resolved": resolved},
        )

    def cancel_pending_requests(self) -> None:
        for request_id, future in self._pending_requests.items():
            if not future.done():
                future.set_exception(RuntimeError("Core server shutting down, request cancelled"))
        self._pending_requests.clear()
        self._request_sessions.clear()
