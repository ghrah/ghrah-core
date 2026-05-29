# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""MessageStore：运行时完整消息 + delta + 定期快照的混合存储。

设计要点：
- 运行时内存中始终维护完整的当前消息列表，O(1) 查询
- compute_delta_since 通过引用比较确定切分点，计算增量
- should_snapshot 在 iteration 0 和每 N 轮触发快照
- rebuild_from 支持从快照 + delta 列表快速重建

快照策略示意：
  iter_0 [snapshot] → iter_1 [delta] → ... → iter_5 [snapshot] → iter_6 [delta]
                                                      ↑ 重建起点
"""

from __future__ import annotations

import copy

from ghrah.chat.message import ChatMessage

__all__ = ["MessageStore"]


class MessageStore:
    """运行时消息存储 — 完整消息 + 定期快照的混合策略。

    Args:
        snapshot_interval: 快照间隔（每 N 轮创建一次快照），默认 5。
            设为 0 或负数则禁用定期快照。
    """

    def __init__(self, snapshot_interval: int = 5) -> None:
        self._messages: list[ChatMessage] = []
        self._snapshot_interval = snapshot_interval
        self._last_snapshot: list[ChatMessage] | None = None
        self._last_snapshot_iteration: int | None = None

    @property
    def current_messages(self) -> list[ChatMessage]:
        """返回当前完整消息列表的副本。"""
        return list(self._messages)

    @property
    def count(self) -> int:
        """当前消息数。"""
        return len(self._messages)

    def __len__(self) -> int:
        return len(self._messages)

    @property
    def last_snapshot(self) -> list[ChatMessage] | None:
        """上一次快照的完整消息（副本），无快照则返回 None。"""
        if self._last_snapshot is None:
            return None
        return list(self._last_snapshot)

    @property
    def last_snapshot_iteration(self) -> int | None:
        """上一次快照时的迭代号。"""
        return self._last_snapshot_iteration

    @property
    def snapshot_interval(self) -> int:
        """快照间隔配置。"""
        return self._snapshot_interval

    def append(self, message: ChatMessage) -> None:
        """追加单条消息。

        Args:
            message: ChatMessage 对象
        """
        self._messages.append(message)

    def extend(self, messages: list[ChatMessage]) -> None:
        """追加多条消息。

        Args:
            messages: ChatMessage 列表
        """
        self._messages.extend(messages)

    def compute_delta_since_last_snapshot(self) -> list[ChatMessage]:
        """计算当前消息相对于内部 _last_snapshot 的增量。

        使用内部 _last_snapshot（引用匹配），确保前缀比较成功。

        Returns:
            增量消息列表。如果没有快照，返回当前完整消息。
        """
        if self._last_snapshot is None:
            return list(self._messages)
        return self.compute_delta_since(self._last_snapshot)

    def compute_delta_since(self, snapshot: list[ChatMessage]) -> list[ChatMessage]:
        """计算当前消息相对于 snapshot 的增量。

        使用引用比较（is）确定 snapshot 在当前列表中的结束位置。
        如果 snapshot 为 None 或无法匹配前缀，返回当前完整消息。
        空列表 snapshot 视为有效基准（从第 0 条消息开始），返回全部消息。

        Args:
            snapshot: 基准快照消息列表

        Returns:
            增量消息列表
        """
        if snapshot is None:
            return list(self._messages)

        snapshot_len = len(snapshot)
        if snapshot_len == 0:
            # 空快照是有效基准：从第 0 条开始的所有消息都是增量
            return list(self._messages)

        if snapshot_len <= len(self._messages):
            # 验证前缀是否一致（引用比较）
            prefix_match = True
            for i in range(snapshot_len):
                if self._messages[i] is not snapshot[i]:
                    prefix_match = False
                    break
            if prefix_match:
                return list(self._messages[snapshot_len:])

        # 无法匹配前缀（可能经历了 rebuild），回退为返回全部消息
        return list(self._messages)

    def should_snapshot(self, iteration: int) -> bool:
        """判断当前迭代是否应创建快照。

        规则：
        - iteration 0 总是快照（根节点）
        - 之后每 snapshot_interval 轮快照一次
        - snapshot_interval <= 0 时不创建定期快照（但 iter 0 仍然快照）

        Args:
            iteration: 当前迭代号

        Returns:
            是否应创建快照
        """
        if iteration == 0:
            return True
        if self._snapshot_interval <= 0:
            return False
        return iteration % self._snapshot_interval == 0

    def take_snapshot(self, iteration: int) -> list[ChatMessage]:
        """创建并返回当前完整消息的深拷贝，同时更新内部快照记录。

        内部 _last_snapshot 存储 _messages 的浅拷贝（引用，用于
        compute_delta_since 的 is 比较）。
        返回给调用者的是深拷贝，确保外部无法修改内部数据。

        Args:
            iteration: 当前迭代号

        Returns:
            完整消息快照（深拷贝）
        """
        # 内部存储浅拷贝（保留消息对象的引用，用于 compute_delta_since 的 is 比较）
        self._last_snapshot = list(self._messages)
        self._last_snapshot_iteration = iteration
        # 返回深拷贝给调用者（外部安全）
        return copy.deepcopy(self._messages)

    def rebuild_from(self, snapshot: list[ChatMessage], deltas: list[list[ChatMessage]]) -> None:
        """从快照 + delta 列表重建完整消息。

        典型场景：从持久化恢复或从某个历史快照节点重建。

        Args:
            snapshot: 基准快照消息列表
            deltas: 按时间顺序排列的增量消息列表
        """
        self._messages = list(snapshot)
        for delta in deltas:
            self._messages.extend(delta)
        self._last_snapshot = list(snapshot)

    def replace_messages(self, messages: list[ChatMessage]) -> None:
        """替换当前完整消息列表。

        用于向后兼容场景（如 property setter 代理）。

        Args:
            messages: 新的消息列表（会被拷贝）
        """
        self._messages = list(messages)

    def clear(self) -> None:
        """清空所有消息和快照记录。"""
        self._messages.clear()
        self._last_snapshot = None
        self._last_snapshot_iteration = None
