# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""HITLFutureStore 和 HITL 结果接收机制测试。

测试 HITL Future 存储的核心功能：
- 创建/解析/取消 Future
- 重复创建处理
- 不存在的 Future 处理
- Agent 的 receive_hitl_response 方法
"""

import pytest

from ghrah.core.hitl import HITLFutureStore, HITLResult


class TestHITLResult:
    """HITLResult 数据类测试。"""

    def test_approved_result(self) -> None:
        """测试批准结果。"""
        result = HITLResult(approved=True)
        assert result.approved is True
        assert result.result is None

    def test_rejected_result(self) -> None:
        """测试拒绝结果。"""
        result = HITLResult(approved=False, result="Permission denied")
        assert result.approved is False
        assert result.result == "Permission denied"

    def test_result_with_data(self) -> None:
        """测试带附加数据的结果。"""
        result = HITLResult(approved=True, result={"modified_path": "/safe/path"})
        assert result.approved is True
        assert result.result == {"modified_path": "/safe/path"}


class TestHITLFutureStore:
    """HITLFutureStore 核心功能测试。"""

    def setup_method(self) -> None:
        """每个测试前创建新的 store。"""
        self.store = HITLFutureStore()

    @pytest.mark.asyncio
    async def test_create_and_resolve_future(self) -> None:
        """测试创建并解析 Future。"""
        future = self.store.create_future("agent-1", "write_file", "call-123")
        assert not future.done()

        result = HITLResult(approved=True)
        resolved = self.store.resolve_future("agent-1", "write_file", "call-123", result)
        assert resolved is True

        hitl_result = await future
        assert hitl_result.approved is True

    @pytest.mark.asyncio
    async def test_resolve_rejected(self) -> None:
        """测试拒绝结果的解析。"""
        future = self.store.create_future("agent-1", "write_file", "call-123")

        result = HITLResult(approved=False, result="Permission denied")
        resolved = self.store.resolve_future("agent-1", "write_file", "call-123", result)
        assert resolved is True

        hitl_result = await future
        assert hitl_result.approved is False
        assert hitl_result.result == "Permission denied"

    def test_resolve_nonexistent_future(self) -> None:
        """测试解析不存在的 Future。"""
        result = HITLResult(approved=True)
        resolved = self.store.resolve_future("nonexistent", "ability", "call", result)
        assert resolved is False

    @pytest.mark.asyncio
    async def test_resolve_already_resolved_future(self) -> None:
        """测试解析已完成的 Future。"""
        future = self.store.create_future("agent-1", "write_file", "call-123")

        result = HITLResult(approved=True)
        self.store.resolve_future("agent-1", "write_file", "call-123", result)

        # 再次解析应该返回 False
        result2 = HITLResult(approved=False)
        resolved = self.store.resolve_future("agent-1", "write_file", "call-123", result2)
        assert resolved is False

    @pytest.mark.asyncio
    async def test_create_future_replaces_existing(self) -> None:
        """测试创建 Future 时替换已存在的 Future。"""
        future1 = self.store.create_future("agent-1", "write_file", "call-123")
        future2 = self.store.create_future("agent-1", "write_file", "call-123")

        # future1 应该被取消
        assert future1.cancelled()

        # future2 应该可以正常解析
        result = HITLResult(approved=True)
        resolved = self.store.resolve_future("agent-1", "write_file", "call-123", result)
        assert resolved is True

        hitl_result = await future2
        assert hitl_result.approved is True

    @pytest.mark.asyncio
    async def test_get_future(self) -> None:
        """测试获取 Future。"""
        future = self.store.create_future("agent-1", "write_file", "call-123")

        retrieved = self.store.get_future("agent-1", "write_file", "call-123")
        assert retrieved is future

        nonexistent = self.store.get_future("nonexistent", "ability", "call")
        assert nonexistent is None

    @pytest.mark.asyncio
    async def test_cancel_future(self) -> None:
        """测试取消 Future。"""
        future = self.store.create_future("agent-1", "write_file", "call-123")
        cancelled = self.store.cancel_future("agent-1", "write_file", "call-123")
        assert cancelled is True
        assert future.cancelled()

    def test_cancel_nonexistent_future(self) -> None:
        """测试取消不存在的 Future。"""
        cancelled = self.store.cancel_future("nonexistent", "ability", "call")
        assert cancelled is False

    @pytest.mark.asyncio
    async def test_cancel_all(self) -> None:
        """测试取消所有 Future。"""
        self.store.create_future("agent-1", "write_file", "call-1")
        self.store.create_future("agent-1", "edit_file", "call-2")
        self.store.create_future("agent-2", "write_file", "call-3")

        self.store.cancel_all()

        pending = self.store.list_pending()
        assert len(pending) == 0

    @pytest.mark.asyncio
    async def test_cancel_all_for_agent(self) -> None:
        """测试取消指定 Agent 的所有 Future。"""
        self.store.create_future("agent-1", "write_file", "call-1")
        self.store.create_future("agent-1", "edit_file", "call-2")
        self.store.create_future("agent-2", "write_file", "call-3")

        self.store.cancel_all(agent_name="agent-1")

        # agent-1 的 Future 应该被取消
        assert self.store.get_future("agent-1", "write_file", "call-1") is None
        assert self.store.get_future("agent-1", "edit_file", "call-2") is None

        # agent-2 的 Future 应该还在
        assert self.store.get_future("agent-2", "write_file", "call-3") is not None

    @pytest.mark.asyncio
    async def test_list_pending(self) -> None:
        """测试列出等待中的 Future。"""
        self.store.create_future("agent-1", "write_file", "call-1")
        self.store.create_future("agent-1", "edit_file", "call-2")
        self.store.create_future("agent-2", "write_file", "call-3")

        all_pending = self.store.list_pending()
        assert len(all_pending) == 3

        agent1_pending = self.store.list_pending(agent_name="agent-1")
        assert len(agent1_pending) == 2

        agent2_pending = self.store.list_pending(agent_name="agent-2")
        assert len(agent2_pending) == 1

    @pytest.mark.asyncio
    async def test_multiple_agents_independent(self) -> None:
        """测试多个 Agent 的 Future 相互独立。"""
        future1 = self.store.create_future("agent-1", "write_file", "call-1")
        future2 = self.store.create_future("agent-2", "write_file", "call-2")

        # 解析 agent-1 的 Future
        result1 = HITLResult(approved=True)
        self.store.resolve_future("agent-1", "write_file", "call-1", result1)

        # agent-2 的 Future 应该还在等待
        assert not future2.done()

        # 解析 agent-2 的 Future
        result2 = HITLResult(approved=False, result="Denied")
        self.store.resolve_future("agent-2", "write_file", "call-2", result2)

        hitl_result1 = await future1
        assert hitl_result1.approved is True

        hitl_result2 = await future2
        assert hitl_result2.approved is False
