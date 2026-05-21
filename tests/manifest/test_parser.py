# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json

import pytest

from ghrah.manifest.errors import ManifestValidationError
from ghrah.manifest.parser import parse_ability_manifest, parse_agent_manifest, validate_manifest

VALID_ABILITY_YAML = """\
manifest: ability
version: "1"
metadata:
  namespace: ghrah.fs
  name: read_file
  description: Read file contents
  permissions:
    fs_read_only: true
tool:
  name: read_file
  description: Read the contents of a file
  parameters:
    file_path:
      type: string
      description: Path to the file
      required: true
    encoding:
      type: string
      description: Text encoding
      required: false
      default: utf-8
      enum:
        - utf-8
        - ascii
implementation:
  type: builtin
  handler: read_file
hooks:
  pre_execute:
    - type: builtin
      handler: approval_hook
"""

VALID_AGENT_YAML = """\
manifest: agent
version: "1"
metadata:
  namespace: my_project
  name: dev_agent
  description: A dev agent
model:
  agent_config_name: gpt-4o-dev
  temperature: 0.3
system_prompt: You are a dev agent.
max_iterations: 20
abilities:
  - ref: ghrah.fs.read_file
  - type: conversation
context:
  window:
    max_tokens: 16384
  persistence:
    type: json_file
    compress: true
hooks:
  before_action:
    - type: builtin
      handler: log_action
"""


class TestParseAbilityManifest:
    def test_yaml_parse(self) -> None:
        manifest = parse_ability_manifest(VALID_ABILITY_YAML)
        assert manifest.manifest == "ability"
        assert manifest.metadata.namespace == "ghrah.fs"
        assert manifest.metadata.name == "read_file"
        assert manifest.full_name == "ghrah.fs.read_file"
        assert manifest.tool.name == "read_file"
        assert "file_path" in manifest.tool.parameters
        assert manifest.tool.parameters["encoding"].enum == ["utf-8", "ascii"]
        assert manifest.implementation.type == "builtin"
        assert manifest.implementation.handler == "read_file"
        assert len(manifest.hooks.pre_execute) == 1

    def test_json_parse(self) -> None:
        data = {
            "manifest": "ability",
            "version": "1",
            "metadata": {
                "namespace": "ghrah.fs",
                "name": "write_file",
                "description": "Write file",
                "permissions": {"fs_write": True},
            },
            "tool": {
                "name": "write_file",
                "description": "Write file",
            },
            "implementation": {"type": "builtin", "handler": "write_file"},
        }
        manifest = parse_ability_manifest(json.dumps(data), format="json")
        assert manifest.full_name == "ghrah.fs.write_file"

    def test_missing_manifest_type(self) -> None:
        with pytest.raises(ManifestValidationError, match="manifest"):
            parse_ability_manifest(
                "manifest: ability\nversion: '1'\nmetadata:\n"
                "  namespace: xx\n  name: y\n  description: z\n"
                "  permissions: {}"
            )

    def test_wrong_manifest_type(self) -> None:
        yaml_str = """
manifest: agent
version: "1"
metadata:
  namespace: x
  name: y
  description: z
  permissions: {}
tool:
  name: t
  description: d
implementation:
  type: builtin
  handler: h
"""
        with pytest.raises(ManifestValidationError):
            parse_ability_manifest(yaml_str)

    def test_unsupported_version(self) -> None:
        with pytest.raises(ManifestValidationError, match="Unsupported"):
            parse_ability_manifest(VALID_ABILITY_YAML.replace('version: "1"', 'version: "2"'))

    def test_missing_required_field(self) -> None:
        with pytest.raises(ManifestValidationError):
            parse_ability_manifest("manifest: ability\nversion: '1'")

    def test_invalid_format(self) -> None:
        with pytest.raises(ValueError, match="Unsupported format"):
            parse_ability_manifest("{}", format="toml")

    def test_ability_without_tool(self) -> None:
        yaml_str = """\
manifest: ability
version: "1"
metadata:
  namespace: ghrah.core
  name: conversation
  description: Conversation ability
  permissions: {}
implementation:
  type: builtin
  handler: conversation
"""
        manifest = parse_ability_manifest(yaml_str)
        assert manifest.tool is None
        assert manifest.implementation.type == "builtin"

    def test_ability_without_tool_sandbox_forbidden(self) -> None:
        yaml_str = """\
manifest: ability
version: "1"
metadata:
  namespace: ghrah.fs
  name: remote_tool
  description: Remote tool
  permissions: {}
implementation:
  type: sandbox
  handler: remote_tool
"""
        with pytest.raises(ManifestValidationError, match="tool is required"):
            parse_ability_manifest(yaml_str)

    def test_ability_without_tool_wasm_forbidden(self) -> None:
        yaml_str = """\
manifest: ability
version: "1"
metadata:
  namespace: ghrah.fs
  name: wasm_tool
  description: Wasm tool
  permissions: {}
implementation:
  type: wasm
  module_ref: ghrah_fs_wasm
"""
        with pytest.raises(ManifestValidationError, match="tool is required"):
            parse_ability_manifest(yaml_str)


