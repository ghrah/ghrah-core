# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ghrah.manifest.ability import AbilityHooks, AbilityManifest, AbilityMetadata
from ghrah.manifest.errors import ManifestVersionError
from ghrah.manifest.types import (
    HookDef,
    PermissionFlags,
)


def _make_ability_manifest(**overrides) -> AbilityManifest:
    defaults: dict = {
        "manifest": "ability",
        "version": "1",
        "metadata": {
            "namespace": "ghrah.fs",
            "name": "read_file",
            "description": "Read file contents",
            "permissions": {"fs_read_only": True},
        },
        "tool": {
            "name": "read_file",
            "description": "Read the contents of a file",
            "parameters": {
                "file_path": {
                    "type": "string",
                    "description": "Path",
                    "required": True,
                },
            },
        },
        "implementation": {
            "type": "builtin",
            "handler": "read_file",
        },
    }
    defaults.update(overrides)
    return AbilityManifest.model_validate(defaults)


class TestAbilityMetadata:
    def test_valid_metadata(self) -> None:
        meta = AbilityMetadata(
            namespace="ghrah.fs",
            name="read_file",
            description="Read file",
            permissions=PermissionFlags(fs_read_only=True),
        )
        assert meta.namespace == "ghrah.fs"
        assert meta.name == "read_file"

    def test_namespace_pattern(self) -> None:
        with pytest.raises(ValidationError):
            AbilityMetadata(
                namespace="Invalid",
                name="read_file",
                description="x",
                permissions=PermissionFlags(),
            )

    def test_name_pattern(self) -> None:
        with pytest.raises(ValidationError):
            AbilityMetadata(
                namespace="ghrah.fs",
                name="Invalid",
                description="x",
                permissions=PermissionFlags(),
            )

    def test_description_required(self) -> None:
        with pytest.raises(ValidationError):
            AbilityMetadata(
                namespace="ghrah.fs",
                name="read_file",
                description="",
                permissions=PermissionFlags(),
            )

    def test_optional_fields(self) -> None:
        meta = AbilityMetadata(
            namespace="ghrah.fs",
            name="read_file",
            description="Read",
            permissions=PermissionFlags(),
            title="Read File",
            tags=["filesystem"],
            icon="file-read",
            deprecated=True,
            since="1.0",
        )
        assert meta.title == "Read File"
        assert meta.tags == ["filesystem"]
        assert meta.deprecated is True

    def test_extra_forbid(self) -> None:
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            AbilityMetadata(
                namespace="ghrah.fs",
                name="read_file",
                description="x",
                permissions=PermissionFlags(),
                unknown="field",
            )


class TestAbilityHooks:
    def test_defaults(self) -> None:
        hooks = AbilityHooks()
        assert hooks.pre_execute == []
        assert hooks.post_execute == []
        assert hooks.on_error == []

    def test_with_hooks(self) -> None:
        hook = HookDef(type="builtin", handler="approval_hook")
        hooks = AbilityHooks(pre_execute=[hook])
        assert len(hooks.pre_execute) == 1


class TestAbilityManifest:
    def test_valid_manifest(self) -> None:
        manifest = _make_ability_manifest()
        assert manifest.manifest == "ability"
        assert manifest.version == "1"
        assert manifest.metadata.namespace == "ghrah.fs"
        assert manifest.full_name == "ghrah.fs.read_file"

    def test_manifest_must_be_ability(self) -> None:
        with pytest.raises(ValidationError):
            _make_ability_manifest(manifest="agent")

    def test_version_unsupported(self) -> None:
        with pytest.raises((ValidationError, ManifestVersionError)):
            _make_ability_manifest(version="2")

    def test_version_missing(self) -> None:
        with pytest.raises(ValidationError):
            _make_ability_manifest(version="")

    def test_version_minor_compatible(self) -> None:
        manifest = _make_ability_manifest(version="1.1")
        assert manifest.version == "1.1"

    def test_version_format_invalid(self) -> None:
        with pytest.raises(ValidationError):
            _make_ability_manifest(version="abc")

    def test_hooks_default(self) -> None:
        manifest = _make_ability_manifest()
        assert manifest.hooks.pre_execute == []
        assert manifest.hooks.post_execute == []

    def test_with_hooks(self) -> None:
        manifest = _make_ability_manifest(
            hooks={
                "pre_execute": [{"type": "builtin", "handler": "approval"}],
            }
        )
        assert len(manifest.hooks.pre_execute) == 1

    def test_full_name(self) -> None:
        manifest = _make_ability_manifest()
        assert manifest.full_name == "ghrah.fs.read_file"

    def test_extra_forbid(self) -> None:
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            AbilityManifest.model_validate(
                {
                    "manifest": "ability",
                    "version": "1",
                    "metadata": {
                        "namespace": "ghrah.fs",
                        "name": "read_file",
                        "description": "Read",
                        "permissions": {},
                    },
                    "tool": {
                        "name": "read_file",
                        "description": "Read",
                    },
                    "implementation": {
                        "type": "builtin",
                        "handler": "read_file",
                    },
                    "unknown_field": True,
                }
            )

    def test_tool_none_builtin_allowed(self) -> None:
        manifest = AbilityManifest.model_validate(
            {
                "manifest": "ability",
                "version": "1",
                "metadata": {
                    "namespace": "ghrah.core",
                    "name": "conversation",
                    "description": "Conversation",
                    "permissions": {},
                },
                "implementation": {
                    "type": "builtin",
                    "handler": "conversation",
                },
            }
        )
        assert manifest.tool is None
        assert manifest.implementation.type == "builtin"

    def test_tool_none_sandbox_forbidden(self) -> None:
        with pytest.raises(ValidationError, match="tool is required"):
            AbilityManifest.model_validate(
                {
                    "manifest": "ability",
                    "version": "1",
                    "metadata": {
                        "namespace": "ghrah.fs",
                        "name": "remote_tool",
                        "description": "Remote",
                        "permissions": {},
                    },
                    "implementation": {
                        "type": "sandbox",
                        "handler": "remote_tool",
                    },
                }
            )

    def test_tool_none_wasm_forbidden(self) -> None:
        with pytest.raises(ValidationError, match="tool is required"):
            AbilityManifest.model_validate(
                {
                    "manifest": "ability",
                    "version": "1",
                    "metadata": {
                        "namespace": "ghrah.fs",
                        "name": "wasm_tool",
                        "description": "Wasm",
                        "permissions": {},
                    },
                    "implementation": {
                        "type": "wasm",
                        "module_ref": "ghrah_fs_wasm",
                    },
                }
            )

    def test_tool_none_python_allowed(self) -> None:
        manifest = AbilityManifest.model_validate(
            {
                "manifest": "ability",
                "version": "1",
                "metadata": {
                    "namespace": "ghrah.core",
                    "name": "custom_hook",
                    "description": "Custom",
                    "permissions": {},
                },
                "implementation": {
                    "type": "python",
                    "entrypoint": "execute",
                    "source": "async def execute(): pass",
                },
            }
        )
        assert manifest.tool is None
