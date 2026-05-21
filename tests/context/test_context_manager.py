# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""ContextManager 门面类集成测试。

测试 ContextManager 整合 ActionChain + StateManager + MessageStore 的完整功能，
覆盖迭代生命周期、状态管理、消息管理、快照机制、fork 继承等场景。
"""

from __future__ import annotations

import pytest
from _helpers import make_action_result

from ghrah.abilities.base import ActionOutcome, ActionResult
from ghrah.abilities.context import AbilityExecutionContext
from ghrah.chat.message import ChatMessage
from ghrah.context.manager import ContextManager
from ghrah.context.node import ContextNode
from ghrah.core.config import AgentConfig
from ghrah.core.message import Message

# ----------------------------------------------------------------
# 辅助工厂
# ----------------------------------------------------------------


def _make_cm(**overrides) -> ContextManager:
    """创建测试用 ContextManager。"""
    defaults = {
        "agent_name": "test-agent",
        "initial_state": None,
        "snapshot_interval": 5,
        "system_prompt": "",
    }
    defaults.update(overrides)
    return ContextManager(**defaults)


def _make_message(content: str = "hello") -> Message:
    """创建测试用 Message。"""
    return Message(sender="user", recipient="test-agent", content=content)


# ----------------------------------------------------------------
# TestContextManagerLifecycle — 初始化和属性
# ----------------------------------------------------------------


class TestContextManagerLifecycle:
    """ContextManager 初始化和基本属性测试。"""

    def test_init_creates_root_node(self) -> None:
        """初始化后 chain 有根节点。"""
        cm = _make_cm()
        assert cm.chain.head is not None
        assert cm.chain.head.ability_names == ["init"]
        assert cm.chain.head.iteration == 0
        assert cm.chain.head.is_snapshot is True

    def test_init_with_initial_state(self) -> None:
        """初始状态正确传入 StateManager 和 root node。"""
        state = {"key": "value", "nested": {"a": 1}}
        cm = _make_cm(initial_state=state)
        assert cm.get_current_state() == state
        assert cm.chain.head.agent_state == state

    def test_init_with_system_prompt(self) -> None:
        """system_prompt 正确保存。"""
        cm = _make_cm(system_prompt="You are a helpful assistant.")
        assert cm._system_prompt == "You are a helpful assistant."

    def test_agent_name_property(self) -> None:
        """agent_name 属性正确。"""
        cm = _make_cm(agent_name="my-agent")
        assert cm.agent_name == "my-agent"

    def test_in_iteration_initially_false(self) -> None:
        """初始不在迭代中。"""
        cm = _make_cm()
        assert cm.in_iteration is False

    def test_chain_has_one_node_after_init(self) -> None:
        """初始化后 chain 只有根节点。"""
        cm = _make_cm()
        assert cm.chain.node_count == 1


# ----------------------------------------------------------------
# TestContextManagerIteration — 迭代生命周期
# ----------------------------------------------------------------


class TestContextManagerIteration:
    """ContextManager 迭代生命周期测试。"""

    def test_begin_iteration(self) -> None:
        """开启迭代，in_iteration=True。"""
        cm = _make_cm()
        cm.begin_iteration()
        assert cm.in_iteration is True
        assert cm.state_manager.in_transaction is True

    def test_begin_iteration_twice_raises(self) -> None:
        """重复开启抛 RuntimeError。"""
        cm = _make_cm()
        cm.begin_iteration()
        with pytest.raises(RuntimeError, match="Iteration already in progress"):
            cm.begin_iteration()

    def test_commit_without_begin_raises(self) -> None:
        """未 begin 就 commit 抛 RuntimeError。"""
        cm = _make_cm()
        with pytest.raises(RuntimeError, match="No iteration in progress"):
            cm.commit_iteration(ability_names=["test"])

    def test_rollback_without_begin_raises(self) -> None:
        """未 begin 就 rollback 抛 RuntimeError。"""
        cm = _make_cm()
        with pytest.raises(RuntimeError, match="No iteration in progress"):
            cm.rollback_iteration(ValueError("test"))

    def test_commit_iteration_basic(self) -> None:
        """基本 commit：创建节点，消息写入 store。"""
        cm = _make_cm()
        cm.begin_iteration()
        cm.add_messages([ChatMessage.user(text_or_blocks="hello")])
        result = make_action_result()
        node = cm.commit_iteration(
            ability_names=["conversation"],
            action_results=[{"ability_name": "conversation", "action_result": result}],
        )

        assert node.ability_names == ["conversation"]
        assert node.iteration == 1
        assert node.action_results == [{"ability_name": "conversation", "action_result": result}]
        assert not cm.in_iteration
        assert cm.message_store.count == 1

    def test_commit_iteration_with_state_changes(self) -> None:
        """commit 时传入 state_changes。"""
        cm = _make_cm(initial_state={"count": 0})
        cm.begin_iteration()
        node = cm.commit_iteration(
            ability_names=["increment"],
            state_changes={"count": 1},
        )

        assert node.agent_state == {"count": 1}
        assert cm.get_current_state() == {"count": 1}

    def test_commit_iteration_increments(self) -> None:
        """多次 commit，iteration 递增。"""
        cm = _make_cm()
        for i in range(3):
            cm.begin_iteration()
            node = cm.commit_iteration(ability_names=[f"ability_{i}"])

        assert node.iteration == 3
        assert cm.chain.node_count == 4

    def test_commit_iteration_auto_snapshot(self) -> None:
        """snapshot_interval=5 时，第 5 轮自动创建 snapshot。"""
        cm = _make_cm(snapshot_interval=5)
        for i in range(5):
            cm.begin_iteration()
            cm.add_messages([ChatMessage.user(text_or_blocks=f"msg_{i}")])
            node = cm.commit_iteration(ability_names=[f"ability_{i}"])

        assert node.is_snapshot is True
        assert node.messages_snapshot is not None

    def test_commit_iteration_delta_calculation(self) -> None:
        """非 snapshot 轮只存 delta。"""
        cm = _make_cm(snapshot_interval=10)
        cm.begin_iteration()
        cm.add_messages([ChatMessage.user(text_or_blocks="msg_1")])
        node = cm.commit_iteration(ability_names=["ability_1"])

        assert node.is_snapshot is False
        assert node.messages_snapshot is None
        assert len(node.messages_delta) == 1

    def test_rollback_iteration(self) -> None:
        """rollback 创建新 branch（从回滚目标节点 fork）。"""
        cm = _make_cm()
        # 先 commit 一次，确保有父节点可以回滚
        cm.begin_iteration()
        cm.add_messages([ChatMessage.user(text_or_blocks="first")])
        cm.commit_iteration(ability_names=["step1"])

        # 再开始一次迭代，然后回滚
        cm.begin_iteration()
        cm.add_messages([ChatMessage.user(text_or_blocks="will be discarded")])
        node = cm.rollback_iteration(ValueError("something went wrong"))

        assert node.ability_names == ["rollback"]
        assert node.metadata.get("is_rollback") is True
        assert "something went wrong" in node.metadata.get("error", "")
        assert node.branch_name.startswith("rollback-")
        assert node.session_id != ""  # 有 session 关联

    def test_rollback_preserves_state(self) -> None:
        """rollback 后状态恢复到迭代前。"""
        cm = _make_cm(initial_state={"key": "original"})
        # 先 commit 一次
        cm.begin_iteration()
        cm.commit_iteration(ability_names=["step1"])

        # 再尝试修改并回滚
        cm.begin_iteration()
        cm.apply_state_changes({"key": "modified"})
        cm.rollback_iteration(RuntimeError("fail"))

        assert cm.get_current_state() == {"key": "original"}

    def test_rollback_discards_messages(self) -> None:
        """rollback 后 pending_messages 不写入 store。"""
        cm = _make_cm()
        # 先 commit 一次
        cm.begin_iteration()
        cm.commit_iteration(ability_names=["step1"])

        cm.begin_iteration()
        cm.add_messages([ChatMessage.user(text_or_blocks="discarded")])
        cm.rollback_iteration(RuntimeError("fail"))

        assert cm.message_store.count == 0

    def test_rollback_node_metadata(self) -> None:
        """回滚节点 metadata 含 is_rollback=True 和 error 信息。"""
        cm = _make_cm()
        # 先 commit 一次
        cm.begin_iteration()
        cm.commit_iteration(ability_names=["step1"])

        cm.begin_iteration()
        node = cm.rollback_iteration(TypeError("bad type"))

        assert node.metadata["is_rollback"] is True
        assert "bad type" in node.metadata["error"]
        assert "rollback_from_branch" in node.metadata
        assert "rollback_from_node_id" in node.metadata

    def test_add_messages_during_iteration(self) -> None:
        """迭代中添加消息。"""
        cm = _make_cm()
        cm.begin_iteration()
        cm.add_messages([ChatMessage.user(text_or_blocks="msg1")])
        cm.add_messages([ChatMessage.ai(text="msg2")])
        assert len(cm._pending_messages) == 2

        cm.commit_iteration(ability_names=["test"])
        assert cm.message_store.count == 2

    def test_add_messages_without_iteration(self) -> None:
        """非迭代中添加消息直接写入 MessageStore。"""
        cm = _make_cm()
        cm.add_messages([ChatMessage.user(text_or_blocks="msg")])
        assert cm.message_store.count == 1

    def test_apply_state_changes_without_iteration(self) -> None:
        """非迭代中 apply_state_changes 抛 RuntimeError。"""
        cm = _make_cm()
        with pytest.raises(RuntimeError, match="No iteration in progress"):
            cm.apply_state_changes({"key": "value"})


# ----------------------------------------------------------------
# TestContextManagerState — 状态管理
# ----------------------------------------------------------------


class TestContextManagerState:
    """ContextManager 状态管理测试。"""

    def test_get_current_state(self) -> None:
        """返回当前状态深拷贝。"""
        cm = _make_cm(initial_state={"a": 1})
        state = cm.get_current_state()
        assert state == {"a": 1}
        state["a"] = 999
        assert cm.get_current_state() == {"a": 1}

    def test_apply_state_changes(self) -> None:
        """在事务中应用变更。"""
        cm = _make_cm(initial_state={"count": 0})
        cm.begin_iteration()
        preview = cm.apply_state_changes({"count": 5})
        assert preview == {"count": 5}
        assert cm.get_current_state() == {"count": 0}

    def test_state_isolation_after_rollback(self) -> None:
        """rollback 后状态完全恢复。"""
        cm = _make_cm(initial_state={"x": 1, "y": 2})
        cm.begin_iteration()
        cm.apply_state_changes({"x": 100, "y": 200, "z": 300})
        cm.rollback_iteration(RuntimeError("fail"))

        assert cm.get_current_state() == {"x": 1, "y": 2}


# ----------------------------------------------------------------
# TestContextManagerQuery — 查询 API
# ----------------------------------------------------------------


class TestContextManagerQuery:
    """ContextManager 查询 API 测试。"""

    def test_get_history(self) -> None:
        """返回完整历史。"""
        cm = _make_cm()
        for i in range(3):
            cm.begin_iteration()
            cm.commit_iteration(ability_names=[f"ability_{i}"])

        history = cm.get_history()
        assert len(history) == 4
        assert history[0].ability_names == ["init"]
        assert history[-1].ability_names == ["ability_2"]

    def test_get_history_with_limit(self) -> None:
        """限制历史数量。"""
        cm = _make_cm()
        for i in range(5):
            cm.begin_iteration()
            cm.commit_iteration(ability_names=[f"ability_{i}"])

        history = cm.get_history(limit=2)
        assert len(history) == 2
        assert history[-1].ability_names == ["ability_4"]

    def test_get_branch_heads(self) -> None:
        """返回分支头节点。"""
        cm = _make_cm()
        cm.begin_iteration()
        cm.commit_iteration(ability_names=["ability_1"])

        heads = cm.get_branch_heads()
        assert "main" in heads
        assert heads["main"].ability_names == ["ability_1"]

    def test_get_chain_node(self) -> None:
        """按 ID 获取节点。"""
        cm = _make_cm()
        root_id = cm.chain.head.id
        node = cm.get_chain_node(root_id)
        assert node is not None
        assert node.ability_names == ["init"]

    def test_get_chain_node_nonexistent(self) -> None:
        """不存在的节点返回 None。"""
        cm = _make_cm()
        assert cm.get_chain_node("nonexistent") is None

    async def test_get_llm_messages(self) -> None:
        """返回当前消息列表。"""
        cm = _make_cm()
        cm.begin_iteration()
        cm.add_messages([ChatMessage.user(text_or_blocks="hello"), ChatMessage.ai(text="hi")])
        cm.commit_iteration(ability_names=["conversation"])

        messages = await cm.get_llm_messages()
        assert len(messages) == 2
        assert messages[0].text == "hello"
        assert messages[1].text == "hi"

    async def test_get_llm_messages_with_filter(self) -> None:
        """使用 filter_fn 过滤消息。"""
        cm = _make_cm()
        cm.begin_iteration()
        cm.add_messages(
            [
                ChatMessage.user(text_or_blocks="hello"),
                ChatMessage.ai(text="hi"),
                ChatMessage.user(text_or_blocks="world"),
            ]
        )
        cm.commit_iteration(ability_names=["conversation"])

        messages = await cm.get_llm_messages(filter_fn=lambda m: m.role == "user")
        assert len(messages) == 2
        assert all(m.role == "user" for m in messages)

    async def test_get_llm_messages_empty(self) -> None:
        """空 store 返回空列表。"""
        cm = _make_cm()
        assert await cm.get_llm_messages() == []

    async def test_get_llm_messages_includes_pending_during_iteration(self) -> None:
        """迭代中 get_llm_messages 应包含尚未 commit 的 pending_messages。

        回归测试：修复 get_llm_messages() 在迭代中不包含 pending_messages
        导致 LLM 收到不完整消息列表（缺少 ChatMessage.user）的问题。
        """
        cm = _make_cm(system_prompt="You are a helpful assistant.")

        assert cm.message_store.count == 1

        cm.begin_iteration()
        cm.add_messages([ChatMessage.user(text_or_blocks="Hello!")])

        messages = await cm.get_llm_messages()
        assert len(messages) == 2
        assert messages[0].text == "You are a helpful assistant."
        assert messages[1].text == "Hello!"

        cm.commit_iteration(
            ability_names=["conversation"],
            action_results=[
                {
                    "ability_name": "conversation",
                    "action_result": ActionResult(
                        outcome=ActionOutcome.SUCCESS,
                        data={"response": "Hi there!"},
                    ),
                }
            ],
        )
        assert cm.message_store.count == 2

        messages = await cm.get_llm_messages()
        assert len(messages) == 2

    async def test_get_llm_messages_no_pending_outside_iteration(self) -> None:
        """迭代外 get_llm_messages 直接从 store 读取。"""
        cm = _make_cm()

        cm.add_messages([ChatMessage.user(text_or_blocks="hello")])
        assert cm.message_store.count == 1

        messages = await cm.get_llm_messages()
        assert len(messages) == 1
        assert messages[0].text == "hello"


# ----------------------------------------------------------------
# TestContextManagerFork — 子 Agent 继承
# ----------------------------------------------------------------


class TestContextManagerFork:
    """ContextManager fork 子 Agent 测试。"""

    def test_fork_creates_independent_cm(self) -> None:
        """fork 创建独立 ContextManager。"""
        cm = _make_cm()
        child = cm.fork_for_sub_agent("child-agent")
        assert child.agent_name == "child-agent"
        assert child is not cm

    def test_fork_inherits_state(self) -> None:
        """子 CM 继承父 CM 状态。"""
        cm = _make_cm(initial_state={"key": "value"})
        child = cm.fork_for_sub_agent("child-agent")
        assert child.get_current_state() == {"key": "value"}

    async def test_fork_inherits_messages(self) -> None:
        """子 CM 继承父 CM 消息。"""
        cm = _make_cm()
        cm.begin_iteration()
        cm.add_messages([ChatMessage.user(text_or_blocks="hello")])
        cm.commit_iteration(ability_names=["conversation"])

        child = cm.fork_for_sub_agent("child-agent")
        assert child.message_store.count == 1
        assert (await child.get_llm_messages())[0].text == "hello"

    def test_fork_with_state_filter(self) -> None:
        """使用 state_filter 过滤继承的状态。"""
        cm = _make_cm(initial_state={"public": "yes", "secret": "no"})
        child = cm.fork_for_sub_agent(
            "child-agent",
            state_filter=lambda s: {k: v for k, v in s.items() if k != "secret"},
        )
        state = child.get_current_state()
        assert state == {"public": "yes"}
        assert "secret" not in state

    def test_fork_with_custom_system_prompt(self) -> None:
        """覆盖 system_prompt。"""
        cm = _make_cm(system_prompt="Parent prompt")
        child = cm.fork_for_sub_agent("child-agent", system_prompt="Child prompt")
        assert child._system_prompt == "Child prompt"

    def test_fork_independent_iterations(self) -> None:
        """子 CM 独立迭代不影响父 CM。"""
        cm = _make_cm()
        parent_history_len = len(cm.get_history())

        child = cm.fork_for_sub_agent("child-agent")
        child.begin_iteration()
        child.commit_iteration(ability_names=["child_ability"])

        assert len(cm.get_history()) == parent_history_len
        assert len(child.get_history()) == 2

    def test_fork_independent_state(self) -> None:
        """子 CM 状态变更不影响父 CM。"""
        cm = _make_cm(initial_state={"count": 0})
        child = cm.fork_for_sub_agent("child-agent")

        child.begin_iteration()
        child.commit_iteration(ability_names=["increment"], state_changes={"count": 100})

        assert cm.get_current_state() == {"count": 0}
        assert child.get_current_state() == {"count": 100}

    def test_fork_independent_messages(self) -> None:
        """子 CM 消息变更不影响父 CM。"""
        cm = _make_cm()
        cm.begin_iteration()
        cm.add_messages([ChatMessage.user(text_or_blocks="parent_msg")])
        cm.commit_iteration(ability_names=["conversation"])

        parent_msg_count = cm.message_store.count

        child = cm.fork_for_sub_agent("child-agent")
        child.begin_iteration()
        child.add_messages([ChatMessage.user(text_or_blocks="child_msg")])
        child.commit_iteration(ability_names=["conversation"])

        assert cm.message_store.count == parent_msg_count
        assert child.message_store.count == parent_msg_count + 1

    def test_fork_preserves_snapshot_interval(self) -> None:
        """fork 时继承父 CM 的 snapshot_interval。"""
        cm = _make_cm(snapshot_interval=3)
        child = cm.fork_for_sub_agent("child-agent")
        assert child.message_store.snapshot_interval == 3

    def test_fork_with_custom_snapshot_interval(self) -> None:
        """fork 时指定自定义 snapshot_interval。"""
        cm = _make_cm(snapshot_interval=5)
        child = cm.fork_for_sub_agent("child-agent", snapshot_interval=10)
        assert child.message_store.snapshot_interval == 10


# ----------------------------------------------------------------
# TestContextManagerBuildContext — 上下文构建
# ----------------------------------------------------------------


class TestContextManagerBuildContext:
    """ContextManager build_execution_context 测试。"""

    def test_build_execution_context_basic(self) -> None:
        """基本构建，字段正确。"""
        cm = _make_cm(initial_state={"key": "value"})
        config = AgentConfig(name="test-agent")

        ctx = cm.build_execution_context(config=config)

        assert isinstance(ctx, AbilityExecutionContext)
        assert ctx.agent_state == {"key": "value"}
        assert ctx.context_manager is cm

    def test_build_execution_context_iteration_from_cm(self) -> None:
        """iteration 由 ContextManager 管理。"""
        cm = _make_cm()

        assert cm.iteration == 0

        cm.begin_iteration()
        cm.commit_iteration(ability_names=["ability_1"])
        cm.begin_iteration()
        cm.commit_iteration(ability_names=["ability_2"])

        cm.advance_iteration()
        cm.advance_iteration()
        assert cm.iteration == 2


# ----------------------------------------------------------------
# TestContextManagerIntegration — 集成场景
# ----------------------------------------------------------------


class TestContextManagerIntegration:
    """ContextManager 集成场景测试。"""

    def test_full_iteration_lifecycle(self) -> None:
        """完整生命周期：init → begin → add → commit。"""
        cm = _make_cm(initial_state={"step": 0})

        cm.begin_iteration()
        cm.add_messages([ChatMessage.user(text_or_blocks="hello")])
        cm.apply_state_changes({"step": 1})
        node = cm.commit_iteration(
            ability_names=["conversation"],
            action_results=[
                {"ability_name": "conversation", "action_result": make_action_result()}
            ],
            state_changes={"extra": "data"},
        )

        assert node.ability_names == ["conversation"]
        assert node.agent_state == {"step": 1, "extra": "data"}
        assert len(node.messages_delta) == 1
        assert cm.message_store.count == 1
        assert not cm.in_iteration

    def test_multiple_iterations(self) -> None:
        """多次迭代完整流程。"""
        cm = _make_cm(initial_state={"count": 0})

        for i in range(1, 4):
            cm.begin_iteration()
            cm.add_messages([ChatMessage.user(text_or_blocks=f"msg_{i}")])
            cm.apply_state_changes({"count": i})
            node = cm.commit_iteration(ability_names=[f"step_{i}"])

        assert node.iteration == 3
        assert cm.get_current_state() == {"count": 3}
        assert cm.message_store.count == 3
        assert cm.chain.node_count == 4

    def test_iteration_with_rollback_and_retry(self) -> None:
        """迭代失败回滚后重试。"""
        cm = _make_cm(initial_state={"retries": 0})

        # 先 commit 一次
        cm.begin_iteration()
        cm.commit_iteration(ability_names=["step1"])

        # 回滚
        cm.begin_iteration()
        cm.add_messages([ChatMessage.user(text_or_blocks="attempt 1")])
        cm.apply_state_changes({"retries": 1})
        rollback_node = cm.rollback_iteration(RuntimeError("timeout"))

        assert rollback_node.metadata["is_rollback"] is True
        assert cm.get_current_state() == {"retries": 0}

        # 在回滚分支上继续
        cm.begin_iteration()
        cm.add_messages([ChatMessage.user(text_or_blocks="attempt 2")])
        cm.apply_state_changes({"retries": 1})
        success_node = cm.commit_iteration(ability_names=["retry_ability"])

        assert success_node.ability_names == ["retry_ability"]
        assert success_node.agent_state == {"retries": 1}

    def test_snapshot_interval_configuration(self) -> None:
        """快照间隔配置生效。"""
        cm = _make_cm(snapshot_interval=2)

        nodes: list[ContextNode] = []
        for i in range(1, 7):
            cm.begin_iteration()
            cm.add_messages([ChatMessage.user(text_or_blocks=f"msg_{i}")])
            node = cm.commit_iteration(ability_names=[f"ability_{i}"])
            nodes.append(node)

        snapshot_iterations = [n.iteration for n in nodes if n.is_snapshot]
        assert snapshot_iterations == [2, 4, 6]

        delta_iterations = [n.iteration for n in nodes if not n.is_snapshot]
        assert delta_iterations == [1, 3, 5]

    def test_full_snapshot_delta_cycle(self) -> None:
        """多轮 commit 验证 snapshot/delta 交替。"""
        cm = _make_cm(snapshot_interval=3)

        cm.begin_iteration()
        cm.add_messages([ChatMessage.user(text_or_blocks="m1")])
        n1 = cm.commit_iteration(ability_names=["a1"])
        assert not n1.is_snapshot
        assert len(n1.messages_delta) == 1

        cm.begin_iteration()
        cm.add_messages([ChatMessage.user(text_or_blocks="m2")])
        n2 = cm.commit_iteration(ability_names=["a2"])
        assert not n2.is_snapshot
        assert len(n2.messages_delta) == 1

        cm.begin_iteration()
        cm.add_messages([ChatMessage.user(text_or_blocks="m3")])
        n3 = cm.commit_iteration(ability_names=["a3"])
        assert n3.is_snapshot
        assert n3.messages_snapshot is not None
        assert len(n3.messages_snapshot) == 3

        cm.begin_iteration()
        cm.add_messages([ChatMessage.user(text_or_blocks="m4")])
        n4 = cm.commit_iteration(ability_names=["a4"])
        assert not n4.is_snapshot
        assert len(n4.messages_delta) == 1

    async def test_rollback_does_not_affect_message_store(self) -> None:
        """回滚不影响已提交的消息。"""
        cm = _make_cm()

        cm.begin_iteration()
        cm.add_messages([ChatMessage.user(text_or_blocks="committed")])
        cm.commit_iteration(ability_names=["ability_1"])
        assert cm.message_store.count == 1

        # 回滚前需要再 commit 一次，因为回滚需要一个有前驱的节点
        cm.begin_iteration()
        cm.add_messages([ChatMessage.user(text_or_blocks="second")])
        cm.commit_iteration(ability_names=["ability_2"])

        cm.begin_iteration()
        cm.add_messages([ChatMessage.user(text_or_blocks="will be discarded")])
        cm.rollback_iteration(RuntimeError("fail"))

        # 已提交的消息保留在 main 分支，回滚不影响
        # 但活跃分支现在是 rollback 分支，history 只包含 rollback 节点
        assert cm.message_store.count == 2

    def test_chain_history_reflects_all_operations(self) -> None:
        """链历史反映所有操作（包括回滚）。"""
        cm = _make_cm()

        cm.begin_iteration()
        cm.commit_iteration(ability_names=["ability_1"])

        cm.begin_iteration()
        rollback_node = cm.rollback_iteration(RuntimeError("fail"))

        # 回滚后，活跃分支是 rollback 分支
        # rollback 分支的历史是：root -> rollback_node（回滚到 root 的状态）
        cm.begin_iteration()
        cm.commit_iteration(ability_names=["ability_2"])

        # 活跃分支的历史应该包含：root, rollback_node, ability_2
        history = cm.get_history()
        assert len(history) == 3
        assert history[0].ability_names == ["init"]
        assert history[1].ability_names == ["rollback"]
        assert history[2].ability_names == ["ability_2"]
