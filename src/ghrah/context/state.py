# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""StateManager：事务性状态管理器。

为 Agent 的状态变更提供原子性保证，支持：
- begin_transaction / apply_changes / commit / rollback 事务模型
- 嵌套事务（savepoint 机制）
- deep copy 保证状态隔离
- 递归字典合并（_DELETE sentinel 删除键）

事务生命周期：
    Idle → begin_transaction → InTransaction
    InTransaction → apply_changes → InTransaction（累积变更）
    InTransaction → commit → Idle（变更生效）
    InTransaction → rollback → Idle（变更丢弃）
"""

from __future__ import annotations

import copy
from typing import Any

__all__ = ["StateManager"]

# 删除标记 sentinel — apply_changes 中使用此值删除特定键
_DELETE = object()


class StateManager:
    """事务性状态管理器 — 提供原子性状态变更。

    使用 deep copy 保证事务隔离：
    - begin_transaction 时保存当前状态的深拷贝作为 baseline
    - apply_changes 将变更累积到 pending 区
    - commit 将 pending 合并到 current
    - rollback 恢复到 baseline

    Thread Safety:
        本类 **不是** 线程安全的。设计为在单线程 Agent loop 中使用，
        每次事务由同一个线程完成 begin → apply → commit/rollback。
        如需跨线程共享状态，请在外部加锁（如 threading.Lock）。

    Args:
        initial_state: 初始状态，None 则为空 dict
    """

    def __init__(self, initial_state: dict[str, Any] | None = None) -> None:
        self._current: dict[str, Any] = copy.deepcopy(initial_state or {})
        self._baseline: dict[str, Any] | None = None
        self._pending: dict[str, Any] | None = None
        self._in_transaction: bool = False
        self._savepoints: list[dict[str, Any]] = []

    @property
    def current(self) -> dict[str, Any]:
        """返回当前已提交状态的深拷贝。

        修改返回值不会影响内部状态。
        """
        return copy.deepcopy(self._current)

    @property
    def in_transaction(self) -> bool:
        """是否在事务中。"""
        return self._in_transaction

    def get_snapshot(self) -> dict[str, Any]:
        """返回当前状态的深拷贝快照。

        等同于 current 属性，但语义更明确（用于需要显式快照的场景）。

        Returns:
            当前状态的深拷贝
        """
        return copy.deepcopy(self._current)

    def begin_transaction(self) -> None:
        """开启事务，保存当前状态为 baseline。

        Raises:
            RuntimeError: 已有事务在进行中
        """
        if self._in_transaction:
            raise RuntimeError("Transaction already in progress")
        self._baseline = copy.deepcopy(self._current)
        self._pending = {}
        self._in_transaction = True

    def apply_changes(self, changes: dict[str, Any]) -> dict[str, Any]:
        """将变更应用到 pending 区，返回合并后的预期结果。

        使用递归合并策略：
        - dict 类型的值递归合并
        - 其他类型的值直接覆盖
        - 值为 _DELETE sentinel 时删除对应键

        多次调用会累积变更到 pending 区。

        Args:
            changes: 要应用的变更

        Returns:
            合并后的预期状态（current + pending 的深拷贝）

        Raises:
            RuntimeError: 没有活跃的事务
        """
        if not self._in_transaction:
            raise RuntimeError("No transaction in progress")
        self._pending = self._merge_pending(self._pending, changes)
        return self._apply_pending_to_current()

    def _merge_pending(self, pending: dict[str, Any], changes: dict[str, Any]) -> dict[str, Any]:
        """合并变更到 pending 区，保留 _DELETE sentinel。

        与 _deep_merge 不同，此方法在 pending 中保留 _DELETE 标记，
        以便最终 commit 时正确处理删除操作。
        """
        result = copy.deepcopy(pending)
        for key, value in changes.items():
            if value is _DELETE:
                result.pop(key, None)
                result[key] = _DELETE
            elif key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._merge_pending(result[key], value)
            else:
                result[key] = copy.deepcopy(value)
        return result

    def _apply_pending_to_current(self) -> dict[str, Any]:
        """将 pending 应用到 current，返回预览结果（深拷贝）。

        处理 _DELETE sentinel：在合并时删除对应键。
        """
        result = copy.deepcopy(self._current)
        for key, value in self._pending.items():
            if value is _DELETE:
                result.pop(key, None)
            elif key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = copy.deepcopy(value)
        return result

    def commit(self) -> dict[str, Any]:
        """提交事务，将 pending 合并到 current。

        Returns:
            新状态的深拷贝

        Raises:
            RuntimeError: 没有活跃的事务
        """
        if not self._in_transaction:
            raise RuntimeError("No transaction in progress")
        self._current = self._apply_pending_to_current()
        self._baseline = None
        self._pending = None
        self._in_transaction = False
        self._savepoints.clear()
        return copy.deepcopy(self._current)

    def rollback(self) -> None:
        """回滚事务，恢复到 baseline。

        丢弃所有 pending 变更和 savepoints。

        Raises:
            RuntimeError: 没有活跃的事务
        """
        if not self._in_transaction:
            raise RuntimeError("No transaction in progress")
        self._current = self._baseline  # baseline 已是 deep copy，安全
        self._baseline = None
        self._pending = None
        self._in_transaction = False
        self._savepoints.clear()

    def savepoint(self) -> str:
        """创建嵌套事务保存点。

        保存当前 pending 区的快照，后续可通过 rollback_to_savepoint 恢复。

        Returns:
            保存点 ID（格式 "sp_{index}"）

        Raises:
            RuntimeError: 没有活跃的事务
        """
        if not self._in_transaction:
            raise RuntimeError("No transaction in progress")
        sp_id = f"sp_{len(self._savepoints)}"
        self._savepoints.append(copy.deepcopy(self._pending))
        return sp_id

    def rollback_to_savepoint(self, savepoint_id: str) -> None:
        """回滚到指定保存点。

        恢复 pending 区到保存点时的状态，丢弃之后的变更和保存点。

        Args:
            savepoint_id: 保存点 ID（由 savepoint() 返回）

        Raises:
            RuntimeError: 没有活跃的事务
            ValueError: 保存点不存在
        """
        if not self._in_transaction:
            raise RuntimeError("No transaction in progress")
        if not savepoint_id.startswith("sp_"):
            raise ValueError(f"Invalid savepoint ID: {savepoint_id}")
        try:
            idx = int(savepoint_id.split("_")[1])
        except (IndexError, ValueError) as e:
            raise ValueError(f"Invalid savepoint ID: {savepoint_id}") from e
        if idx >= len(self._savepoints):
            raise ValueError(f"Savepoint '{savepoint_id}' not found")
        self._pending = self._savepoints[idx]
        # 丢弃该保存点之后的所有保存点（不含自身）
        self._savepoints = self._savepoints[:idx]

    def reset(self, new_state: dict[str, Any] | None = None) -> None:
        """重置状态管理器。

        清空所有状态、事务和保存点，设为新的初始状态。

        Args:
            new_state: 新的初始状态，None 则为空 dict
        """
        self._current = copy.deepcopy(new_state or {})
        self._baseline = None
        self._pending = None
        self._in_transaction = False
        self._savepoints.clear()

    @staticmethod
    def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
        """递归合并两个字典。

        规则：
        - dict 值递归合并
        - 其他值直接覆盖
        - _DELETE sentinel 删除键

        Args:
            base: 基础字典
            override: 覆盖字典

        Returns:
            合并后的新字典
        """
        result = copy.deepcopy(base)
        for key, value in override.items():
            if value is _DELETE:
                result.pop(key, None)
            elif key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = StateManager._deep_merge(result[key], value)
            else:
                result[key] = copy.deepcopy(value)
        return result
