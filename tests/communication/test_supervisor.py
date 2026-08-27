# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""SupervisorActor 单元测试。

通过 mock actor handle 和 ActorAgent 来测试 Supervisor 的逻辑。
直接实例化 SupervisorActor。
"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from ghrah.communication.errors import AgentNotFoundError, RegistryError
from ghrah.communication.supervisor import SupervisorActor
from ghrah.context.manager import ContextManager
from ghrah.context.persistence.memory import InMemoryBackend
from ghrah.core.config import AgentConfig


@pytest.fixture
def supervisor() -> SupervisorActor:
    """创建 SupervisorActor 实例（直接实例化）。"""
    sv = SupervisorActor()
    return sv


class TestSupervisorActor:
    """SupervisorActor 测试套件。"""

    @pytest.mark.asyncio
    async def test_list_agents_empty(self, supervisor: SupervisorActor) -> None:
        """空 Supervisor 列出 Agent。"""
        agents = await supervisor.list_agents()
        assert agents == []

    @pytest.mark.asyncio
    async def test_health_check_empty(self, supervisor: SupervisorActor) -> None:
        """空 Supervisor 健康检查。"""
        health = await supervisor.health_check()
        assert health == {}

    @pytest.mark.asyncio
    async def test_send_agent_not_found(self, supervisor: SupervisorActor) -> None:
        """发送消息到不存在的 Agent 抛出 AgentNotFoundError。"""
        with pytest.raises(AgentNotFoundError, match="nonexistent"):
            await supervisor.send("nonexistent", "Hello")

    @pytest.mark.asyncio
    async def test_delegate_agent_not_found(self, supervisor: SupervisorActor) -> None:
        """委托到不存在的 Agent 抛出 AgentNotFoundError。"""
        with pytest.raises(AgentNotFoundError, match="agent-a"):
            await supervisor.delegate("agent-a", "agent-b", "Do something")

    @pytest.mark.asyncio
    async def test_broadcast_empty(self, supervisor: SupervisorActor) -> None:
        """空 Supervisor 广播返回空列表。"""
        responses = await supervisor.broadcast("Hello everyone")
        assert responses == []

    @pytest.mark.asyncio
    async def test_spawn_duplicate_raises(
        self, supervisor: SupervisorActor, sample_config: AgentConfig
    ) -> None:
        """重复 spawn 同名 Agent 抛出 RegistryError。"""
        # 手动注册一个 Agent（直接操作注册表）
        mock_handle = MagicMock()
        supervisor._registry.register("test-agent", sample_config, mock_handle)

        with pytest.raises(RegistryError, match="already registered"):
            await supervisor.spawn_agent(sample_config)

    @pytest.mark.asyncio
    async def test_terminate_agent(self, supervisor: SupervisorActor) -> None:
        """终止已注册的 Agent。"""
        config = AgentConfig(name="to-terminate")
        mock_handle = MagicMock()
        supervisor._registry.register("to-terminate", config, mock_handle)

        assert supervisor._registry.exists("to-terminate")

        await supervisor.terminate_agent("to-terminate")

        assert not supervisor._registry.exists("to-terminate")

    @pytest.mark.asyncio
    async def test_terminate_not_found(self, supervisor: SupervisorActor) -> None:
        """终止未注册 Agent 抛出 AgentNotFoundError。"""
        with pytest.raises(AgentNotFoundError, match="nonexistent"):
            await supervisor.terminate_agent("nonexistent")

    @pytest.mark.asyncio
    async def test_list_agents_with_data(self, supervisor: SupervisorActor) -> None:
        """列出已注册的 Agent。"""
        config_a = AgentConfig(name="agent-a", description="Agent A")
        config_b = AgentConfig(name="agent-b", description="Agent B")

        mock_handle = MagicMock()
        supervisor._registry.register("agent-a", config_a, mock_handle)
        supervisor._registry.register("agent-b", config_b, mock_handle)

        agents = await supervisor.list_agents()
        assert len(agents) == 2

        names = {a["name"] for a in agents}
        assert names == {"agent-a", "agent-b"}

    @pytest.mark.asyncio
    async def test_health_check_healthy(self, supervisor: SupervisorActor) -> None:
        """健康检查 - 所有 Agent 健康。"""
        config = AgentConfig(name="healthy-agent")
        mock_handle = MagicMock()

        mock_handle.get_state = MagicMock(
            return_value={"name": "healthy-agent", "initialized": True}
        )
        supervisor._registry.register("healthy-agent", config, mock_handle)

        health = await supervisor.health_check()
        assert health == {"healthy-agent": True}

    @pytest.mark.asyncio
    async def test_health_check_unhealthy(self, supervisor: SupervisorActor) -> None:
        """健康检查 - Agent 不健康。"""
        config = AgentConfig(name="sick-agent")
        mock_handle = MagicMock()

        def _fail():
            raise RuntimeError("Agent crashed")

        mock_handle.get_state = MagicMock(side_effect=_fail)
        supervisor._registry.register("sick-agent", config, mock_handle)

        health = await supervisor.health_check()
        assert health == {"sick-agent": False}

    def test_resolve_timeout_uses_agent_config(self, supervisor: SupervisorActor) -> None:
        """_resolve_timeout 使用目标 Agent 的 communication_timeout 配置。"""
        config = AgentConfig(name="slow-agent", communication_timeout=600.0)
        mock_handle = MagicMock()
        supervisor._registry.register("slow-agent", config, mock_handle)

        result = supervisor._resolve_timeout("slow-agent", None)
        assert result == 600.0

    def test_resolve_timeout_explicit_overrides_config(self, supervisor: SupervisorActor) -> None:
        """显式 timeout 参数优先于 Agent 配置。"""
        config = AgentConfig(name="slow-agent", communication_timeout=600.0)
        mock_handle = MagicMock()
        supervisor._registry.register("slow-agent", config, mock_handle)

        result = supervisor._resolve_timeout("slow-agent", -1)
        assert result == -1

    def test_resolve_timeout_fallback_to_default(self, supervisor: SupervisorActor) -> None:
        """未注册的 Agent 回退到 router 的 default_timeout。"""
        result = supervisor._resolve_timeout("nonexistent", None)
        assert result == supervisor._router._default_timeout

    def test_resolve_timeout_infinite(self, supervisor: SupervisorActor) -> None:
        """_resolve_timeout 支持 -1 表示无限等待。"""
        config = AgentConfig(name="infinite-agent", communication_timeout=-1)
        mock_handle = MagicMock()
        supervisor._registry.register("infinite-agent", config, mock_handle)

        result = supervisor._resolve_timeout("infinite-agent", None)
        assert result == -1


