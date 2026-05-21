# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""RemoteBackend 测试。

测试远程持久化后端的核心功能：
- 所有 PersistenceBackend 接口方法通过 CommandSender 发送命令
- 命令格式正确性
- 错误处理
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from ghrah.chat.message import ChatMessage
from ghrah.context.persistence.remote_backend import RemoteBackend
from ghrah.core.command_sender import CommandSender

# ─── Fixtures ───


@pytest.fixture
def mock_command_sender():
    """创建 mock CommandSender。"""
    sender = AsyncMock(spec=CommandSender)
    return sender


@pytest.fixture
def remote_backend(mock_command_sender):
    """创建 RemoteBackend 实例。"""
    return RemoteBackend(
        command_sender=mock_command_sender,
        agent_name="test-agent",
        request_timeout=10.0,
    )


# ─── 测试用例 ───


class TestRemoteBackendInit:
    """RemoteBackend 初始化测试。"""

    def test_default_init(self, mock_command_sender):
        backend = RemoteBackend(command_sender=mock_command_sender)
        assert backend._agent_name == ""
        assert backend._request_timeout == 30.0

    def test_custom_init(self, mock_command_sender):
        backend = RemoteBackend(
            command_sender=mock_command_sender,
            agent_name="my-agent",
            request_timeout=15.0,
        )
        assert backend._agent_name == "my-agent"
        assert backend._request_timeout == 15.0

    def test_requires_command_sender(self):
        """测试 RemoteBackend 需要 command_sender 参数。"""
        # CommandSender 是 Protocol，Python 运行时不会强制类型检查，
        # 但传递 None 会导致后续调用 send_command 时失败。
        # 此测试验证构造函数签名要求 command_sender 参数。
        from ghrah.context.persistence.remote_backend import RemoteBackend
        assert "command_sender" in RemoteBackend.__init__.__code__.co_varnames


class TestRemoteBackendSaveNode:
    """RemoteBackend save_node 测试。"""

    @pytest.mark.asyncio
    async def test_save_node(self, remote_backend, mock_command_sender):
        """测试保存节点到远程。"""
        mock_command_sender.send_command.return_value = {"success": True}

        from ghrah.context.node import ContextNode

        node = ContextNode(
            id="node-1",
            agent_name="test-agent",
            iteration=1,
        )

        await remote_backend.save_node(node)

        mock_command_sender.send_command.assert_called_once()
        call_args = mock_command_sender.send_command.call_args
        assert call_args[0][0] == "persist_save_node"
        assert call_args[0][1]["agent_name"] == "test-agent"
        assert "node" in call_args[0][1]
        assert call_args[1]["timeout"] == 10.0


class TestRemoteBackendLoadNode:
    """RemoteBackend load_node 测试。"""

    @pytest.mark.asyncio
    async def test_load_node_exists(self, remote_backend, mock_command_sender):
        """测试加载存在的节点。"""
        from ghrah.context.node import ContextNode
        from ghrah.context.persistence.serialization import serialize_node

        node = ContextNode(
            id="node-1",
            agent_name="test-agent",
            iteration=1,
        )
        serialized = serialize_node(node)

        mock_command_sender.send_command.return_value = {
            "success": True,
            "data": {"node": serialized},
        }

        result = await remote_backend.load_node("node-1")

        mock_command_sender.send_command.assert_called_once()
        call_args = mock_command_sender.send_command.call_args
        assert call_args[0][0] == "persist_load_node"
        assert call_args[0][1]["node_id"] == "node-1"
        assert result is not None
        assert result.id == "node-1"

    @pytest.mark.asyncio
    async def test_load_node_not_exists(self, remote_backend, mock_command_sender):
        """测试加载不存在的节点。"""
        mock_command_sender.send_command.return_value = {
            "success": True,
            "data": {"node": None},
        }

        result = await remote_backend.load_node("nonexistent")
        assert result is None


