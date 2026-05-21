# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""ActorAgent 基类：Actor + Ability 组合 + Hook 驱动循环 + ContextManager 集成。

每个 ActorAgent 是一个 Agent Actor，内部持有：
- ChatFormat（通过 agentconf 配置惰性创建）
- 已注册的 Ability 集合（组合模式）
- 绑定的 tool schema（从 Ability.bind_tool() 收集）
- ContextManager（上下文管理：消息历史、状态、链式历史、窗口管理、驱动循环控制状态）
- AbilityExecutor（Ability 执行器，将执行与 Agent 循环解耦）

Hook:
    三层 Hook 架构：
    drive_loop 级：BEFORE_ACTION → _action → AFTER_ACTION
    action 级：PRE_LLM_CALL → [LLM 调用] → POST_LLM_CALL → [tool 执行] → PRE/POST_EXECUTE
    ability 级：PRE_EXECUTE → [execute] → POST_EXECUTE
    特殊触发：ON_ERROR（异常时）、ON_MAX_ITERATIONS（达到最大迭代时）

AbilityExecutor:
    - AbilityExecutor 接口将 Ability 执行从 Agent 循环中解耦
    - LocalAbilityExecutor：单体模式，在 Core 端本地执行 Ability + HITL
    - RemoteAbilityExecutor（待实现）：分布式模式，将执行委托给 Subject

ContextManager:
    - ContextManager 统一管理消息、状态、链式历史和驱动循环控制状态
    - _drive_loop 中每次迭代通过 begin_iteration / commit_iteration / rollback_iteration
    - 驱动循环控制状态（iteration, max_iterations, should_continue 等）由 ContextManager 管理
    - AbilityExecutionContext 只保留 Ability 执行所需的最少信息
