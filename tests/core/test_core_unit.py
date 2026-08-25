# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""CoreUnit 挂载形态测试。

不 import ouroboros：FakeCtx 为纯 duck-typed stub，模拟 subject 侧
mount_unit 桥契约中 ctx 的 emit/provide/get/on/serial 形状。
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from ghrah.protocol.types import CommandType, EventType

from ghrah.abilities.base import Ability
from ghrah.abilities.context import AbilityExecutionContext
from ghrah.abilities.hooks import Hook, HookPoint, HookResult
from ghrah.core.events import HITLRequestEvent
from ghrah.core.unit import (
    CoreUnit,
    CoreUnitConfig,
    UnitEventPublisher,
    create_core_unit,
)
from ghrah.types.config_types import AgentConfig
from ghrah.types.results import ActionOutcome, ActionResult

# ----------------------------------------------------------------
# 测试辅助
# ----------------------------------------------------------------


class FakeCtx:
    """宿主上下文 stub — 模拟 Ouroboros Context 的 duck-type 形状。"""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []
        self.services: dict[str, Any] = {}
        self._handlers: dict[str, Any] = {}

    def emit(self, name: str, payload: dict[str, Any]) -> None:
        self.events.append((name, payload))

    def provide(self, name: str, value: Any) -> None:
        self.services[name] = value

    def get(self, name: str) -> Any:
        return self.services.get(name)

    def on(self, name: str, handler: Any) -> None:
        self._handlers[name] = handler

    async def serial(self, name: str, payload: dict[str, Any]) -> Any:
        handler = self._handlers.get(name)
        if handler is None:
            return None
        return await handler(payload)

    def event_names(self) -> list[str]:
        return [name for name, _ in self.events]


class MockAbility(Ability):
    """测试用 Ability — 返回固定成功结果，可携带 hooks。"""

    def __init__(self, name: str = "mock_ability", hooks: list[Hook] | None = None) -> None:
        self._name = name
        self._hooks = hooks or []
        self.execute_count = 0

    @property
    def name(self) -> str:
        return self._name

    async def execute(self, context: AbilityExecutionContext) -> ActionResult:
        self.execute_count += 1
        return ActionResult(
            outcome=ActionOutcome.SUCCESS,
            data={"response": "mock response"},
        )

    def get_hooks(self) -> list[Hook]:
        return self._hooks

    def bind_tool(self) -> dict[str, Any] | None:
        return None


class HITLBlockingHook(Hook):
    """PRE_EXECUTE 拦截并要求 HITL 审批的 Hook。"""

    hook_point = HookPoint.PRE_EXECUTE

    def __init__(self, target_ability: str = "mock_ability") -> None:
        self._target_ability = target_ability

    async def should_trigger(self, context: AbilityExecutionContext) -> bool:
        return context.current_ability_name == self._target_ability

    async def execute(
        self, context: AbilityExecutionContext, result: ActionResult | None
    ) -> HookResult:
        return HookResult.hitl(message="Human approval required")


@pytest.fixture
def ctx() -> FakeCtx:
    return FakeCtx()


@pytest.fixture
async def unit(ctx: FakeCtx) -> CoreUnit:
    u = create_core_unit(CoreUnitConfig())
    await u.init(ctx)
    return u


def _spawn_payload(name: str) -> dict[str, Any]:
    return {"config": {"name": name, "system_prompt": "You are a test agent."}}


# ----------------------------------------------------------------
# a. meta 形状契约
# ----------------------------------------------------------------


class TestMetaContract:
    def test_meta_shape(self) -> None:
        unit = create_core_unit(CoreUnitConfig())
        meta = unit.meta
        assert meta.name == "core"
        assert meta.requires == frozenset()
        assert {key.name for key in meta.provides} == {"supervisor", "core_registry"}
        assert meta.routes.long_running_commands == frozenset()
        assert meta.routes.events == frozenset()

    def test_meta_commands_exactly_17(self) -> None:
        unit = create_core_unit(CoreUnitConfig())
        expected = {
            CommandType.SPAWN_AGENT.value,
            CommandType.TERMINATE_AGENT.value,
            CommandType.SEND_MESSAGE.value,
            CommandType.BROADCAST_MESSAGE.value,
            CommandType.REGISTER_ABILITY.value,
            CommandType.UNREGISTER_ABILITY.value,
            CommandType.LIST_AGENTS.value,
            CommandType.HEALTH_CHECK.value,
            CommandType.DELEGATE.value,
            CommandType.GET_AGENT_INFO.value,
            CommandType.EXECUTE_ABILITY.value,
            CommandType.HITL_RESPONSE.value,
            CommandType.SESSION_CREATE.value,
            CommandType.SESSION_SWITCH.value,
            CommandType.SESSION_LIST.value,
            CommandType.SESSION_ARCHIVE.value,
            CommandType.SESSION_DELETE.value,
        }
        assert len(unit.meta.routes.commands) == 17
        assert unit.meta.routes.commands == expected


