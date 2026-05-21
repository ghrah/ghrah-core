# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""ManifestResolver 测试。

覆盖：
1. 完整解析流程 — builtin type 引用
2. 完整解析流程 — ref 引用
3. 权限覆盖（AbilityManifest.permissions.merge(AbilityRef.permissions)）
4. ref 引用不存在的能力 → ManifestNotFoundError
5. type 引用未注册的 builtin → ManifestValidationError
6. ContextOverrides → WindowConfig/ContextConfig 映射
7. runtime_name 覆盖
8. AbilityRegistry.register_from_resolved — builtin 验证
9. AbilityRegistry.register_from_resolved — 未注册 type 报错
10. ModelOverrides 构建（ManifestResolver._build_config）
11. WindowOverrides/PersistenceOverrides 零值正确处理（or → is not None）
"""

from __future__ import annotations

import pytest

from ghrah.abilities.registry import AbilityRegistry
from ghrah.core.config import AgentConfig
from ghrah.manifest.ability import AbilityHooks
from ghrah.manifest.agent import (
    AbilityRef,
    AgentManifest,
    AgentMetadata,
    ContextOverrides,
    ModelConfig,
    PersistenceOverrides,
    WindowOverrides,
)
from ghrah.manifest.errors import ManifestNotFoundError, ManifestValidationError
from ghrah.manifest.resolver import ManifestResolver, ResolvedAbility, ResolvedAgent
from ghrah.manifest.store import BuiltinManifestStore
from ghrah.manifest.types import ImplementationDef, PermissionFlags


def _make_agent_manifest(
    abilities: list[AbilityRef] | None = None,
    context: ContextOverrides | None = None,
    namespace: str = "test_ns",
    name: str = "test_agent",
    system_prompt: str = "You are a test agent.",
    agent_config_name: str = "gpt-4o",
    communication_timeout: float = 300.0,
) -> AgentManifest:
    """创建测试用 AgentManifest。"""
    if abilities is None:
        abilities = [AbilityRef(type="conversation")]
    return AgentManifest(
        manifest="agent",
        version="1",
        metadata=AgentMetadata(namespace=namespace, name=name, description="test"),
        model=ModelConfig(agent_config_name=agent_config_name),
        system_prompt=system_prompt,
        max_iterations=10,
        communication_timeout=communication_timeout,
        abilities=abilities,
        context=context,
    )


class TestBuiltinManifestStore:
    """BuiltinManifestStore 测试。"""

    def test_load_ability_found(self) -> None:
        store = BuiltinManifestStore()
        manifest = store.load_ability("ghrah.core.conversation")
        assert manifest.metadata.name == "conversation"
        assert manifest.implementation.type == "builtin"

    def test_load_ability_not_found(self) -> None:
        store = BuiltinManifestStore()
        with pytest.raises(ManifestNotFoundError, match="not found"):
            store.load_ability("nonexistent.ability")

    def test_list_abilities_no_filter(self) -> None:
        store = BuiltinManifestStore()
        names = store.list_abilities()
        assert len(names) == 13
        assert "ghrah.core.conversation" in names

    def test_list_abilities_with_namespace(self) -> None:
        store = BuiltinManifestStore()
        fs_abilities = store.list_abilities(namespace="ghrah.fs")
        assert len(fs_abilities) == 6
        assert all(n.startswith("ghrah.fs.") for n in fs_abilities)

    def test_list_agents_returns_empty(self) -> None:
        store = BuiltinManifestStore()
        assert store.list_agents() == []

    def test_load_agent_not_found(self) -> None:
        store = BuiltinManifestStore()
        with pytest.raises(ManifestNotFoundError):
            store.load_agent("any.agent")


class TestResolvedAbilityFromBuiltin:
    """ResolvedAbility.from_builtin 测试。"""

    def test_conversation_builtin(self) -> None:
        resolved = ResolvedAbility.from_builtin("conversation")
        assert resolved.ability_name == "ghrah.core.conversation"
        assert resolved.implementation.type == "builtin"
        assert resolved.implementation.handler == "conversation"
        assert resolved.tool_schema is None

    def test_read_file_builtin(self) -> None:
        resolved = ResolvedAbility.from_builtin("read_file")
        assert resolved.ability_name == "ghrah.fs.read_file"
        assert resolved.tool_schema is not None
        assert resolved.tool_schema.name == "read_file"
        assert resolved.permissions.fs_read_only is True

    def test_write_file_builtin(self) -> None:
        resolved = ResolvedAbility.from_builtin("write_file")
        assert resolved.ability_name == "ghrah.fs.write_file"
        assert resolved.permissions.fs_write is True
        assert resolved.permissions.require_hitl is True
        assert len(resolved.hooks.pre_execute) == 1

    def test_unknown_builtin_raises(self) -> None:
        with pytest.raises(ManifestValidationError, match="Unknown builtin"):
            ResolvedAbility.from_builtin("nonexistent_ability")


class TestManifestResolver:
    """ManifestResolver 测试。"""

    def test_resolve_builtin_type_only(self) -> None:
        store = BuiltinManifestStore()
        resolver = ManifestResolver(store)
        manifest = _make_agent_manifest(abilities=[AbilityRef(type="conversation")])
        result = resolver.resolve(manifest)

        assert isinstance(result, ResolvedAgent)
        assert isinstance(result.config, AgentConfig)
        assert result.config.name == "test_agent"
        assert result.config.agent_config_name == "gpt-4o"
        assert result.config.system_prompt == "You are a test agent."
        assert len(result.abilities) == 1
        assert result.abilities[0].ability_name == "ghrah.core.conversation"

    def test_resolve_ref_ability(self) -> None:
        store = BuiltinManifestStore()
        resolver = ManifestResolver(store)
        manifest = _make_agent_manifest(
            abilities=[AbilityRef(ref="ghrah.fs.read_file")]
        )
        result = resolver.resolve(manifest)

        assert len(result.abilities) == 1
        ability = result.abilities[0]
        assert ability.ability_name == "ghrah.fs.read_file"
        assert ability.tool_schema is not None
        assert ability.tool_schema.name == "read_file"
        assert ability.permissions.fs_read_only is True

    def test_resolve_mixed_abilities(self) -> None:
        store = BuiltinManifestStore()
        resolver = ManifestResolver(store)
        manifest = _make_agent_manifest(
            abilities=[
                AbilityRef(type="conversation"),
                AbilityRef(ref="ghrah.fs.read_file"),
            ]
        )
        result = resolver.resolve(manifest)

        assert len(result.abilities) == 2
        assert result.abilities[0].ability_name == "ghrah.core.conversation"
        assert result.abilities[1].ability_name == "ghrah.fs.read_file"

    def test_resolve_permission_override(self) -> None:
        store = BuiltinManifestStore()
        resolver = ManifestResolver(store)
        manifest = _make_agent_manifest(
            abilities=[
                AbilityRef(
                    ref="ghrah.fs.read_file",
                    permissions=PermissionFlags(require_hitl=True),
                )
            ]
        )
        result = resolver.resolve(manifest)

        ability = result.abilities[0]
        assert ability.permissions.fs_read_only is True
        assert ability.permissions.require_hitl is True

    def test_resolve_builtin_with_permission_override(self) -> None:
        store = BuiltinManifestStore()
        resolver = ManifestResolver(store)
        manifest = _make_agent_manifest(
            abilities=[
                AbilityRef(
                    type="read_file",
                    permissions=PermissionFlags(require_hitl=True),
                )
            ]
        )
        result = resolver.resolve(manifest)

        ability = result.abilities[0]
        assert ability.permissions.fs_read_only is True
        assert ability.permissions.require_hitl is True

    def test_resolve_ref_not_found_raises(self) -> None:
        store = BuiltinManifestStore()
        resolver = ManifestResolver(store)
        manifest = _make_agent_manifest(
            abilities=[AbilityRef(ref="nonexistent.ability")]
        )
        with pytest.raises(ManifestNotFoundError):
            resolver.resolve(manifest)

    def test_resolve_unknown_type_raises(self) -> None:
        store = BuiltinManifestStore()
        resolver = ManifestResolver(store)
        manifest = _make_agent_manifest(
            abilities=[AbilityRef(type="totally_unknown_ability")]
        )
        with pytest.raises(ManifestValidationError, match="Unknown builtin"):
            resolver.resolve(manifest)

    def test_resolve_context_window(self) -> None:
        store = BuiltinManifestStore()
        resolver = ManifestResolver(store)
        manifest = _make_agent_manifest(
            context=ContextOverrides(
                window=WindowOverrides(
                    max_tokens=8192,
                    strategies=["tool_call_fold", "sliding_window"],
                    tool_call_max_length=1000,
                    sliding_window_size=50,
                )
            )
        )
        result = resolver.resolve(manifest)

        assert result.config.window is not None
        assert result.config.window.max_tokens == 8192
        assert result.config.window.strategies == ["tool_call_fold", "sliding_window"]
        assert result.config.window.tool_call_max_length == 1000
        assert result.config.window.sliding_window_size == 50

    def test_resolve_context_persistence(self) -> None:
        store = BuiltinManifestStore()
        resolver = ManifestResolver(store)
        manifest = _make_agent_manifest(
            context=ContextOverrides(
                persistence=PersistenceOverrides(
                    type="json_file",
                    compress=False,
                    auto_persist=True,
                    snapshot_interval=10,
                )
            )
        )
        result = resolver.resolve(manifest)

        assert result.config.context is not None
        assert result.config.context.persistence_type == "json_file"
        assert result.config.context.persistence_compress is False
        assert result.config.context.auto_persist is True
        assert result.config.context.snapshot_interval == 10

    def test_resolve_no_context(self) -> None:
        store = BuiltinManifestStore()
        resolver = ManifestResolver(store)
        manifest = _make_agent_manifest(context=None)
        result = resolver.resolve(manifest)

        assert result.config.window is None
        assert result.config.context is None

    def test_resolve_runtime_name_override(self) -> None:
        store = BuiltinManifestStore()
        resolver = ManifestResolver(store)
        manifest = _make_agent_manifest()
        result = resolver.resolve(manifest, runtime_name="custom-agent-name")

        assert result.config.name == "custom-agent-name"

    def test_resolve_runtime_name_default(self) -> None:
        store = BuiltinManifestStore()
        resolver = ManifestResolver(store)
        manifest = _make_agent_manifest()
        result = resolver.resolve(manifest, runtime_name=None)

        assert result.config.name == "test_agent"

    


class TestAbilityRegistryRegisterFromResolved:
    """AbilityRegistry.register_from_resolved 测试。"""

    def test_builtin_validation_passes(self) -> None:
        resolved = ResolvedAbility.from_builtin("conversation")
        AbilityRegistry.register_from_resolved(resolved)

    def test_unknown_builtin_raises(self) -> None:
        resolved = ResolvedAbility(
            ability_name="test.unknown",
            tool_schema=None,
            permissions=PermissionFlags(),
            implementation=ImplementationDef(type="builtin", handler="unknown_builtin"),
            hooks=AbilityHooks(),
        )
        with pytest.raises(ManifestValidationError, match="Unknown builtin"):
            AbilityRegistry.register_from_resolved(resolved)

    def test_python_type_with_valid_module(self) -> None:
        resolved = ResolvedAbility(
            ability_name="test.python_ability",
            tool_schema=None,
            permissions=PermissionFlags(),
            implementation=ImplementationDef(
                type="python", handler="test_handler", module_ref="json"
            ),
            hooks=AbilityHooks(),
        )
        AbilityRegistry.register_from_resolved(resolved)

    def test_python_type_with_invalid_module_raises(self) -> None:
        resolved = ResolvedAbility(
            ability_name="test.python_ability",
            tool_schema=None,
            permissions=PermissionFlags(),
            implementation=ImplementationDef(
                type="python",
                handler="test_handler",
                module_ref="totally_nonexistent_module_xyz",
            ),
            hooks=AbilityHooks(),
        )
        with pytest.raises(ManifestValidationError, match="Cannot import"):
            AbilityRegistry.register_from_resolved(resolved)

    def test_sandbox_type_raises(self) -> None:
        resolved = ResolvedAbility(
            ability_name="test.sandbox_ability",
            tool_schema=None,
            permissions=PermissionFlags(),
            implementation=ImplementationDef(type="sandbox", handler="test"),
            hooks=AbilityHooks(),
        )
        with pytest.raises(ManifestValidationError, match="Unsupported"):
            AbilityRegistry.register_from_resolved(resolved)


class TestModelOverridesBuild:
    """ManifestResolver._build_config 中 ModelOverrides 构建测试。"""

    def test_model_overrides_built_from_manifest_model(self) -> None:
        store = BuiltinManifestStore()
        resolver = ManifestResolver(store)
        manifest = _make_agent_manifest()
        manifest.model = ModelConfig(
            agent_config_name="gpt-4o",
            temperature=0.5,
            max_tokens=2048,
            top_p=0.9,
            top_k=50,
        )
        result = resolver.resolve(manifest)

        assert result.config.model_overrides is not None
        assert result.config.model_overrides.temperature == 0.5
        assert result.config.model_overrides.max_tokens == 2048
        assert result.config.model_overrides.top_p == 0.9
        assert result.config.model_overrides.top_k == 50

    def test_model_overrides_none_when_no_overrides(self) -> None:
        store = BuiltinManifestStore()
        resolver = ManifestResolver(store)
        manifest = _make_agent_manifest()
        result = resolver.resolve(manifest)

        assert result.config.model_overrides is None

    def test_model_overrides_partial(self) -> None:
        store = BuiltinManifestStore()
        resolver = ManifestResolver(store)
        manifest = _make_agent_manifest()
        manifest.model = ModelConfig(
            agent_config_name="gpt-4o",
            temperature=0.3,
        )
        result = resolver.resolve(manifest)

        assert result.config.model_overrides is not None
        assert result.config.model_overrides.temperature == 0.3
        assert result.config.model_overrides.max_tokens is None
        assert result.config.model_overrides.top_p is None
        assert result.config.model_overrides.top_k is None

    def test_model_overrides_top_k_only(self) -> None:
        store = BuiltinManifestStore()
        resolver = ManifestResolver(store)
        manifest = _make_agent_manifest()
        manifest.model = ModelConfig(
            agent_config_name="gpt-4o",
            top_k=40,
        )
        result = resolver.resolve(manifest)

        assert result.config.model_overrides is not None
        assert result.config.model_overrides.top_k == 40
        assert result.config.model_overrides.temperature is None


class TestWindowConfigZeroValues:
    """WindowOverrides 零值正确处理测试（or → is not None 修复）。"""

    def test_max_tokens_zero_uses_override(self) -> None:
        store = BuiltinManifestStore()
        resolver = ManifestResolver(store)
        manifest = _make_agent_manifest(
            context=ContextOverrides(
                window=WindowOverrides(max_tokens=0)
            )
        )
        result = resolver.resolve(manifest)

        assert result.config.window is not None
        assert result.config.window.max_tokens == 0

    def test_sliding_window_size_zero_uses_override(self) -> None:
        store = BuiltinManifestStore()
        resolver = ManifestResolver(store)
        manifest = _make_agent_manifest(
            context=ContextOverrides(
                window=WindowOverrides(sliding_window_size=0)
            )
        )
        result = resolver.resolve(manifest)

        assert result.config.window is not None
        assert result.config.window.sliding_window_size == 0

    def test_tool_call_max_length_zero_uses_override(self) -> None:
        store = BuiltinManifestStore()
        resolver = ManifestResolver(store)
        manifest = _make_agent_manifest(
            context=ContextOverrides(
                window=WindowOverrides(tool_call_max_length=0)
            )
        )
        result = resolver.resolve(manifest)

        assert result.config.window is not None
        assert result.config.window.tool_call_max_length == 0

    def test_snapshot_interval_zero_uses_override(self) -> None:
        store = BuiltinManifestStore()
        resolver = ManifestResolver(store)
        manifest = _make_agent_manifest(
            context=ContextOverrides(
                persistence=PersistenceOverrides(snapshot_interval=0)
            )
        )
        result = resolver.resolve(manifest)

        assert result.config.context is not None
        assert result.config.context.snapshot_interval == 0

    def test_resolve_communication_timeout_default(self) -> None:
        store = BuiltinManifestStore()
        resolver = ManifestResolver(store)
        manifest = _make_agent_manifest()
        result = resolver.resolve(manifest)

        assert result.config.communication_timeout == 300.0

    def test_resolve_communication_timeout_custom(self) -> None:
        store = BuiltinManifestStore()
        resolver = ManifestResolver(store)
        manifest = _make_agent_manifest(communication_timeout=600.0)
        result = resolver.resolve(manifest)

        assert result.config.communication_timeout == 600.0

    def test_resolve_communication_timeout_infinite(self) -> None:
        store = BuiltinManifestStore()
        resolver = ManifestResolver(store)
        manifest = _make_agent_manifest(communication_timeout=-1)
        result = resolver.resolve(manifest)

        assert result.config.communication_timeout == -1
