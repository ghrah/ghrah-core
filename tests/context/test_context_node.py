# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""ContextNode + ActionChain 单元测试。"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from ghrah.abilities.base import ActionOutcome, ActionResult
from ghrah.context import ActionChain, ContextNode

# ============================================================================
# ContextNode 测试
# ============================================================================


class TestContextNode:
    """ContextNode frozen dataclass 测试。"""

    def test_create_root(self) -> None:
        """根节点：parent_id=None, is_snapshot=True, ability_names=['init']。"""
        root = ContextNode.create_root(
            agent_name="test_agent",
            agent_state={"key": "value"},
            messages=["msg1", "msg2"],
        )

        assert root.parent_id is None
        assert root.agent_name == "test_agent"
        assert root.iteration == 0
        assert root.ability_names == ["init"]
        assert root.is_snapshot is True
        assert root.messages_snapshot == ["msg1", "msg2"]
        assert root.messages_delta == []
        assert root.agent_state == {"key": "value"}
        assert root.branch_name == "main"
        assert root.action_results == []

    def test_create_root_defaults(self) -> None:
        """根节点默认值：空状态和空消息。"""
        root = ContextNode.create_root(agent_name="agent")
        assert root.agent_state == {}
        assert root.messages_snapshot == []

    def test_frozen_immutability(self) -> None:
        """修改 frozen 字段抛出 FrozenInstanceError。"""
        node = ContextNode.create_root(agent_name="agent")
        with pytest.raises(FrozenInstanceError):
            node.iteration = 99  # type: ignore[misc]

    def test_frozen_id(self) -> None:
        """id 字段不可修改。"""
        node = ContextNode(agent_name="agent")
        with pytest.raises(FrozenInstanceError):
            node.id = "hacked"  # type: ignore[misc]

    def test_agent_state_isolation(self) -> None:
        """修改原始 dict 不影响节点内部状态。"""
        original_state = {"count": 0, "items": [1, 2, 3]}
        node = ContextNode(agent_name="agent", agent_state=original_state)

        # 修改原始 dict
        original_state["count"] = 99
        original_state["items"].append(4)

        # 节点内部状态不受影响
        assert node.agent_state["count"] == 0
        assert node.agent_state["items"] == [1, 2, 3]

    def test_auto_generated_id(self) -> None:
        """id 自动生成，非空且唯一。"""
        node1 = ContextNode(agent_name="agent")
        node2 = ContextNode(agent_name="agent")
        assert len(node1.id) == 12
        assert len(node2.id) == 12
        assert node1.id != node2.id

    def test_auto_generated_timestamp(self) -> None:
        """timestamp 自动生成，非 None。"""
        node = ContextNode(agent_name="agent")
        assert node.timestamp is not None

    def test_messages_delta_default_empty(self) -> None:
        """messages_delta 默认空列表。"""
        node = ContextNode(agent_name="agent")
        assert node.messages_delta == []

    def test_messages_snapshot_default_none(self) -> None:
        """messages_snapshot 默认 None。"""
        node = ContextNode(agent_name="agent")
        assert node.messages_snapshot is None

    def test_metadata_deep_copy(self) -> None:
        """metadata 是深拷贝，修改原始不影响节点。"""
        original_meta = {"rollback": True, "tags": ["a"]}
        node = ContextNode(agent_name="agent", metadata=original_meta)

        original_meta["tags"].append("b")
        assert node.metadata["tags"] == ["a"]

    def test_default_branch_name(self) -> None:
        """默认分支名为 main。"""
        node = ContextNode(agent_name="agent")
        assert node.branch_name == "main"

    def test_ability_names_isolation(self) -> None:
        """ability_names 列表是隔离的，修改原始不影响节点。"""
        original_names = ["ability_a", "ability_b"]
        node = ContextNode(agent_name="agent", ability_names=original_names)

        original_names.append("ability_c")
        assert node.ability_names == ["ability_a", "ability_b"]

    def test_action_results_isolation(self) -> None:
        """action_results 列表是深拷贝隔离的。"""
        result = ActionResult(outcome=ActionOutcome.SUCCESS, data={"key": "val"})
        original_results = [{"ability_name": "test", "action_result": result}]
        node = ContextNode(agent_name="agent", action_results=original_results)

        # 修改原始列表不影响节点
        original_results.append({"ability_name": "extra", "action_result": None})
        assert len(node.action_results) == 1

        # 修改原始 ActionResult 不影响节点内的深拷贝
        result.data["key"] = "modified"
        assert node.action_results[0]["action_result"].data["key"] == "val"


