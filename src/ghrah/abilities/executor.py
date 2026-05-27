# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""Ability 执行器：将 Ability 执行从 Agent 循环中解耦。

核心设计：
- AbilityExecutor 是 Ability 执行的抽象接口
- LocalAbilityExecutor 在 Core 端本地执行 Ability（单体模式）
- RemoteAbilityExecutor 将执行委托给 Subject（分布式模式）

单体模式下，HITL 在 Core 端处理：
    Hook → HITLFutureStore.create_future() → EventPublisher.publish(HITLRequestEvent)
    → Subject → Observer → 审批 → Core Server → receive_hitl_response() → resolve_future()

分布式模式下，HITL 在 Subject 端处理：
    Core 发送 tool_call → Subject
    Subject 执行 Ability + HITL 裁决
    Subject 返回 ActionResult → Core Server resolve AbilityResultFuture
"""

from __future__ import annotations

import asyncio
import copy
import logging
import uuid
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ghrah.abilities._utils import ABILITY_PATH_SPECS
from ghrah.abilities.base import Ability, ActionOutcome, ActionResult
from ghrah.abilities.context import AbilityExecutionContext
from ghrah.abilities.hooks import HookPoint, HookResult
from ghrah.chat.content import ToolCallBlock
from ghrah.core.event_publisher import EventPublisher, NullEventPublisher
from ghrah.core.events import HITLRequestEvent
from ghrah.core.exceptions import HookError
from ghrah.core.hitl import HITLFutureStore, HITLResult
from ghrah.protocol.types import CommandType

if TYPE_CHECKING:
    from ghrah.abilities.hooks import Hook
    from ghrah.context.manager import ContextManager

logger = logging.getLogger(__name__)

__all__ = [
    "AbilityExecutor",
    "LocalAbilityExecutor",
    "RemoteAbilityExecutor",
]


class AbilityExecutor(ABC):
    """Ability 执行器接口 — 将执行与 Agent 循环解耦。

    单体模式使用 LocalAbilityExecutor（在 Core 端直接执行 Ability + HITL）。
    分布式模式使用 RemoteAbilityExecutor（将执行委托给 Subject，待实现）。

    子类必须实现：
    - execute_ability(): 执行单个 Ability
    - execute_tool_calls(): 执行一组 tool_calls
    - run_hooks(): 运行 Hook
    - handle_hitl_hook_result(): 处理 HITL Hook 结果
    - update_hooks(): 同步 Hook 列表
    - update_event_publisher(): 同步事件发布器
    - receive_hitl_response(): 接收 HITL 审批结果
    """

    @abstractmethod
    async def execute_ability(
        self,
        ability: Ability,
        context: AbilityExecutionContext,
    ) -> ActionResult:
        """执行单个 Ability。

        Args:
            ability: 要执行的 Ability 实例
            context: 执行上下文

        Returns:
            执行结果
        """
        ...

    @abstractmethod
    async def execute_tool_calls(
        self,
        tool_calls: list[ToolCallBlock],
        abilities: dict[str, Ability],
        accumulated_data: dict[str, Any],
        context_manager: ContextManager,
    ) -> list[dict]:
        """执行一组 tool_calls，返回结果列表。

        每个 tool_call 映射到对应的 Ability 执行。

        Args:
            tool_calls: LLM 返回的 ToolCallBlock 列表
            abilities: 已注册的 Ability 字典
            accumulated_data: 累积数据
            context_manager: 上下文管理器

        Returns:
            结果列表，每个 dict 包含 "ability_name", "action_result", "tool_call_id"
        """
        ...

    @abstractmethod
    async def run_hooks(
        self,
        point: HookPoint,
        context: AbilityExecutionContext,
        result: ActionResult | None = None,
    ) -> HookResult | None:
        """运行指定触发点的所有 Hooks。

        Args:
            point: Hook 触发点
            context: 当前执行上下文
            result: ActionResult（POST_EXECUTE 时传入）

        Returns:
            合并后的 HookResult，如果没有 hook 触发则返回 None
        """
        ...

    @abstractmethod
    async def handle_hitl_hook_result(
        self,
        hook_result: HookResult,
        context: AbilityExecutionContext,
    ) -> bool:
        """处理 HITL Hook 结果。

        当 PRE_EXECUTE Hook 返回 should_continue=False 且 requires_hitl=True 时，
        执行器需要决定如何处理：单体模式创建 Future 等待审批，分布式模式委托给 Subject。

        Args:
            hook_result: Hook 返回的结果
            context: 当前执行上下文

        Returns:
            True 表示继续执行，False 表示需要等待 HITL 批准
        """
        ...

    @abstractmethod
    def update_hooks(self, hooks: list[Hook]) -> None:
        """同步更新 Hook 列表。

        当 Agent 注册/反注册 Ability 时，需要同步更新执行器的 Hook 列表。

        Args:
            hooks: 最新的 Hook 列表
        """
        ...

    @abstractmethod
    def update_event_publisher(self, publisher: EventPublisher) -> None:
        """同步更新事件发布器。

        当 Agent 的事件发布器变更时，需要同步更新执行器的事件发布器。

        Args:
            publisher: 新的事件发布器
        """
        ...

    @abstractmethod
    def receive_hitl_response(
        self,
        ability_name: str,
        tool_call_id: str,
        approved: bool,
        result: Any = None,
    ) -> bool:
        """接收 HITL 审批结果。

        当 Observer 审批 HITL 请求后，通过此方法 resolve 对应的 Future。
        单体模式下由 LocalAbilityExecutor 处理，分布式模式下可空实现。

        Args:
            ability_name: Ability 名称
            tool_call_id: 工具调用 ID
            approved: 是否批准
            result: 审批附加结果

        Returns:
            是否成功解析 Future
        """
        ...


class LocalAbilityExecutor(AbilityExecutor):
    """本地执行器 — 在 Core 端直接执行 Ability。

    保留当前所有行为：
    - PRE_EXECUTE / POST_EXECUTE Hook
    - HITL 审批（通过 HITLFutureStore）
    - 本地 I/O 操作

    用于单体模式（ghrah-core 独立使用）。
    """

    def __init__(
        self,
        agent_name: str,
        hooks: list[Hook] | None = None,
        event_publisher: EventPublisher | None = None,
        hitl_timeout: float = 300.0,
        workspace_root: str | None = None,
    ) -> None:
        """初始化本地执行器。

        Args:
            agent_name: Agent 名称（用于 HITL Future 的 key）
            hooks: 已注册的 Hook 列表
            event_publisher: 事件发布器（默认 NullEventPublisher）
            hitl_timeout: HITL 等待超时时间（秒）
            workspace_root: 工作区根目录，用于将相对路径解析到沙盒内（None 表示不解析）
        """
        self._agent_name = agent_name
        self._hooks: list[Hook] = hooks or []
        self._event_publisher: EventPublisher = event_publisher or NullEventPublisher()
        self._hitl_store = HITLFutureStore()
        self._hitl_timeout = hitl_timeout
        self._workspace_root = Path(workspace_root).resolve() if workspace_root else None

    @property
    def hitl_store(self) -> HITLFutureStore:
        """获取 HITL Future 存储（供外部 resolve 使用）。"""
        return self._hitl_store

    def update_hooks(self, hooks: list[Hook]) -> None:
        """同步更新 Hook 列表。

        Args:
            hooks: 最新的 Hook 列表
        """
        self._hooks = hooks

    def update_event_publisher(self, publisher: EventPublisher) -> None:
        """同步更新事件发布器。

        Args:
            publisher: 新的事件发布器
        """
        self._event_publisher = publisher

    async def execute_ability(
        self,
        ability: Ability,
        context: AbilityExecutionContext,
    ) -> ActionResult:
        """执行单个 Ability，包含 PRE_EXECUTE 和 POST_EXECUTE Hook。

        如果 PRE_EXECUTE Hook 返回 should_continue=False 且包含 HITL 请求，
        会创建 Future 等待审批结果。

        Args:
            ability: 要执行的 Ability 实例
            context: 执行上下文

        Returns:
            执行结果

        Raises:
            HookError: Hook 执行出错时
        """
        # PRE_EXECUTE hook（ability 级）
        hook_result = await self.run_hooks(HookPoint.PRE_EXECUTE, context)

        # 处理 Hook 结果
        if hook_result is not None:
            if not hook_result.should_continue:
                if hook_result.requires_hitl:
                    # 需要 HITL 审批：创建 Future 等待人工审批
                    should_continue = await self.handle_hitl_hook_result(hook_result, context)
                    if not should_continue:
                        # HITL 拒绝或超时
                        return ActionResult(
                            outcome=ActionOutcome.FAILURE,
                            data={
                                "error": hook_result.message or "Execution blocked by HITL",
                                "hitl_rejected": True,
                            },
                        )
                    # HITL 批准，继续执行
                else:
                    # 直接拦截，不进入 HITL 等待流程
                    return ActionResult(
                        outcome=ActionOutcome.FAILURE,
                        data={
                            "error": hook_result.message or "Execution blocked by hook",
                        },
                    )
            elif hook_result.route_to:
                # 路由到其他 ability
                return ActionResult(
                    outcome=ActionOutcome.DELEGATE,
                    data={"route_to": hook_result.route_to},
                    next_action_hint=hook_result.route_to,
                )
            elif hook_result.modified_context:
                # 合并修改的上下文
                context.accumulated_data.update(hook_result.modified_context)

        # 执行 Ability
        action_result = await ability.execute(context)

        # POST_EXECUTE hook（ability 级）
        await self.run_hooks(HookPoint.POST_EXECUTE, context, action_result)

        return action_result

    async def execute_tool_calls(
        self,
        tool_calls: list[ToolCallBlock],
        abilities: dict[str, Ability],
        accumulated_data: dict[str, Any],
        context_manager: ContextManager,
    ) -> list[dict]:
        """执行一组 tool_calls，返回结果列表。

        多个 tool_calls 使用 asyncio.gather 并行执行。

        Args:
            tool_calls: LLM 返回的 ToolCallBlock 列表
            abilities: 已注册的 Ability 字典
            accumulated_data: 累积数据
            context_manager: 上下文管理器

        Returns:
            结果列表
        """
        results: list[dict] = []
        tool_call_tasks: list[tuple[Ability, dict[str, Any], str]] = []
        task_ability_names: list[str] = []

        for tc in tool_calls:
            ability_name = tc.name
            ability_args = tc.arguments
            tool_call_id = tc.id

            ability = abilities.get(ability_name)
            if ability is None:
                # 未知 ability，直接记录失败结果
                results.append(
                    {
                        "ability_name": ability_name,
                        "action_result": ActionResult(
                            outcome=ActionOutcome.FAILURE,
                            data={"error": f"Unknown ability: {ability_name}"},
                        ),
                        "tool_call_id": tool_call_id,
                    }
                )
                continue

            tool_call_tasks.append((ability, ability_args, tool_call_id))
            task_ability_names.append(ability_name)

        if tool_call_tasks:
            # 为每个 ability 创建独立的 AbilityExecutionContext
            raw_results = await asyncio.gather(
                *[
                    self._execute_single_with_context(
                        ability, args, accumulated_data, context_manager
                    )
                    for ability, args, _tc_id in tool_call_tasks
                ],
                return_exceptions=True,
            )
            for i, r in enumerate(raw_results):
                if isinstance(r, Exception):
                    results.append(
                        {
                            "ability_name": task_ability_names[i],
                            "action_result": ActionResult(
                                outcome=ActionOutcome.FAILURE,
                                data={"error": str(r)},
                            ),
                            "tool_call_id": tool_call_tasks[i][2],
                        }
                    )
                else:
                    r["tool_call_id"] = tool_call_tasks[i][2]
                    results.append(r)

        return results

    async def _execute_single_with_context(
        self,
        ability: Ability,
        tool_args: dict[str, Any],
        accumulated_data: dict[str, Any],
        context_manager: ContextManager,
    ) -> dict:
        """执行单个 ability（用于并行执行），创建独立的 AbilityExecutionContext。

        Args:
            ability: 要执行的 ability 实例
            tool_args: 工具调用参数
            accumulated_data: 累积数据
            context_manager: 上下文管理器

        Returns:
            dict 包含 "ability_name" 和 "action_result"
        """
        resolved_args = self._resolve_paths(tool_args, ability.name)

        per_ability_context = AbilityExecutionContext(
            current_ability_name=ability.name,
            tool_args=resolved_args,
            agent_state=context_manager.get_current_state(),
            context_manager=context_manager,
            accumulated_data={
                **copy.deepcopy(accumulated_data),
                "tool_args": resolved_args,
            },
            last_action_result=context_manager.last_action_result,
            agent_name=self._agent_name,
        )

        action_result = await self.execute_ability(ability, per_ability_context)

        return {"ability_name": ability.name, "action_result": action_result}

    def _resolve_paths(self, tool_args: dict[str, Any], ability_name: str) -> dict[str, Any]:
        """将 tool_args 中的相对路径解析到 workspace_root 下。

        如果 workspace_root 未设置，直接返回原 tool_args。
        仅对 ABILITY_PATH_SPECS 中已知的路径参数进行解析，
        绝对路径保持不变。

        Args:
            tool_args: LLM 工具调用参数
            ability_name: Ability 名称

        Returns:
            解析后的 tool_args（副本）
        """
        if self._workspace_root is None:
            return tool_args

        spec = ABILITY_PATH_SPECS.get(ability_name)
        if spec is None:
            return tool_args

        resolved = dict(tool_args)
        for key in spec.path_keys:
            value = resolved.get(key)
            if value and isinstance(value, str) and not Path(value).is_absolute():
                resolved[key] = str((Path(self._workspace_root) / value).resolve())
        for key in spec.working_dir_keys:
            value = resolved.get(key)
            if value and isinstance(value, str) and not Path(value).is_absolute():
                resolved[key] = str((Path(self._workspace_root) / value).resolve())

        return resolved

    async def run_hooks(
        self,
        point: HookPoint,
        context: AbilityExecutionContext,
        result: ActionResult | None = None,
    ) -> HookResult | None:
        """运行所有注册的指定触发点的 hooks。

        只运行 hook_point 匹配且 should_trigger 返回 True 的 hooks。
        如果多个 hook 都触发，合并其结果（后者覆盖前者）。

        Args:
            point: Hook 触发点
            context: 当前执行上下文
            result: ActionResult（POST_EXECUTE 时传入）

        Returns:
            合并后的 HookResult，如果没有 hook 触发则返回 None

        Raises:
            HookError: hook 执行出错时
        """
        merged: HookResult | None = None

        for hook in self._hooks:
            if hook.hook_point != point:
                continue

            try:
                should_fire = await hook.should_trigger(context)
            except Exception as e:
                raise HookError(
                    point.value,
                    f"should_trigger failed for {type(hook).__name__}: {e}",
                ) from e

            if not should_fire:
                continue

            try:
                hook_result = await hook.execute(context, result)
            except Exception as e:
                raise HookError(
                    point.value,
                    f"execute failed for {type(hook).__name__}: {e}",
                ) from e

            # 合并结果：后者覆盖前者
            if merged is None:
                merged = hook_result
            else:
                merged = merged.merge(hook_result)

        return merged

    async def handle_hitl_hook_result(
        self,
        hook_result: HookResult,
        context: AbilityExecutionContext,
    ) -> bool:
        """处理 HITL Hook 结果。

        在单体模式下，创建 asyncio.Future 等待 HITL 审批：
        1. 发布 HITLRequestEvent 到 EventPublisher
        2. 创建 HITL Future 并等待
        3. 收到审批结果后继续或终止

        Args:
            hook_result: Hook 返回的结果
            context: 当前执行上下文

        Returns:
            True 表示继续执行，False 表示需要等待 HITL 批准或被拒绝
        """
        # 生成 tool_call_id
        tool_call_id = context.tool_args.get("call_id", "") or uuid.uuid4().hex[:12]

        # 发布 HITL 请求事件
        await self._event_publisher.publish(
            HITLRequestEvent(
                agent_name=self._agent_name,
                ability_name=context.current_ability_name,
                tool_call=context.tool_args,
                context={"tool_call_id": tool_call_id},
            )
        )

        # 创建 Future 并等待
        future = self._hitl_store.create_future(
            agent_name=self._agent_name,
            ability_name=context.current_ability_name,
            tool_call_id=tool_call_id,
        )

        # 等待 HITL 结果（带超时）
        try:
            hitl_result: HITLResult = await asyncio.wait_for(future, timeout=self._hitl_timeout)
            if hitl_result.approved:
                logger.info(
                    f"LocalAbilityExecutor[{self._agent_name}] HITL approved: "
                    f"ability={context.current_ability_name}, tool_call_id={tool_call_id}"
                )
                return True
            else:
                logger.info(
                    f"LocalAbilityExecutor[{self._agent_name}] HITL rejected: "
                    f"ability={context.current_ability_name}, tool_call_id={tool_call_id}"
                )
                return False
        except TimeoutError:
            logger.warning(
                f"LocalAbilityExecutor[{self._agent_name}] HITL request timed out: "
                f"ability={context.current_ability_name}, tool_call_id={tool_call_id}"
            )
            return False

    def receive_hitl_response(
        self,
        ability_name: str,
        tool_call_id: str,
        approved: bool,
        result: Any = None,
    ) -> bool:
        """接收 HITL 审批结果（由外部调用）。

        当 Observer 审批 HITL 请求后，通过此方法 resolve 对应的 Future。

        Args:
            ability_name: Ability 名称
            tool_call_id: 工具调用 ID
            approved: 是否批准
            result: 审批附加结果

        Returns:
            是否成功解析 Future
        """
        hitl_result = HITLResult(approved=approved, result=result)
        resolved = self._hitl_store.resolve_future(
            agent_name=self._agent_name,
            ability_name=ability_name,
            tool_call_id=tool_call_id,
            result=hitl_result,
        )
        if resolved:
            logger.info(
                f"LocalAbilityExecutor[{self._agent_name}] HITL response received: "
                f"ability={ability_name}, tool_call_id={tool_call_id}, approved={approved}"
            )
        else:
            logger.warning(
                f"LocalAbilityExecutor[{self._agent_name}] HITL response ignored "
                f"(no pending future): ability={ability_name}, tool_call_id={tool_call_id}"
            )
        return resolved


class RemoteAbilityExecutor(AbilityExecutor):
    """远程执行器 — 将 Ability 执行委托给 Subject。

    Core 端不执行 Ability，不处理 HITL。
    只发送 tool_call 意图，等待 Subject 返回结果。

    在新架构中：
    1. Core 通过 CommandSender 发送 execute_ability 请求到 Subject
    2. Subject 执行 Ability（含 HITL 裁决）
    3. Subject 返回 ActionResult 到 Core，resolve 对应的 Future
    """

    # 默认超时时间（秒），等待 Subject 返回 Ability 执行结果
    DEFAULT_ABILITY_TIMEOUT = 600.0

    def __init__(
        self,
        command_sender: Any,
        agent_name: str,
        timeout: float = DEFAULT_ABILITY_TIMEOUT,
    ) -> None:
        """初始化远程执行器。

        Args:
            command_sender: CommandSender 实例（通常为 MessageRouter），用于发送请求
            agent_name: Agent 名称（用于标识请求来源）
            timeout: 等待 Ability 执行结果的超时时间（秒）
        """
        self._command_sender = command_sender
        self._agent_name = agent_name
        self._timeout = timeout

    async def execute_ability(
        self,
        ability: Ability,
        context: AbilityExecutionContext,
    ) -> ActionResult:
        """发送 tool_call 到 Subject，等待执行结果。

        通过 CommandSender 发送 execute_ability 请求，
        转发到 Subject 执行，结果通过 command_result 返回。

        Args:
            ability: 要执行的 Ability 实例
            context: 执行上下文

        Returns:
            执行结果

        Raises:
            TimeoutError: 等待结果超时
            ConnectionError: 没有可用的 Subject 连接
        """
        request_id = uuid.uuid4().hex

        try:
            result = await self._command_sender.send_command(
                CommandType.EXECUTE_ABILITY.value,
                {
                    "request_id": request_id,
                    "agent_name": self._agent_name,
                    "ability_name": ability.name,
                    "tool_args": context.tool_args,
                },
                request_id=request_id,
                timeout=self._timeout,
            )
            logger.info(
                f"RemoteAbilityExecutor[{self._agent_name}] ability request completed: "
                f"ability={ability.name}, request_id={request_id}"
            )

            if result.get("success", False):
                return ActionResult(
                    outcome=ActionOutcome.SUCCESS,
                    data=result.get("data", result.get("result", {})),
                )
            else:
                return ActionResult(
                    outcome=ActionOutcome.FAILURE,
                    data={"error": result.get("error", "Unknown error")},
                )

        except TimeoutError:
            logger.warning(
                f"RemoteAbilityExecutor[{self._agent_name}] ability request timed out: "
                f"ability={ability.name}, request_id={request_id}"
            )
            raise
        except Exception:
            logger.error(
                f"RemoteAbilityExecutor[{self._agent_name}] ability request failed: "
                f"ability={ability.name}, request_id={request_id}",
                exc_info=True,
            )
            raise

    async def execute_tool_calls(
        self,
        tool_calls: list[ToolCallBlock],
        abilities: dict[str, Ability],
        accumulated_data: dict[str, Any],
        context_manager: ContextManager,
    ) -> list[dict]:
        """并行发送多个 tool_calls 到 Subject。

        为每个 tool_call 创建独立的请求，并行等待结果。

        Args:
            tool_calls: LLM 返回的 ToolCallBlock 列表
            abilities: 已注册的 Ability 字典
            accumulated_data: 累积数据
            context_manager: 上下文管理器

        Returns:
            结果列表，每个 dict 包含 "ability_name", "action_result", "tool_call_id"
        """
        results: list[dict] = []
        tasks: list[tuple[str, str, dict[str, Any], str]] = []

        for tc in tool_calls:
            ability_name = tc.name
            ability_args = tc.arguments
            tool_call_id = tc.id

            ability = abilities.get(ability_name)
            if ability is None:
                # 未知 ability，直接记录失败结果
                results.append(
                    {
                        "ability_name": ability_name,
                        "action_result": ActionResult(
                            outcome=ActionOutcome.FAILURE,
                            data={"error": f"Unknown ability: {ability_name}"},
                        ),
                        "tool_call_id": tool_call_id,
                    }
                )
                continue

            tasks.append((ability_name, ability.name, ability_args, tool_call_id))

        if tasks:
            # 并行发送所有请求
            raw_results = await asyncio.gather(
                *[
                    self._execute_single_remote(
                        ability_name=ability_name,
                        ability_display_name=ability_display_name,
                        tool_args=tool_args,
                    )
                    for ability_name, ability_display_name, tool_args, _tc_id in tasks
                ],
                return_exceptions=True,
            )
            for i, r in enumerate(raw_results):
                if isinstance(r, Exception):
                    results.append(
                        {
                            "ability_name": tasks[i][0],
                            "action_result": ActionResult(
                                outcome=ActionOutcome.FAILURE,
                                data={"error": str(r)},
                            ),
                            "tool_call_id": tasks[i][3],
                        }
                    )
                else:
                    r["tool_call_id"] = tasks[i][3]
                    results.append(r)

        return results

    async def _execute_single_remote(
        self,
        ability_name: str,
        ability_display_name: str,
        tool_args: dict[str, Any],
    ) -> dict:
        """执行单个远程 Ability 请求。

        注意：与 execute_ability 不同，此方法将所有异常（包括超时）
        转换为 FAILURE ActionResult 返回，而非抛出异常。
        这是为了与 asyncio.gather(return_exceptions=True) 配合使用，
        确保单个 tool_call 的失败不会影响其他并行请求。

        Args:
            ability_name: Ability 名称（用于查找）
            ability_display_name: Ability 显示名称
            tool_args: 工具调用参数

        Returns:
            dict 包含 "ability_name" 和 "action_result"
        """
        request_id = uuid.uuid4().hex

        try:
            result = await self._command_sender.send_command(
                CommandType.EXECUTE_ABILITY.value,
                {
                    "request_id": request_id,
                    "agent_name": self._agent_name,
                    "ability_name": ability_display_name,
                    "tool_args": tool_args,
                },
                request_id=request_id,
                timeout=self._timeout,
            )
            logger.debug(
                f"RemoteAbilityExecutor[{self._agent_name}] single request completed: "
                f"ability={ability_display_name}, request_id={request_id}"
            )

            if result.get("success", False):
                return {
                    "ability_name": ability_name,
                    "action_result": ActionResult(
                        outcome=ActionOutcome.SUCCESS,
                        data=result.get("data", result.get("result", {})),
                    ),
                }
            else:
                return {
                    "ability_name": ability_name,
                    "action_result": ActionResult(
                        outcome=ActionOutcome.FAILURE,
                        data={"error": result.get("error", "Unknown error")},
                    ),
                }

        except TimeoutError:
            return {
                "ability_name": ability_name,
                "action_result": ActionResult(
                    outcome=ActionOutcome.FAILURE,
                    data={"error": f"Ability request timed out: {ability_display_name}"},
                ),
            }
        except Exception as e:
            return {
                "ability_name": ability_name,
                "action_result": ActionResult(
                    outcome=ActionOutcome.FAILURE,
                    data={"error": str(e)},
                ),
            }

    async def run_hooks(
        self,
        point: HookPoint,
        context: AbilityExecutionContext,
        result: ActionResult | None = None,
    ) -> HookResult | None:
        """分布式模式下 Core 端不运行 Ability 级 Hook。

        Hook 在 Subject 端执行，Core 端只负责发送请求和接收结果。

        Returns:
            始终返回 None，表示不拦截执行
        """
        return None

    async def handle_hitl_hook_result(
        self,
        hook_result: HookResult,
        context: AbilityExecutionContext,
    ) -> bool:
        """分布式模式下 HITL 在 Subject 端处理，Core 端不需要。

        Returns:
            始终返回 True，表示继续执行
        """
        return True

    def update_hooks(self, hooks: list[Hook]) -> None:
        """分布式模式下 Core 端不维护 Hook 列表。

        Hook 在 Subject 端管理，此方法为空实现。
        """

    def update_event_publisher(self, publisher: EventPublisher) -> None:
        """分布式模式下 Core 端不使用本地事件发布器。

        事件通过 CommandSender/EventBus 转发，此方法为空实现。
        """

    def receive_hitl_response(
        self,
        ability_name: str,
        tool_call_id: str,
        approved: bool,
        result: Any = None,
    ) -> bool:
        """分布式模式下 Core 端不处理 HITL 响应。

        HITL 在 Subject 端处理，此方法始终返回 False。

        Returns:
            始终返回 False，表示没有 Future 被解析
        """
        return False

    def resolve_ability_result(
        self,
        request_id: str,
        action_result: ActionResult,
    ) -> bool:
        """解析 Ability 执行结果 Future（遗留兼容接口）。

        新版本中 execute_ability 直接通过 command_result 返回结果，
        不再依赖 _pending_futures 机制。此方法保留用于兼容性，始终返回 False。

        Args:
            request_id: 请求 ID（不再使用）
            action_result: Subject 返回的执行结果（不再使用）

        Returns:
            始终返回 False，表示没有 Future 被解析
        """
        logger.debug(
            f"RemoteAbilityExecutor[{self._agent_name}] resolve_ability_result called "
            f"(request_id={request_id}), but no longer uses pending futures"
        )
        return False