class TestRemoteBackendLoadChain:
    """RemoteBackend load_chain 测试。"""

    @pytest.mark.asyncio
    async def test_load_chain(self, remote_backend, mock_command_sender):
        """测试加载链。"""
        from ghrah.context.node import ContextNode
        from ghrah.context.persistence.serialization import serialize_node

        nodes = [
            ContextNode(id="node-1", agent_name="test-agent", iteration=1),
            ContextNode(id="node-2", agent_name="test-agent", iteration=2),
        ]
        serialized_nodes = [serialize_node(n) for n in nodes]

        mock_command_sender.send_command.return_value = {
            "success": True,
            "data": {"nodes": serialized_nodes},
        }

        result = await remote_backend.load_chain("test-agent")

        mock_command_sender.send_command.assert_called_once()
        call_args = mock_command_sender.send_command.call_args
        assert call_args[0][0] == "persist_load_chain"
        assert call_args[0][1]["agent_name"] == "test-agent"
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_load_chain_empty(self, remote_backend, mock_command_sender):
        """测试加载空链。"""
        mock_command_sender.send_command.return_value = {
            "success": True,
            "data": {"nodes": []},
        }

        result = await remote_backend.load_chain("test-agent")
        assert result == []


class TestRemoteBackendChainMeta:
    """RemoteBackend save/load_chain_meta 测试。"""

    @pytest.mark.asyncio
    async def test_save_chain_meta(self, remote_backend, mock_command_sender):
        """测试保存链元信息。"""
        mock_command_sender.send_command.return_value = {"success": True}

        await remote_backend.save_chain_meta(
            "test-agent",
            {"main": "node-1"},
            {"key": "value"},
        )

        mock_command_sender.send_command.assert_called_once()
        call_args = mock_command_sender.send_command.call_args
        assert call_args[0][0] == "persist_save_chain_meta"
        assert call_args[0][1]["agent_name"] == "test-agent"
        assert call_args[0][1]["branches"] == {"main": "node-1"}
        assert call_args[0][1]["current_state"] == {"key": "value"}

    @pytest.mark.asyncio
    async def test_load_chain_meta_exists(self, remote_backend, mock_command_sender):
        """测试加载存在的链元信息。"""
        mock_command_sender.send_command.return_value = {
            "success": True,
            "data": {
                "branches": {"main": "node-1"},
                "current_state": {"key": "value"},
            },
        }

        result = await remote_backend.load_chain_meta("test-agent")

        mock_command_sender.send_command.assert_called_once()
        assert result is not None
        branches, _, state = result
        assert branches == {"main": "node-1"}
        assert state == {"key": "value"}

    @pytest.mark.asyncio
    async def test_load_chain_meta_not_exists(self, remote_backend, mock_command_sender):
        """测试加载不存在的链元信息。"""
        mock_command_sender.send_command.return_value = {
            "success": True,
            "data": None,
        }

        result = await remote_backend.load_chain_meta("test-agent")
        assert result is None


class TestRemoteBackendMessages:
    """RemoteBackend save/load_messages 测试。"""

    @pytest.mark.asyncio
    async def test_save_messages(self, remote_backend, mock_command_sender):
        """测试保存消息。"""
        mock_command_sender.send_command.return_value = {"success": True}

        messages = [
            ChatMessage.user(text_or_blocks="hello"),
            ChatMessage.ai(text="hi there"),
        ]

        await remote_backend.save_messages("test-agent", messages)

        mock_command_sender.send_command.assert_called_once()
        call_args = mock_command_sender.send_command.call_args
        assert call_args[0][0] == "persist_save_messages"
        assert call_args[0][1]["agent_name"] == "test-agent"
        assert "messages" in call_args[0][1]

    @pytest.mark.asyncio
    async def test_load_messages(self, remote_backend, mock_command_sender):
        """测试加载消息。"""
        mock_command_sender.send_command.return_value = {
            "success": True,
            "data": {"messages": []},
        }

        await remote_backend.load_messages("test-agent")

        mock_command_sender.send_command.assert_called_once()
        call_args = mock_command_sender.send_command.call_args
        assert call_args[0][0] == "persist_load_messages"
        assert call_args[0][1]["agent_name"] == "test-agent"