"""

from __future__ import annotations

import asyncio
import copy
import logging
from typing import Any

from ghrah.abilities.base import Ability, ActionOutcome, ActionResult
from ghrah.abilities.context import AbilityExecutionContext
from ghrah.abilities.executor import (
    AbilityExecutor,
    LocalAbilityExecutor,
    RemoteAbilityExecutor,
)
from ghrah.abilities.hooks import Hook, HookPoint, HookResult
from ghrah.chat.format import ChatFormat, LLMResponse
from ghrah.chat.message import ChatMessage
from ghrah.context.manager import ContextManager
from ghrah.context.persistence.serialization import serialize_node
from ghrah.context.window import WindowManager
from ghrah.core.config import AgentConfig, WindowConfig
from ghrah.core.event_publisher import (
    EventPublisher,
    NullEventPublisher,
    ServerEventPublisher,
)
from ghrah.core.events import (
    ActionChainUpdatedEvent,
    AgentErrorEvent,
    AgentResponseEvent,
)
from ghrah.core.exceptions import (
    AbilityNotFoundError,
    AgentError,
    AgentInitializationError,
    HookError,
)
from ghrah.core.message import Message, MessageType
from ghrah.llm.factory import LLMFactory
from ghrah.llm.response_utils import (
    extract_reasoning_content,
    extract_response_metadata,
    extract_token_usage,
)

logger = logging.getLogger(__name__)


def _build_window_manager(config: WindowConfig) -> WindowManager:
    """从 WindowConfig 构建 WindowManager 实例。

    根据配置中的策略名称列表，创建对应的策略实例并组合到 WindowManager 中。

    Args:
        config: 窗口管理配置

    Returns:
        配置好的 WindowManager 实例
    """
    from ghrah.context.strategies.llm_summary import LLMSummaryStrategy
    from ghrah.context.strategies.sliding_window import SlidingWindowStrategy
    from ghrah.context.strategies.tool_call_fold import ToolCallFoldStrategy
    from ghrah.context.strategies.truncation import TruncationStrategy

    strategy_map = {
        "truncation": lambda: TruncationStrategy(),
        "sliding_window": lambda: SlidingWindowStrategy(window_size=config.sliding_window_size),
        "tool_call_fold": lambda: ToolCallFoldStrategy(
            max_content_length=config.tool_call_max_length
        ),
        "llm_summary": lambda: LLMSummaryStrategy(llm=None),  # 需要后续注入 LLM
    }

    strategies = []
    for name in config.strategies:
        factory = strategy_map.get(name)
        if factory is not None:
            strategies.append(factory())
        else:
            logger.warning("Unknown window strategy: %s, skipping", name)

    return WindowManager(
        strategies=strategies,
        max_tokens=config.max_tokens,
    )


class ActorAgent:
    """基于 Ability 组合的 Agent Actor。

    生命周期:
        1. __init__ 接收 AgentConfig，创建 ContextManager
        2. 首次调用 _ensure_llm() 时，从 agentconf 读取配置并创建 ChatModel
        3. 通过 register_ability() 注册能力（含 bind_tool 收集）
        4. receive() 触发驱动循环：ability 选择 → hook 时序 → 执行 → 条件转移

        - 所有消息和状态通过 ContextManager 管理
        - 驱动循环控制状态（iteration, max_iterations 等）由 ContextManager 管理

    用法:
        # 创建 Agent
        config = AgentConfig(name="code-reviewer")
        agent = ActorAgent(config)

        # 注册能力
        await agent.register_ability(ConversationAbility())

        # 发送消息（触发驱动循环）
        response = await agent.receive(Message(
            sender="user",
            recipient="code-reviewer",
            content="请帮我审查这段代码",
        ))
    """

    def __init__(
        self,
        config: AgentConfig,
        supervisor: Any = None,
        ability_executor: AbilityExecutor | None = None,
    ) -> None:
        self.config = config
        self._supervisor = supervisor
        self._llm: ChatFormat | None = None
        self._initialized = False
        self._abilities: dict[str, Ability] = {}
        self._bound_tools: list[dict[str, Any]] = []
        self._all_hooks: list[Hook] = []
        self._event_publisher: EventPublisher = NullEventPublisher()
        self._message_queue: asyncio.Queue[ChatMessage] = asyncio.Queue()

        if ability_executor is not None:
            self._ability_executor = ability_executor
        else:
            self._ability_executor = LocalAbilityExecutor(
                agent_name=config.name,
                hooks=self._all_hooks,
                event_publisher=self._event_publisher,
            )

        # ────── 分布式模式：由 SupervisorActor 后置注入 ──────
        self._command_sender: Any = None
        self._event_bus: Any = None

        # 创建 ContextManager
        window_manager = None
        if config.window is not None:
            window_manager = _build_window_manager(config.window)

        context_config = config.context

        # 根据 ContextConfig 创建持久化后端（通过工厂方法，支持多种后端类型）
        persistence = None
        if context_config is not None:
            persistence = context_config.create_persistence()

        self._context_manager = ContextManager(
            agent_name=config.name,
            initial_state={},
            system_prompt=config.system_prompt,
            window_manager=window_manager,
            persistence=persistence,
            snapshot_interval=context_config.snapshot_interval if context_config else 5,
            auto_persist=context_config.auto_persist if context_config else False,
        )

        # 框架级消息历史（Message 对象，使用自有 ChatMessage 格式）
        # ContextManager 管理 ChatMessage 消息，这里保留框架 Message 对象的记录
        self._message_history: list[Message] = []

        logger.info(f"ActorAgent[{config.name}] created")

    def inject_command_sender(self, command_sender: Any, event_bus: Any) -> None:
        """由 SupervisorActor 在服务器模式下注入命令发送器和事件总线。

        SupervisorActor 在创建 Agent 后，
        将 MessageRouter（实现 CommandSender 协议）和 EventBus 注入到 Agent，
        使 Agent 可以通过 Server 内部通信与 Subject 交互。

        Args:
            command_sender: CommandSender 实例（通常为 MessageRouter）
            event_bus: EventBus 实例，用于发布事件
        """
        self._command_sender = command_sender
        self._event_bus = event_bus

        if event_bus is not None:
            self._event_publisher = ServerEventPublisher(event_bus)
            logger.info(
                f"ActorAgent[{self.config.name}] injected ServerEventPublisher via event_bus"
            )

        if command_sender is not None and isinstance(self._ability_executor, LocalAbilityExecutor):
            self._ability_executor = RemoteAbilityExecutor(
                command_sender=command_sender,
                agent_name=self.config.name,
            )
            logger.info(
                f"ActorAgent[{self.config.name}] switched to RemoteAbilityExecutor"
            )
        elif command_sender is not None and isinstance(self._ability_executor, RemoteAbilityExecutor):
            self._ability_executor._command_sender = command_sender
            logger.info(
                f"ActorAgent[{self.config.name}] updated RemoteAbilityExecutor command_sender"
            )

    # ----------------------------------------------------------------
    # Ability 注册
    # ----------------------------------------------------------------

    def register_ability(self, ability: Ability) -> str:
        """注册一个能力到 Agent。

        相当于 tool 的绑定，但比单纯的 tool bind 有更多的控制与自由度。
        内部会调用 ability.bind_tool() 获取原生 Function Calling schema。
        注册后会更新 ContextManager 中的状态作用域。

        Args:
            ability: 要注册的能力实例

        Returns:
            注册的 ability 名称（调用方可用于确认注册成功）

        Raises:
            AgentError: 如果同名能力已注册
        """
        if ability.name in self._abilities:
            raise AgentError(
                self.config.name,
                f"Ability '{ability.name}' already registered",
            )

        # 收集 bind_tool 的 schema，后续绑定到 LLM
        tool_schema = ability.bind_tool()
        if tool_schema is not None:
            self._bound_tools.append(tool_schema)

        # 收集 hooks
        ability_hooks = ability.get_hooks()
        self._all_hooks.extend(ability_hooks)

        # 同步更新 executor 的 hooks
        self._ability_executor.update_hooks(self._all_hooks)

        self._abilities[ability.name] = ability

        # 写入 ability 默认状态到 ContextManager 的状态作用域
        # 注意：current 返回深拷贝，修改后通过 reset 替换内部状态
        default_state = ability.get_default_state()
        if default_state:
            state_snapshot = self._context_manager.state_manager.current
            state_snapshot[ability.name] = copy.deepcopy(default_state)
            self._context_manager.state_manager.reset(new_state=state_snapshot)

        logger.info(
            f"ActorAgent[{self.config.name}] registered ability: "
            f"{ability.name} (tool_bound={tool_schema is not None}, "
            f"hooks={len(ability_hooks)})"
        )

        return ability.name

    def unregister_ability(self, name: str) -> None:
        """移除已注册的能力。

        Args:
            name: 能力名称

        Raises:
            AbilityNotFoundError: 如果能力不存在
        """
        if name not in self._abilities:
            raise AbilityNotFoundError(name)

        ability = self._abilities.pop(name)

        # 移除对应的 tool schema
        tool_schema = ability.bind_tool()
        if tool_schema is not None:
            self._bound_tools = [
                t for t in self._bound_tools if t.get("function", {}).get("name") != name
            ]

        # 移除对应的 hooks
        ability_hooks = ability.get_hooks()
        ability_hook_ids = {id(h) for h in ability_hooks}
        self._all_hooks = [h for h in self._all_hooks if id(h) not in ability_hook_ids]

        # 同步更新 executor 的 hooks
        self._ability_executor.update_hooks(self._all_hooks)

        logger.info(f"ActorAgent[{self.config.name}] unregistered ability: {name}")

    def get_abilities(self) -> list[str]:
        """获取所有已注册的能力名称列表。"""
        return list(self._abilities.keys())

    def set_event_publisher(self, publisher: EventPublisher) -> None:
        """注入事件发布器（由 Supervisor 在创建时注入）。
        本地模式使用 NullEventPublisher（默认），远程模式使用 ServerEventPublisher。
        同时更新 AbilityExecutor 的事件发布器。

        Args:
            publisher: EventPublisher 实例
        """
        self._event_publisher = publisher
        # 同步更新 executor 的事件发布器
        self._ability_executor.update_event_publisher(publisher)
        logger.info(
            f"ActorAgent[{self.config.name}] event publisher set: {type(publisher).__name__}"
        )

    async def receive_hitl_response(
        self,
        ability_name: str,
        tool_call_id: str,
        approved: bool,
        result: Any = None,
    ) -> None:
        """接收 HITL 审批结果（由 Supervisor 通过 Ray.remote 调用）。

        当 Observer 审批 HITL 请求后，Core Server 路由到
        Supervisor，Supervisor 调用此方法将结果传递给 Agent。

        此方法委托给 AbilityExecutor.receive_hitl_response()。

        流程：Observer → Subject → Core Server → Supervisor → Agent

        Args:
            ability_name: Ability 名称
            tool_call_id: 工具调用 ID
            approved: 是否批准
            result: 审批附加结果
        """
        self._ability_executor.receive_hitl_response(
            ability_name=ability_name,
            tool_call_id=tool_call_id,
            approved=approved,
            result=result,
        )

    async def inject_message(self, message: ChatMessage) -> None:
        """向 Agent 注入消息，在下一轮迭代中被消费。

        线程安全，可从外部（WebSocket、HITL 回调等）异步调用。
        消息会在 _drive_loop 的下一次迭代开始时注入到 ContextManager。

        Args:
            message: 要注入的 ChatMessage
        """
        await self._message_queue.put(message)
        logger.info(
            f"ActorAgent[{self.config.name}] message injected: "
            f"role={message.role}, queue_size={self._message_queue.qsize()}"
        )

    def _drain_message_queue(self) -> list[ChatMessage]:
        """非阻塞排空消息队列，返回所有待处理消息。

        使用 get_nowait() 非阻塞获取，不会等待新消息到达。
        适用于 _drive_loop 每轮迭代开始时调用。

        Returns:
            队列中所有待处理的 ChatMessage 列表，可能为空
        """
        messages: list[ChatMessage] = []
        while not self._message_queue.empty():
            try:
                msg = self._message_queue.get_nowait()
                messages.append(msg)
            except asyncio.QueueEmpty:
                break
        return messages

    # ----------------------------------------------------------------
    # LLM 初始化
    # ----------------------------------------------------------------

    async def _ensure_llm(self) -> ChatFormat:
        """惰性初始化 LLM 客户端。

        从 agentconf 读取配置 → LLMFactory 创建 ChatFormat。
        采用惰性初始化避免 Ray 序列化问题。

        使用 config.effective_agent_config_name 查找 agentconf 配置，
        支持运行时名称与 LLM 配置名称分离（如 worker 池场景）。

        LLM 创建后自动 configure_tools，使 LLM 能在响应中返回 tool_calls。
        system_prompt 已在 ContextManager.__init__ 中注入，
        此方法仅负责 LLM 客户端创建。
        """
        if self._llm is not None:
            return self._llm

        agent_config_name = self.config.effective_agent_config_name

        try:
            from agentconf import AgentsConfig

            config_client = AgentsConfig()
            resolved = config_client.resolve_agent(agent_config_name)
            self._llm = LLMFactory.create(resolved)

            # Phase 1: 绑定已注册的 tools，使 LLM 能在响应中返回 tool_calls
            if self._bound_tools:
                self._llm.configure_tools(self._bound_tools)

            # Manifest 模型配置覆盖（优先级高于 agentconf）
            if self.config.model_overrides is not None:
                self._llm.apply_model_overrides(self.config.model_overrides)

            self._inject_llm_into_summary_strategy(self._llm)

            self._initialized = True

            logger.info(
                f"ActorAgent[{self.config.name}] LLM initialized from config "
                f"'{agent_config_name}': {type(self._llm).__name__}"
            )
            return self._llm

        except Exception as e:
            raise AgentInitializationError(
                agent_name=self.config.name,
                message=f"Failed to initialize LLM from agentconf "
                f"(config_name='{agent_config_name}'): {e}",
            ) from e

    def _inject_llm_into_summary_strategy(self, llm: ChatFormat) -> None:
        from ghrah.context.strategies.llm_summary import LLMSummaryStrategy

        wm = self._context_manager._window_manager
        if wm is None:
            return
        for strategy in wm._strategies:
            if isinstance(strategy, LLMSummaryStrategy) and strategy.llm is None:
                strategy.set_llm(llm)

    # ----------------------------------------------------------------
    # 核心驱动循环
    # ----------------------------------------------------------------

    async def receive(self, message: Message) -> Message:
        """接收并处理消息 — 驱动执行循环。

        LLM 调用移入 _action 层，receive 不再直接传递 llm。
        用户消息通过 ContextManager 管理。

        Args:
            message: 输入消息

        Returns:
            回复消息
        """
        logger.info(
            f"ActorAgent[{self.config.name}] received: {message.type.value} from {message.sender}"
        )
        self._message_history.append(message)

        if not self._abilities:
            raise AgentError(
                self.config.name,
                "No abilities registered. Register at least one ability "
                "(e.g., ConversationAbility) before calling receive(). "
                "Agent behavior is determined by ability composition.",
            )

        try:
            # 确保LLM已初始化（但不再直接传递给 context）
            await self._ensure_llm()

            # 将用户消息入队，供 _drive_loop 在迭代中消费
            await self._message_queue.put(
                ChatMessage.user(text_or_blocks=message.content, source="human")
            )

            # 将 max_iterations 从 config 设置到 ContextManager
            cm = self._context_manager
            cm.max_iterations = self.config.max_iterations
            cm.reset_iteration()
            cm.last_action_result = None
            cm.pending_route = None

            # ────── 分布式模式：CoreClient 自动连接（在新架构中始终连接） ──────
            if self._command_sender is not None:
                logger.debug(
                    "ActorAgent.receive: command_sender available for agent=%s",
                    self.config.name,
                )
            # ────── 结束 ──────

            # 驱动循环
            # 发布根节点的 ActionChainUpdatedEvent
            root_node = self._context_manager.chain.head
            if root_node is not None:
                try:
                    await self._event_publisher.publish(
                        ActionChainUpdatedEvent(
                            agent_name=self.config.name,
                            node=serialize_node(root_node),
                        )
                    )
                except Exception:
                    logger.debug("Failed to publish root node event", exc_info=True)

            await self._drive_loop()

            # 构建最终回复
            response = self._build_response(message)

            # ────── 发布 AgentResponse 事件 ──────
            await self._event_publisher.publish(
                AgentResponseEvent(
                    agent_name=self.config.name,
                    content=response.content,
                    message_type="result",
                    metadata={
                        "iteration": self._context_manager.iteration,
                    },
                )
            )
            # ────── 结束 ──────
            return response

        except AgentError:
            raise
        except Exception as e:
            logger.error(f"ActorAgent[{self.config.name}] error in drive loop: {e}")
            error_reply = Message(
                sender=self.config.name,
                recipient=message.sender,
                content=f"Error: {e}",
                type=MessageType.ERROR,
                reply_to=message.id,
            )
            return error_reply

    async def _drive_loop(self) -> None:
        """核心驱动循环 — 每次迭代执行一个 action。

        驱动循环控制状态（iteration, max_iterations, should_continue 等）
        由 ContextManager 管理，不再通过 AbilityExecutionContext 传递。

        三层 Hook 架构：
            drive_loop 级：BEFORE_ACTION → _action → AFTER_ACTION
            特殊触发：ON_ERROR、ON_MAX_ITERATIONS

        每次迭代通过 ContextManager 的 begin/commit/rollback 管理事务。
        每轮迭代开始时从 _message_queue 排空新消息并注入到 ContextManager，
        支持迭代中注入新消息（如 HITL 回复、WebSocket 追加提示等）。
        迭代失败回滚时，排空的消息会重新注入队列，防止消息丢失。
        """
        cm = self._context_manager
        accumulated_data: dict[str, Any] = {}

        # 注意：CommandSender 在新架构中通过 MessageRouter 本地方法调用，无需显式连接

        while cm.should_continue:
            # 1. BEFORE_ACTION hook（drive_loop 级）
            before_ctx = self._build_hook_context(accumulated_data)
            hook_result = await self._run_hooks(HookPoint.BEFORE_ACTION, before_ctx)
            if hook_result is not None:
                if hook_result.modified_context:
                    accumulated_data.update(hook_result.modified_context)
                if not hook_result.should_continue:
                    if hook_result.route_to:
                        # 路由到指定 ability（如 end_task）
                        await self._execute_routed_ability(accumulated_data, hook_result.route_to)
                    break

            # 2. 开始事务
            cm.begin_iteration()

            # 在迭代内注入新消息（从队列排空）
            # 保存本迭代排空的消息，用于回滚时重新入队，防止消息丢失
            iteration_drained_messages: list[ChatMessage] = []
            new_messages = self._drain_message_queue()
            if new_messages:
                iteration_drained_messages.extend(new_messages)
                cm.add_messages(new_messages)

            try:
                # 3. 执行 _action（包含 LLM 调用 + tool 执行）
                action_output = await self._action(accumulated_data)
                action_results = action_output["results"]
                llm_meta_for_node = action_output.get("llm_metadata", {})

                # 4. 提交事务
                ability_names = (
                    [r.get("ability_name", "unknown") for r in action_results]
                    if action_results
                    else ["no_action"]
                )
                node = cm.commit_iteration(
                    ability_names=ability_names,
                    action_results=action_results,
                    llm_metadata=llm_meta_for_node or None,
                )

                # ────── 发布 ActionChainUpdated 事件 ──────
                # NOTE: 性能优化点 — 当前传输完整序列化 node，
                # 后续可改为仅传输 delta 数据以减少序列化/反序列化开销。
                await self._event_publisher.publish(
                    ActionChainUpdatedEvent(
                        agent_name=self.config.name,
                        node=serialize_node(node),
                    )
                )
                # ────── 结束 ──────

                # 4.5 累加 token 用量到 accumulated_data
                current_usage = node.metadata.get("token_usage", {})
                if current_usage:
                    cumulative = dict(
                        accumulated_data.get(
                            "cumulative_token_usage",
                            {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
                        )
                    )
                    cumulative["input_tokens"] += current_usage.get("input_tokens", 0)
                    cumulative["output_tokens"] += current_usage.get("output_tokens", 0)
                    cumulative["total_tokens"] += current_usage.get("total_tokens", 0)
                    accumulated_data["cumulative_token_usage"] = cumulative
            except Exception as e:
                # ────── 发布 AgentError 事件 ──────
                await self._event_publisher.publish(
                    AgentErrorEvent(
                        agent_name=self.config.name,
                        error=str(e),
                    )
                )
                # ────── 结束 ──────

                cm.rollback_iteration(e)

                # 将本迭代排空的消息重新注入队列，确保回滚后消息不丢失
                for msg in iteration_drained_messages:
                    await self._message_queue.put(msg)

                error_ctx = self._build_hook_context(accumulated_data)
                await self._run_hooks(HookPoint.ON_ERROR, error_ctx)
                raise AgentError(self.config.name, f"Action failed: {e}") from e

            # 5. AFTER_ACTION hook（drive_loop 级）
            # 从 action_results 提取最后一个 ActionResult 作为 last_action_result
            last_ability_name = ""
            if action_results:
                last_entry = action_results[-1]
                cm.last_action_result = last_entry.get("action_result")
                last_ability_name = last_entry.get("ability_name", "")
            else:
                cm.last_action_result = None

            after_ctx = self._build_hook_context(accumulated_data, ability_name=last_ability_name)
            hook_result = await self._run_hooks(HookPoint.AFTER_ACTION, after_ctx)
            if hook_result is not None:
                if hook_result.modified_context:
                    accumulated_data.update(hook_result.modified_context)
                if hook_result.route_to:
                    cm.pending_route = hook_result.route_to
                    cm.advance_iteration()
                    continue
                if not hook_result.should_continue:
                    break

            # 6. 检查最大迭代
            if not cm.is_unlimited and cm.iteration + 1 >= cm.max_iterations:
                max_ctx = self._build_hook_context(accumulated_data)
                max_hook_result = await self._run_hooks(HookPoint.ON_MAX_ITERATIONS, max_ctx)
                if max_hook_result is not None and max_hook_result.route_to:
                    await self._execute_routed_ability(accumulated_data, max_hook_result.route_to)
                break

            cm.advance_iteration()

    async def _action(self, accumulated_data: dict[str, Any]) -> dict[str, Any]:
        """执行一次 action：调用 LLM → 解析响应 → 执行 abilities。

        多个 tool_calls 使用 asyncio.gather 并行执行，

        Args:
            accumulated_data: 累积数据（跨迭代传递的中间结果）

        Returns:
            dict 包含:
                - "results": list[dict] — 每个 dict 包含 "ability_name" 和 "action_result"
                - "llm_metadata": dict — LLM 响应元数据（token_usage、response_metadata 等）
        """
        cm = self._context_manager
        llm = await self._ensure_llm()

        # 1. PRE_LLM_CALL hook（action 级）
        pre_ctx = self._build_hook_context(accumulated_data)
        hook_result = await self._run_hooks(HookPoint.PRE_LLM_CALL, pre_ctx)
        if hook_result is not None:
            if hook_result.modified_context:
                accumulated_data.update(hook_result.modified_context)

        # 2. 调用 LLM
        messages = await cm.get_llm_messages()
        llm_response: LLMResponse = await llm.generate(messages)

        # 2.5 提取 LLM 响应 metadata
        token_usage = extract_token_usage(llm_response)
        cot_content = extract_reasoning_content(llm_response)
        resp_meta = extract_response_metadata(llm_response)

        # CoT 写入 accumulated_data，供 Ability/Hook 使用
        if cot_content:
            accumulated_data["cot_content"] = cot_content

        # 构建 llm_metadata dict，供 commit_iteration 使用
        llm_meta: dict[str, Any] = {}
        if token_usage:
            llm_meta["token_usage"] = token_usage.to_dict()
        if resp_meta:
            llm_meta["response_metadata"] = resp_meta

        # 3. 将 AI 响应添加到消息历史
        cm.add_messages([llm_response.to_chat_message(source=f"agent:{self.config.name}")])

        # 4. POST_LLM_CALL hook（action 级）
        post_ctx = self._build_hook_context(accumulated_data)
        hook_result = await self._run_hooks(HookPoint.POST_LLM_CALL, post_ctx)
        if hook_result is not None:
            if hook_result.modified_context:
                accumulated_data.update(hook_result.modified_context)

        # 5. 解析 LLM 响应
        tool_calls = llm_response.tool_calls
        response_content = llm_response.text or ""

        results: list[dict] = []

        if not tool_calls:
            # 纯文本响应 → conversation ability
            accumulated_data["llm_response"] = response_content
            conversation_ability = self._abilities.get("conversation")
            if conversation_ability:
                ability_ctx = self._build_ability_context("conversation", {}, accumulated_data)
                # 委托给 AbilityExecutor 执行（包含 PRE/POST_EXECUTE Hook 和 HITL 处理）
                action_result = await self._ability_executor.execute_ability(
                    conversation_ability, ability_ctx
                )
                results.append({"ability_name": "conversation", "action_result": action_result})
        else:
            # 有 tool_calls → 委托给 AbilityExecutor 执行
            results = await self._ability_executor.execute_tool_calls(
                tool_calls=tool_calls,
                abilities=self._abilities,
                accumulated_data=accumulated_data,
                context_manager=cm,
            )

            # 将 ChatMessage.tool() 添加到 ContextManager
            tool_messages: list[ChatMessage] = []
            for result_dict in results:
                tc_id = result_dict.get("tool_call_id", "")
                action_result = result_dict["action_result"]
                if tc_id:
                    if action_result.outcome == ActionOutcome.SUCCESS:
                        tool_messages.append(
                            ChatMessage.tool(
                                tool_call_id=tc_id,
                                content=str(action_result.data),
                                source=f"agent:{self.config.name}",
                            )
                        )
                    else:
                        error_msg = action_result.data.get("error", "Unknown error")
                        tool_messages.append(
                            ChatMessage.tool(
                                tool_call_id=tc_id,
                                content=f"Error: {error_msg}",
                                success=False,
                                error=error_msg,
                                source=f"agent:{self.config.name}",
                            )
                        )
            if tool_messages:
                cm.add_messages(tool_messages)

        return {"results": results, "llm_metadata": llm_meta}

    async def _execute_single_ability(
        self, ability: Ability, tool_args: dict[str, Any], accumulated_data: dict[str, Any]
    ) -> dict:
        """执行单个 ability — 委托给 AbilityExecutor。

        为每个 ability 创建独立的 AbilityExecutionContext，
        避免并行执行时的状态污染。

        Args:
            ability: 要执行的 ability 实例
            tool_args: 工具调用参数
            accumulated_data: 累积数据

        Returns:
            dict 包含 "ability_name" 和 "action_result"
        """
        per_ability_context = self._build_ability_context(ability.name, tool_args, accumulated_data)

        # 委托给 AbilityExecutor 执行（包含 PRE/POST_EXECUTE Hook 和 HITL 处理）
        action_result = await self._ability_executor.execute_ability(ability, per_ability_context)

        return {"ability_name": ability.name, "action_result": action_result}

    async def _execute_routed_ability(
        self, accumulated_data: dict[str, Any], ability_name: str
    ) -> None:
        """执行路由目标的 ability（用于 BEFORE_ACTION 和 ON_MAX_ITERATIONS 的强制路由）。"""
        cm = self._context_manager
        ability = self._abilities.get(ability_name)
        if ability is None:
            logger.warning(f"Route target ability '{ability_name}' not found")
            return

        cm.begin_iteration()
        try:
            ctx = self._build_ability_context(ability_name, {}, accumulated_data)
            action_result = await ability.execute(ctx)
            cm.last_action_result = action_result
            cm.commit_iteration(
                ability_names=[ability_name],
                action_results=[{"ability_name": ability_name, "action_result": action_result}],
            )
        except Exception as e:
            cm.rollback_iteration(e)
            raise

    # ----------------------------------------------------------------
    # Hook 运行机制
    # ----------------------------------------------------------------

    # drive_loop 级和 action 级 hook 在 Agent 端直接执行，
    # ability 级 hook 由 AbilityExecutor 管理（远程模式下在 Subject 端执行）。
    _LOCAL_HOOK_POINTS: frozenset[HookPoint] = frozenset(
        {
            HookPoint.BEFORE_ACTION,
            HookPoint.AFTER_ACTION,
            HookPoint.ON_ERROR,
            HookPoint.ON_MAX_ITERATIONS,
            HookPoint.PRE_LLM_CALL,
            HookPoint.POST_LLM_CALL,
        }
    )

    async def _run_hooks(
        self,
        point: HookPoint,
        context: AbilityExecutionContext,
        result: ActionResult | None = None,
    ) -> HookResult | None:
        """运行所有注册的指定触发点的 hooks。

        drive_loop 级和 action 级 hook 由 Agent 直接执行（遍历 self._all_hooks），
        确保在远程模式下这些控制流 hook 仍然生效（如 ConversationDoneHook 终止循环）。
        ability 级 hook（PRE_EXECUTE, POST_EXECUTE）委托给 AbilityExecutor，
        在远程模式下由 Subject 端执行（含 HITL 审批等）。

        Args:
            point: Hook 触发点
            context: 当前执行上下文
            result: ActionResult（POST_EXECUTE 时传入）

        Returns:
            合并后的 HookResult，如果没有 hook 触发则返回 None

        Raises:
            HookError: hook 执行出错时
        """
        if point in self._LOCAL_HOOK_POINTS:
            return await self._run_local_hooks(point, context, result)
        return await self._ability_executor.run_hooks(point, context, result)

    async def _run_local_hooks(
        self,
        point: HookPoint,
        context: AbilityExecutionContext,
        result: ActionResult | None = None,
    ) -> HookResult | None:
        """直接遍历 self._all_hooks 执行匹配的 hook。

        用于 drive_loop 级和 action 级 hook，确保在远程模式下
        控制流 hook（如 ConversationDoneHook终止循环）仍然生效。

        逻辑与 LocalAbilityExecutor.run_hooks() 一致：
        匹配 hook_point 且 should_trigger 返回 True 的 hook 才执行，
        多个 hook 触发时合并结果（后者覆盖前者）。

        Args:
            point: Hook 触发点
            context: 当前执行上下文
            result: ActionResult（用于 POST_EXECUTE 等触发点）

        Returns:
            合并后的 HookResult，如果没有 hook 触发则返回 None

        Raises:
            HookError: hook 执行出错时
        """
        merged: HookResult | None = None

        for hook in self._all_hooks:
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

            if merged is None:
                merged = hook_result
            else:
                merged = merged.merge(hook_result)

        return merged

    # ----------------------------------------------------------------
    # 上下文构建和回复
    # ----------------------------------------------------------------

    def _build_hook_context(
        self,
        accumulated_data: dict[str, Any],
        ability_name: str = "",
    ) -> AbilityExecutionContext:
        """构建用于 Hook 的 AbilityExecutionContext。

        Args:
            accumulated_data: 累积数据
            ability_name: 最后执行的 ability 名称（供 AFTER_ACTION 等 hook 判断）

        Returns:
            初始化后的 AbilityExecutionContext
        """
        cm = self._context_manager
        return AbilityExecutionContext(
            current_ability_name=ability_name,
            agent_state=cm.get_current_state(),
            context_manager=cm,
            accumulated_data=copy.deepcopy(accumulated_data),
            last_action_result=cm.last_action_result,
            supervisor=self._supervisor,
            agent_name=self.config.name,
        )

    def _build_ability_context(
        self,
        ability_name: str,
        tool_args: dict[str, Any],
        accumulated_data: dict[str, Any],
    ) -> AbilityExecutionContext:
        """构建用于 Ability 执行的 AbilityExecutionContext。

        Args:
            ability_name: ability 名称
            tool_args: 工具调用参数
            accumulated_data: 累积数据

        Returns:
            初始化后的 AbilityExecutionContext
        """
        cm = self._context_manager
        return AbilityExecutionContext(
            current_ability_name=ability_name,
            tool_args=tool_args,
            agent_state=cm.get_current_state(),
            context_manager=cm,
            accumulated_data={
                **copy.deepcopy(accumulated_data),
                "tool_args": tool_args,
            },
            last_action_result=cm.last_action_result,
            supervisor=self._supervisor,
            agent_name=self.config.name,
        )

    def _build_response(self, original: Message) -> Message:
        """根据循环结果构建最终回复消息。

        Args:
            original: 原始输入消息

        Returns:
            回复消息
        """
        cm = self._context_manager

        # 从 last_action_result 中提取回复内容
        if cm.last_action_result is not None:
            ar = cm.last_action_result
            content = ar.data.get("response", ar.data.get("content", ""))
            if not content:
                # 尝试将整个 data 转为字符串
                content = str(ar.data) if ar.data else "Task completed"
        else:
            content = "No action executed"

        reply = Message.create_reply(
            original=original,
            content=content,
            msg_type=MessageType.RESULT,
        )
        self._message_history.append(reply)

        # 将 AI 回复添加到 ContextManager
        self._context_manager.add_messages(
            [ChatMessage.ai(text=content, source=f"agent:{self.config.name}")]
        )

        logger.info(f"ActorAgent[{self.config.name}] replied: {content[:100]}...")
        return reply

    # ----------------------------------------------------------------
    # 公共 API
    # ----------------------------------------------------------------

    async def chat(self, content: str, sender: str = "user") -> str:
        """简化的对话接口。

        Args:
            content: 用户输入文本
            sender: 发送者标识

        Returns:
            AI 回复文本
        """
        message = Message(
            sender=sender,
            recipient=self.config.name,
            content=content,
            type=MessageType.CHAT,
        )
        reply = await self.receive(message)
        return reply.content

    def get_history(self) -> list[dict[str, Any]]:
        """获取消息历史。"""
        return [
            {
                "id": msg.id,
                "sender": msg.sender,
                "type": msg.type.value,
                "content": msg.content[:200],
                "timestamp": msg.timestamp,
            }
            for msg in self._message_history
        ]

    def get_state(self) -> dict[str, Any]:
        """获取 Agent 内部状态。"""
        return {
            "name": self.config.name,
            "initialized": self._initialized,
            "abilities": list(self._abilities.keys()),
            "bound_tools": len(self._bound_tools),
            "message_count": len(self._message_history),
            "state": self._context_manager.get_current_state(),
            "event_publisher_type": type(self._event_publisher).__name__,
            "ability_executor_type": type(self._ability_executor).__name__,
        }

    def set_state(self, key: str, value: Any) -> None:
        """设置 Agent 内部状态。

        通过 StateManager.reset() 设置单个键值，
        适用于迭代外的状态设置。
        """
        current = self._context_manager.state_manager.current
        current[key] = value
        self._context_manager.state_manager.reset(new_state=current)

    async def reset(self) -> None:
        """重置 Agent 状态（清空对话历史，保留 LLM 客户端和 abilities）。

        重建 ContextManager 而非清空列表。
        """
        self._message_history.clear()

        # 清空消息队列
        self._message_queue = asyncio.Queue()

        # 重建 ContextManager
        window_manager = None
        if self.config.window is not None:
            window_manager = _build_window_manager(self.config.window)

        context_config = self.config.context
        self._context_manager = ContextManager(
            agent_name=self.config.name,
            initial_state={},
            system_prompt=self.config.system_prompt,
            window_manager=window_manager,
            snapshot_interval=context_config.snapshot_interval if context_config else 5,
            auto_persist=context_config.auto_persist if context_config else False,
        )

        # 重新写入所有 ability 的默认状态（一次性收集，避免多次 reset）
        default_states: dict[str, dict[str, Any]] = {}
        for ability in self._abilities.values():
            default_state = ability.get_default_state()
            if default_state:
                default_states[ability.name] = default_state

        if default_states:
            state_snapshot = self._context_manager.state_manager.current
            for name, state in default_states.items():
                state_snapshot[name] = copy.deepcopy(state)
            self._context_manager.state_manager.reset(new_state=state_snapshot)

        logger.info(f"ActorAgent[{self.config.name}] reset")

    async def send(self, target: str, content: str) -> Message:
        """向其他 Agent 发送消息。

        通过构造函数注入的 Supervisor handle 路由消息，
        无需每次调用传入 supervisor。

        Args:
            target: 目标 Agent 名称
            content: 消息内容

        Returns:
            目标 Agent 的回复消息

        Raises:
            AgentError: 如果未配置 Supervisor
        """
        if self._supervisor is None:
            raise AgentError(
                self.config.name,
                "No supervisor configured, cannot send message to other agents",
            )

        message = Message(
            sender=self.config.name,
            recipient=target,
            content=content,
            type=MessageType.COMMAND,
        )
        logger.info(f"ActorAgent[{self.config.name}] sending to {target}: {content[:100]}...")
        return await self._supervisor.route_message(message)
