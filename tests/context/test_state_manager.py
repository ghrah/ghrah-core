# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""StateManager 单元测试 — 事务性状态管理器。

覆盖：
- 初始化（空状态 / 带数据 / deep copy 隔离）
- 事务生命周期（begin / apply / commit / rollback）
- 异常场景（事务外操作 / 重复开启事务）
- 递归合并（嵌套 dict / 新增键 / 覆盖 / _DELETE sentinel）
- 嵌套事务（savepoint / rollback_to_savepoint）
- 集成场景（模拟 Agent loop / 串行事务 / 复杂嵌套状态）
"""

from __future__ import annotations

import pytest

from ghrah.context.state import _DELETE, StateManager

# ─────────────────────────────────────────────────────
# 基础初始化
# ─────────────────────────────────────────────────────


class TestStateManagerInit:
    """StateManager 初始化测试。"""

    def test_initial_state_empty(self) -> None:
        """无参数初始化，current 为空 dict。"""
        sm = StateManager()
        assert sm.current == {}
        assert sm.in_transaction is False

    def test_initial_state_with_data(self) -> None:
        """传入初始状态，current 包含该数据。"""
        initial = {"key": "value", "count": 42}
        sm = StateManager(initial)
        assert sm.current == {"key": "value", "count": 42}

    def test_initial_state_deep_copy(self) -> None:
        """修改外部 dict 不影响内部状态。"""
        initial = {"nested": {"a": 1}}
        sm = StateManager(initial)
        initial["nested"]["a"] = 999
        assert sm.current["nested"]["a"] == 1

    def test_initial_state_none(self) -> None:
        """传入 None 等同于空状态。"""
        sm = StateManager(None)
        assert sm.current == {}

    def test_get_snapshot_returns_copy(self) -> None:
        """get_snapshot 返回深拷贝。"""
        sm = StateManager({"key": [1, 2, 3]})
        snapshot = sm.get_snapshot()
        snapshot["key"].append(4)
        assert sm.current["key"] == [1, 2, 3]

    def test_current_property_returns_deep_copy(self) -> None:
        """current 返回深拷贝，修改不影响内部。"""
        sm = StateManager({"nested": {"a": 1}})
        cur = sm.current
        cur["nested"]["a"] = 999
        assert sm.current["nested"]["a"] == 1


# ─────────────────────────────────────────────────────
# 事务生命周期
# ─────────────────────────────────────────────────────


class TestTransactionLifecycle:
    """事务生命周期测试。"""

    def test_begin_transaction(self) -> None:
        """开启事务后 in_transaction=True。"""
        sm = StateManager({"x": 1})
        sm.begin_transaction()
        assert sm.in_transaction is True

    def test_begin_transaction_twice_raises(self) -> None:
        """重复开启事务抛出 RuntimeError。"""
        sm = StateManager()
        sm.begin_transaction()
        with pytest.raises(RuntimeError, match="Transaction already in progress"):
            sm.begin_transaction()

    def test_apply_changes_without_transaction(self) -> None:
        """事务外 apply_changes 抛出 RuntimeError。"""
        sm = StateManager()
        with pytest.raises(RuntimeError, match="No transaction in progress"):
            sm.apply_changes({"key": "value"})

    def test_commit_without_transaction_raises(self) -> None:
        """事务外 commit 抛出 RuntimeError。"""
        sm = StateManager()
        with pytest.raises(RuntimeError, match="No transaction in progress"):
            sm.commit()

    def test_rollback_without_transaction_raises(self) -> None:
        """事务外 rollback 抛出 RuntimeError。"""
        sm = StateManager()
        with pytest.raises(RuntimeError, match="No transaction in progress"):
            sm.rollback()

    def test_apply_changes_returns_preview(self) -> None:
        """apply_changes 返回合并后的预期结果。"""
        sm = StateManager({"x": 1})
        sm.begin_transaction()
        preview = sm.apply_changes({"y": 2})
        assert preview == {"x": 1, "y": 2}
        # current 尚未改变（事务未提交）
        assert sm.current == {"x": 1}

    def test_apply_changes_nested_dict(self) -> None:
        """apply_changes 嵌套 dict 递归合并。"""
        sm = StateManager({"config": {"a": 1, "b": 2}})
        sm.begin_transaction()
        sm.apply_changes({"config": {"b": 3, "c": 4}})
        assert sm.current == {"config": {"a": 1, "b": 2}}  # 未提交
        result = sm.commit()
        assert result == {"config": {"a": 1, "b": 3, "c": 4}}

    def test_apply_changes_multiple(self) -> None:
        """多次 apply_changes 累积效果。"""
        sm = StateManager()
        sm.begin_transaction()
        sm.apply_changes({"a": 1})
        sm.apply_changes({"b": 2})
        sm.apply_changes({"c": 3})
        result = sm.commit()
        assert result == {"a": 1, "b": 2, "c": 3}

    def test_commit_updates_state(self) -> None:
        """commit 后 current 更新。"""
        sm = StateManager({"x": 1})
        sm.begin_transaction()
        sm.apply_changes({"y": 2})
        result = sm.commit()
        assert result == {"x": 1, "y": 2}
        assert sm.current == {"x": 1, "y": 2}

    def test_commit_returns_snapshot(self) -> None:
        """commit 返回新快照（深拷贝）。"""
        sm = StateManager({"x": 1})
        sm.begin_transaction()
        sm.apply_changes({"y": 2})
        result = sm.commit()
        result["z"] = 999  # 修改返回值
        assert "z" not in sm.current

    def test_commit_clears_transaction(self) -> None:
        """commit 后 in_transaction=False。"""
        sm = StateManager()
        sm.begin_transaction()
        sm.apply_changes({"x": 1})
        sm.commit()
        assert sm.in_transaction is False

    def test_rollback_restores_state(self) -> None:
        """rollback 后状态恢复到 baseline。"""
        sm = StateManager({"x": 1})
        sm.begin_transaction()
        sm.apply_changes({"x": 999, "y": 2})
        sm.rollback()
        assert sm.current == {"x": 1}

    def test_rollback_clears_transaction(self) -> None:
        """rollback 后 in_transaction=False。"""
        sm = StateManager()
        sm.begin_transaction()
        sm.rollback()
        assert sm.in_transaction is False

    def test_rollback_discards_all_applied(self) -> None:
        """多次 apply 后 rollback，全部丢弃。"""
        sm = StateManager({"original": True})
        sm.begin_transaction()
        sm.apply_changes({"a": 1})
        sm.apply_changes({"b": 2})
        sm.apply_changes({"c": 3})
        sm.rollback()
        assert sm.current == {"original": True}

    def test_full_transaction_cycle(self) -> None:
        """begin → apply → commit 完整流程。"""
        sm = StateManager({"init": 0})
        sm.begin_transaction()
        preview = sm.apply_changes({"step1": 1})
        assert preview == {"init": 0, "step1": 1}
        result = sm.commit()
        assert result == {"init": 0, "step1": 1}
        assert sm.in_transaction is False

    def test_rollback_after_apply(self) -> None:
        """begin → apply → rollback，状态正确。"""
        sm = StateManager({"base": True})
        sm.begin_transaction()
        sm.apply_changes({"new": True})
        sm.rollback()
        assert sm.current == {"base": True}
        assert sm.in_transaction is False


# ─────────────────────────────────────────────────────
# Deep Merge
# ─────────────────────────────────────────────────────


class TestDeepMerge:
    """递归字典合并测试。"""

    def test_flat_merge(self) -> None:
        """扁平 dict 合并。"""
        result = StateManager._deep_merge({"a": 1}, {"b": 2})
        assert result == {"a": 1, "b": 2}

    def test_flat_overwrite(self) -> None:
        """扁平 dict 覆盖。"""
        result = StateManager._deep_merge({"a": 1}, {"a": 2})
        assert result == {"a": 2}

    def test_nested_merge(self) -> None:
        """嵌套 dict 递归合并。"""
        base = {"config": {"a": 1, "b": 2}}
        override = {"config": {"b": 3, "c": 4}}
        result = StateManager._deep_merge(base, override)
        assert result == {"config": {"a": 1, "b": 3, "c": 4}}

    def test_deeply_nested_merge(self) -> None:
        """深层嵌套合并。"""
        base = {"l1": {"l2": {"l3": {"a": 1, "b": 2}}}}
        override = {"l1": {"l2": {"l3": {"b": 3, "c": 4}}}}
        result = StateManager._deep_merge(base, override)
        assert result == {"l1": {"l2": {"l3": {"a": 1, "b": 3, "c": 4}}}}

    def test_overwrite_non_dict_with_dict(self) -> None:
        """非 dict 值被 dict 覆盖。"""
        result = StateManager._deep_merge({"key": "string"}, {"key": {"nested": 1}})
        assert result == {"key": {"nested": 1}}

    def test_overwrite_dict_with_non_dict(self) -> None:
        """dict 值被非 dict 覆盖。"""
        result = StateManager._deep_merge({"key": {"nested": 1}}, {"key": "string"})
        assert result == {"key": "string"}

    def test_new_keys(self) -> None:
        """新增键。"""
        result = StateManager._deep_merge({"a": 1}, {"b": 2, "c": 3})
        assert result == {"a": 1, "b": 2, "c": 3}

    def test_delete_marker(self) -> None:
        """使用 _DELETE 删除键。"""
        result = StateManager._deep_merge({"a": 1, "b": 2}, {"b": _DELETE})
        assert result == {"a": 1}

    def test_delete_nonexistent_key(self) -> None:
        """删除不存在的键不报错。"""
        result = StateManager._deep_merge({"a": 1}, {"b": _DELETE})
        assert result == {"a": 1}

    def test_delete_nested_key(self) -> None:
        """删除嵌套 dict 中的键。"""
        base = {"config": {"a": 1, "b": 2, "c": 3}}
        override = {"config": {"b": _DELETE}}
        result = StateManager._deep_merge(base, override)
        assert result == {"config": {"a": 1, "c": 3}}

    def test_merge_does_not_modify_base(self) -> None:
        """合并不修改原始 base dict。"""
        base = {"a": 1, "nested": {"x": 10}}
        override = {"b": 2, "nested": {"y": 20}}
        result = StateManager._deep_merge(base, override)
        assert base == {"a": 1, "nested": {"x": 10}}  # 未被修改
        assert result == {"a": 1, "nested": {"x": 10, "y": 20}, "b": 2}

    def test_merge_does_not_modify_override(self) -> None:
        """合并不修改原始 override dict。"""
        base: dict = {}
        override = {"nested": {"a": 1}}
        result = StateManager._deep_merge(base, override)
        result["nested"]["a"] = 999
        assert override["nested"]["a"] == 1


# ─────────────────────────────────────────────────────
# 嵌套事务（Savepoint）
# ─────────────────────────────────────────────────────


class TestSavepoint:
    """嵌套事务 savepoint 测试。"""

    def test_savepoint_without_transaction(self) -> None:
        """事务外 savepoint 抛出 RuntimeError。"""
        sm = StateManager()
        with pytest.raises(RuntimeError, match="No transaction in progress"):
            sm.savepoint()

    def test_rollback_to_savepoint_without_transaction(self) -> None:
        """事务外 rollback_to_savepoint 抛出 RuntimeError。"""
        sm = StateManager()
        with pytest.raises(RuntimeError, match="No transaction in progress"):
            sm.rollback_to_savepoint("sp_0")

    def test_savepoint_returns_id(self) -> None:
        """savepoint 返回格式正确的 ID。"""
        sm = StateManager()
        sm.begin_transaction()
        sp = sm.savepoint()
        assert sp == "sp_0"

    def test_multiple_savepoints(self) -> None:
        """多个 savepoint 返回递增 ID。"""
        sm = StateManager()
        sm.begin_transaction()
        assert sm.savepoint() == "sp_0"
        assert sm.savepoint() == "sp_1"
        assert sm.savepoint() == "sp_2"

    def test_rollback_to_savepoint(self) -> None:
        """savepoint → apply → rollback_to_savepoint 恢复 pending。"""
        sm = StateManager({"x": 1})
        sm.begin_transaction()
        sm.apply_changes({"a": 1})
        sp = sm.savepoint()
        sm.apply_changes({"b": 2})
        # 此时 pending 应包含 a + b
        sm.rollback_to_savepoint(sp)
        # pending 恢复到 savepoint 时只有 a
        result = sm.commit()
        assert result == {"x": 1, "a": 1}

    def test_nested_savepoints_rollback(self) -> None:
        """多层 savepoint 逐层回滚。"""
        sm = StateManager({"base": 0})
        sm.begin_transaction()
        sm.apply_changes({"l1": 1})
        sp0 = sm.savepoint()
        sm.apply_changes({"l2": 2})
        sp1 = sm.savepoint()
        sm.apply_changes({"l3": 3})

        # 回滚到 sp1（l3 被丢弃）
        sm.rollback_to_savepoint(sp1)
        result = sm.commit()
        assert result == {"base": 0, "l1": 1, "l2": 2}

    def test_rollback_to_earlier_savepoint(self) -> None:
        """回滚到更早的保存点，丢弃中间变更。"""
        sm = StateManager({"base": 0})
        sm.begin_transaction()
        sm.apply_changes({"a": 1})
        sp0 = sm.savepoint()
        sm.apply_changes({"b": 2})
        sm.savepoint()
        sm.apply_changes({"c": 3})

        # 回滚到 sp0（b、c 全被丢弃）
        sm.rollback_to_savepoint(sp0)
        result = sm.commit()
        assert result == {"base": 0, "a": 1}

    def test_invalid_savepoint_id(self) -> None:
        """无效的 savepoint ID 抛出 ValueError。"""
        sm = StateManager()
        sm.begin_transaction()
        with pytest.raises(ValueError, match="Invalid savepoint ID"):
            sm.rollback_to_savepoint("invalid")
        sm.rollback()

    def test_nonexistent_savepoint(self) -> None:
        """不存在的 savepoint 抛出 ValueError。"""
        sm = StateManager()
        sm.begin_transaction()
        with pytest.raises(ValueError, match="Savepoint.*not found"):
            sm.rollback_to_savepoint("sp_99")
        sm.rollback()

    def test_rollback_clears_savepoints(self) -> None:
        """完整 rollback 清空 savepoint 栈。"""
        sm = StateManager()
        sm.begin_transaction()
        sm.savepoint()
        sm.savepoint()
        sm.rollback()
        # rollback 后事务已结束，savepoint 应被清空
        # 重新开始事务验证
        sm.begin_transaction()
        sp = sm.savepoint()
        assert sp == "sp_0"  # savepoint 从 0 重新开始

    def test_commit_clears_savepoints(self) -> None:
        """commit 清空 savepoint 栈。"""
        sm = StateManager()
        sm.begin_transaction()
        sm.apply_changes({"x": 1})
        sm.savepoint()
        sm.apply_changes({"y": 2})
        sm.commit()
        # commit 后事务已结束
        sm.begin_transaction()
        sp = sm.savepoint()
        assert sp == "sp_0"

    def test_savepoint_commit_all(self) -> None:
        """savepoint → apply → commit 全部提交。"""
        sm = StateManager({"base": 0})
        sm.begin_transaction()
        sm.apply_changes({"a": 1})
        sm.savepoint()
        sm.apply_changes({"b": 2})
        result = sm.commit()
        assert result == {"base": 0, "a": 1, "b": 2}


# ─────────────────────────────────────────────────────
# Reset
# ─────────────────────────────────────────────────────


class TestReset:
    """reset 方法测试。"""

    def test_reset_to_empty(self) -> None:
        """reset(None) 清空状态。"""
        sm = StateManager({"x": 1})
        sm.reset()
        assert sm.current == {}

    def test_reset_to_new_state(self) -> None:
        """reset(new_state) 设为新状态。"""
        sm = StateManager({"x": 1})
        sm.reset({"y": 2})
        assert sm.current == {"y": 2}

    def test_reset_clears_transaction(self) -> None:
        """reset 清除活跃事务。"""
        sm = StateManager()
        sm.begin_transaction()
        sm.apply_changes({"x": 1})
        sm.reset()
        assert sm.in_transaction is False
        assert sm.current == {}

    def test_reset_deep_copies(self) -> None:
        """reset 对新状态做 deep copy。"""
        new_state = {"nested": {"a": 1}}
        sm = StateManager()
        sm.reset(new_state)
        new_state["nested"]["a"] = 999
        assert sm.current["nested"]["a"] == 1


# ─────────────────────────────────────────────────────
# 集成场景
# ─────────────────────────────────────────────────────


class TestStateManagerIntegration:
    """集成场景测试。"""

    def test_simulated_agent_loop(self) -> None:
        """模拟 Agent drive loop 的事务流程。"""
        sm = StateManager({"iteration": 0, "data": []})

        # 迭代 1：成功
        sm.begin_transaction()
        sm.apply_changes({"iteration": 1, "data": ["step1"]})
        sm.commit()
        assert sm.current == {"iteration": 1, "data": ["step1"]}

        # 迭代 2：失败，回滚
        sm.begin_transaction()
        sm.apply_changes({"iteration": 2, "data": ["step1", "step2"], "error": True})
        sm.rollback()
        assert sm.current == {"iteration": 1, "data": ["step1"]}

        # 迭代 3：成功
        sm.begin_transaction()
        sm.apply_changes({"iteration": 2, "data": ["step1", "step2b"]})
        result = sm.commit()
        assert result == {"iteration": 2, "data": ["step1", "step2b"]}

    def test_serial_transactions_no_interference(self) -> None:
        """串行多个事务不互相干扰。"""
        sm = StateManager({"value": 0})

        # 事务 1
        sm.begin_transaction()
        sm.apply_changes({"value": 10})
        sm.commit()
        assert sm.current["value"] == 10

        # 事务 2
        sm.begin_transaction()
        sm.apply_changes({"value": 20})
        sm.commit()
        assert sm.current["value"] == 20

        # 事务 3：回滚
        sm.begin_transaction()
        sm.apply_changes({"value": 999})
        sm.rollback()
        assert sm.current["value"] == 20

    def test_complex_nested_state(self) -> None:
        """复杂嵌套状态的事务操作。"""
        initial = {
            "config": {"model": "gpt-4", "temperature": 0.7},
            "counters": {"calls": 0, "errors": 0},
            "history": [],
        }
        sm = StateManager(initial)

        # 事务 1：更新配置和计数器
        sm.begin_transaction()
        sm.apply_changes(
            {
                "config": {"temperature": 0.9},
                "counters": {"calls": 1},
            }
        )
        result = sm.commit()
        assert result["config"] == {"model": "gpt-4", "temperature": 0.9}
        assert result["counters"] == {"calls": 1, "errors": 0}
        assert result["history"] == []

        # 事务 2：添加历史记录
        sm.begin_transaction()
        sm.apply_changes(
            {
                "history": ["entry1"],
                "counters": {"calls": 2},
            }
        )
        result = sm.commit()
        assert result["history"] == ["entry1"]
        assert result["counters"]["calls"] == 2

    def test_delete_marker_in_transaction(self) -> None:
        """事务中使用 _DELETE sentinel 删除键。"""
        sm = StateManager({"a": 1, "b": 2, "c": 3})
        sm.begin_transaction()
        sm.apply_changes({"b": _DELETE})
        result = sm.commit()
        assert result == {"a": 1, "c": 3}

    def test_delete_rollback(self) -> None:
        """删除操作在 rollback 后恢复。"""
        sm = StateManager({"a": 1, "b": 2})
        sm.begin_transaction()
        sm.apply_changes({"b": _DELETE})
        sm.rollback()
        assert sm.current == {"a": 1, "b": 2}

    def test_apply_changes_preview_isolation(self) -> None:
        """apply_changes 返回的预览不影响实际状态。"""
        sm = StateManager({"x": 1})
        sm.begin_transaction()
        preview = sm.apply_changes({"y": 2})
        preview["z"] = 999  # 修改预览
        # current 未变
        assert sm.current == {"x": 1}
        # commit 后也不应包含 z
        result = sm.commit()
        assert result == {"x": 1, "y": 2}