# ----------------------------------------------------------------
# b. init 服务注册
# ----------------------------------------------------------------


class TestInit:
    async def test_init_provides_services(self, unit: CoreUnit, ctx: FakeCtx) -> None:
        supervisor = ctx.get("supervisor")
        registry = ctx.get("core_registry")
        assert supervisor is not None
        assert supervisor is unit.supervisor
        assert registry is not None
        assert registry is supervisor._registry


# ----------------------------------------------------------------
# c/d. spawn / terminate 与事件
# ----------------------------------------------------------------


class TestSpawnTerminate:
    async def test_spawn_agent_visible_in_list(self, unit: CoreUnit) -> None:
        result = await unit.handle_command("spawn_agent", _spawn_payload("agent-1"), None)
        assert result["success"] is True
        assert result["data"]["name"] == "agent-1"

        assert unit.supervisor is not None
        agents = await unit.supervisor.list_agents()
        assert [a["name"] for a in agents] == ["agent-1"]

    async def test_spawn_emits_agent_spawned(self, unit: CoreUnit, ctx: FakeCtx) -> None:
        await unit.handle_command("spawn_agent", _spawn_payload("agent-1"), None)
        assert f"core:{EventType.AGENT_SPAWNED.value}" in ctx.event_names()
        name, payload = next(
            e for e in ctx.events if e[0] == f"core:{EventType.AGENT_SPAWNED.value}"
        )
        assert payload["name"] == "agent-1"

    async def test_terminate_emits_agent_terminated(self, unit: CoreUnit, ctx: FakeCtx) -> None:
        await unit.handle_command("spawn_agent", _spawn_payload("agent-1"), None)
        result = await unit.handle_command("terminate_agent", {"name": "agent-1"}, None)
        assert result["success"] is True
        assert result["data"] == {"name": "agent-1", "terminated": True}
        assert f"core:{EventType.AGENT_TERMINATED.value}" in ctx.event_names()

        assert unit.supervisor is not None
        assert await unit.supervisor.list_agents() == []

    async def test_spawn_duplicate_fails(self, unit: CoreUnit) -> None:
        await unit.handle_command("spawn_agent", _spawn_payload("agent-1"), None)
        result = await unit.handle_command("spawn_agent", _spawn_payload("agent-1"), None)
        assert result["success"] is False
        assert "already registered" in result["error"]


# ----------------------------------------------------------------
# e. execute_ability → core:ability_result
# ----------------------------------------------------------------


class TestExecuteAbility:
    async def test_execute_ability_emits_ability_result(
        self, unit: CoreUnit, ctx: FakeCtx
    ) -> None:
        assert unit.supervisor is not None
        await unit.supervisor.spawn_agent(
            AgentConfig(name="agent-1"), abilities=[MockAbility()]
        )

        result = await unit.handle_command(
            "execute_ability",
            {
                "request_id": "req-1",
                "agent_name": "agent-1",
                "ability_name": "mock_ability",
                "tool_args": {},
            },
            None,
        )
        assert result["success"] is True
        assert result["data"]["request_id"] == "req-1"
        assert result["data"]["success"] is True

        name, payload = next(
            e for e in ctx.events if e[0] == f"core:{EventType.ABILITY_RESULT.value}"
        )
        assert payload["request_id"] == "req-1"
        assert payload["agent_name"] == "agent-1"
        assert payload["ability_name"] == "mock_ability"
        assert payload["success"] is True

    async def test_execute_ability_unknown_ability(self, unit: CoreUnit) -> None:
        assert unit.supervisor is not None
        await unit.supervisor.spawn_agent(AgentConfig(name="agent-1"), abilities=[])
        result = await unit.handle_command(
            "execute_ability",
            {
                "request_id": "req-2",
                "agent_name": "agent-1",
                "ability_name": "nonexistent",
                "tool_args": {},
            },
            None,
        )
        assert result["success"] is False
        assert "nonexistent" in result["error"]


