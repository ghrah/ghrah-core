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
    async def test_execute_ability_emits_ability_result(self, unit: CoreUnit, ctx: FakeCtx) -> None:
        assert unit.supervisor is not None
        await unit.supervisor.spawn_agent(AgentConfig(name="agent-1"), abilities=[MockAbility()])

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
    async def test_stop_clears_agents_and_idempotent(self, unit: CoreUnit, ctx: FakeCtx) -> None:
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
        publisher = UnitEventPublisher(emit=lambda name, payload: emitted.append((name, payload)))
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


# ----------------------------------------------------------------
# j. per-agent 注入（聚合裁决 D-B/D-D：sandbox / persistence_factory /
#    HITL 运行时覆盖层 / Fork 上下文连续）
# ----------------------------------------------------------------


class FakeCommandRunner:
    """SandboxExecutor duck-type stub（记录命令）。"""

    def __init__(self) -> None:
        self.commands: list[str] = []

    async def run_command(
        self, command: str, *, cwd: str | None = None, timeout: float | None = None
    ) -> Any:
        self.commands.append(command)
        return {"returncode": 0, "stdout": "", "stderr": ""}


class FakePersistenceBackend:
    """PersistenceBackend duck-type stub（记录 save 调用）。"""

    def __init__(self, tag: str) -> None:
        self.tag = tag
        self.saved: list[Any] = []

    async def connect(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def save_node(self, node: Any) -> None:
        self.saved.append(node)

    async def load_chain(self, agent_name: str) -> list[Any]:
        return []

    async def load_chain_meta(self, agent_name: str) -> Any:
        return None


def _ability_def(ability_type: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"ability_type": ability_type, "params": params or {}}


def _spawn_payload_with_abilities(name: str, abilities: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "config": {"name": name, "system_prompt": "You are a test agent."},
        "abilities": abilities,
    }


def _actor_of(unit: CoreUnit, name: str) -> Any:
    assert unit.supervisor is not None
    return unit.supervisor._registry.get_info(name).actor_handle


class TestPerAgentInjection:
    async def test_sandbox_command_runner_injected_into_execute_command(self, ctx: FakeCtx) -> None:
        runner = FakeCommandRunner()
        unit = create_core_unit(CoreUnitConfig(command_runner=runner))
        await unit.init(ctx)

        result = await unit.handle_command(
            "spawn_agent",
            _spawn_payload_with_abilities(
                "sandboxed", [_ability_def("execute_command", {"require_approval": False})]
            ),
            None,
        )
        assert result["success"] is True

        actor = _actor_of(unit, "sandboxed")
        ability = actor._abilities["execute_command"]
        assert ability._command_runner is runner

    async def test_no_command_runner_keeps_standalone_subprocess_mode(self, unit: CoreUnit) -> None:
        result = await unit.handle_command(
            "spawn_agent",
            _spawn_payload_with_abilities("plain", [_ability_def("execute_command")]),
            None,
        )
        assert result["success"] is True

        actor = _actor_of(unit, "plain")
        ability = actor._abilities["execute_command"]
        assert ability._command_runner is None

    async def test_persistence_factory_reaches_agent_context_manager(self, ctx: FakeCtx) -> None:
        backend = FakePersistenceBackend(tag="custom")
        calls: list[str] = []

        def factory(config: Any) -> FakePersistenceBackend:
            calls.append(config.name)
            return backend

        unit = create_core_unit(CoreUnitConfig(persistence_factory=factory))
        await unit.init(ctx)

        result = await unit.handle_command("spawn_agent", _spawn_payload("persisted"), None)
        assert result["success"] is True
        assert calls == ["persisted"]

        actor = _actor_of(unit, "persisted")
        assert actor._context_manager.persistence is backend

    async def test_default_persistence_untouched_without_factory(self, unit: CoreUnit) -> None:
        result = await unit.handle_command("spawn_agent", _spawn_payload("default-p"), None)
        assert result["success"] is True
        actor = _actor_of(unit, "default-p")
        # 无 context 配置 → 默认 persistence 为 None（AgentBuilder 现状）
        assert actor._context_manager.persistence is None


class TestHITLRuntimeOverride:
    """HITL 运行时覆盖层（语义平移自 subject 侧旧 HITLPolicy）。"""

    async def test_auto_approve_overrides_manifest_require_hitl(self, ctx: FakeCtx) -> None:
        unit = create_core_unit(CoreUnitConfig(auto_approve_abilities=("execute_command",)))
        await unit.init(ctx)

        result = await unit.handle_command(
            "spawn_agent",
            _spawn_payload_with_abilities(
                "auto", [_ability_def("execute_command", {"require_approval": True})]
            ),
            None,
        )
        assert result["success"] is True
        checker = _actor_of(unit, "auto")._abilities["execute_command"]._checker
        assert checker._require_approval is False

    async def test_manifest_require_hitl_respected_without_override(self, unit: CoreUnit) -> None:
        result = await unit.handle_command(
            "spawn_agent",
            _spawn_payload_with_abilities(
                "strict", [_ability_def("execute_command", {"require_approval": True})]
            ),
            None,
        )
        assert result["success"] is True
        checker = _actor_of(unit, "strict")._abilities["execute_command"]._checker
        assert checker._require_approval is True

    async def test_fallback_default_when_manifest_silent(self, ctx: FakeCtx) -> None:
        unit = create_core_unit(CoreUnitConfig(require_approval_by_default=False))
        await unit.init(ctx)

        result = await unit.handle_command(
            "spawn_agent",
            _spawn_payload_with_abilities("loose", [_ability_def("execute_command")]),
            None,
        )
        assert result["success"] is True
        checker = _actor_of(unit, "loose")._abilities["execute_command"]._checker
        assert checker._require_approval is False

    async def test_fs_ability_require_hitl_fallback(self, ctx: FakeCtx) -> None:
        """FS 能力 manifest 未声明 require_hitl → 兜底默认覆盖（旧默认恒 True）。"""
        unit = create_core_unit(CoreUnitConfig(require_approval_by_default=False))
        await unit.init(ctx)

        result = await unit.handle_command(
            "spawn_agent",
            _spawn_payload_with_abilities(
                "fs-loose", [_ability_def("read_file", {"workspace_root": "/tmp"})]
            ),
            None,
        )
        assert result["success"] is True
        checker = _actor_of(unit, "fs-loose")._abilities["read_file"]._checker
        assert checker._require_approval is False


class TestForkContextContinuity:
    """Fork 场景验证（补遗 §四）：换实现不丢上下文。"""

    async def test_per_agent_backend_swap_and_rebase_context(self, tmp_path: Any) -> None:
        """换持久化后端 = 新 spawn 注入新 factory；Fork = 上下文继承（正交）。"""
        from ghrah.context.manager import ContextManager
        from ghrah.context.persistence.sqlite_backend import SqliteBackend
        from ghrah.context.rebase import create_rebased_context

        # Agent A：真实 sqlite 后端，产生链
        backend_a = SqliteBackend(db_path=tmp_path / "a.db", run_id="run-a")
        await backend_a.connect()
        from ghrah.chat.factory import ChatMessageFactory

        cm_a = ContextManager(
            agent_name="agent-a",
            persistence=backend_a,
            auto_persist=True,
            message_factory=ChatMessageFactory(),
        )
        for step in (1, 2):
            cm_a.begin_iteration()
            cm_a.add_messages([type("M", (), {"role": "assistant", "content": f"step {step}"})()])
            cm_a.commit_iteration(ability_names=[], action_results=[])
        head_a = cm_a.chain.active_head
        assert head_a is not None

        # per-agent 注入：新 spawn agent B 用 memory fake 后端（factory 生效证明）
        backend_b = FakePersistenceBackend(tag="memory")
        actor_b_cm_factory_calls: list[str] = []

        def factory_b(config: Any) -> FakePersistenceBackend:
            actor_b_cm_factory_calls.append(config.name)
            return backend_b

        unit = create_core_unit(CoreUnitConfig(persistence_factory=factory_b))
        await unit.init(FakeCtx())
        result = await unit.handle_command("spawn_agent", _spawn_payload("agent-b"), None)
        assert result["success"] is True
        cm_b = _actor_of(unit, "agent-b")._context_manager
        assert cm_b.persistence is backend_b
        assert actor_b_cm_factory_calls == ["agent-b"]

        # Fork：从 A 链头 rebase 出新 CM——上下文连续（链头记 rebase 元数据）
        rebased = create_rebased_context(
            source_cm=cm_a, agent_name="agent-c", system_prompt="rebased"
        )
        rebased_head = rebased.chain.active_head
        assert rebased_head is not None
        assert rebased_head.metadata["rebase_from_agent"] == "agent-a"
        assert rebased_head.metadata["rebase_from_node_id"] == head_a.id
        # 继承 A 的消息（2 条 thought），过滤 system
        assert len(rebased.message_store.current_messages) >= 2
        await backend_a.close()

    async def test_strategy_swap_via_new_config_keeps_fork_lineage(self, ctx: FakeCtx) -> None:
        """换 HITL 策略 = 新 CoreUnitConfig spawn 新 agent（fork 链可接续）。"""
        from ghrah.context.rebase import create_rebased_context

        # 旧策略 agent（严格）
        unit_strict = create_core_unit(CoreUnitConfig())
        await unit_strict.init(ctx)
        await unit_strict.handle_command("spawn_agent", _spawn_payload("old-agent"), None)
        cm_old = _actor_of(unit_strict, "old-agent")._context_manager
        cm_old.begin_iteration()
        cm_old.add_messages([type("M", (), {"role": "assistant", "content": "legacy work"})()])
        cm_old.commit_iteration(ability_names=[], action_results=[])
        head = cm_old.chain.active_head
        assert head is not None

        # 新策略 unit（宽松）spawn agent-c，fork 自 old-agent 链头
        unit_loose = create_core_unit(
            CoreUnitConfig(require_approval_by_default=False, cluster_id="policy-v2")
        )
        await unit_loose.init(FakeCtx())
        await unit_loose.handle_command("spawn_agent", _spawn_payload("new-agent"), None)

        rebased = create_rebased_context(
            source_cm=cm_old, agent_name="new-agent-fork", system_prompt="v2"
        )
        assert rebased.chain.active_head is not None
        assert rebased.chain.active_head.metadata["rebase_from_agent"] == "old-agent"
        # 新策略对新 spawn 生效（旧 unit 不受影响）
        checker_loose = unit_loose._config.require_approval_by_default
        checker_strict = unit_strict._config.require_approval_by_default
        assert checker_loose is False and checker_strict is True
