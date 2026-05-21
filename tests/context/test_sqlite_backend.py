# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""SqliteBackend 持久化后端测试。

覆盖：
- 初始化与连接管理
- 节点保存/加载/批量加载
- 链元信息保存/加载
- 消息保存/加载
- 删除链/列出 agents
- 上下文管理器（async with）
- 批量节点保存
"""

from __future__ import annotations

from pathlib import Path

import pytest
from _helpers import make_action_result, make_node

from ghrah.abilities.base import ActionOutcome
from ghrah.chat.message import ChatMessage
from ghrah.context.node import ContextNode
from ghrah.context.persistence.sqlite_backend import SqliteBackend

# ----------------------------------------------------------------
# Fixture
# ----------------------------------------------------------------


@pytest.fixture
async def sqlite_backend(tmp_path: Path) -> SqliteBackend:
    """创建并打开一个临时 SqliteBackend。"""
    db_path = tmp_path / "test.db"
    backend = SqliteBackend(db_path=db_path, run_id="test-run")
    await backend.connect()
    yield backend
    await backend.close()


# ----------------------------------------------------------------
# TestSqliteBackendInit — 初始化测试
# ----------------------------------------------------------------


class TestSqliteBackendInit:
    """SqliteBackend 初始化测试。"""

    def test_default_db_path(self) -> None:
        backend = SqliteBackend()
        assert str(backend.db_path).endswith("ghrah.db")

    def test_custom_db_path(self, tmp_path: Path) -> None:
        db_path = tmp_path / "custom.db"
        backend = SqliteBackend(db_path=db_path)
        assert backend.db_path == db_path

    def test_custom_run_id(self, tmp_path: Path) -> None:
        backend = SqliteBackend(db_path=tmp_path / "test.db", run_id="my-run")
        assert backend.run_id == "my-run"

    def test_auto_run_id_format(self, tmp_path: Path) -> None:
        backend = SqliteBackend(db_path=tmp_path / "test.db")
        assert backend.run_id.startswith("run_")


# ----------------------------------------------------------------
# TestSqliteBackendConnection — 连接管理测试
# ----------------------------------------------------------------


class TestSqliteBackendConnection:
    """SqliteBackend 连接管理测试。"""

    @pytest.mark.asyncio
    async def test_connect_creates_db(self, tmp_path: Path) -> None:
        db_path = tmp_path / "new.db"
        backend = SqliteBackend(db_path=db_path)
        await backend.connect()
        assert db_path.exists()
        await backend.close()

    @pytest.mark.asyncio
    async def test_connect_double_raises(self, tmp_path: Path) -> None:
        backend = SqliteBackend(db_path=tmp_path / "test.db")
        await backend.connect()
        with pytest.raises(RuntimeError, match="already connected"):
            await backend.connect()
        await backend.close()

    @pytest.mark.asyncio
    async def test_close_idempotent(self, tmp_path: Path) -> None:
        backend = SqliteBackend(db_path=tmp_path / "test.db")
        await backend.connect()
        await backend.close()
        await backend.close()

    @pytest.mark.asyncio
    async def test_context_manager(self, tmp_path: Path) -> None:
        db_path = tmp_path / "ctx.db"
        async with SqliteBackend(db_path=db_path, run_id="ctx-session") as backend:
            assert backend._db is not None
            node = make_node(agent_name="ctx-agent")
            await backend.save_node(node)
            loaded = await backend.load_node(node.id)
            assert loaded is not None
        assert backend._db is None

    @pytest.mark.asyncio
    async def test_operation_without_connect_raises(self, tmp_path: Path) -> None:
        backend = SqliteBackend(db_path=tmp_path / "test.db")
        node = make_node()
        with pytest.raises(RuntimeError, match="not connected"):
            await backend.save_node(node)


# ----------------------------------------------------------------
# TestSqliteBackendNode — 节点操作测试
# ----------------------------------------------------------------


class TestSqliteBackendNode:
    """SqliteBackend 节点操作测试。"""

    @pytest.mark.asyncio
    async def test_save_and_load_node(self, sqlite_backend: SqliteBackend) -> None:
        node = make_node(
            agent_state={"count": 42, "items": ["a", "b"]},
            messages_delta=[ChatMessage.user(text_or_blocks="hello")],
        )
        await sqlite_backend.save_node(node)

        loaded = await sqlite_backend.load_node(node.id)
        assert loaded is not None
        assert loaded.id == node.id
        assert loaded.agent_name == node.agent_name
        assert loaded.iteration == node.iteration
        assert loaded.agent_state == {"count": 42, "items": ["a", "b"]}
        assert loaded.is_snapshot is True

    @pytest.mark.asyncio
    async def test_load_nonexistent_node(self, sqlite_backend: SqliteBackend) -> None:
        result = await sqlite_backend.load_node("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_save_node_upsert(self, sqlite_backend: SqliteBackend) -> None:
        node = make_node(iteration=0, agent_state={"version": 1})
        await sqlite_backend.save_node(node)

        updated_node = ContextNode(
            id=node.id,
            parent_id=None,
            agent_name="test-agent",
            iteration=0,
            ability_names=["init"],
            agent_state={"version": 2},
            messages_delta=[],
            is_snapshot=True,
            branch_name="main",
        )
        await sqlite_backend.save_node(updated_node)

        loaded = await sqlite_backend.load_node(node.id)
        assert loaded is not None
        assert loaded.agent_state == {"version": 2}

    @pytest.mark.asyncio
    async def test_save_node_with_action_results(self, sqlite_backend: SqliteBackend) -> None:
        result = make_action_result(
            outcome=ActionOutcome.SUCCESS,
            data={"output": "done"},
            hint="next_step",
        )
        node = make_node(
            iteration=1,
            ability_names=["read_file"],
            action_results=[{"ability_name": "read_file", "action_result": result}],
        )
        await sqlite_backend.save_node(node)

        loaded = await sqlite_backend.load_node(node.id)
        assert loaded is not None
        assert len(loaded.action_results) == 1
        assert loaded.action_results[0]["ability_name"] == "read_file"
        assert loaded.action_results[0]["action_result"].outcome == ActionOutcome.SUCCESS

    @pytest.mark.asyncio
    async def test_save_node_with_messages_snapshot(self, sqlite_backend: SqliteBackend) -> None:
        messages = [
            ChatMessage.system(text="system"),
            ChatMessage.user(text_or_blocks="hi"),
            ChatMessage.ai(text="hello"),
        ]
        node = make_node(
            iteration=5,
            is_snapshot=True,
            messages_snapshot=messages,
        )
        await sqlite_backend.save_node(node)

        loaded = await sqlite_backend.load_node(node.id)
        assert loaded is not None
        assert loaded.messages_snapshot is not None
        assert len(loaded.messages_snapshot) == 3
        assert loaded.messages_snapshot[0].role == "system"

    @pytest.mark.asyncio
    async def test_save_node_null_snapshot(self, sqlite_backend: SqliteBackend) -> None:
        node = make_node(iteration=1, is_snapshot=False)
        assert node.messages_snapshot is None
        await sqlite_backend.save_node(node)

        loaded = await sqlite_backend.load_node(node.id)
        assert loaded is not None
        assert loaded.messages_snapshot is None


# ----------------------------------------------------------------
# TestSqliteBackendChain — 链操作测试
# ----------------------------------------------------------------


class TestSqliteBackendChain:
    """SqliteBackend 链操作测试。"""

    @pytest.mark.asyncio
    async def test_load_chain_ordered(self, sqlite_backend: SqliteBackend) -> None:
        node0 = make_node(iteration=0, agent_name="chain-agent")
        node2 = make_node(
            iteration=2,
            parent_id=node0.id,
            agent_name="chain-agent",
        )
        node1 = make_node(
            iteration=1,
            parent_id=node0.id,
            agent_name="chain-agent",
        )

        await sqlite_backend.save_node(node2)
        await sqlite_backend.save_node(node0)
        await sqlite_backend.save_node(node1)

        chain = await sqlite_backend.load_chain("chain-agent")
        assert len(chain) == 3
        assert chain[0].iteration == 0
        assert chain[1].iteration == 1
        assert chain[2].iteration == 2

    @pytest.mark.asyncio
    async def test_load_chain_empty(self, sqlite_backend: SqliteBackend) -> None:
        chain = await sqlite_backend.load_chain("nonexistent-agent")
        assert chain == []


# ----------------------------------------------------------------
# TestSqliteBackendChainMeta — 链元信息测试
# ----------------------------------------------------------------


class TestSqliteBackendChainMeta:
    """SqliteBackend 链元信息测试。"""

    @pytest.mark.asyncio
    async def test_save_and_load_chain_meta(self, sqlite_backend: SqliteBackend) -> None:
        branches = {"main": "node-abc", "feature": "node-def"}
        current_state = {"status": "running", "count": 5}

        await sqlite_backend.save_chain_meta("test-agent", branches, current_state)
        result = await sqlite_backend.load_chain_meta("test-agent")

        assert result is not None
        loaded_branches, loaded_session_id, loaded_state = result
        assert loaded_branches == branches
        assert loaded_state == current_state

    @pytest.mark.asyncio
    async def test_load_nonexistent_chain_meta(self, sqlite_backend: SqliteBackend) -> None:
        result = await sqlite_backend.load_chain_meta("nonexistent-agent")
        assert result is None

    @pytest.mark.asyncio
    async def test_update_chain_meta(self, sqlite_backend: SqliteBackend) -> None:
        await sqlite_backend.save_chain_meta("test-agent", {"main": "node-1"}, {"step": 1})
        await sqlite_backend.save_chain_meta(
            "test-agent", {"main": "node-2", "dev": "node-3"}, {"step": 2}
        )

        result = await sqlite_backend.load_chain_meta("test-agent")
        assert result is not None
        branches, _, state = result
        assert branches == {"main": "node-2", "dev": "node-3"}
        assert state == {"step": 2}


# ----------------------------------------------------------------
# TestSqliteBackendMessages — 消息操作测试
# ----------------------------------------------------------------


class TestSqliteBackendMessages:
    """SqliteBackend 消息操作测试。"""

    @pytest.mark.asyncio
    async def test_save_and_load_messages(self, sqlite_backend: SqliteBackend) -> None:
        messages = [
            ChatMessage.system(text="system"),
            ChatMessage.user(text_or_blocks="hello"),
            ChatMessage.ai(text="world"),
        ]

        await sqlite_backend.save_messages("test-agent", messages)
        loaded = await sqlite_backend.load_messages("test-agent")

        assert len(loaded) == 3
        assert loaded[0].role == "system"
        assert loaded[1].role == "user"
        assert loaded[2].role == "ai"

    @pytest.mark.asyncio
    async def test_load_nonexistent_messages(self, sqlite_backend: SqliteBackend) -> None:
        result = await sqlite_backend.load_messages("nonexistent-agent")
        assert result == []

    @pytest.mark.asyncio
    async def test_update_messages(self, sqlite_backend: SqliteBackend) -> None:
        messages_v1 = [ChatMessage.user(text_or_blocks="v1")]
        await sqlite_backend.save_messages("test-agent", messages_v1)

        messages_v2 = [ChatMessage.user(text_or_blocks="v2"), ChatMessage.ai(text="response")]
        await sqlite_backend.save_messages("test-agent", messages_v2)

        loaded = await sqlite_backend.load_messages("test-agent")
        assert len(loaded) == 2
        assert loaded[0].text == "v2"


# ----------------------------------------------------------------
# TestSqliteBackendDeleteAndList — 删除和列表测试
# ----------------------------------------------------------------


class TestSqliteBackendDeleteAndList:
    """SqliteBackend 删除和列表测试。"""

    @pytest.mark.asyncio
    async def test_delete_chain(self, sqlite_backend: SqliteBackend) -> None:
        node = make_node(agent_name="delete-agent")
        await sqlite_backend.save_node(node)
        await sqlite_backend.save_chain_meta("delete-agent", {"main": node.id}, {"step": 1})
        await sqlite_backend.save_messages("delete-agent", [ChatMessage.user(text_or_blocks="hi")])

        await sqlite_backend.delete_chain("delete-agent")

        assert await sqlite_backend.load_node(node.id) is None
        assert await sqlite_backend.load_chain_meta("delete-agent") is None
        assert await sqlite_backend.load_messages("delete-agent") == []

    @pytest.mark.asyncio
    async def test_list_agents(self, sqlite_backend: SqliteBackend) -> None:
        node1 = make_node(agent_name="agent-alpha")
        node2 = make_node(agent_name="agent-beta")

        await sqlite_backend.save_node(node1)
        await sqlite_backend.save_node(node2)

        agents = await sqlite_backend.list_agents()
        assert "agent-alpha" in agents
        assert "agent-beta" in agents

    @pytest.mark.asyncio
    async def test_list_agents_empty(self, sqlite_backend: SqliteBackend) -> None:
        agents = await sqlite_backend.list_agents()
        assert agents == []


# ----------------------------------------------------------------
# TestSqliteBackendBatch — 批量操作测试
# ----------------------------------------------------------------


class TestSqliteBackendBatch:
    """SqliteBackend 批量操作测试。"""

    @pytest.mark.asyncio
    async def test_save_nodes_batch(self, sqlite_backend: SqliteBackend) -> None:
        nodes = [make_node(iteration=i, agent_name="batch-agent") for i in range(5)]
        await sqlite_backend.save_nodes_batch(nodes)

        chain = await sqlite_backend.load_chain("batch-agent")
        assert len(chain) == 5

    @pytest.mark.asyncio
    async def test_save_nodes_batch_empty(self, sqlite_backend: SqliteBackend) -> None:
        await sqlite_backend.save_nodes_batch([])


# ----------------------------------------------------------------
# TestSqliteBackendMultiAgent — 多 Agent 隔离测试
# ----------------------------------------------------------------


class TestSqliteBackendMultiAgent:
    """SqliteBackend 多 Agent 数据隔离测试。"""

    @pytest.mark.asyncio
    async def test_agent_isolation(self, sqlite_backend: SqliteBackend) -> None:
        node_a = make_node(agent_name="agent-a", iteration=0)
        node_b = make_node(agent_name="agent-b", iteration=0)

        await sqlite_backend.save_node(node_a)
        await sqlite_backend.save_node(node_b)

        chain_a = await sqlite_backend.load_chain("agent-a")
        chain_b = await sqlite_backend.load_chain("agent-b")

        assert len(chain_a) == 1
        assert len(chain_b) == 1
        assert chain_a[0].agent_name == "agent-a"
        assert chain_b[0].agent_name == "agent-b"

    @pytest.mark.asyncio
    async def test_delete_one_agent_preserves_other(self, sqlite_backend: SqliteBackend) -> None:
        node_a = make_node(agent_name="agent-a")
        node_b = make_node(agent_name="agent-b")

        await sqlite_backend.save_node(node_a)
        await sqlite_backend.save_node(node_b)

        await sqlite_backend.delete_chain("agent-a")

        loaded = await sqlite_backend.load_node(node_b.id)
        assert loaded is not None
        assert loaded.agent_name == "agent-b"

        assert await sqlite_backend.load_node(node_a.id) is None


# ----------------------------------------------------------------
# TestSqliteBackendConfig — ContextConfig 集成测试
# ----------------------------------------------------------------


class TestSqliteBackendConfig:
    """ContextConfig 创建 SqliteBackend 的集成测试。"""

    def test_create_sqlite_backend(self, tmp_path: Path) -> None:
        from ghrah.core.config import ContextConfig

        config = ContextConfig(
            persistence_type="sqlite",
            persistence_root_dir=str(tmp_path),
            persistence_run_id="config-test",
        )
        backend = config.create_persistence()
        assert isinstance(backend, SqliteBackend)
        assert backend.run_id == "config-test"

    def test_create_sqlite_backend_default_path(self) -> None:
        from ghrah.core.config import ContextConfig

        config = ContextConfig(
            persistence_type="sqlite",
            persistence_run_id="default-path-test",
        )
        backend = config.create_persistence()
        assert isinstance(backend, SqliteBackend)
        assert "ghrah.db" in str(backend.db_path)

    def test_unsupported_persistence_type(self) -> None:
        from ghrah.core.config import ContextConfig

        config = ContextConfig(persistence_type="redis")
        with pytest.raises(ValueError, match="Unsupported persistence_type"):
            config.create_persistence()