# ----------------------------------------------------------------
# f. hitl_request / hitl_response 链路
# ----------------------------------------------------------------


class TestHITL:
    async def test_hitl_roundtrip(self, unit: CoreUnit, ctx: FakeCtx) -> None:
        assert unit.supervisor is not None
        ability = MockAbility(hooks=[HITLBlockingHook()])
        await unit.supervisor.spawn_agent(AgentConfig(name="agent-1"), abilities=[ability])

        task = asyncio.create_task(
            unit.handle_command(
                "execute_ability",
                {
                    "request_id": "req-hitl",
                    "agent_name": "agent-1",
                    "ability_name": "mock_ability",
                    "tool_args": {"call_id": "call-1"},
                },
                None,
            )
        )

        # 等待 HITL future 建立
        handle = await unit.supervisor.get_agent_handle("agent-1")
        store = handle._ability_executor.hitl_store
        for _ in range(100):
            if store.list_pending():
                break
            await asyncio.sleep(0.01)
        assert store.list_pending() == [("agent-1", "mock_ability", "call-1")]

        # HITL 请求事件已上抛
        name, payload = next(
            e for e in ctx.events if e[0] == f"core:{EventType.HITL_REQUEST.value}"
        )
        assert payload["agent_name"] == "agent-1"
        assert payload["ability_name"] == "mock_ability"
        assert payload["context"]["tool_call_id"] == "call-1"

        # 审批通过 → resolve 进程内 future
        resp = await unit.handle_command(
            "hitl_response",
            {
                "agent_name": "agent-1",
                "ability_name": "mock_ability",
                "tool_call_id": "call-1",
                "approved": True,
            },
            None,
        )
        assert resp["success"] is True
        assert resp["data"]["resolved"] is True

        result = await asyncio.wait_for(task, timeout=2.0)
        assert result["success"] is True
        assert result["data"]["success"] is True
        assert ability.execute_count == 1

    async def test_hitl_response_no_pending_future(self, unit: CoreUnit) -> None:
        assert unit.supervisor is not None
        await unit.supervisor.spawn_agent(AgentConfig(name="agent-1"), abilities=[])
        resp = await unit.handle_command(
            "hitl_response",
            {
                "agent_name": "agent-1",
                "ability_name": "mock_ability",
                "tool_call_id": "call-x",
                "approved": True,
            },
            None,
        )
        assert resp["success"] is True
        assert resp["data"]["resolved"] is False

    async def test_hitl_timeout_blocks_execution(self, unit: CoreUnit, ctx: FakeCtx) -> None:
        """HITL 超时路径：future 超时 → ability 不执行 → ability_result(success=False)。"""
        assert unit.supervisor is not None
        ability = MockAbility(hooks=[HITLBlockingHook()])
        await unit.supervisor.spawn_agent(AgentConfig(name="agent-1"), abilities=[ability])

        # 缩短 HITL 等待超时（CoreUnitConfig.hitl_timeout 的 best-effort 应用
        # 仅覆盖 unit 命令面 spawn 路径，直挂 spawn 时直接调 executor 字段）
        handle = await unit.supervisor.get_agent_handle("agent-1")
        handle._ability_executor._hitl_timeout = 0.05

        result = await unit.handle_command(
            "execute_ability",
            {
                "request_id": "req-timeout",
                "agent_name": "agent-1",
                "ability_name": "mock_ability",
                "tool_args": {"call_id": "call-t"},
            },
            None,
        )
        assert ability.execute_count == 0
        assert result["success"] is True
        assert result["data"]["success"] is False
        name, payload = next(
            e for e in ctx.events if e[0] == f"core:{EventType.ABILITY_RESULT.value}"
        )
        assert payload["request_id"] == "req-timeout"
        assert payload["success"] is False

    async def test_stop_cancels_pending_hitl(self, unit: CoreUnit, ctx: FakeCtx) -> None:
        """stop() 清理路径：cancel_all 取消 pending future，在途 execute_ability 终结。"""
        assert unit.supervisor is not None
        ability = MockAbility(hooks=[HITLBlockingHook()])
        await unit.supervisor.spawn_agent(AgentConfig(name="agent-1"), abilities=[ability])

        task = asyncio.create_task(
            unit.handle_command(
                "execute_ability",
                {
                    "request_id": "req-stop",
                    "agent_name": "agent-1",
                    "ability_name": "mock_ability",
                    "tool_args": {"call_id": "call-s"},
                },
                None,
            )
        )

        handle = await unit.supervisor.get_agent_handle("agent-1")
        store = handle._ability_executor.hitl_store
        for _ in range(100):
            if store.list_pending():
                break
            await asyncio.sleep(0.01)
        assert store.list_pending() == [("agent-1", "mock_ability", "call-s")]

        await unit.stop()
        assert store.list_pending() == []

        # future 被取消 → wait_for 传播 CancelledError，在途命令任务随之终结
        # （若 handler 层捕获则为失败回执，两种终结形态均可接受）
        try:
            result = await asyncio.wait_for(task, timeout=2.0)
        except asyncio.CancelledError:
            pass
        else:
            assert result["success"] is False or result["data"]["success"] is False
        assert ability.execute_count == 0


