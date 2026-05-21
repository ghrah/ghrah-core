# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

__all__ = ["Session"]


@dataclass
class Session:
    """Agent 迭代会话 — 代表 ActionChain 中的一个分支及其元数据。

    一个 Session 对应链中的一个 branch，记录：
    - 会话身份（session_id, branch_name）
    - 起始信息（从哪个节点分叉、从哪个 session 分叉）
    - 跨 Agent rebasing 来源
    - 系统提示词（session 级别，rebase 时不继承来源的）

    Attributes:
        session_id: 唯一标识（UUID4 hex[:16]）
        agent_name: 所属 Agent 名称
        branch_name: 在 ActionChain 中对应的分支名
        created_at: 创建时间
        parent_node_id: 同一 Agent chain 中 fork 起始节点 ID（None 表示根 session）
        parent_session_id: 同一 Agent 中 fork 来源 session ID（None 表示根 session）
        rebase_from_agent: 跨 Agent rebase 来源的 Agent 名称（None 表示非 rebase）
        rebase_from_node_id: 跨 Agent rebase 来源的节点 ID（None 表示非 rebase）
        rebase_from_session_id: 跨 Agent rebase 来源的 session ID
        system_prompt: 此 session 使用的系统提示词
        metadata: 扩展元数据
    """

    session_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    agent_name: str = ""
    branch_name: str = "main"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    parent_node_id: str | None = None
    parent_session_id: str | None = None
    rebase_from_agent: str | None = None
    rebase_from_node_id: str | None = None
    rebase_from_session_id: str | None = None
    system_prompt: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.metadata:
            object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def is_root(self) -> bool:
        return self.parent_node_id is None and self.rebase_from_agent is None

    @property
    def is_rebase(self) -> bool:
        return self.rebase_from_agent is not None