# ============================================================================
# ActionChain 测试
# ============================================================================


class TestActionChain:
    """ActionChain 链管理器测试。"""

    def test_init_chain(self) -> None:
        """创建根节点，main head 指向它。"""
        chain = ActionChain(agent_name="test_agent")
        root = chain.init_chain(
            agent_state={"status": "ready"},
            messages=["init_msg"],
        )

        assert root.parent_id is None
        assert root.iteration == 0
        assert root.is_snapshot is True
        assert chain.head is root
        assert chain.node_count == 1

    def test_init_chain_raises_if_already_initialized(self) -> None:
        """重复初始化抛出 ValueError。"""
        chain = ActionChain(agent_name="agent")
        chain.init_chain()
        with pytest.raises(ValueError, match="already initialized"):
            chain.init_chain()

    def test_commit_node_basic(self) -> None:
        """提交一个节点，parent 指向 root，iteration 递增。"""
        chain = ActionChain(agent_name="agent")
        root = chain.init_chain()

        node1 = chain.commit_node(
            ability_names=["conversation"],
            agent_state={"step": 1},
            messages_delta=["msg1"],
        )

        assert node1.parent_id == root.id
        assert node1.iteration == 1
        assert node1.ability_names == ["conversation"]
        assert chain.head is node1
        assert chain.node_count == 2

    def test_commit_chain_of_3(self) -> None:
        """3 个连续 commit，迭代号递增，head 指向最后一个。"""
        chain = ActionChain(agent_name="agent")
        chain.init_chain()

        node1 = chain.commit_node(
            ability_names=["step1"],
            agent_state={"n": 1},
            messages_delta=["d1"],
        )
        node2 = chain.commit_node(
            ability_names=["step2"],
            agent_state={"n": 2},
            messages_delta=["d2"],
        )
        node3 = chain.commit_node(
            ability_names=["step3"],
            agent_state={"n": 3},
            messages_delta=["d3"],
        )

        assert node1.iteration == 1
        assert node2.iteration == 2
        assert node3.iteration == 3
        assert node2.parent_id == node1.id
        assert node3.parent_id == node2.id
        assert chain.head is node3
        assert chain.node_count == 4  # root + 3

    def test_commit_with_snapshot(self) -> None:
        """带 snapshot 的节点正确存储。"""
        chain = ActionChain(agent_name="agent")
        chain.init_chain()

        node = chain.commit_node(
            ability_names=["step"],
            agent_state={},
            messages_delta=["d1"],
            messages_snapshot=["m1", "m2"],
            is_snapshot=True,
        )

        assert node.is_snapshot is True
        assert node.messages_snapshot == ["m1", "m2"]

    def test_commit_with_action_results(self) -> None:
        """带 action_results 的节点正确存储。"""
        chain = ActionChain(agent_name="agent")
        chain.init_chain()

        result = ActionResult(outcome=ActionOutcome.SUCCESS, data={"output": "ok"})
        node = chain.commit_node(
            ability_names=["step"],
            agent_state={},
            messages_delta=[],
            action_results=[{"ability_name": "step", "action_result": result}],
        )

        assert len(node.action_results) == 1
        assert node.action_results[0]["action_result"].outcome == ActionOutcome.SUCCESS

    def test_commit_with_multiple_action_results(self) -> None:
        """多个并行 ability 的 action_results 正确存储。"""
        chain = ActionChain(agent_name="agent")
        chain.init_chain()

        result1 = ActionResult(outcome=ActionOutcome.SUCCESS, data={"file": "a.py"})
        result2 = ActionResult(outcome=ActionOutcome.SUCCESS, data={"file": "b.py"})
        node = chain.commit_node(
            ability_names=["read_file", "read_file"],
            agent_state={},
            messages_delta=[],
            action_results=[
                {"ability_name": "read_file", "action_result": result1},
                {"ability_name": "read_file", "action_result": result2},
            ],
        )

        assert node.ability_names == ["read_file", "read_file"]
        assert len(node.action_results) == 2
        assert node.action_results[0]["action_result"].data["file"] == "a.py"
        assert node.action_results[1]["action_result"].data["file"] == "b.py"

    def test_commit_without_init_raises(self) -> None:
        """未初始化时 commit 抛出 ValueError。"""
        chain = ActionChain(agent_name="agent")
        with pytest.raises(ValueError, match="not initialized"):
            chain.commit_node(
                ability_names=["step"],
                agent_state={},
                messages_delta=[],
            )

    def test_commit_to_nonexistent_branch_raises(self) -> None:
        """commit 到不存在的分支抛出 ValueError。"""
        chain = ActionChain(agent_name="agent")
        chain.init_chain()

        with pytest.raises(ValueError, match="does not exist"):
            chain.commit_node(
                ability_names=["step"],
                agent_state={},
                messages_delta=[],
                branch_name="nonexistent",
            )

    def test_get_history_full(self) -> None:
        """返回完整历史（根在前，head 在后）。"""
        chain = ActionChain(agent_name="agent")
        root = chain.init_chain()
        node1 = chain.commit_node(ability_names=["s1"], agent_state={}, messages_delta=["d1"])
        node2 = chain.commit_node(ability_names=["s2"], agent_state={}, messages_delta=["d2"])

        history = chain.get_history()

        assert len(history) == 3
        assert history[0] is root
        assert history[1] is node1
        assert history[2] is node2

    def test_get_history_with_limit(self) -> None:
        """limit=2 只返回最近 2 个节点。"""
        chain = ActionChain(agent_name="agent")
        chain.init_chain()
        chain.commit_node(ability_names=["s1"], agent_state={}, messages_delta=["d1"])
        node2 = chain.commit_node(ability_names=["s2"], agent_state={}, messages_delta=["d2"])

        history = chain.get_history(limit=2)

        assert len(history) == 2
        assert history[0].ability_names == ["s1"]
        assert history[1] is node2

    def test_get_history_limit_1(self) -> None:
        """limit=1 只返回 head。"""
        chain = ActionChain(agent_name="agent")
        chain.init_chain()
        node1 = chain.commit_node(ability_names=["s1"], agent_state={}, messages_delta=["d1"])

        history = chain.get_history(limit=1)

        assert len(history) == 1
        assert history[0] is node1

    def test_get_history_empty_chain(self) -> None:
        """空链返回空列表。"""
        chain = ActionChain(agent_name="agent")
        assert chain.get_history() == []

    def test_get_history_nonexistent_branch(self) -> None:
        """不存在的分支返回空列表。"""
        chain = ActionChain(agent_name="agent")
        chain.init_chain()
        assert chain.get_history(branch="nonexistent") == []

    def test_fork_creates_branch(self) -> None:
        """fork 创建新分支，分支 head 正确。"""
        chain = ActionChain(agent_name="agent")
        root = chain.init_chain(agent_state={"v": 0})
        chain.commit_node(ability_names=["s1"], agent_state={"v": 1}, messages_delta=["d1"])

        fork_node = chain.fork("sub_agent")

        assert fork_node.branch_name == "sub_agent"
        assert fork_node.ability_names == ["fork"]
        assert fork_node.parent_id == chain.head.id
        assert fork_node.metadata.get("fork_from") == chain.head.id
        assert chain.get_branch_head("sub_agent") is fork_node

    def test_fork_inherits_state(self) -> None:
        """fork 节点继承 parent 的 agent_state。"""
        chain = ActionChain(agent_name="agent")
        chain.init_chain(agent_state={"shared": "data", "count": 5})
        chain.commit_node(
            ability_names=["s1"], agent_state={"shared": "data", "count": 6}, messages_delta=["d1"]
        )

        fork_node = chain.fork("child")

        assert fork_node.agent_state == {"shared": "data", "count": 6}

    def test_fork_from_specific_parent(self) -> None:
        """fork 从指定 parent_id 创建分支。"""
        chain = ActionChain(agent_name="agent")
        root = chain.init_chain(agent_state={"v": 0})
        node1 = chain.commit_node(ability_names=["s1"], agent_state={"v": 1}, messages_delta=["d1"])
        chain.commit_node(ability_names=["s2"], agent_state={"v": 2}, messages_delta=["d2"])

        # 从 node1（而非 head）fork
        fork_node = chain.fork("child", parent_id=node1.id)

        assert fork_node.parent_id == node1.id
        assert fork_node.agent_state == {"v": 1}

    def test_fork_existing_branch_raises(self) -> None:
        """fork 到已存在的分支名抛出 ValueError。"""
        chain = ActionChain(agent_name="agent")
        chain.init_chain()
        chain.fork("child")

        with pytest.raises(ValueError, match="already exists"):
            chain.fork("child")

    def test_fork_empty_chain_raises(self) -> None:
        """空链上 fork 抛出 ValueError。"""
        chain = ActionChain(agent_name="agent")
        with pytest.raises(ValueError, match="empty chain"):
            chain.fork("child")

    def test_fork_nonexistent_parent_raises(self) -> None:
        """fork 到不存在的 parent_id 抛出 ValueError。"""
        chain = ActionChain(agent_name="agent")
        chain.init_chain()

        with pytest.raises(ValueError, match="not found"):
            chain.fork("child", parent_id="nonexistent_id")

    def test_checkout(self) -> None:
        """checkout 返回指定节点。"""
        chain = ActionChain(agent_name="agent")
        root = chain.init_chain()
        node1 = chain.commit_node(ability_names=["s1"], agent_state={}, messages_delta=["d1"])

        assert chain.checkout(root.id) is root
        assert chain.checkout(node1.id) is node1

    def test_checkout_nonexistent(self) -> None:
        """checkout 不存在的节点返回 None。"""
        chain = ActionChain(agent_name="agent")
        chain.init_chain()

        assert chain.checkout("nonexistent") is None

    def test_head_property(self) -> None:
        """head 返回 main 分支 head。"""
        chain = ActionChain(agent_name="agent")
        assert chain.head is None

        root = chain.init_chain()
        assert chain.head is root

        node1 = chain.commit_node(ability_names=["s1"], agent_state={}, messages_delta=["d1"])
        assert chain.head is node1

    def test_branches_property(self) -> None:
        """返回所有分支。"""
        chain = ActionChain(agent_name="agent")
        root = chain.init_chain()

        assert chain.branches == {"main": root.id}

        fork_node = chain.fork("child")
        assert chain.branches == {
            "main": root.id,
            "child": fork_node.id,
        }

    def test_node_count(self) -> None:
        """节点计数正确。"""
        chain = ActionChain(agent_name="agent")
        assert chain.node_count == 0

        chain.init_chain()
        assert chain.node_count == 1

        chain.commit_node(ability_names=["s1"], agent_state={}, messages_delta=["d1"])
        assert chain.node_count == 2

        chain.fork("child")
        assert chain.node_count == 3

    def test_multiple_branches_parallel(self) -> None:
        """多分支并行 commit。"""
        chain = ActionChain(agent_name="agent")
        chain.init_chain()

        # main 分支
        chain.commit_node(ability_names=["main_s1"], agent_state={"v": 1}, messages_delta=["d1"])

        # 创建 child 分支
        chain.fork("child")

        # 两个分支各自 commit
        main_node = chain.commit_node(
            ability_names=["main_s2"],
            agent_state={"v": 2},
            messages_delta=["d2"],
            branch_name="main",
        )
        child_node = chain.commit_node(
            ability_names=["child_s1"],
            agent_state={"v": 10},
            messages_delta=["d_c1"],
            branch_name="child",
        )

        # 验证各自 head
        assert chain.get_branch_head("main") is main_node
        assert chain.get_branch_head("child") is child_node

        # 验证历史独立
        main_history = chain.get_history(branch="main")
        child_history = chain.get_history(branch="child")

        assert len(main_history) == 3  # root + main_s1 + main_s2
        assert len(child_history) == 4  # root + main_s1 + fork + child_s1

    def test_get_branch_head_nonexistent(self) -> None:
        """不存在的分支返回 None。"""
        chain = ActionChain(agent_name="agent")
        assert chain.get_branch_head("nonexistent") is None

    def test_branch_commit_iteration_increments(self) -> None:
        """分支 commit 的 iteration 从 fork 节点继续递增。"""
        chain = ActionChain(agent_name="agent")
        chain.init_chain()
        chain.commit_node(ability_names=["s1"], agent_state={}, messages_delta=["d1"])  # iter 1

        fork_node = chain.fork("child")  # iter 2
        assert fork_node.iteration == 2

        child_node = chain.commit_node(
            ability_names=["c1"], agent_state={}, messages_delta=["d_c1"], branch_name="child"
        )
        assert child_node.iteration == 3

    def test_agent_name_property(self) -> None:
        """agent_name 属性正确。"""
        chain = ActionChain(agent_name="my_agent")
        assert chain.agent_name == "my_agent"
