# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""持久化接口测试。

覆盖：
- 序列化/反序列化函数（ContextNode、ActionResult、Messages）
- InMemoryBackend 各方法
- ContextManager persist/restore 集成
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from _helpers import make_action_result, make_node

from ghrah.abilities.base import ActionOutcome
from ghrah.chat.message import ChatMessage
from ghrah.context.persistence import (
    InMemoryBackend,
    deserialize_action_result,
    deserialize_messages,
    deserialize_node,
    serialize_action_result,
    serialize_messages,
    serialize_node,
)

# ----------------------------------------------------------------
# TestSerialization — 序列化工具函数测试
# ----------------------------------------------------------------


class TestActionResultSerialization:
    """ActionResult 序列化/反序列化测试。"""

    def test_serialize_none_returns_none(self) -> None:
        assert serialize_action_result(None) is None

    def test_deserialize_none_returns_none(self) -> None:
        assert deserialize_action_result(None) is None

    def test_roundtrip_basic(self) -> None:
        result = make_action_result(data={"foo": "bar"}, hint="next_action")
        serialized = serialize_action_result(result)
        deserialized = deserialize_action_result(serialized)

        assert deserialized is not None
        assert deserialized.outcome == ActionOutcome.SUCCESS
        assert deserialized.data == {"foo": "bar"}
        assert deserialized.next_action_hint == "next_action"

    def test_roundtrip_failure_result(self) -> None:
        result = make_action_result(outcome=ActionOutcome.FAILURE, data={"error": "oops"})
        serialized = serialize_action_result(result)
        deserialized = deserialize_action_result(serialized)

        assert deserialized is not None
        assert deserialized.outcome == ActionOutcome.FAILURE
        assert deserialized.data == {"error": "oops"}
        assert deserialized.next_action_hint is None

    def test_serialize_preserves_outcome_value(self) -> None:
        result = make_action_result(outcome=ActionOutcome.DELEGATE)
        serialized = serialize_action_result(result)
        assert serialized["outcome"] == "delegate"


class TestMessagesSerialization:
    """消息列表序列化/反序列化测试。"""

    def test_serialize_none_returns_none(self) -> None:
        assert serialize_messages(None) is None

    def test_deserialize_none_returns_none(self) -> None:
        assert deserialize_messages(None) is None

    def test_roundtrip_empty_list(self) -> None:
        serialized = serialize_messages([])
        assert serialized == []
        deserialized = deserialize_messages(serialized)
        assert deserialized == []

    def test_roundtrip_human_message(self) -> None:
        msgs = [ChatMessage.user(text_or_blocks="hello")]
        serialized = serialize_messages(msgs)
        deserialized = deserialize_messages(serialized)

        assert len(deserialized) == 1
        assert deserialized[0].role == "user"
        assert deserialized[0].text == "hello"

    def test_roundtrip_mixed_message_types(self) -> None:
        msgs = [
            ChatMessage.system(text="system"),
            ChatMessage.user(text_or_blocks="user msg"),
            ChatMessage.ai(text="ai response"),
        ]
        serialized = serialize_messages(msgs)
        deserialized = deserialize_messages(serialized)

        assert len(deserialized) == 3
        assert deserialized[0].role == "system"
        assert deserialized[1].role == "user"
        assert deserialized[2].role == "ai"
        assert deserialized[0].text == "system"
        assert deserialized[1].text == "user msg"
        assert deserialized[2].text == "ai response"