class TestRemoteBackendDeleteChain:
    """RemoteBackend delete_chain 测试。"""

    @pytest.mark.asyncio
    async def test_delete_chain(self, remote_backend, mock_command_sender):
        """测试删除链。"""
        mock_command_sender.send_command.return_value = {"success": True}

        await remote_backend.delete_chain("test-agent")

        mock_command_sender.send_command.assert_called_once()
        call_args = mock_command_sender.send_command.call_args
        assert call_args[0][0] == "persist_delete_chain"
        assert call_args[0][1]["agent_name"] == "test-agent"


class TestRemoteBackendListAgents:
    """RemoteBackend list_agents 测试。"""

    @pytest.mark.asyncio
    async def test_list_agents(self, remote_backend, mock_command_sender):
        """测试列出 agents。"""
        mock_command_sender.send_command.return_value = {
            "success": True,
            "data": {"agents": ["agent1", "agent2"]},
        }

        result = await remote_backend.list_agents()

        mock_command_sender.send_command.assert_called_once()
        call_args = mock_command_sender.send_command.call_args
        assert call_args[0][0] == "persist_list_agents"
        assert result == ["agent1", "agent2"]

    @pytest.mark.asyncio
    async def test_list_agents_empty(self, remote_backend, mock_command_sender):
        """测试列出空 agents。"""
        mock_command_sender.send_command.return_value = {
            "success": True,
            "data": {},
        }

        result = await remote_backend.list_agents()
        assert result == []


class TestRemoteBackendErrorResponse:
    """RemoteBackend 错误响应处理测试。"""

    @pytest.mark.asyncio
    async def test_validate_response_raises_on_failure(self, mock_command_sender):
        """测试远程返回失败响应时抛出 RuntimeError。"""
        mock_command_sender.send_command.return_value = {
            "success": False,
            "error": "node not found",
        }

        backend = RemoteBackend(command_sender=mock_command_sender, agent_name="test-agent")

        with pytest.raises(RuntimeError, match="Remote persistence 'load_node' failed"):
            await backend.load_node("nonexistent")

    @pytest.mark.asyncio
    async def test_validate_response_raises_with_message_field(self, mock_command_sender):
        """测试远程返回失败响应（使用 message 字段）时抛出 RuntimeError。"""
        mock_command_sender.send_command.return_value = {
            "success": False,
            "message": "internal error",
        }

        backend = RemoteBackend(command_sender=mock_command_sender, agent_name="test-agent")

        with pytest.raises(RuntimeError, match="Remote persistence 'save_node' failed"):
            from ghrah.context.node import ContextNode

            node = ContextNode(id="node-1", agent_name="test-agent", iteration=1)
            await backend.save_node(node)

    @pytest.mark.asyncio
    async def test_validate_response_passes_on_success(self, mock_command_sender):
        """测试远程返回成功响应时不抛出异常。"""
        mock_command_sender.send_command.return_value = {"success": True}

        backend = RemoteBackend(command_sender=mock_command_sender, agent_name="test-agent")

        from ghrah.context.node import ContextNode

        node = ContextNode(id="node-1", agent_name="test-agent", iteration=1)
        await backend.save_node(node)


class TestRemoteBackendConfigIntegration:
    """RemoteBackend 与 ContextConfig 集成测试。"""

    def test_config_remote_backend_type(self):
        """测试 ContextConfig 支持 remote 持久化类型。"""
        from ghrah.core.config import PERSISTENCE_BACKEND_TYPES

        assert "remote" in PERSISTENCE_BACKEND_TYPES

    def test_config_create_remote_backend_with_command_sender(self):
        """测试 ContextConfig 通过 set_command_sender 创建 RemoteBackend。"""
        from ghrah.core.config import ContextConfig

        config = ContextConfig(
            persistence_type="remote",
        )
        mock_command_sender = MagicMock(spec=CommandSender)
        config.set_command_sender(mock_command_sender, agent_name="test-agent")

        backend = config.create_persistence()
        assert isinstance(backend, RemoteBackend)

    def test_config_remote_backend_without_command_sender(self):
        """测试 ContextConfig 创建 RemoteBackend 时缺少 command_sender 应报错。"""
        from ghrah.core.config import ContextConfig

        config = ContextConfig(
            persistence_type="remote",
        )
        with pytest.raises(ValueError, match="command_sender is required"):
            config.create_persistence()
