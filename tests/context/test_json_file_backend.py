# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""JsonFileBackend 持久化后端测试。

覆盖：
- 节点保存/加载/批量加载
- 链元信息保存/加载
- 消息保存/加载
- 删除链/列出 agents
- 压缩开关
- ContextManager 集成（persist + restore）
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest
from _helpers import make_action_result, make_node

from ghrah.abilities.base import ActionOutcome, ActionResult
from ghrah.chat.message import ChatMessage
from ghrah.context.persistence import (
    JsonFileBackend,
)

# ----------------------------------------------------------------
# TestJsonFileBackendInit — 初始化测试
# ----------------------------------------------------------------


class TestJsonFileBackendInit:
    """JsonFileBackend 初始化测试。"""

    def test_default_root_dir(self, tmp_path: Path) -> None:
        backend = JsonFileBackend(root_dir=tmp_path)
        assert backend.root_dir == tmp_path

    def test_custom_run_id(self, tmp_path: Path) -> None:
        backend = JsonFileBackend(root_dir=tmp_path, run_id="my-run")
        assert backend.run_id == "my-run"
        assert backend.run_dir == tmp_path / "my-run"

    def test_auto_run_id_format(self, tmp_path: Path) -> None:
        backend = JsonFileBackend(root_dir=tmp_path)
        assert backend.run_id.startswith("run_")

    def test_compress_default_true(self, tmp_path: Path) -> None:
        backend = JsonFileBackend(root_dir=tmp_path)
        assert backend._compress is True

    def test_compress_disabled(self, tmp_path: Path) -> None:
        backend = JsonFileBackend(root_dir=tmp_path, compress=False)
        assert backend._compress is False


# ----------------------------------------------------------------
# TestJsonFileBackendNodeOperations — 节点操作测试
# ----------------------------------------------------------------