class TestNodeSerialization:
    """ContextNode 序列化/反序列化测试。"""

    def test_roundtrip_basic_node(self) -> None:
        node = make_node()
        serialized = serialize_node(node)
        deserialized = deserialize_node(serialized)

        assert deserialized.id == node.id
        assert deserialized.parent_id == node.parent_id
        assert deserialized.agent_name == node.agent_name
        assert deserialized.iteration == node.iteration
        assert deserialized.ability_names == node.ability_names
        assert deserialized.agent_state == node.agent_state
        assert deserialized.branch_name == node.branch_name
        assert deserialized.is_snapshot == node.is_snapshot

    def test_roundtrip_with_timestamp(self) -> None:
        ts = datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC)
        node = make_node(timestamp=ts)
        serialized = serialize_node(node)
        deserialized = deserialize_node(serialized)

        assert deserialized.timestamp == ts

    def test_roundtrip_with_messages_delta(self) -> None:
        node = make_node(
            messages_delta=[ChatMessage.user(text_or_blocks="hello"), ChatMessage.ai(text="hi")],
            is_snapshot=False,
        )
        serialized = serialize_node(node)
        deserialized = deserialize_node(serialized)

        assert len(deserialized.messages_delta) == 2
        assert deserialized.messages_delta[0].role == "user"
        assert deserialized.messages_delta[1].role == "ai"
        assert deserialized.messages_delta[0].text == "hello"

    def test_roundtrip_with_messages_snapshot(self) -> None:
        node = make_node(
            messages_snapshot=[
                ChatMessage.system(text="sys"),
                ChatMessage.user(text_or_blocks="hi"),
            ],
            is_snapshot=True,
        )
        serialized = serialize_node(node)
        deserialized = deserialize_node(serialized)

        assert deserialized.messages_snapshot is not None
        assert len(deserialized.messages_snapshot) == 2
        assert deserialized.messages_snapshot[0].role == "system"

    def test_roundtrip_with_none_snapshot(self) -> None:
        node = make_node(messages_snapshot=None, is_snapshot=False)
        serialized = serialize_node(node)
        deserialized = deserialize_node(serialized)

        assert deserialized.messages_snapshot is None

    def test_roundtrip_with_action_results(self) -> None:
        result = make_action_result(data={"file": "test.py", "content": "print('hi')"}, hint="next")
        node = make_node(action_results=[{"ability_name": "test", "action_result": result}])
        serialized = serialize_node(node)
        deserialized = deserialize_node(serialized)

        assert len(deserialized.action_results) == 1
        assert deserialized.action_results[0]["action_result"].outcome == ActionOutcome.SUCCESS
        assert deserialized.action_results[0]["action_result"].data["file"] == "test.py"
        assert deserialized.action_results[0]["action_result"].next_action_hint == "next"

    def test_roundtrip_with_empty_action_results(self) -> None:
        node = make_node(action_results=[])
        serialized = serialize_node(node)
        deserialized = deserialize_node(serialized)

        assert deserialized.action_results == []

    def test_roundtrip_preserves_metadata(self) -> None:
        node = make_node(metadata={"is_rollback": True, "error": "test error"})
        serialized = serialize_node(node)
        deserialized = deserialize_node(serialized)

        assert deserialized.metadata["is_rollback"] is True
        assert deserialized.metadata["error"] == "test error"

    def test_roundtrip_preserves_parent_id(self) -> None:
        node = make_node(parent_id="abc123def456", iteration=3)
        serialized = serialize_node(node)
        deserialized = deserialize_node(serialized)

        assert deserialized.parent_id == "abc123def456"
        assert deserialized.iteration == 3

    def test_serialized_is_json_compatible(self) -> None:
        """确保序列化结果中所有值都是 JSON 兼容类型。"""
        import json

        node = make_node(
            messages_delta=[ChatMessage.user(text_or_blocks="test")],
            action_results=[
                {"ability_name": "test", "action_result": make_action_result(data={"x": 1})}
            ],
            metadata={"key": "val"},
        )
        serialized = serialize_node(node)

        json_str = json.dumps(serialized)
        assert isinstance(json_str, str)


# ----------------------------------------------------------------
# TestInMemoryBackend — InMemoryBackend 测试
# ----------------------------------------------------------------