class TestSupervisorPersistenceRecovery:
    """spawn 必须 restore-first，且恢复失败不能注册空白 Agent。"""

    @staticmethod
    def _patch_builder(monkeypatch: pytest.MonkeyPatch) -> None:
        def build_actor(**kwargs: object) -> SimpleNamespace:
            from ghrah.chat.factory import ChatMessageFactory

            config = kwargs["config"]
            assert isinstance(config, AgentConfig)
            persistence_factory = kwargs.get("persistence_factory")
            backend = persistence_factory(config) if callable(persistence_factory) else None
            cm = ContextManager(
                agent_name=config.effective_agent_id,
                initial_state={},
                system_prompt=config.system_prompt,
                persistence=backend,
                auto_persist=backend is not None,
                message_factory=ChatMessageFactory(),
            )
            return SimpleNamespace(_context_manager=cm)

        monkeypatch.setattr(
            "ghrah.communication.supervisor.AgentBuilder.from_config",
            build_actor,
        )

    @pytest.mark.asyncio
    async def test_respawn_restores_existing_chain_without_overwrite(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._patch_builder(monkeypatch)
        backend = InMemoryBackend()
        config = AgentConfig(name="recoverable", system_prompt="stable")

        first = SupervisorActor()
        await first.spawn_agent(
            config,
            abilities=[],
            persistence_factory=lambda _: backend,
        )
        first_info = first._registry.get_info("recoverable")
        first_cm = first_info.actor_handle._context_manager
        assert first.recovery_mode("recoverable") == "initialized"

        first_cm.begin_iteration()
        first_cm.apply_state_changes({"phase": "waiting"})
        committed = first_cm.commit_iteration(ability_names=["conversation"])
        await first.terminate_agent("recoverable")

        old_node_ids = {node.id for node in await backend.load_chain("recoverable")}
        assert committed.id in old_node_ids

        restarted = SupervisorActor()
        await restarted.spawn_agent(
            config,
            abilities=[],
            persistence_factory=lambda _: backend,
        )
        restored_cm = restarted._registry.get_info("recoverable").actor_handle._context_manager

        assert restarted.recovery_mode("recoverable") == "restored"
        assert restored_cm.chain.active_head is not None
        assert restored_cm.chain.active_head.id == committed.id
        assert restored_cm.get_current_state() == {"phase": "waiting"}
        assert old_node_ids.issubset(
            {node.id for node in await backend.load_chain("recoverable")}
        )
        await restarted.terminate_agent("recoverable")

    @pytest.mark.asyncio
    async def test_corrupt_snapshot_fails_closed_without_overwrite(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._patch_builder(monkeypatch)
        backend = InMemoryBackend()
        await backend.save_chain_meta(
            "broken",
            branches={"main": "missing-node"},
            current_state={"sentinel": True},
        )
        supervisor = SupervisorActor()

        with pytest.raises(RegistryError, match="persistence recovery failed"):
            await supervisor.spawn_agent(
                AgentConfig(name="broken"),
                abilities=[],
                persistence_factory=lambda _: backend,
            )

        assert not supervisor._registry.exists("broken")
        meta = await backend.load_chain_meta("broken")
        assert meta is not None
        assert meta[2] == {"sentinel": True}

    @pytest.mark.asyncio
    async def test_restore_first_across_fresh_sqlite_backends(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from ghrah.context.persistence.sqlite_backend import SqliteBackend

        self._patch_builder(monkeypatch)
        db_path = tmp_path / "action-chains.sqlite3"
        config = AgentConfig(name="sqlite-agent")

        first = SupervisorActor()
        await first.spawn_agent(
            config,
            abilities=[],
            persistence_factory=lambda _: SqliteBackend(db_path=db_path, run_id="run-1"),
        )
        first_cm = first._registry.get_info("sqlite-agent").actor_handle._context_manager
        first_cm.begin_iteration()
        first_cm.apply_state_changes({"checkpoint": 1})
        committed = first_cm.commit_iteration(ability_names=["conversation"])
        await first.terminate_agent("sqlite-agent")

        restarted = SupervisorActor()
        await restarted.spawn_agent(
            config,
            abilities=[],
            persistence_factory=lambda _: SqliteBackend(db_path=db_path, run_id="run-2"),
        )
        restored_cm = restarted._registry.get_info("sqlite-agent").actor_handle._context_manager

        assert restarted.recovery_mode("sqlite-agent") == "restored"
        assert restored_cm.chain.active_head is not None
        assert restored_cm.chain.active_head.id == committed.id
        assert restored_cm.get_current_state() == {"checkpoint": 1}
        await restarted.terminate_agent("sqlite-agent")