class TestJsonFileBackendNodeOperations:
    """节点保存/加载测试。"""

    @pytest.mark.asyncio
    async def test_save_and_load_node(self, tmp_path: Path) -> None:
        backend = JsonFileBackend(root_dir=tmp_path)
        node = make_node()

        await backend.save_node(node)
        loaded = await backend.load_node(node.id)

        assert loaded is not None
        assert loaded.id == node.id
        assert loaded.agent_name == node.agent_name
        assert loaded.iteration == node.iteration

    @pytest.mark.asyncio
    async def test_load_nonexistent_node(self, tmp_path: Path) -> None:
        backend = JsonFileBackend(root_dir=tmp_path)
        result = await backend.load_node("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_save_multiple_nodes(self, tmp_path: Path) -> None:
        backend = JsonFileBackend(root_dir=tmp_path)

        node1 = make_node(id="node1", iteration=0)
        node2 = make_node(id="node2", iteration=1, parent_id="node1")
        await backend.save_node(node1)
        await backend.save_node(node2)

        loaded1 = await backend.load_node("node1")
        loaded2 = await backend.load_node("node2")

        assert loaded1 is not None
        assert loaded2 is not None
        assert loaded1.iteration == 0
        assert loaded2.iteration == 1

    @pytest.mark.asyncio
    async def test_save_node_creates_files(self, tmp_path: Path) -> None:
        backend = JsonFileBackend(root_dir=tmp_path)
        node = make_node()

        await backend.save_node(node)

        nodes_path = backend._nodes_path("test-agent")
        assert nodes_path.exists()
        assert "test-agent" in str(nodes_path)

    @pytest.mark.asyncio
    async def test_load_chain_sorted_by_iteration(self, tmp_path: Path) -> None:
        backend = JsonFileBackend(root_dir=tmp_path)

        node3 = make_node(id="node3", iteration=2, parent_id="node2")
        node1 = make_node(id="node1", iteration=0)
        node2 = make_node(id="node2", iteration=1, parent_id="node1")

        await backend.save_node(node3)
        await backend.save_node(node1)
        await backend.save_node(node2)

        chain = await backend.load_chain("test-agent")
        assert len(chain) == 3
        assert chain[0].iteration == 0
        assert chain[1].iteration == 1
        assert chain[2].iteration == 2

    @pytest.mark.asyncio
    async def test_load_chain_empty(self, tmp_path: Path) -> None:
        backend = JsonFileBackend(root_dir=tmp_path)
        chain = await backend.load_chain("nonexistent-agent")
        assert chain == []

    @pytest.mark.asyncio
    async def test_save_node_with_messages(self, tmp_path: Path) -> None:
        backend = JsonFileBackend(root_dir=tmp_path)

        node = make_node(
            messages_delta=[
                ChatMessage.user(text_or_blocks="hello"),
                ChatMessage.ai(text="world"),
            ],
        )
        await backend.save_node(node)

        loaded = await backend.load_node(node.id)
        assert loaded is not None
        assert len(loaded.messages_delta) == 2
        assert loaded.messages_delta[0].role == "user"
        assert loaded.messages_delta[1].role == "ai"

    @pytest.mark.asyncio
    async def test_save_node_with_action_results(self, tmp_path: Path) -> None:
        backend = JsonFileBackend(root_dir=tmp_path)

        result = make_action_result(data={"foo": "bar"}, hint="next")
        node = make_node(
            action_results=[
                {
                    "ability_name": "test_ability",
                    "action_result": result,
                }
            ],
        )
        await backend.save_node(node)

        loaded = await backend.load_node(node.id)
        assert loaded is not None
        assert len(loaded.action_results) == 1
        assert loaded.action_results[0]["ability_name"] == "test_ability"
        ar = loaded.action_results[0]["action_result"]
        assert ar.outcome == ActionOutcome.SUCCESS
        assert ar.data == {"foo": "bar"}
        assert ar.next_action_hint == "next"


# ----------------------------------------------------------------
# TestJsonFileBackendChainMeta — 链元信息测试
# ----------------------------------------------------------------


class TestJsonFileBackendChainMeta:
    """链元信息保存/加载测试。"""

    @pytest.mark.asyncio
    async def test_save_and_load_chain_meta(self, tmp_path: Path) -> None:
        backend = JsonFileBackend(root_dir=tmp_path)

        branches = {"main": "node1", "dev": "node2"}
        state = {"status": "running", "count": 42}

        await backend.save_chain_meta("test-agent", branches, state)
        result = await backend.load_chain_meta("test-agent")

        assert result is not None
        loaded_branches, loaded_session_id, loaded_state = result
        assert loaded_branches == branches
        assert loaded_state == state

    @pytest.mark.asyncio
    async def test_load_chain_meta_nonexistent(self, tmp_path: Path) -> None:
        backend = JsonFileBackend(root_dir=tmp_path)
        result = await backend.load_chain_meta("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_chain_meta_creates_file(self, tmp_path: Path) -> None:
        backend = JsonFileBackend(root_dir=tmp_path)

        await backend.save_chain_meta("test-agent", {"main": "n1"}, {})

        meta_path = backend._meta_path("test-agent")
        assert meta_path.exists()


# ----------------------------------------------------------------
# TestJsonFileBackendMessages — 消息操作测试
# ----------------------------------------------------------------


class TestJsonFileBackendMessages:
    """消息保存/加载测试。"""

    @pytest.mark.asyncio
    async def test_save_and_load_messages(self, tmp_path: Path) -> None:
        backend = JsonFileBackend(root_dir=tmp_path)

        messages = [
            ChatMessage.system(text="system"),
            ChatMessage.user(text_or_blocks="hello"),
            ChatMessage.ai(text="world"),
        ]

        await backend.save_messages("test-agent", messages)
        loaded = await backend.load_messages("test-agent")

        assert len(loaded) == 3
        assert loaded[0].role == "system"
        assert loaded[1].role == "user"
        assert loaded[2].role == "ai"
        assert loaded[0].text == "system"
        assert loaded[1].text == "hello"
        assert loaded[2].text == "world"

    @pytest.mark.asyncio
    async def test_load_messages_empty(self, tmp_path: Path) -> None:
        backend = JsonFileBackend(root_dir=tmp_path)
        loaded = await backend.load_messages("nonexistent")
        assert loaded == []

    @pytest.mark.asyncio
    async def test_save_empty_messages(self, tmp_path: Path) -> None:
        backend = JsonFileBackend(root_dir=tmp_path)

        await backend.save_messages("test-agent", [])
        loaded = await backend.load_messages("test-agent")
        assert loaded == []


# ----------------------------------------------------------------
# TestJsonFileBackendDeleteAndList — 删除和列出测试
# ----------------------------------------------------------------


class TestJsonFileBackendDeleteAndList:
    """删除链和列出 agents 测试。"""

    @pytest.mark.asyncio
    async def test_delete_chain(self, tmp_path: Path) -> None:
        backend = JsonFileBackend(root_dir=tmp_path)

        node = make_node()
        await backend.save_node(node)
        await backend.save_chain_meta("test-agent", {"main": node.id}, {})
        await backend.save_messages("test-agent", [ChatMessage.user(text_or_blocks="hi")])

        agent_dir = backend._agent_dir("test-agent")
        assert agent_dir.exists()

        await backend.delete_chain("test-agent")
        assert not agent_dir.exists()

        assert await backend.load_node(node.id) is None
        assert await backend.load_chain_meta("test-agent") is None
        assert await backend.load_messages("test-agent") == []

    @pytest.mark.asyncio
    async def test_delete_nonexistent_chain(self, tmp_path: Path) -> None:
        backend = JsonFileBackend(root_dir=tmp_path)
        await backend.delete_chain("nonexistent")

    @pytest.mark.asyncio
    async def test_list_agents(self, tmp_path: Path) -> None:
        backend = JsonFileBackend(root_dir=tmp_path)

        node1 = make_node(agent_name="agent-a", id="n1")
        node2 = make_node(agent_name="agent-b", id="n2")
        await backend.save_node(node1)
        await backend.save_node(node2)

        agents = await backend.list_agents()
        assert "agent-a" in agents
        assert "agent-b" in agents

    @pytest.mark.asyncio
    async def test_list_agents_empty(self, tmp_path: Path) -> None:
        backend = JsonFileBackend(root_dir=tmp_path)
        agents = await backend.list_agents()
        assert agents == []

    @pytest.mark.asyncio
    async def test_list_agents_sorted(self, tmp_path: Path) -> None:
        backend = JsonFileBackend(root_dir=tmp_path)

        for name in ["charlie", "alpha", "bravo"]:
            node = make_node(agent_name=name, id=f"n-{name}")
            await backend.save_node(node)

        agents = await backend.list_agents()
        assert agents == ["alpha", "bravo", "charlie"]


# ----------------------------------------------------------------
# TestJsonFileBackendCompression — 压缩测试
# ----------------------------------------------------------------


class TestJsonFileBackendCompression:
    """压缩开关测试。"""

    @pytest.mark.asyncio
    async def test_compressed_file_is_gzip(self, tmp_path: Path) -> None:
        backend = JsonFileBackend(root_dir=tmp_path, compress=True)

        node = make_node()
        await backend.save_node(node)

        nodes_path = backend._nodes_path("test-agent")
        assert nodes_path.suffix == ".gz"

        with gzip.open(nodes_path, "rt", encoding="utf-8") as f:
            data = json.load(f)
        assert node.id in data

    @pytest.mark.asyncio
    async def test_uncompressed_file_is_json(self, tmp_path: Path) -> None:
        backend = JsonFileBackend(root_dir=tmp_path, compress=False)

        node = make_node()
        await backend.save_node(node)

        nodes_path = backend._nodes_path("test-agent")
        assert nodes_path.suffix == ".json"
        assert not nodes_path.name.endswith(".gz")

        with open(nodes_path, encoding="utf-8") as f:
            data = json.load(f)
        assert node.id in data

    @pytest.mark.asyncio
    async def test_compressed_roundtrip(self, tmp_path: Path) -> None:
        backend = JsonFileBackend(root_dir=tmp_path, compress=True)

        node = make_node(
            messages_delta=[ChatMessage.user(text_or_blocks="test")],
            agent_state={"key": "value"},
        )
        await backend.save_node(node)

        loaded = await backend.load_node(node.id)
        assert loaded is not None
        assert loaded.id == node.id
        assert len(loaded.messages_delta) == 1

    @pytest.mark.asyncio
    async def test_uncompressed_roundtrip(self, tmp_path: Path) -> None:
        backend = JsonFileBackend(root_dir=tmp_path, compress=False)

        node = make_node(
            messages_delta=[ChatMessage.ai(text="response")],
        )
        await backend.save_node(node)

        loaded = await backend.load_node(node.id)
        assert loaded is not None
        assert loaded.id == node.id


# ----------------------------------------------------------------
# TestJsonFileBackendAtomicWrite — 原子写入测试
# ----------------------------------------------------------------


class TestJsonFileBackendAtomicWrite:
    """原子写入安全性测试。"""

    @pytest.mark.asyncio
    async def test_no_tmp_files_after_success(self, tmp_path: Path) -> None:
        backend = JsonFileBackend(root_dir=tmp_path)

        await backend.save_chain_meta("test-agent", {"main": "n1"}, {})

        agent_dir = backend._agent_dir("test-agent")
        tmp_files = list(agent_dir.glob("*.tmp"))
        assert len(tmp_files) == 0

    @pytest.mark.asyncio
    async def test_overwrite_preserves_integrity(self, tmp_path: Path) -> None:
        """多次覆写后数据仍完整。"""
        backend = JsonFileBackend(root_dir=tmp_path)

        for i in range(5):
            await backend.save_chain_meta(
                "test-agent",
                {"main": f"node-{i}"},
                {"count": i},
            )
            result = await backend.load_chain_meta("test-agent")
            assert result is not None
            assert result[0] == {"main": f"node-{i}"}
            assert result[2] == {"count": i}


# ----------------------------------------------------------------
# TestJsonFileBackendSessionIsolation — 会话隔离测试
# ----------------------------------------------------------------


class TestJsonFileBackendRunIsolation:
    """不同 run 之间的数据隔离测试。"""

    @pytest.mark.asyncio
    async def test_different_runs_isolated(self, tmp_path: Path) -> None:
        backend1 = JsonFileBackend(root_dir=tmp_path, run_id="run-1")
        backend2 = JsonFileBackend(root_dir=tmp_path, run_id="run-2")

        node1 = make_node(agent_name="agent", id="n1", iteration=0)
        node2 = make_node(agent_name="agent", id="n2", iteration=0)

        await backend1.save_node(node1)
        await backend2.save_node(node2)

        chain1 = await backend1.load_chain("agent")
        assert len(chain1) == 1
        assert chain1[0].id == "n1"

        chain2 = await backend2.load_chain("agent")
        assert len(chain2) == 1
        assert chain2[0].id == "n2"

    @pytest.mark.asyncio
    async def test_different_runs_different_dirs(self, tmp_path: Path) -> None:
        backend1 = JsonFileBackend(root_dir=tmp_path, run_id="s1")
        backend2 = JsonFileBackend(root_dir=tmp_path, run_id="s2")

        assert backend1.run_dir != backend2.run_dir
        assert backend1.run_dir.name == "s1"
        assert backend2.run_dir.name == "s2"


# ----------------------------------------------------------------
# TestJsonFileBackendWithContextManager — 集成测试
# ----------------------------------------------------------------


class TestJsonFileBackendWithContextManager:
    """JsonFileBackend 与 ContextManager 的集成测试。"""

    @pytest.mark.asyncio
    async def test_persist_and_restore_basic(self, tmp_path: Path) -> None:
        """基本 persist + restore 往返。"""
        from ghrah.context.manager import ContextManager

        backend = JsonFileBackend(root_dir=tmp_path)

        cm = ContextManager(
            agent_name="test-agent",
            initial_state={"count": 0},
            persistence=backend,
        )

        await cm.persist()

        cm2 = ContextManager(
            agent_name="test-agent",
            persistence=backend,
        )
        await cm2.restore("test-agent")

        assert cm2.agent_name == "test-agent"
        assert cm2.chain.node_count >= 1

    @pytest.mark.asyncio
    async def test_persist_and_restore_with_iterations(self, tmp_path: Path) -> None:
        """多轮迭代后 persist + restore。"""
        from ghrah.context.manager import ContextManager

        backend = JsonFileBackend(root_dir=tmp_path)

        cm = ContextManager(
            agent_name="test-agent",
            initial_state={"step": 0},
            persistence=backend,
        )

        for i in range(1, 4):
            cm.begin_iteration()
            cm.add_messages([ChatMessage.user(text_or_blocks=f"msg-{i}")])
            result = ActionResult(outcome=ActionOutcome.SUCCESS, data={"step": i})
            cm.commit_iteration(
                ability_names=[f"ability-{i}"],
                action_results=[
                    {
                        "ability_name": f"ability-{i}",
                        "action_result": result,
                    }
                ],
                state_changes={"step": i},
            )

        await cm.persist()

        cm2 = ContextManager(
            agent_name="test-agent",
            persistence=backend,
        )
        await cm2.restore("test-agent")

        assert cm2.chain.node_count == 4
        assert cm2.state_manager.current.get("step") == 3
        assert cm2.message_store.count >= 3

    @pytest.mark.asyncio
    async def test_auto_persist_with_json_backend(self, tmp_path: Path) -> None:
        """auto_persist 模式与 JsonFileBackend 的集成。"""
        from ghrah.context.manager import ContextManager

        backend = JsonFileBackend(root_dir=tmp_path)

        cm = ContextManager(
            agent_name="test-agent",
            initial_state={"count": 0},
            persistence=backend,
            auto_persist=True,
        )

        cm.begin_iteration()
        cm.add_messages([ChatMessage.user(text_or_blocks="hello")])
        result = ActionResult(outcome=ActionOutcome.SUCCESS, data={"count": 1})
        cm.commit_iteration(
            ability_names=["test_ability"],
            action_results=[
                {
                    "ability_name": "test_ability",
                    "action_result": result,
                }
            ],
        )

        await cm.wait_for_persist()

        chain = await backend.load_chain("test-agent")
        assert len(chain) >= 1

    @pytest.mark.asyncio
    async def test_persist_restore_preserves_messages(self, tmp_path: Path) -> None:
        """persist + restore 保持消息完整。"""
        from ghrah.context.manager import ContextManager

        backend = JsonFileBackend(root_dir=tmp_path)

        cm = ContextManager(
            agent_name="test-agent",
            system_prompt="You are a helper.",
            persistence=backend,
        )

        messages_to_add = [
            ChatMessage.user(text_or_blocks="What is 2+2?"),
            ChatMessage.ai(text="The answer is 4."),
            ChatMessage.user(text_or_blocks="Thank you!"),
            ChatMessage.ai(text="You're welcome!"),
        ]

        cm.begin_iteration()
        cm.add_messages(messages_to_add[:2])
        cm.commit_iteration(
            ability_names=["chat"],
            action_results=[
                {
                    "ability_name": "chat",
                    "action_result": ActionResult(outcome=ActionOutcome.SUCCESS),
                }
            ],
        )

        cm.begin_iteration()
        cm.add_messages(messages_to_add[2:])
        cm.commit_iteration(
            ability_names=["chat"],
            action_results=[
                {
                    "ability_name": "chat",
                    "action_result": ActionResult(outcome=ActionOutcome.SUCCESS),
                }
            ],
        )

        await cm.persist()

        cm2 = ContextManager(
            agent_name="test-agent",
            persistence=backend,
        )
        await cm2.restore("test-agent")

        restored = cm2.message_store.current_messages
        contents = [m.text for m in restored]
        assert "What is 2+2?" in contents
        assert "The answer is 4." in contents
        assert "Thank you!" in contents
        assert "You're welcome!" in contents
