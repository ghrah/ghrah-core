# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ghrah.manifest.agent import (
    AbilityRef,
    AgentHooks,
    AgentManifest,
    AgentMetadata,
    ContextOverrides,
    ModelConfig,
    PersistenceOverrides,
    WindowOverrides,
)
from ghrah.manifest.errors import ManifestVersionError
from ghrah.manifest.types import HookDef, PermissionFlags


def _make_agent_manifest(**overrides) -> AgentManifest:
    defaults: dict = {
        "manifest": "agent",
        "version": "1",
        "metadata": {
            "namespace": "my_project",
            "name": "dev_agent",
        },
        "model": {
            "agent_config_name": "gpt-4o-dev",
        },
        "system_prompt": "You are a dev agent.",
        "abilities": [
            {"ref": "ghrah.fs.read_file"},
            {"type": "conversation"},
        ],
    }
    defaults.update(overrides)
    return AgentManifest.model_validate(defaults)


class TestAgentMetadata:
    def test_valid(self) -> None:
        meta = AgentMetadata(namespace="my_project", name="dev_agent")
        assert meta.namespace == "my_project"
        assert meta.name == "dev_agent"

    def test_namespace_pattern_invalid(self) -> None:
        with pytest.raises(ValidationError):
            AgentMetadata(namespace="Invalid", name="dev_agent")

    def test_name_pattern_invalid(self) -> None:
        with pytest.raises(ValidationError):
            AgentMetadata(namespace="my_project", name="Invalid")

    def test_optional_fields(self) -> None:
        meta = AgentMetadata(
            namespace="my_project",
            name="dev_agent",
            title="Dev Agent",
            description="A dev agent",
            tags=["dev"],
            icon="agent-dev",
            deprecated=True,
        )
        assert meta.title == "Dev Agent"
        assert meta.tags == ["dev"]

    def test_extra_forbid(self) -> None:
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            AgentMetadata(namespace="my_project", name="dev_agent", unknown=True)


class TestModelConfig:
    def test_valid(self) -> None:
        config = ModelConfig(agent_config_name="gpt-4o-dev")
        assert config.agent_config_name == "gpt-4o-dev"

    def test_with_overrides(self) -> None:
        config = ModelConfig(
            agent_config_name="gpt-4o-dev",
            temperature=0.3,
            max_tokens=8192,
            top_p=0.95,
            top_k=5,
        )
        assert config.temperature == 0.3
        assert config.max_tokens == 8192

    def test_agent_config_name_required(self) -> None:
        with pytest.raises(ValidationError):
            ModelConfig(agent_config_name="")

    def test_extra_forbid(self) -> None:
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            ModelConfig(agent_config_name="x", unknown=True)


class TestAbilityRef:
    def test_ref_only(self) -> None:
        ref = AbilityRef(ref="ghrah.fs.read_file")
        assert ref.ref == "ghrah.fs.read_file"
        assert ref.type is None

    def test_type_only(self) -> None:
        ref = AbilityRef(type="conversation")
        assert ref.type == "conversation"
        assert ref.ref is None

    def test_with_permissions(self) -> None:
        ref = AbilityRef(
            ref="ghrah.fs.write_file",
            permissions=PermissionFlags(require_hitl=True),
        )
        assert ref.permissions is not None
        assert ref.permissions.require_hitl is True

    def test_both_ref_and_type_raises(self) -> None:
        with pytest.raises(ValidationError, match="Only one of"):
            AbilityRef(ref="ghrah.fs.read_file", type="conversation")

    def test_neither_ref_nor_type_raises(self) -> None:
        with pytest.raises(ValidationError, match="Either 'ref' or 'type'"):
            AbilityRef()

    def test_extra_forbid(self) -> None:
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            AbilityRef(ref="x", unknown=True)