class TestParseAgentManifest:
    def test_yaml_parse(self) -> None:
        manifest = parse_agent_manifest(VALID_AGENT_YAML)
        assert manifest.manifest == "agent"
        assert manifest.metadata.namespace == "my_project"
        assert manifest.metadata.name == "dev_agent"
        assert manifest.full_name == "my_project.dev_agent"
        assert manifest.model.agent_config_name == "gpt-4o-dev"
        assert manifest.model.temperature == 0.3
        assert manifest.max_iterations == 20
        assert manifest.communication_timeout == 300.0
        assert len(manifest.abilities) == 2
        assert manifest.abilities[0].ref == "ghrah.fs.read_file"
        assert manifest.abilities[1].type == "conversation"
        assert manifest.context is not None
        assert manifest.context.window is not None
        assert manifest.context.window.max_tokens == 16384

    def test_json_parse(self) -> None:
        data = {
            "manifest": "agent",
            "version": "1",
            "metadata": {"namespace": "ns", "name": "agent1"},
            "model": {"agent_config_name": "cfg"},
            "system_prompt": "prompt",
            "abilities": [{"type": "conversation"}],
        }
        manifest = parse_agent_manifest(json.dumps(data), format="json")
        assert manifest.full_name == "ns.agent1"

    def test_missing_manifest_type(self) -> None:
        with pytest.raises(ManifestValidationError):
            parse_agent_manifest(
                "version: '1'\nmetadata:\n  namespace: x\n  name: y\n"
                "model:\n  agent_config_name: z\n"
                "system_prompt: p\nabilities:\n  - type: t"
            )

    def test_ability_ref_mutual_exclusion(self) -> None:
        yaml_str = """
manifest: agent
version: "1"
metadata:
  namespace: x
  name: y
model:
  agent_config_name: z
system_prompt: prompt
abilities:
  - ref: some.ref
    type: conversation
"""
        with pytest.raises(ManifestValidationError, match="Only one of"):
            parse_agent_manifest(yaml_str)

    def test_ability_ref_neither(self) -> None:
        yaml_str = """
manifest: agent
version: "1"
metadata:
  namespace: x
  name: y
model:
  agent_config_name: z
system_prompt: prompt
abilities:
  - {}
"""
        with pytest.raises(ManifestValidationError, match="Either 'ref' or 'type'"):
            parse_agent_manifest(yaml_str)

    def test_communication_timeout_default(self) -> None:
        yaml_str = """
manifest: agent
version: "1"
metadata:
  namespace: test_ns
  name: test_agent
model:
  agent_config_name: test_cfg
system_prompt: prompt
abilities:
  - type: conversation
"""
        manifest = parse_agent_manifest(yaml_str)
        assert manifest.communication_timeout == 300.0

    def test_communication_timeout_custom(self) -> None:
        yaml_str = """
manifest: agent
version: "1"
metadata:
  namespace: test_ns
  name: test_agent
model:
  agent_config_name: test_cfg
system_prompt: prompt
max_iterations: 20
communication_timeout: 600.0
abilities:
  - type: conversation
"""
        manifest = parse_agent_manifest(yaml_str)
        assert manifest.communication_timeout == 600.0

    def test_communication_timeout_infinite(self) -> None:
        yaml_str = """
manifest: agent
version: "1"
metadata:
  namespace: test_ns
  name: test_agent
model:
  agent_config_name: test_cfg
system_prompt: prompt
communication_timeout: -1
abilities:
  - type: conversation
"""
        manifest = parse_agent_manifest(yaml_str)
        assert manifest.communication_timeout == -1


class TestValidateManifest:
    def test_valid_ability(self) -> None:
        ok, errors = validate_manifest(VALID_ABILITY_YAML)
        assert ok is True
        assert errors == []

    def test_valid_agent(self) -> None:
        ok, errors = validate_manifest(VALID_AGENT_YAML)
        assert ok is True
        assert errors == []

    def test_invalid_ability(self) -> None:
        yaml_str = "manifest: ability\nversion: '1'"
        ok, errors = validate_manifest(yaml_str)
        assert ok is False
        assert len(errors) > 0

    def test_unknown_manifest_type(self) -> None:
        ok, errors = validate_manifest('manifest: "unknown"\nversion: "1"')
        assert ok is False
        assert any("Unknown or missing" in e for e in errors)

    def test_missing_manifest_type(self) -> None:
        ok, errors = validate_manifest('version: "1"')
        assert ok is False
        assert any("Unknown or missing" in e for e in errors)

    def test_invalid_yaml_syntax(self) -> None:
        ok, errors = validate_manifest("{{invalid yaml}}")
        assert ok is False
        assert len(errors) > 0

    def test_json_format(self) -> None:
        data = {
            "manifest": "ability",
            "version": "1",
            "metadata": {
                "namespace": "ghrah.fs",
                "name": "read_file",
                "description": "Read",
                "permissions": {},
            },
            "tool": {"name": "read_file", "description": "Read"},
            "implementation": {"type": "builtin", "handler": "read_file"},
        }
        ok, errors = validate_manifest(json.dumps(data), format="json")
        assert ok is True
        assert errors == []

    def test_yaml_non_mapping(self) -> None:
        ok, errors = validate_manifest("- item1\n- item2")
        assert ok is False
        assert any("not a mapping" in e.lower() or "Parse error" in e for e in errors)
