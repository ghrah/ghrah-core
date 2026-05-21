# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""ContextManager：上下文管理器门面类。

整合 ActionChain + StateManager + MessageStore + Session 管理，
为 ActorAgent 提供统一的上下文管理接口。

核心职责：
- 迭代生命周期：begin_iteration → commit_iteration / rollback_iteration
- 消息+状态协调：commit 时自动计算 delta、定期存储 snapshot、管理 state 事务
- 上下文构建：build_execution_context 供 Ability/Hook 使用
- 子 Agent 继承：fork_for_sub_agent 创建独立但继承的上下文
- Session 管理：create_session / switch_session / list_sessions
- 持久化：persist/restore 异步保存和恢复完整链式状态
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from ghrah.abilities.base import ActionResult
from ghrah.context.chain import ActionChain
from ghrah.context.message_store import MessageStore
from ghrah.context.node import ContextNode
from ghrah.context.persistence import PersistenceBackend
from ghrah.context.session import Session
from ghrah.context.state import StateManager
from ghrah.context.window import WindowManager

if TYPE_CHECKING:
    from ghrah.abilities.context import AbilityExecutionContext
    from ghrah.core.config import AgentConfig
    from ghrah.core.message import Message

logger = logging.getLogger(__name__)

__all__ = ["ContextManager"]


