# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""AgentRegistry 单元测试。"""

from unittest.mock import MagicMock

import pytest

from ghrah.communication.registry import AgentInfo, AgentRegistry
from ghrah.core.config import AgentConfig
from ghrah.core.exceptions import AgentNotFoundError, RegistryError


@pytest.fixture
def registry() -> AgentRegistry:
    """创建空的 AgentRegistry 实例。"""
    return AgentRegistry()


@pytest.fixture
def mock_handle() -> MagicMock:
    """创建 mock actor handle。"""
    return MagicMock()


class TestAgentRegistry:
    """AgentRegistry 测试套件。"""

    def test_register_success(
        self, registry: AgentRegistry, sample_config: AgentConfig, mock_handle: MagicMock
    ) -> None:
        """成功注册 Agent。"""
        registry.register("test-agent", sample_config, mock_handle)

        assert registry.exists("test-agent")
        assert len(registry) == 1

    def test_register_duplicate_raises(
        self, registry: AgentRegistry, sample_config: AgentConfig, mock_handle: MagicMock
    ) -> None:
        """重复注册同名 Agent 抛出 RegistryError。"""
        registry.register("test-agent", sample_config, mock_handle)

        with pytest.raises(RegistryError, match="already registered"):
            registry.register("test-agent", sample_config, mock_handle)

    def test_unregister_success(
        self, registry: AgentRegistry, sample_config: AgentConfig, mock_handle: MagicMock
    ) -> None:
        """成功注销 Agent。"""
        registry.register("test-agent", sample_config, mock_handle)
        registry.unregister("test-agent")

        assert not registry.exists("test-agent")
        assert len(registry) == 0

    def test_unregister_not_found_raises(self, registry: AgentRegistry) -> None:
        """注销未注册的 Agent 抛出 AgentNotFoundError。"""
        with pytest.raises(AgentNotFoundError, match="nonexistent"):
            registry.unregister("nonexistent")

    def test_get_handle(
        self, registry: AgentRegistry, sample_config: AgentConfig, mock_handle: MagicMock
    ) -> None:
        """获取 Agent handle。"""
        registry.register("test-agent", sample_config, mock_handle)

        handle = registry.get_handle("test-agent")
        assert handle is mock_handle

    def test_get_handle_not_found(self, registry: AgentRegistry) -> None:
        """获取未注册 Agent 的 handle 抛出 AgentNotFoundError。"""
        with pytest.raises(AgentNotFoundError):
            registry.get_handle("nonexistent")

    def test_get_info(
        self, registry: AgentRegistry, sample_config: AgentConfig, mock_handle: MagicMock
    ) -> None:
        """获取 Agent 完整信息。"""
        registry.register("test-agent", sample_config, mock_handle)

        info = registry.get_info("test-agent")
        assert isinstance(info, AgentInfo)
        assert info.name == "test-agent"
        assert info.config is sample_config
        assert info.actor_handle is mock_handle
        assert info.created_at > 0

    def test_get_info_not_found(self, registry: AgentRegistry) -> None:
        """获取未注册 Agent 的信息抛出 AgentNotFoundError。"""
        with pytest.raises(AgentNotFoundError):
            registry.get_info("nonexistent")

    def test_list_agents(self, registry: AgentRegistry, mock_handle: MagicMock) -> None:
        """列出所有已注册 Agent。"""
        config_a = AgentConfig(name="agent-a", description="Agent A")
        config_b = AgentConfig(name="agent-b", description="Agent B")

        registry.register("agent-a", config_a, mock_handle)
        registry.register("agent-b", config_b, mock_handle)

        agents = registry.list_agents()
        assert len(agents) == 2
        names = [a.name for a in agents]
        assert "agent-a" in names
        assert "agent-b" in names

    def test_list_names(self, registry: AgentRegistry, mock_handle: MagicMock) -> None:
        """列出所有 Agent 名称。"""
        config_a = AgentConfig(name="agent-a")
        config_b = AgentConfig(name="agent-b")

        registry.register("agent-a", config_a, mock_handle)
        registry.register("agent-b", config_b, mock_handle)

        names = registry.list_names()
        assert set(names) == {"agent-a", "agent-b"}

    def test_exists(
        self, registry: AgentRegistry, sample_config: AgentConfig, mock_handle: MagicMock
    ) -> None:
        """检查 Agent 是否存在。"""
        assert not registry.exists("test-agent")

        registry.register("test-agent", sample_config, mock_handle)
        assert registry.exists("test-agent")

    def test_contains(
        self, registry: AgentRegistry, sample_config: AgentConfig, mock_handle: MagicMock
    ) -> None:
        """__contains__ 语法糖。"""
        assert "test-agent" not in registry

        registry.register("test-agent", sample_config, mock_handle)
        assert "test-agent" in registry

    def test_len(self, registry: AgentRegistry, mock_handle: MagicMock) -> None:
        """__len__ 语法糖。"""
        assert len(registry) == 0

        config_a = AgentConfig(name="agent-a")
        config_b = AgentConfig(name="agent-b")
        registry.register("agent-a", config_a, mock_handle)
        assert len(registry) == 1

        registry.register("agent-b", config_b, mock_handle)
        assert len(registry) == 2

        registry.unregister("agent-a")
        assert len(registry) == 1


class TestAgentInfo:
    """AgentInfo 数据类测试。"""

    def test_to_dict(self, sample_config: AgentConfig, mock_handle: MagicMock) -> None:
        """to_dict 返回可序列化的字典。"""
        info = AgentInfo(
            name="test-agent",
            config=sample_config,
            actor_handle=mock_handle,
        )
        d = info.to_dict()
        assert d["name"] == "test-agent"
        assert d["description"] == "Test agent"
        assert "created_at" in d
        # 不应包含 actor_handle（不可序列化）
        assert "actor_handle" not in d