class TestInMemoryBackend:
    """InMemoryBackend 各方法测试。"""

    @pytest.fixture
    def backend(self) -> InMemoryBackend:
        return InMemoryBackend()

    @pytest.mark.asyncio
    async def test_save_and_load_node(self, backend: InMemoryBackend) -> None:
        node = make_node()
        await backend.save_node(node)
        loaded = await backend.load_node(node.id)

        assert loaded is not None
        assert loaded.id == node.id
        assert loaded.agent_name == node.agent_name

    @pytest.mark.asyncio
    async def test_load_nonexistent_node(self, backend: InMemoryBackend) -> None:
        loaded = await backend.load_node("nonexistent")
        assert loaded is None

    @pytest.mark.asyncio
    async def test_save_and_load_chain(self, backend: InMemoryBackend) -> None:
        root = make_node(agent_name="agent-a")
        await backend.save_node(root)

        child = make_node(
            parent_id=root.id,
            agent_name="agent-a",
            iteration=1,
            ability_names=["chat"],
        )
        await backend.save_node(child)

        chain = await backend.load_chain("agent-a")
        assert len(chain) == 2
        assert chain[0].iteration == 0
        assert chain[1].iteration == 1

    @pytest.mark.asyncio
    async def test_load_chain_empty(self, backend: InMemoryBackend) -> None:
        chain = await backend.load_chain("nonexistent-agent")
        assert chain == []

    @pytest.mark.asyncio
    async def test_save_and_load_chain_meta(self, backend: InMemoryBackend) -> None:
        branches = {"main": "node-123", "sub": "node-456"}
        state = {"status": "running", "count": 5}

        await backend.save_chain_meta("agent-a", branches, state)
        result = await backend.load_chain_meta("agent-a")

        assert result is not None
        loaded_branches, loaded_session_id, loaded_state = result
        assert loaded_branches == branches
        assert loaded_state == state

    @pytest.mark.asyncio
    async def test_load_chain_meta_nonexistent(self, backend: InMemoryBackend) -> None:
        result = await backend.load_chain_meta("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_save_and_load_messages(self, backend: InMemoryBackend) -> None:
        msgs = [ChatMessage.user(text_or_blocks="hello"), ChatMessage.ai(text="hi")]
        await backend.save_messages("agent-a", msgs)

        loaded = await backend.load_messages("agent-a")
        assert len(loaded) == 2
        assert loaded[0].role == "user"
        assert loaded[0].text == "hello"

    @pytest.mark.asyncio
    async def test_load_messages_empty(self, backend: InMemoryBackend) -> None:
        loaded = await backend.load_messages("nonexistent")
        assert loaded == []

    @pytest.mark.asyncio
    async def test_messages_deep_copy(self, backend: InMemoryBackend) -> None:
        """确保 load_messages 返回深拷贝，修改不影响后端存储。"""
        msgs = [ChatMessage.user(text_or_blocks="original")]
        await backend.save_messages("agent-a", msgs)

        loaded = await backend.load_messages("agent-a")
        loaded[0].content_blocks[0].text = "modified"  # type: ignore[attr-defined]

        reloaded = await backend.load_messages("agent-a")
        assert reloaded[0].text == "original"

    @pytest.mark.asyncio
    async def test_chain_meta_deep_copy(self, backend: InMemoryBackend) -> None:
        """确保 load_chain_meta 返回深拷贝。"""
        state = {"key": "value"}
        await backend.save_chain_meta("agent-a", {"main": "n1"}, state)

        _, _, loaded_state = await backend.load_chain_meta("agent-a")  # type: ignore
        loaded_state["key"] = "modified"

        _, _, reloaded_state = await backend.load_chain_meta("agent-a")  # type: ignore
        assert reloaded_state["key"] == "value"

    @pytest.mark.asyncio
    async def test_delete_chain(self, backend: InMemoryBackend) -> None:
        node = make_node(agent_name="agent-a")
        await backend.save_node(node)
        await backend.save_chain_meta("agent-a", {"main": node.id}, {})
        await backend.save_messages("agent-a", [ChatMessage.user(text_or_blocks="hi")])

        await backend.delete_chain("agent-a")

        assert await backend.load_node(node.id) is None
        assert await backend.load_chain_meta("agent-a") is None
        assert await backend.load_messages("agent-a") == []
        assert "agent-a" not in await backend.list_agents()

    @pytest.mark.asyncio
    async def test_delete_nonexistent_chain(self, backend: InMemoryBackend) -> None:
        """删除不存在的 agent 不应报错。"""
        await backend.delete_chain("nonexistent")

    @pytest.mark.asyncio
    async def test_list_agents(self, backend: InMemoryBackend) -> None:
        await backend.save_node(make_node(agent_name="agent-a"))
        await backend.save_chain_meta("agent-b", {"main": "n1"}, {})

        agents = await backend.list_agents()
        assert "agent-a" in agents
        assert "agent-b" in agents

    @pytest.mark.asyncio
    async def test_list_agents_empty(self, backend: InMemoryBackend) -> None:
        agents = await backend.list_agents()
        assert agents == []

    @pytest.mark.asyncio
    async def test_save_node_no_duplicate_in_agent_index(self, backend: InMemoryBackend) -> None:
        """同一节点多次 save 不应重复追加到 agent_nodes 索引。"""
        node = make_node(agent_name="agent-a")
        await backend.save_node(node)
        await backend.save_node(node)

        chain = await backend.load_chain("agent-a")
        assert len(chain) == 1

    @pytest.mark.asyncio
    async def test_chain_sorted_by_iteration(self, backend: InMemoryBackend) -> None:
        """load_chain 应按 iteration 升序返回。"""
        root = make_node(agent_name="agent-a", iteration=0)
        n1 = make_node(agent_name="agent-a", iteration=2, parent_id=root.id)
        n2 = make_node(agent_name="agent-a", iteration=1, parent_id=root.id)

        await backend.save_node(n1)
        await backend.save_node(n2)
        await backend.save_node(root)

        chain = await backend.load_chain("agent-a")
        assert [n.iteration for n in chain] == [0, 1, 2]


# ----------------------------------------------------------------
# TestContextManagerPersistence — ContextManager 持久化集成测试
# ----------------------------------------------------------------


class TestContextManagerPersistRestore:
    """ContextManager persist/restore 集成测试。"""

    @pytest.fixture
    def backend(self) -> InMemoryBackend:
        return InMemoryBackend()

    @pytest.mark.asyncio
    async def test_persist_and_restore_basic(self, backend: InMemoryBackend) -> None:
        """基本 persist + restore 流程。"""
        from ghrah.context.manager import ContextManager

        cm = ContextManager(
            agent_name="test-agent",
            initial_state={"status": "idle"},
            persistence=backend,
        )

        cm.begin_iteration()
        cm.commit_iteration(
            ability_names=["chat"],
            action_results=[
                {
                    "ability_name": "chat",
                    "action_result": make_action_result(data={"response": "hello"}),
                }
            ],
        )

        cm.begin_iteration()
        cm.apply_state_changes({"status": "active"})
        cm.commit_iteration(
            ability_names=["tool"],
            action_results=[
                {
                    "ability_name": "tool",
                    "action_result": make_action_result(data={"result": "ok"}),
                }
            ],
        )

        await cm.persist()

        cm2 = ContextManager(
            agent_name="test-agent",
            persistence=backend,
        )
        await cm2.restore("test-agent")

        assert cm2.agent_name == "test-agent"
        assert cm2.get_current_state() == {"status": "active"}
        assert cm2.chain.node_count == cm.chain.node_count

        history = cm2.get_history()
        assert len(history) == len(cm.get_history())
        assert history[-1].ability_names == ["tool"]
        assert history[-1].agent_state == {"status": "active"}

    @pytest.mark.asyncio
    async def test_persist_and_restore_with_messages(self, backend: InMemoryBackend) -> None:
        """含消息的持久化/恢复。"""
        from ghrah.context.manager import ContextManager

        cm = ContextManager(
            agent_name="msg-agent",
            persistence=backend,
        )

        cm.begin_iteration()
        cm.add_messages([ChatMessage.user(text_or_blocks="hello")])
        cm.commit_iteration(ability_names=["chat"])

        cm.begin_iteration()
        cm.add_messages([ChatMessage.ai(text="hi there")])
        cm.commit_iteration(ability_names=["respond"])

        await cm.persist()

        cm2 = ContextManager(
            agent_name="msg-agent",
            persistence=backend,
        )
        await cm2.restore("msg-agent")

        messages = cm2.message_store.current_messages
        assert len(messages) == 2
        assert messages[0].role == "user"
        assert messages[0].text == "hello"
        assert messages[1].role == "ai"
        assert messages[1].text == "hi there"

    @pytest.mark.asyncio
    async def test_persist_and_restore_preserves_chain_structure(
        self, backend: InMemoryBackend
    ) -> None:
        """链结构（parent_id 关系、分支）在 restore 后完整。"""
        from ghrah.context.manager import ContextManager

        cm = ContextManager(
            agent_name="chain-agent",
            persistence=backend,
        )

        cm.begin_iteration()
        cm.commit_iteration(ability_names=["step1"])

        cm.begin_iteration()
        cm.commit_iteration(ability_names=["step2"])

        await cm.persist()

        cm2 = ContextManager(
            agent_name="chain-agent",
            persistence=backend,
        )
        await cm2.restore("chain-agent")

        history = cm2.get_history()
        assert len(history) == 3

        assert history[0].parent_id is None
        assert history[1].parent_id == history[0].id
        assert history[2].parent_id == history[1].id

        branches = cm2.chain.branches
        assert "main" in branches

    @pytest.mark.asyncio
    async def test_persist_and_restore_preserves_branches(self, backend: InMemoryBackend) -> None:
        """分支信息在 restore 后正确恢复。"""
        from ghrah.context.manager import ContextManager

        cm = ContextManager(
            agent_name="branch-agent",
            persistence=backend,
        )

        cm.begin_iteration()
        cm.commit_iteration(ability_names=["step1"])

        head = cm.chain.head
        cm.chain.fork("sub-branch", parent_id=head.id)

        await cm.persist()

        cm2 = ContextManager(
            agent_name="branch-agent",
            persistence=backend,
        )
        await cm2.restore("branch-agent")

        branches = cm2.chain.branches
        assert "main" in branches
        assert "sub-branch" in branches

    @pytest.mark.asyncio
    async def test_persist_without_backend_is_noop(self) -> None:
        """无后端时 persist 不报错，只记录警告。"""
        from ghrah.context.manager import ContextManager

        cm = ContextManager(agent_name="no-backend")
        cm.begin_iteration()
        cm.commit_iteration(ability_names=["chat"])

        await cm.persist()

    @pytest.mark.asyncio
    async def test_restore_without_backend_raises(self) -> None:
        """无后端时 restore 应抛出 RuntimeError。"""
        from ghrah.context.manager import ContextManager

        cm = ContextManager(agent_name="no-backend")
        with pytest.raises(RuntimeError, match="No persistence backend"):
            await cm.restore("test")

    @pytest.mark.asyncio
    async def test_restore_nonexistent_raises(self, backend: InMemoryBackend) -> None:
        """后端中无数据时 restore 应抛出 ValueError。"""
        from ghrah.context.manager import ContextManager

        cm = ContextManager(
            agent_name="empty",
            persistence=backend,
        )
        with pytest.raises(ValueError, match="No persisted data"):
            await cm.restore("nonexistent-agent")

    @pytest.mark.asyncio
    async def test_auto_persist_on_commit(self, backend: InMemoryBackend) -> None:
        """auto_persist=True 时，commit_iteration 自动保存节点。"""
        import asyncio

        from ghrah.context.manager import ContextManager

        cm = ContextManager(
            agent_name="auto-agent",
            persistence=backend,
            auto_persist=True,
        )

        cm.begin_iteration()
        cm.add_messages([ChatMessage.user(text_or_blocks="auto-test")])
        cm.commit_iteration(
            ability_names=["chat"],
            action_results=[{"ability_name": "chat", "action_result": make_action_result()}],
        )
        await asyncio.sleep(0.05)

        loaded = await backend.load_node(cm.chain.head.id)
        assert loaded is not None
        assert loaded.ability_names == ["chat"]

    @pytest.mark.asyncio
    async def test_auto_persist_on_rollback(self, backend: InMemoryBackend) -> None:
        """auto_persist=True 时，rollback_iteration 自动保存回滚节点。"""
        import asyncio

        from ghrah.context.manager import ContextManager

        cm = ContextManager(
            agent_name="auto-rollback",
            persistence=backend,
            auto_persist=True,
        )

        # 先 commit 一次，确保有父节点
        cm.begin_iteration()
        cm.commit_iteration(ability_names=["step1"])
        await asyncio.sleep(0.05)

        cm.begin_iteration()
        cm.rollback_iteration(ValueError("test error"))
        await asyncio.sleep(0.05)

        # 回滚发生在新 branch 上，检查 rollback 分支的 head
        loaded = await backend.load_node(cm.chain.active_head.id)
        assert loaded is not None
        assert loaded.ability_names == ["rollback"]
        assert loaded.metadata.get("is_rollback") is True

    @pytest.mark.asyncio
    async def test_restore_rebuilds_from_snapshot(self, backend: InMemoryBackend) -> None:
        """从快照节点 + delta 恢复消息。"""
        from ghrah.context.manager import ContextManager

        cm = ContextManager(
            agent_name="snapshot-agent",
            snapshot_interval=2,
            persistence=backend,
        )

        for i in range(1, 4):
            cm.begin_iteration()
            cm.add_messages([ChatMessage.user(text_or_blocks=f"msg-{i}")])
            cm.commit_iteration(ability_names=[f"step{i}"])

        await cm.persist()

        cm2 = ContextManager(
            agent_name="snapshot-agent",
            snapshot_interval=2,
            persistence=backend,
        )
        await cm2.restore("snapshot-agent")

        messages = cm2.message_store.current_messages
        assert len(messages) == 3
        assert messages[0].text == "msg-1"
        assert messages[1].text == "msg-2"
        assert messages[2].text == "msg-3"

    @pytest.mark.asyncio
    async def test_persist_restore_preserves_state(self, backend: InMemoryBackend) -> None:
        """状态在 persist/restore 后一致。"""
        from ghrah.context.manager import ContextManager

        cm = ContextManager(
            agent_name="state-agent",
            initial_state={"counter": 0, "items": []},
            persistence=backend,
        )

        cm.begin_iteration()
        cm.apply_state_changes({"counter": 1, "items": ["a"]})
        cm.commit_iteration(ability_names=["step1"])

        cm.begin_iteration()
        cm.apply_state_changes({"counter": 2, "items": ["a", "b"]})
        cm.commit_iteration(ability_names=["step2"])

        await cm.persist()

        cm2 = ContextManager(
            agent_name="state-agent",
            persistence=backend,
        )
        await cm2.restore("state-agent")

        state = cm2.get_current_state()
        assert state["counter"] == 2
        assert state["items"] == ["a", "b"]

    @pytest.mark.asyncio
    async def test_cm_persistence_property(self, backend: InMemoryBackend) -> None:
        """persistence 属性返回配置的后端。"""
        from ghrah.context.manager import ContextManager

        cm = ContextManager(
            agent_name="prop-test",
            persistence=backend,
        )
        assert cm.persistence is backend

    @pytest.mark.asyncio
    async def test_cm_no_persistence_property(self) -> None:
        """未配置后端时 persistence 属性返回 None。"""
        from ghrah.context.manager import ContextManager

        cm = ContextManager(agent_name="no-backend")
        assert cm.persistence is None