class ContextManager:
    """上下文管理器门面类 — 整合 Chain + StateManager + MessageStore + Session。

    为 ActorAgent 的驱动循环提供统一的上下文管理，支持：
    - 原子性迭代（事务性状态变更 + 消息管理）
    - 链式历史（类似 Git 的不可变节点链）
    - Session 管理（分支 + 元数据）
    - 回滚即分支（rollback 自动创建新 branch，保持 chain 只读性）
    - 子 Agent 继承（fork_for_sub_agent 创建独立上下文）
    - 异步持久化（persist/restore）

    迭代生命周期：
        begin_iteration() → add_messages() / apply_state_changes()
        → commit_iteration() 或 rollback_iteration()

    Args:
        agent_name: 所属 Agent 名称
        initial_state: 初始 Agent 状态
        snapshot_interval: 消息快照间隔，默认 5
        system_prompt: 系统提示词
        window_manager: 窗口管理器（可选）
        persistence: 持久化后端（可选，None 则不持久化）
        auto_persist: 是否在每次 commit/rollback 后自动持久化节点，默认 False
    """

    def __init__(
        self,
        agent_name: str,
        initial_state: dict[str, Any] | None = None,
        snapshot_interval: int = 5,
        system_prompt: str = "",
        window_manager: WindowManager | None = None,
        persistence: PersistenceBackend | None = None,
        auto_persist: bool = False,
    ) -> None:
        self._agent_name = agent_name
        self._chain = ActionChain(agent_name)
        self._state_manager = StateManager(initial_state)
        self._message_store = MessageStore(snapshot_interval=snapshot_interval)
        self._system_prompt = system_prompt
        self._window_manager = window_manager
        self._persistence = persistence
        self._auto_persist = auto_persist
        self._pending_messages: list[Any] = []
        self._in_iteration: bool = False
        self._persist_tasks: set[asyncio.Task[Any]] = set()

        # 驱动循环控制状态
        self._iteration: int = 0
        self._max_iterations: int = 10
        self._last_action_result: ActionResult | None = None
        self._pending_route: str | None = None

        # Session 管理
        self._sessions: dict[str, Session] = {}
        self._active_session_id: str | None = None

        # 初始化链：创建根节点
        initial_messages: list[Any] = []
        if system_prompt:
            from ghrah.chat.message import ChatMessage

            msg = ChatMessage.system(text=system_prompt)
            initial_messages.append(msg)
            self._message_store.append(msg)

        self._chain.init_chain(
            agent_state=initial_state or {},
            messages=initial_messages,
        )

        # 创建根 session
        root_session = Session(
            agent_name=agent_name,
            branch_name="main",
            system_prompt=system_prompt or "",
        )
        self._sessions[root_session.session_id] = root_session
        self._active_session_id = root_session.session_id

        # 建立初始快照基准
        self._message_store.take_snapshot(0)

    # ----------------------------------------------------------------
    # 属性
    # ----------------------------------------------------------------

    @property
    def agent_name(self) -> str:
        """所属 Agent 名称。"""
        return self._agent_name

    @property
    def chain(self) -> ActionChain:
        """底层链管理器（只读访问）。"""
        return self._chain

    @property
    def state_manager(self) -> StateManager:
        """底层状态管理器（只读访问）。"""
        return self._state_manager

    @property
    def message_store(self) -> MessageStore:
        """底层消息存储（只读访问）。"""
        return self._message_store

    @property
    def in_iteration(self) -> bool:
        """是否在迭代中。"""
        return self._in_iteration

    @property
    def window_manager(self) -> WindowManager | None:
        """窗口管理器（只读访问）。"""
        return self._window_manager

    @property
    def persistence(self) -> PersistenceBackend | None:
        """持久化后端（只读访问）。"""
        return self._persistence

    @property
    def auto_persist(self) -> bool:
        """是否自动持久化。"""
        return self._auto_persist

    # ----------------------------------------------------------------
    # 驱动循环控制状态
    # ----------------------------------------------------------------

    @property
    def iteration(self) -> int:
        """当前迭代次数。"""
        return self._iteration

    @property
    def max_iterations(self) -> int:
        """最大迭代次数（-1 代表无上限）。"""
        return self._max_iterations

    @max_iterations.setter
    def max_iterations(self, value: int) -> None:
        self._max_iterations = value

    @property
    def is_unlimited(self) -> bool:
        """是否无上限迭代。"""
        return self._max_iterations < 0

    @property
    def should_continue(self) -> bool:
        """是否应该继续循环。"""
        return self.is_unlimited or self._iteration < self._max_iterations

    def advance_iteration(self) -> None:
        """推进迭代计数。"""
        self._iteration += 1

    def reset_iteration(self) -> None:
        """重置迭代计数。"""
        self._iteration = 0

    @property
    def last_action_result(self) -> ActionResult | None:
        """上一次 action 的结果。"""
        return self._last_action_result

    @last_action_result.setter
    def last_action_result(self, value: ActionResult | None) -> None:
        self._last_action_result = value

    @property
    def pending_route(self) -> str | None:
        """Hook 设置的路由目标。"""
        return self._pending_route

    @pending_route.setter
    def pending_route(self, value: str | None) -> None:
        self._pending_route = value

    # ----------------------------------------------------------------
    # Session 管理
    # ----------------------------------------------------------------

    def create_session(
        self,
        from_node_id: str | None = None,
        system_prompt: str | None = None,
        session_name: str | None = None,
        session_metadata: dict[str, Any] | None = None,
    ) -> Session:
        """创建新 session（分支）。

        从指定节点处 fork 出新分支。如果不指定 from_node_id，
        则从当前活跃分支的 head 创建。

        Args:
            from_node_id: fork 起始节点 ID（None 表示当前活跃 head）
            system_prompt: 新 session 的系统提示词（None 继承当前）
            session_name: 人类可读的分支名（None 自动生成）
            session_metadata: session 的扩展元数据

        Returns:
            新创建的 Session 实例
        """
        # 确定起始节点
        if from_node_id is None:
            parent_node = self._chain.active_head
            if parent_node is None:
                raise ValueError("Cannot create session from empty chain.")
            from_node_id = parent_node.id
        else:
            parent_node = self._chain.checkout(from_node_id)
            if parent_node is None:
                raise ValueError(f"Node '{from_node_id}' not found.")

        # 生成分支名
        if session_name is None:
            session_name = f"session-{len(self._sessions) + 1}"

        # 获取当前活跃 session 的信息
        current_session = self._sessions.get(self._active_session_id or "")

        # 在 ActionChain 中 fork
        fork_node = self._chain.fork(
            branch_name=session_name,
            parent_id=from_node_id,
            ability_names=["session"],
            metadata={
                "fork_from": from_node_id,
                "fork_branch": session_name,
                "session_created": True,
            },
            session_id="",  # session_id 还没生成，下面补上
        )

        # 创建 Session 对象
        session = Session(
            agent_name=self._agent_name,
            branch_name=session_name,
            parent_node_id=from_node_id,
            parent_session_id=self._active_session_id,
            system_prompt=system_prompt or (current_session.system_prompt if current_session else ""),
            metadata=session_metadata or {},
        )

        # 用 dataclasses.replace 更新 fork 节点的 session_id
        # 因为 ContextNode 是 frozen 的，需要创建新节点替换
        updated_fork = dataclasses.replace(fork_node, session_id=session.session_id)
        self._chain.replace_node(updated_fork)

        self._sessions[session.session_id] = session
        self._active_session_id = session.session_id

        return session

    def list_sessions(self) -> list[Session]:
        """列出所有 session。"""
        return list(self._sessions.values())

    def get_active_session(self) -> Session:
        """获取当前活跃 session。"""
        if self._active_session_id is None:
            raise RuntimeError("No active session.")
        return self._sessions[self._active_session_id]

    def switch_session(self, session_id: str) -> None:
        """切换到指定 session。

        恢复目标 session 对应的 branch head 的状态和消息。

        Args:
            session_id: 目标 session ID

        Raises:
            ValueError: session 不存在
        """
        if session_id not in self._sessions:
            raise ValueError(f"Session '{session_id}' not found.")
        session = self._sessions[session_id]
        self._chain.set_active_branch(session.branch_name)
        self._active_session_id = session_id

        # 从 branch head 的状态恢复
        branch_head = self._chain.active_head
        if branch_head:
            self._state_manager.reset(branch_head.agent_state)

    # ----------------------------------------------------------------
    # 迭代生命周期
    # ----------------------------------------------------------------

    def begin_iteration(self) -> None:
        """开始新迭代。

        开启状态事务，清空 pending_messages 缓冲区。

        Raises:
            RuntimeError: 已有迭代在进行中
        """
        if self._in_iteration:
            raise RuntimeError("Iteration already in progress")
        self._state_manager.begin_transaction()
        self._pending_messages = []
        self._in_iteration = True

    def apply_state_changes(self, changes: dict[str, Any]) -> dict[str, Any]:
        """在当前迭代的事务中应用状态变更。

        变更累积到 pending 区，commit 时才生效。

        Args:
            changes: 要应用的变更（支持嵌套 dict 递归合并）

        Returns:
            合并后的预期状态（深拷贝）

        Raises:
            RuntimeError: 没有活跃的迭代
        """
        if not self._in_iteration:
            raise RuntimeError("No iteration in progress")
        return self._state_manager.apply_changes(changes)

    def add_messages(self, messages: list[Any]) -> None:
        """收集本轮新消息到缓冲区。

        消息在 commit_iteration 时才写入 MessageStore，
        rollback_iteration 时会被丢弃。

        如果不在迭代中（_in_iteration=False），直接写入 MessageStore。
        这种模式用于迭代外的消息注入（如 system_prompt 初始化）。

        Args:
            messages: ChatMessage 列表
        """
        if self._in_iteration:
            self._pending_messages.extend(messages)
        else:
            self._message_store.extend(messages)

    def commit_iteration(
        self,
        ability_names: list[str] | None = None,
        action_results: list[dict[str, Any]] | None = None,
        state_changes: dict[str, Any] | None = None,
        llm_metadata: dict[str, Any] | None = None,
    ) -> ContextNode:
        """提交当前迭代。

        流程：
        1. 如果有额外的 state_changes，先应用
        2. 提交状态事务
        3. 将 pending_messages 写入 MessageStore
        4. 计算 delta / 判断是否需要 snapshot
        5. 创建链式节点

        Args:
            ability_names: 本轮执行的 ability 名称列表
            action_results: 本轮执行结果列表
            state_changes: 额外的状态变更（可选）
            llm_metadata: LLM 响应元数据

        Returns:
            新创建的 ContextNode

        Raises:
            RuntimeError: 没有活跃的迭代
        """
        if not self._in_iteration:
            raise RuntimeError("No iteration in progress")

        effective_names: list[str]
        effective_result: Any | None

        if ability_names is not None:
            effective_names = ability_names
            effective_result = action_results
        else:
            effective_names = ["unknown"]
            effective_result = None

        # 1. 如果有额外的 state_changes，先应用
        if state_changes:
            self._state_manager.apply_changes(state_changes)

        # 2. 提交状态事务
        new_state = self._state_manager.commit()

        # 3. 将 pending_messages 写入 MessageStore
        self._message_store.extend(self._pending_messages)

        # 4. 计算迭代号（基于 chain head）
        head = self._chain.active_head
        iteration = (head.iteration + 1) if head else 0

        # 5. delta 为当前轮次新增的消息
        delta = list(self._pending_messages)

        # 6. 判断是否需要快照
        is_snapshot = self._message_store.should_snapshot(iteration)
        if is_snapshot:
            snapshot = self._message_store.take_snapshot(iteration)
        else:
            snapshot = None

        # 7. 合并 llm_metadata 到节点 metadata
        node_metadata: dict[str, Any] = {}
        if llm_metadata:
            node_metadata.update(llm_metadata)

        # 8. 获取活跃 session 信息
        active_session_id = self._active_session_id or ""

        # 9. 创建链式节点
        node = self._chain.commit_node(
            ability_names=effective_names,
            agent_state=new_state,
            messages_delta=delta,
            messages_snapshot=snapshot,
            is_snapshot=is_snapshot,
            action_results=effective_result or [],
            metadata=node_metadata or None,
            session_id=active_session_id,
        )

        # 10. 清理迭代状态
        self._pending_messages = []
        self._in_iteration = False

        # 11. 自动持久化（如果启用）
        if self._auto_persist and self._persistence is not None:
            self._schedule_persist_node(node)

        return node

    # ----------------------------------------------------------------
    # 回滚即分支
    # ----------------------------------------------------------------

    def rollback_iteration(self, error: Exception) -> ContextNode:
        """回滚当前迭代，自动创建新 branch/session 从回滚目标重新开始。

        流程：
        1. 回滚状态事务（恢复到迭代前）
        2. 丢弃 pending_messages（不写入 MessageStore）
        3. 确定回滚目标：当前 branch head 的前驱节点
        4. 创建新 session（自动命名 rollback-{n}）
        5. 通过 ActionChain.fork() 从回滚目标节点创建新 branch
        6. fork 节点的 metadata 记录 rollback 事件
        7. 切换到新 session

        Args:
            error: 导致回滚的异常

        Returns:
            fork 节点（rollback branch 的起点）

        Raises:
            RuntimeError: 没有活跃的迭代
            ValueError: 无法回滚（没有前驱节点可回退到）
        """
        if not self._in_iteration:
            raise RuntimeError("No iteration in progress")

        # 1. 回滚状态事务
        self._state_manager.rollback()

        # 2. 确定回滚目标：当前活跃 branch head 的前驱节点
        #    如果活跃 head 没有前驱节点（根节点），回滚目标是根节点自身
        current_head = self._chain.active_head
        if current_head is None:
            # 不应该发生：活跃分支没有 head
            self._pending_messages = []
            self._in_iteration = False
            raise ValueError("Cannot rollback: no active branch head.")

        if current_head.parent_id is None:
            # 根节点：回滚到根节点自身，fork 仍在根节点上
            rollback_target_id = current_head.id
        else:
            rollback_target_id = current_head.parent_id

        # 4. 生成分支名
        rollback_branch = f"rollback-{len(self._sessions) + 1}"

        # 5. 获取当前 session 信息用于 rollback metadata
        current_session_id = self._active_session_id or ""

        # 6. 通过 fork 创建新 branch，从回滚目标节点开始
        fork_node = self._chain.fork(
            branch_name=rollback_branch,
            parent_id=rollback_target_id,
            ability_names=["rollback"],
            metadata={
                "is_rollback": True,
                "rollback_from_branch": current_head.branch_name,
                "rollback_from_node_id": current_head.id,
                "rollback_to_node_id": rollback_target_id,
                "error": str(error),
                "error_type": type(error).__name__,
            },
            session_id=current_session_id,
        )

        # 7. 创建 rollback session
        current_session = self._sessions.get(current_session_id)
        session = Session(
            agent_name=self._agent_name,
            branch_name=rollback_branch,
            parent_node_id=rollback_target_id,
            parent_session_id=current_session_id,
            system_prompt=current_session.system_prompt if current_session else "",
            metadata={
                "is_rollback": True,
                "rollback_from_branch": current_head.branch_name,
                "rollback_from_node_id": current_head.id,
                "rollback_to_node_id": rollback_target_id,
                "error": str(error),
                "error_type": type(error).__name__,
            },
        )

        # 更新 fork 节点的 session_id
        updated_fork = dataclasses.replace(fork_node, session_id=session.session_id)
        self._chain.replace_node(updated_fork)

        self._sessions[session.session_id] = session
        self._active_session_id = session.session_id

        # 8. 清理迭代状态
        self._pending_messages = []
        self._in_iteration = False

        # 9. 自动持久化 fork 节点（如果启用）
        if self._auto_persist and self._persistence is not None:
            self._schedule_persist_node(updated_fork)

        return updated_fork

    # ----------------------------------------------------------------
    # 上下文构建
    # ----------------------------------------------------------------

    def build_execution_context(
        self,
        message: Message | None = None,
        config: AgentConfig | None = None,
        system_prompt: str | None = None,
        context_filter: Callable | None = None,
    ) -> AbilityExecutionContext:
        """构建 AbilityExecutionContext。

        Args:
            message: 输入消息（可选，保留向后兼容）
            config: Agent 配置（可选）
            system_prompt: 覆盖默认 system_prompt（可选）
            context_filter: 上下文过滤函数（可选）

        Returns:
            初始化后的 AbilityExecutionContext
        """
        from ghrah.abilities.context import AbilityExecutionContext

        return AbilityExecutionContext(
            current_ability_name="",
            agent_state=self._state_manager.current,
            context_manager=self,
            last_action_result=self._last_action_result,
        )

    async def get_llm_messages(
        self,
        max_tokens: int | None = None,
        filter_fn: Callable | None = None,
    ) -> list[Any]:
        """获取 LLM 消息列表。

        返回经过窗口管理策略处理后的消息列表。
        如果配置了 WindowManager，会自动应用压缩策略确保消息在 token 预算内。

        Args:
            max_tokens: 最大 token 数（可选，覆盖 WindowManager 的默认值）
            filter_fn: 消息过滤函数（可选）

        Returns:
            ChatMessage 列表
        """
        messages = self._message_store.current_messages

        # 合并 pending_messages（迭代中尚未 commit 的消息）
        if self._in_iteration and self._pending_messages:
            messages = messages + list(self._pending_messages)
            logger.debug(
                "get_llm_messages: merged %d pending "
                "messages into LLM context (total=%d)",
                len(self._pending_messages),
                len(messages),
            )

        if filter_fn is not None:
            messages = [m for m in messages if filter_fn(m)]

        # 应用窗口管理策略
        if self._window_manager is not None:
            budget = max_tokens or self._window_manager.max_tokens
            messages = await self._window_manager.apply(messages, max_tokens=budget)

        return messages

    def get_cumulative_token_usage(self) -> dict[str, int]:
        """从链历史中累计计算总 token 用量。

        遍历所有链节点的 metadata.token_usage 字段，累加得到总和。

        Returns:
            包含 input_tokens、output_tokens、total_tokens 的 dict
        """
        total: dict[str, int] = {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
        }
        for node in self._chain.get_history():
            usage = node.metadata.get("token_usage", {})
            if isinstance(usage, dict):
                total["input_tokens"] += usage.get("input_tokens", 0)
                total["output_tokens"] += usage.get("output_tokens", 0)
                total["total_tokens"] += usage.get("total_tokens", 0)
        return total

    # ----------------------------------------------------------------
    # 子 Agent 支持
    # ----------------------------------------------------------------

    def fork_for_sub_agent(
        self,
        agent_name: str,
        system_prompt: str | None = None,
        state_filter: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        snapshot_interval: int | None = None,
    ) -> ContextManager:
        """为子 Agent fork 出独立的上下文。

        向后兼容的子 Agent fork 方法。内部调用 create_rebased_context()。

        注意：如果 system_prompt=None，旧行为是继承父 Agent 的 system_prompt。
        这与 rebase 的默认语义（不继承 system_prompt）不同。
        为保持向后兼容，当 system_prompt=None 时使用父 Agent 的 system_prompt。

        Args:
            agent_name: 子 Agent 名称
            system_prompt: 覆盖 system_prompt（可选，None 继承父 Agent 的）
            state_filter: 状态过滤函数，选择性继承状态（可选）
            snapshot_interval: 快照间隔（可选，默认使用父 CM 的设置）

        Returns:
            子 Agent 的 ContextManager
        """
        from ghrah.context.rebase import create_rebased_context

        effective_prompt = system_prompt or self._system_prompt
        return create_rebased_context(
            source_cm=self,
            agent_name=agent_name,
            system_prompt=effective_prompt,
            inherit_messages=True,
            inherit_state=True,
            state_filter=state_filter,
            snapshot_interval=snapshot_interval,
        )

    # ----------------------------------------------------------------
    # Rebase 辅助方法
    # ----------------------------------------------------------------

    def extend_messages(self, messages: list[Any]) -> None:
        """直接向 MessageStore 追加消息（不受迭代状态影响）。

        用于 rebase 等场景，需要将源 Agent 的消息直接注入到 MessageStore。

        Args:
            messages: 要追加的消息列表
        """
        self._message_store.extend(messages)

    def upsert_session(self, session: Session) -> None:
        """插入或更新 session，并设为活跃 session。

        Args:
            session: Session 实例
        """
        self._sessions[session.session_id] = session
        self._active_session_id = session.session_id

    def update_root_node(self, node: ContextNode) -> None:
        """替换 main 分支的根节点（用于 rebase 时记录来源信息）。

        Args:
            node: 替换后的根节点（ID 必须与当前根节点一致）
        """
        self._chain.replace_node(node)

    # ----------------------------------------------------------------
    # 查询
    # ----------------------------------------------------------------

    def get_history(self, limit: int = -1) -> list[ContextNode]:
        """获取链历史。

        Args:
            limit: 限制返回数量。-1 表示全部，>0 返回最近 N 个。

        Returns:
            历史节点列表（根在前）
        """
        return self._chain.get_history(limit=limit)

    def get_current_state(self) -> dict[str, Any]:
        """获取当前状态的深拷贝。

        Returns:
            当前状态快照
        """
        return self._state_manager.get_snapshot()

    def get_branch_heads(self) -> dict[str, ContextNode]:
        """获取所有分支的头节点。

        Returns:
            分支名 → head ContextNode 的映射
        """
        result: dict[str, ContextNode] = {}
        for branch_name, head_id in self._chain.branches.items():
            node = self._chain.checkout(head_id)
            if node is not None:
                result[branch_name] = node
        return result

    def get_chain_node(self, node_id: str) -> ContextNode | None:
        """获取指定 ID 的链节点。

        Args:
            node_id: 节点 ID

        Returns:
            对应的 ContextNode，不存在则返回 None
        """
        return self._chain.checkout(node_id)

    # ----------------------------------------------------------------
    # 持久化
    # ----------------------------------------------------------------

    async def persist(self) -> None:
        """显式持久化当前完整状态到后端。

        保存内容：
        1. 链的所有节点（遍历 ActionChain 内部节点）
        2. 链元信息（分支映射 + 当前状态 + 活跃 session）
        3. 当前完整消息列表
        4. 所有 session

        Raises:
            RuntimeError: 未配置持久化后端
        """
        if self._persistence is None:
            logger.warning("persist() called but no persistence backend configured")
            return

        # 等待所有后台 auto-persist 任务完成，避免竞态
        await self.wait_for_persist()

        # 原子替换：先清除旧数据
        await self._persistence.delete_chain(self._agent_name)

        try:
            # 1. 保存所有节点
            for node_id, node in self._chain._nodes.items():
                await self._persistence.save_node(node)

            # 2. 保存所有 session
            for session in self._sessions.values():
                await self._persistence.save_session(session)

            # 3. 保存链元信息
            await self._persistence.save_chain_meta(
                agent_name=self._agent_name,
                branches=self._chain.branches,
                current_state=self._state_manager.get_snapshot(),
                active_session_id=self._active_session_id or "",
            )

            # 4. 保存当前完整消息列表
            await self._persistence.save_messages(
                agent_name=self._agent_name,
                messages=self._message_store.current_messages,
            )
        except Exception:
            # 持久化失败，清理残留数据避免不一致
            logger.exception(
                "Persist failed for agent '%s', cleaning up partial data",
                self._agent_name,
            )
            await self._persistence.delete_chain(self._agent_name)
            raise

        logger.debug(
            "Persisted context for agent '%s': %d nodes, %d sessions, %d messages",
            self._agent_name,
            self._chain.node_count,
            len(self._sessions),
            self._message_store.count,
        )

    async def restore(self, agent_name: str) -> None:
        """从后端恢复状态，重建 chain、state、messages、sessions。

        恢复流程：
        1. 加载链元信息（branches + current_state + active_session_id）
        2. 加载所有节点，重建 ActionChain
        3. 从 current_state 恢复 StateManager
        4. 加载消息列表，恢复 MessageStore
        5. 加载 sessions，恢复 session 映射

        Args:
            agent_name: 要恢复的 Agent 名称

        Raises:
            RuntimeError: 未配置持久化后端
            ValueError: 后端中无该 agent 的数据
        """
        if self._persistence is None:
            raise RuntimeError("No persistence backend configured")

        # 1. 加载链元信息
        meta = await self._persistence.load_chain_meta(agent_name)
        if meta is None:
            raise ValueError(f"No persisted data found for agent '{agent_name}'")

        branches, active_session_id, current_state = meta

        # 2. 加载所有节点，重建 ActionChain
        nodes = await self._persistence.load_chain(agent_name)
        if not nodes:
            raise ValueError(f"No persisted nodes found for agent '{agent_name}'")

        # 重建 chain
        self._agent_name = agent_name
        self._chain = ActionChain(agent_name)

        # 找到根节点（iteration=0 或 parent_id=None）
        root = next((n for n in nodes if n.parent_id is None), nodes[0])
        self._chain._nodes[root.id] = root
        self._chain._branches["main"] = root.id

        # 添加其余节点（跳过根节点）
        for node in nodes:
            if node.id == root.id:
                continue
            self._chain._nodes[node.id] = node

        # 恢复分支映射
        for branch_name, head_id in branches.items():
            self._chain._branches[branch_name] = head_id

        # 恢复活跃分支
        if active_session_id:
            # 从 session 映射找到对应的 branch_name
            sessions = await self._persistence.list_sessions(agent_name)
            self._sessions = {s.session_id: s for s in sessions}
            active_session = self._sessions.get(active_session_id)
            if active_session:
                self._chain._active_branch = active_session.branch_name
            else:
                self._chain._active_branch = "main"
        else:
            self._chain._active_branch = "main"

        self._active_session_id = active_session_id or None

        # 3. 恢复 StateManager
        self._state_manager = StateManager(current_state)

        # 4. 恢复 MessageStore
        messages = await self._persistence.load_messages(agent_name)

        # 尝试从快照节点重建
        snapshot_node = next(
            (n for n in reversed(nodes) if n.is_snapshot and n.messages_snapshot),
            None,
        )
        if snapshot_node and snapshot_node.messages_snapshot:
            deltas: list[list[Any]] = []
            found_snapshot = False
            for node in nodes:
                if node.id == snapshot_node.id:
                    found_snapshot = True
                    continue
                if found_snapshot and node.messages_delta:
                    deltas.append(node.messages_delta)

            self._message_store = MessageStore(
                snapshot_interval=self._message_store.snapshot_interval,
            )
            self._message_store.rebuild_from(snapshot_node.messages_snapshot, deltas)
        elif messages:
            self._message_store = MessageStore(
                snapshot_interval=self._message_store.snapshot_interval,
            )
            self._message_store.extend(messages)

        self._pending_messages = []
        self._in_iteration = False

        # 恢复 system_prompt
        active_session = self._sessions.get(active_session_id) if active_session_id else None
        if active_session:
            self._system_prompt = active_session.system_prompt
        elif not self._sessions:
            # 旧格式没有 session 数据，需要从根节点的 system message 恢复
            root_session = Session(
                agent_name=agent_name,
                branch_name="main",
                system_prompt=self._system_prompt,
            )
            self._sessions[root_session.session_id] = root_session
            self._active_session_id = root_session.session_id

        logger.debug(
            "Restored context for agent '%s': %d nodes, %d sessions, %d messages",
            agent_name,
            self._chain.node_count,
            len(self._sessions),
            self._message_store.count,
        )

    async def wait_for_persist(self) -> None:
        """等待所有待处理的后台持久化任务完成。

        在调用 persist() 前自动调用，也可手动调用以确保所有
        auto-persist 调度的节点保存操作已完成。
        """
        if self._persist_tasks:
            await asyncio.gather(*self._persist_tasks, return_exceptions=True)
            self._persist_tasks.clear()

    def _schedule_persist_node(self, node: ContextNode) -> None:
        """后台异步保存单个节点（不阻塞主循环）。

        Args:
            node: 要保存的 ContextNode
        """
        if self._persistence is None:
            return

        tasks = self._persist_tasks
        persist_backend = self._persistence
        agent_name = self._agent_name

        async def _do_save() -> None:
            try:
                await persist_backend.save_node(node)
            except Exception:
                logger.warning(
                    "Failed to persist node '%s' for agent '%s'",
                    node.id,
                    agent_name,
                    exc_info=True,
                )

        async def _tracked_save() -> None:
            try:
                await _do_save()
            finally:
                tasks.discard(task)

        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(_tracked_save())
            tasks.add(task)
        except RuntimeError:
            logger.debug(
                "No running event loop, skipping auto-persist for node '%s'",
                node.id,
            )

    # ----------------------------------------------------------------
    # 内部辅助
    # ----------------------------------------------------------------

    def _get_conversation_history(self) -> list[Any]:
        """获取对话历史（Message 对象列表）。

        Returns:
            消息历史列表
        """
        return []
