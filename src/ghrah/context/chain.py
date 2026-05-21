# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""ActionChain：链式节点管理器。

管理 ContextNode 集合，支持：
- commit_node：追加新节点到链尾
- fork：从指定节点创建分支
- checkout：按 ID 获取节点
- get_history：从 head 回溯到根节点

设计要点：
- 内部用 dict[str, ContextNode] 存储，O(1) 查找
- 分支通过 dict[str, str]（branch_name → head_node_id）管理
- 节点不可变，链管理器只负责创建和索引
- 活跃分支追踪：commit_node 默认使用 _active_branch
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ghrah.context.node import ContextNode

if TYPE_CHECKING:
    pass

__all__ = ["ActionChain"]


class ActionChain:
    """链式节点管理器 — 类似 Git 的 commit 链。

    管理一棵由 ContextNode 组成的不可变链式结构，支持分支。

    Args:
        agent_name: 所属 Agent 名称
    """

    def __init__(self, agent_name: str) -> None:
        self._agent_name = agent_name
        self._nodes: dict[str, ContextNode] = {}
        self._branches: dict[str, str] = {}  # branch_name → head node_id
        self._active_branch: str = "main"

    @property
    def agent_name(self) -> str:
        """所属 Agent 名称。"""
        return self._agent_name

    @property
    def head(self) -> ContextNode | None:
        """main 分支的 head 节点。"""
        return self.get_branch_head("main")

    @property
    def active_branch(self) -> str:
        """当前活跃分支名。"""
        return self._active_branch

    @property
    def active_head(self) -> ContextNode | None:
        """当前活跃分支的 head 节点。"""
        return self.get_branch_head(self._active_branch)

    @property
    def branches(self) -> dict[str, str]:
        """所有分支名 → head node_id 的映射（副本）。"""
        return dict(self._branches)

    @property
    def node_count(self) -> int:
        """总节点数。"""
        return len(self._nodes)

    def set_active_branch(self, branch_name: str) -> None:
        """切换活跃分支。

        Args:
            branch_name: 目标分支名

        Raises:
            ValueError: 分支不存在
        """
        if branch_name not in self._branches:
            raise ValueError(f"Branch '{branch_name}' does not exist.")
        self._active_branch = branch_name

    def init_chain(
        self,
        agent_state: dict[str, Any] | None = None,
        messages: list[Any] | None = None,
    ) -> ContextNode:
        """初始化链，创建根节点。

        只能在链为空时调用。

        Args:
            agent_state: 初始 Agent 状态
            messages: 初始完整消息列表

        Returns:
            根节点

        Raises:
            ValueError: 链已初始化
        """
        if self._nodes:
            raise ValueError("Chain already initialized. Use commit_node() instead.")

        root = ContextNode.create_root(
            agent_name=self._agent_name,
            agent_state=agent_state,
            messages=messages,
        )
        self._nodes[root.id] = root
        self._branches["main"] = root.id
        self._active_branch = "main"
        return root

    def commit_node(
        self,
        ability_names: list[str] | None = None,
        agent_state: dict[str, Any] | None = None,
        messages_delta: list[Any] | None = None,
        messages_snapshot: list[Any] | None = None,
        is_snapshot: bool = False,
        action_results: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
        branch_name: str | None = None,
        session_id: str = "",
    ) -> ContextNode:
        """创建新节点并链接到当前 head。

        新节点的 parent_id 指向当前分支的 head，iteration 自动递增。

        Args:
            ability_names: 本轮执行的 ability 名称列表
            agent_state: 此刻的 Agent 状态快照
            messages_delta: 本轮新增的消息（增量）
            messages_snapshot: 完整消息快照（仅快照节点）
            is_snapshot: 是否为快照节点
            action_results: 本轮执行结果列表
            metadata: 扩展信息
            branch_name: 目标分支名，None 表示使用 active_branch
            session_id: 所属 session 的 ID

        Returns:
            新创建的节点

        Raises:
            ValueError: 目标分支不存在（需先 init_chain 或 fork）
        """
        effective_branch = branch_name or self._active_branch
        head = self.get_branch_head(effective_branch)
        if head is None and effective_branch == "main" and not self._nodes:
            raise ValueError("Chain not initialized. Call init_chain() first.")
        if head is None:
            raise ValueError(
                f"Branch '{effective_branch}' does not exist. Call fork() first."
            )

        node = ContextNode(
            parent_id=head.id,
            agent_name=self._agent_name,
            iteration=head.iteration + 1,
            ability_names=ability_names or [],
            agent_state=agent_state or {},
            messages_delta=messages_delta or [],
            messages_snapshot=messages_snapshot,
            is_snapshot=is_snapshot,
            action_results=action_results or [],
            metadata=metadata or {},
            branch_name=effective_branch,
            session_id=session_id,
        )
        self._nodes[node.id] = node
        self._branches[effective_branch] = node.id
        return node

    def fork(
        self,
        branch_name: str,
        parent_id: str | None = None,
        ability_names: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        session_id: str = "",
    ) -> ContextNode:
        """从指定节点创建分支。

        创建一个 fork 节点，复制 parent 节点的状态作为分支起点。
        分支的 iteration 从 parent 的 iteration + 1 开始。
        fork 后自动切换活跃分支到新分支。

        Args:
            branch_name: 新分支名
            parent_id: fork 起始节点 ID，None 表示从 active head fork
            ability_names: fork 节点的 ability 名称，默认 ["fork"]
            metadata: fork 节点的扩展信息，默认记录 fork_from 和 fork_branch
            session_id: 所属 session 的 ID

        Returns:
            fork 节点

        Raises:
            ValueError: 分支已存在，或 parent 节点不存在
        """
        if branch_name in self._branches:
            raise ValueError(f"Branch '{branch_name}' already exists.")

        # 确定 parent
        if parent_id is None:
            parent = self.active_head
            if parent is None:
                raise ValueError("Cannot fork from empty chain. Call init_chain() first.")
        else:
            parent = self._nodes.get(parent_id)
            if parent is None:
                raise ValueError(f"Node '{parent_id}' not found.")

        effective_ability_names = ability_names or ["fork"]
        effective_metadata = metadata or {
            "fork_from": parent.id,
            "fork_branch": branch_name,
        }

        # 创建 fork 节点：继承 parent 状态
        fork_node = ContextNode(
            parent_id=parent.id,
            agent_name=self._agent_name,
            iteration=parent.iteration + 1,
            ability_names=effective_ability_names,
            agent_state=parent.agent_state,
            messages_delta=[],
            messages_snapshot=None,
            is_snapshot=False,
            metadata=effective_metadata,
            branch_name=branch_name,
            session_id=session_id,
        )
        self._nodes[fork_node.id] = fork_node
        self._branches[branch_name] = fork_node.id
        self._active_branch = branch_name
        return fork_node

    def checkout(self, node_id: str) -> ContextNode | None:
        """获取指定 ID 的节点。

        Args:
            node_id: 节点 ID

        Returns:
            对应的 ContextNode，不存在则返回 None
        """
        return self._nodes.get(node_id)

    def get_branch_head(self, branch: str = "main") -> ContextNode | None:
        """获取指定分支的 head 节点。

        Args:
            branch: 分支名，默认 "main"

        Returns:
            分支的 head 节点，分支不存在则返回 None
        """
        head_id = self._branches.get(branch)
        if head_id is None:
            return None
        return self._nodes.get(head_id)

    def get_history(self, branch: str | None = None, limit: int = -1) -> list[ContextNode]:
        """从 head 回溯到根节点，返回历史序列。

        返回列表按时间顺序排列（根节点在前，head 在后）。

        Args:
            branch: 分支名，None 表示使用 active_branch
            limit: 限制返回数量。-1 表示全部，>0 返回最近 N 个。

        Returns:
            历史节点列表
        """
        effective_branch = branch or self._active_branch
        head = self.get_branch_head(effective_branch)
        if head is None:
            return []

        history: list[ContextNode] = []
        current: ContextNode | None = head
        while current is not None:
            history.append(current)
            current = self._nodes.get(current.parent_id) if current.parent_id else None

        history.reverse()

        if limit > 0:
            return history[-limit:]
        return history

    @classmethod
    def rebuild_from_nodes(
        cls,
        agent_name: str,
        nodes: list[ContextNode],
        active_branch: str = "main",
    ) -> ActionChain:
        """从持久化的节点列表重建 ActionChain。

        按 parent → child 的拓扑顺序重建内部索引和分支映射。
        根节点（parent_id=None）的 branch_name 作为分支的起始点，
        每个节点会将其 branch_name 的 head 更新为自身（即最晚写入的节点为 head）。

        Args:
            agent_name: 所属 Agent 名称
            nodes: 持久化恢复的节点列表（顺序不限）
            active_branch: 重建后的活跃分支名，默认 "main"

        Returns:
            重建后的 ActionChain 实例
        """
        chain = cls(agent_name)
        for node in nodes:
            chain._nodes[node.id] = node
            chain._branches[node.branch_name] = node.id
        chain._active_branch = active_branch
        return chain

    def ingest_node(self, node: ContextNode) -> None:
        """接纳外部创建的节点到链中。

        与 commit_node 不同，ingest_node 接受已完整构造的 ContextNode，
        不修改其任何字段，仅更新内部索引。

        Args:
            node: 要接纳的节点
        """
        self._nodes[node.id] = node
        self._branches[node.branch_name] = node.id

    def replace_node(self, node: ContextNode) -> None:
        """替换链中同 ID 的已有节点。

        用于 frozen dataclass 的字段更新场景（如补充 session_id）。
        节点 ID 必须已存在于链中。

        Args:
            node: 要替换的新节点（ID 必须与链中已有节点一致）

        Raises:
            ValueError: 节点 ID 不存在于链中
        """
        if node.id not in self._nodes:
            raise ValueError(f"Node '{node.id}' not found in chain.")
        self._nodes[node.id] = node

    def update_branch(self, branch_name: str, head_id: str) -> None:
        """更新指定分支的 head 指针。

        Args:
            branch_name: 分支名
            head_id: 新的 head 节点 ID
        """
        self._branches[branch_name] = head_id