# ----------------------------------------------------------------
# g. 回执形状
# ----------------------------------------------------------------


class TestReceiptShape:
    async def test_unknown_command(self, unit: CoreUnit) -> None:
        result = await unit.handle_command("no_such_command", {}, None)
        assert result["success"] is False
        assert "Unknown command" in result["error"]

    async def test_handler_exception_receipt(self, unit: CoreUnit) -> None:
        # terminate 不存在的 agent → AgentNotFoundError → 统一回执
        result = await unit.handle_command("terminate_agent", {"name": "ghost"}, None)
        assert result["success"] is False
        assert "ghost" in result["error"]

    async def test_invalid_payload_receipt(self, unit: CoreUnit) -> None:
        # 缺 name 字段 → model_validate 抛 ValidationError → 统一回执
        result = await unit.handle_command("terminate_agent", {}, None)
        assert result["success"] is False
        assert "error" in result

    async def test_handle_before_init(self, ctx: FakeCtx) -> None:
        unit = create_core_unit(CoreUnitConfig())
        result = await unit.handle_command("list_agents", {}, None)
        assert result["success"] is False
        assert "not initialized" in result["error"]


# ----------------------------------------------------------------
# h. stop 幂等 + agents 清空
# ----------------------------------------------------------------


class TestStop:
    async def test_stop_clears_agents_and_idempotent(
        self, unit: CoreUnit, ctx: FakeCtx
    ) -> None:
        await unit.handle_command("spawn_agent", _spawn_payload("agent-1"), None)
        await unit.handle_command("spawn_agent", _spawn_payload("agent-2"), None)

        await unit.stop()
        assert unit.supervisor is not None
        assert await unit.supervisor.list_agents() == []

        # 幂等：重复调用不抛异常
        await unit.stop()


# ----------------------------------------------------------------
# i. standalone 场景（emit=None）
# ----------------------------------------------------------------


class TestStandalone:
    async def test_null_emit_publisher_no_raise(self) -> None:
        publisher = UnitEventPublisher(emit=None)
        await publisher.publish(
            HITLRequestEvent(
                agent_name="agent-1",
                ability_name="mock_ability",
                tool_call={"call_id": "call-1"},
                context={"tool_call_id": "call-1"},
            )
        )

    async def test_publisher_payload_shape(self) -> None:
        emitted: list[tuple[str, dict[str, Any]]] = []
        publisher = UnitEventPublisher(
            emit=lambda name, payload: emitted.append((name, payload))
        )
        await publisher.publish(
            HITLRequestEvent(
                agent_name="agent-1",
                ability_name="mock_ability",
                tool_call={"call_id": "call-1"},
                context={"tool_call_id": "call-1"},
            )
        )
        assert emitted[0][0] == "core:hitl_request"
        assert emitted[0][1]["ability_name"] == "mock_ability"

    async def test_unit_without_emit_ctx(self) -> None:
        """ctx 无 emit 方法时退化为 Null 行为，不抛异常。"""

        class NoEmitCtx:
            def __init__(self) -> None:
                self.services: dict[str, Any] = {}

            def provide(self, name: str, value: Any) -> None:
                self.services[name] = value

        no_emit_ctx = NoEmitCtx()
        unit = create_core_unit(CoreUnitConfig())
        await unit.init(no_emit_ctx)
        result = await unit.handle_command("spawn_agent", _spawn_payload("agent-1"), None)
        assert result["success"] is True
        assert "supervisor" in no_emit_ctx.services
        await unit.stop()
