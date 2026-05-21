# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import pytest

from ghrah.manifest.builtins import (
    _BUILTIN_YAML_NAMES,
    load_all_builtin_manifests,
    load_builtin_manifest,
)


class TestLoadBuiltinManifest:
    @pytest.mark.parametrize("full_name", _BUILTIN_YAML_NAMES)
    def test_each_builtin_parses_successfully(self, full_name: str) -> None:
        manifest = load_builtin_manifest(full_name)
        assert manifest.manifest == "ability"
        assert manifest.implementation.type == "builtin"
        assert manifest.implementation.handler is not None

    @pytest.mark.parametrize("full_name", _BUILTIN_YAML_NAMES)
    def test_full_name_matches_yaml_name(self, full_name: str) -> None:
        manifest = load_builtin_manifest(full_name)
        assert manifest.full_name == full_name

    def test_conversation_has_no_tool(self) -> None:
        manifest = load_builtin_manifest("ghrah.core.conversation")
        assert manifest.tool is None

    def test_end_task_has_tool(self) -> None:
        manifest = load_builtin_manifest("ghrah.core.end_task")
        assert manifest.tool is not None
        assert manifest.tool.name == "end_task"

    def test_read_file_permissions(self) -> None:
        manifest = load_builtin_manifest("ghrah.fs.read_file")
        assert manifest.metadata.permissions.fs_read_only is True

    def test_write_file_permissions(self) -> None:
        manifest = load_builtin_manifest("ghrah.fs.write_file")
        assert manifest.metadata.permissions.fs_write is True
        assert manifest.metadata.permissions.require_hitl is True

    def test_edit_file_permissions(self) -> None:
        manifest = load_builtin_manifest("ghrah.fs.edit_file")
        assert manifest.metadata.permissions.fs_write is True
        assert manifest.metadata.permissions.require_hitl is True

    def test_delete_file_permissions(self) -> None:
        manifest = load_builtin_manifest("ghrah.fs.delete_file")
        assert manifest.metadata.permissions.fs_write is True
        assert manifest.metadata.permissions.require_hitl is True

    def test_move_file_permissions(self) -> None:
        manifest = load_builtin_manifest("ghrah.fs.move_file")
        assert manifest.metadata.permissions.fs_write is True
        assert manifest.metadata.permissions.fs_read_only is True
        assert manifest.metadata.permissions.require_hitl is True

    def test_list_directory_permissions(self) -> None:
        manifest = load_builtin_manifest("ghrah.fs.list_directory")
        assert manifest.metadata.permissions.fs_read_only is True

    def test_execute_command_permissions(self) -> None:
        manifest = load_builtin_manifest("ghrah.shell.execute_command")
        assert manifest.metadata.permissions.shell_access is True
        assert manifest.metadata.permissions.require_hitl is True

    def test_write_file_has_write_approval_hook(self) -> None:
        manifest = load_builtin_manifest("ghrah.fs.write_file")
        assert len(manifest.hooks.pre_execute) >= 1
        hook = manifest.hooks.pre_execute[0]
        assert hook.handler == "write_approval"

    def test_execute_command_has_command_approval_hook(self) -> None:
        manifest = load_builtin_manifest("ghrah.shell.execute_command")
        assert len(manifest.hooks.pre_execute) >= 1
        hook = manifest.hooks.pre_execute[0]
        assert hook.handler == "command_approval"

    def test_conversation_has_post_execute_hook(self) -> None:
        manifest = load_builtin_manifest("ghrah.core.conversation")
        assert len(manifest.hooks.post_execute) >= 1
        hook = manifest.hooks.post_execute[0]
        assert hook.handler == "conversation_done"

    def test_nonexistent_raises_error(self) -> None:
        with pytest.raises(FileNotFoundError):
            load_builtin_manifest("ghrah.fs.nonexistent")


class TestLoadAllBuiltinManifests:
    def test_returns_all_builtins(self) -> None:
        manifests = load_all_builtin_manifests()
        assert len(manifests) == len(_BUILTIN_YAML_NAMES)

    def test_all_keys_are_full_names(self) -> None:
        manifests = load_all_builtin_manifests()
        for full_name in _BUILTIN_YAML_NAMES:
            assert full_name in manifests
            assert manifests[full_name].full_name == full_name

    def test_all_have_builtin_implementation(self) -> None:
        manifests = load_all_builtin_manifests()
        for full_name, manifest in manifests.items():
            assert manifest.implementation.type == "builtin", (
                f"{full_name} should have builtin implementation"
            )


class TestBuiltinYamlRoundTrip:
    @pytest.mark.parametrize("full_name", _BUILTIN_YAML_NAMES)
    def test_yaml_parse_produces_valid_manifest(self, full_name: str) -> None:
        manifest = load_builtin_manifest(full_name)
        assert manifest.manifest == "ability"
        assert manifest.version == "1"
        assert manifest.metadata.namespace
        assert manifest.metadata.name
        assert manifest.metadata.description

    @pytest.mark.parametrize("full_name", _BUILTIN_YAML_NAMES)
    def test_tool_parameters_match_ability_input(self, full_name: str) -> None:
        manifest = load_builtin_manifest(full_name)
        if manifest.tool is None:
            pytest.skip(f"{full_name} has no tool schema")
        assert manifest.tool.name
        assert manifest.tool.description