class TestContextOverrides:
    def test_window_overrides(self) -> None:
        wo = WindowOverrides(max_tokens=16384, strategies=["tool_call_fold"])
        assert wo.max_tokens == 16384
        assert wo.strategies == ["tool_call_fold"]

    def test_persistence_overrides(self) -> None:
        po = PersistenceOverrides(type="json_file", compress=True)
        assert po.type == "json_file"
        assert po.compress is True

    def test_context_overrides_nested(self) -> None:
        co = ContextOverrides(
            window=WindowOverrides(max_tokens=8192),
            persistence=PersistenceOverrides(auto_persist=True),
        )
        assert co.window is not None
        assert co.window.max_tokens == 8192
        assert co.persistence is not None
        assert co.persistence.auto_persist is True

    def test_context_overrides_none(self) -> None:
        co = ContextOverrides()
        assert co.window is None
        assert co.persistence is None


class TestAgentHooks:
    def test_defaults(self) -> None:
        hooks = AgentHooks()
        assert hooks.before_action == []
        assert hooks.after_action == []
        assert hooks.pre_llm_call == []
        assert hooks.post_llm_call == []
        assert hooks.pre_tool_execute == []
        assert hooks.post_tool_execute == []
        assert hooks.on_error == []
        assert hooks.on_max_iterations == []

    def test_with_hooks(self) -> None:
        hook = HookDef(type="builtin", handler="log_action")
        hooks = AgentHooks(before_action=[hook], on_error=[hook])
        assert len(hooks.before_action) == 1
        assert len(hooks.on_error) == 1


class TestAgentManifest:
    def test_valid_manifest(self) -> None:
        manifest = _make_agent_manifest()
        assert manifest.manifest == "agent"
        assert manifest.version == "1"
        assert manifest.metadata.namespace == "my_project"
        assert manifest.full_name == "my_project.dev_agent"

    def test_manifest_must_be_agent(self) -> None:
        with pytest.raises(ValidationError):
            _make_agent_manifest(manifest="ability")

    def test_version_unsupported(self) -> None:
        with pytest.raises((ValidationError, ManifestVersionError)):
            _make_agent_manifest(version="2")

    def test_version_minor_compatible(self) -> None:
        manifest = _make_agent_manifest(version="1.1")
        assert manifest.version == "1.1"

    def test_system_prompt_required(self) -> None:
        with pytest.raises(ValidationError):
            _make_agent_manifest(system_prompt="")

    def test_abilities_must_be_non_empty(self) -> None:
        with pytest.raises(ValidationError):
            _make_agent_manifest(abilities=[])

    def test_max_iterations_minimum(self) -> None:
        with pytest.raises(ValidationError):
            _make_agent_manifest(max_iterations=-2)

    def test_max_iterations_valid(self) -> None:
        manifest = _make_agent_manifest(max_iterations=20)
        assert manifest.max_iterations == 20

    def test_default_max_iterations(self) -> None:
        manifest = _make_agent_manifest()
        assert manifest.max_iterations == 10

    def test_communication_timeout_default(self) -> None:
        manifest = _make_agent_manifest()
        assert manifest.communication_timeout == 300.0

    def test_communication_timeout_custom(self) -> None:
        manifest = _make_agent_manifest(communication_timeout=600.0)
        assert manifest.communication_timeout == 600.0

    def test_communication_timeout_infinite(self) -> None:
        manifest = _make_agent_manifest(communication_timeout=-1)
        assert manifest.communication_timeout == -1

    def test_communication_timeout_below_minus_one_raises(self) -> None:
        with pytest.raises(ValidationError):
            _make_agent_manifest(communication_timeout=-2)

    def test_context_overrides(self) -> None:
        manifest = _make_agent_manifest(
            context={
                "window": {"max_tokens": 16384},
                "persistence": {"type": "json_file"},
            }
        )
        assert manifest.context is not None
        assert manifest.context.window is not None
        assert manifest.context.window.max_tokens == 16384

    def test_hooks_default(self) -> None:
        manifest = _make_agent_manifest()
        assert manifest.hooks.before_action == []

    def test_full_name(self) -> None:
        manifest = _make_agent_manifest()
        assert manifest.full_name == "my_project.dev_agent"

    def test_extra_forbid(self) -> None:
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            AgentManifest.model_validate(
                {
                    "manifest": "agent",
                    "version": "1",
                    "metadata": {"namespace": "x", "name": "y"},
                    "model": {"agent_config_name": "z"},
                    "system_prompt": "prompt",
                    "abilities": [{"ref": "a"}],
                    "unknown": True,
                }
            )
