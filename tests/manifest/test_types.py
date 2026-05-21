# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ghrah.manifest.types import (
    HookDef,
    ImplementationDef,
    PermissionFlags,
    ToolParameter,
    ToolSchema,
)


class TestPermissionFlags:
    def test_defaults(self) -> None:
        pf = PermissionFlags()
        assert pf.require_hitl is False
        assert pf.fs_read_only is False
        assert pf.fs_write is False
        assert pf.net_access is False
        assert pf.shell_access is False
        assert pf.allowed_paths == []
        assert pf.denied_paths == []
        assert pf.allowed_commands == []
        assert pf.denied_commands == []

    def test_merge_none_returns_copy(self) -> None:
        pf = PermissionFlags(fs_write=True, allowed_paths=["src/**"])
        result = pf.merge(None)
        assert result is not pf
        assert result.fs_write is True
        assert result.allowed_paths == ["src/**"]

    def test_merge_bool_or(self) -> None:
        base = PermissionFlags(fs_write=True, net_access=False)
        override = PermissionFlags(fs_write=False, net_access=True)
        result = base.merge(override)
        assert result.fs_write is True
        assert result.net_access is True

    def test_merge_allowed_paths_replace(self) -> None:
        base = PermissionFlags(allowed_paths=["$WORKSPACE/**"])
        override = PermissionFlags(allowed_paths=["src/**"])
        result = base.merge(override)
        assert result.allowed_paths == ["src/**"]

    def test_merge_allowed_paths_inherit_when_empty(self) -> None:
        base = PermissionFlags(allowed_paths=["$WORKSPACE/**"])
        override = PermissionFlags(allowed_paths=[])
        result = base.merge(override)
        assert result.allowed_paths == ["$WORKSPACE/**"]

    def test_merge_denied_paths_append(self) -> None:
        base = PermissionFlags(denied_paths=["**/.env"])
        override = PermissionFlags(denied_paths=["**/credentials/**"])
        result = base.merge(override)
        assert result.denied_paths == ["**/.env", "**/credentials/**"]

    def test_merge_allowed_commands_replace(self) -> None:
        base = PermissionFlags(allowed_commands=["ls", "cat"])
        override = PermissionFlags(allowed_commands=["python3"])
        result = base.merge(override)
        assert result.allowed_commands == ["python3"]

    def test_merge_allowed_commands_inherit_when_empty(self) -> None:
        base = PermissionFlags(allowed_commands=["ls", "cat"])
        override = PermissionFlags(allowed_commands=[])
        result = base.merge(override)
        assert result.allowed_commands == ["ls", "cat"]

    def test_merge_denied_commands_append(self) -> None:
        base = PermissionFlags(denied_commands=["rm -rf"])
        override = PermissionFlags(denied_commands=["sudo"])
        result = base.merge(override)
        assert result.denied_commands == ["rm -rf", "sudo"]

    def test_extra_forbid(self) -> None:
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            PermissionFlags(unknown_field=True)


class TestHookDef:
    def test_defaults(self) -> None:
        hook = HookDef()
        assert hook.type == "builtin"
        assert hook.handler is None
        assert hook.source is None
        assert hook.params == {}

    def test_builtin_hook(self) -> None:
        hook = HookDef(type="builtin", handler="write_approval_hook", params={"auto": True})
        assert hook.type == "builtin"
        assert hook.handler == "write_approval_hook"

    def test_python_hook(self) -> None:
        hook = HookDef(type="python", source="async def hook(ctx): pass")
        assert hook.type == "python"
        assert hook.source is not None

    def test_extra_forbid(self) -> None:
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            HookDef(type="builtin", unknown="x")


class TestToolParameter:
    def test_string_param(self) -> None:
        param = ToolParameter(type="string", description="A path", required=True)
        assert param.type == "string"
        assert param.required is True

    def test_integer_param_with_range(self) -> None:
        param = ToolParameter(type="integer", minimum=1, maximum=1000)
        assert param.minimum == 1
        assert param.maximum == 1000

    def test_array_with_items(self) -> None:
        param = ToolParameter(
            type="array",
            items=ToolParameter(type="string", description="An item"),
        )
        assert param.items is not None
        assert param.items.type == "string"

    def test_enum_param(self) -> None:
        param = ToolParameter(type="string", enum=["utf-8", "ascii"])
        assert param.enum == ["utf-8", "ascii"]

    def test_extra_flag(self) -> None:
        param = ToolParameter(type="string", sensitive=True)
        assert param.sensitive is True

    def test_extra_forbid(self) -> None:
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            ToolParameter(type="string", unknown="x")


class TestToolSchema:
    def test_basic_schema(self) -> None:
        schema = ToolSchema(
            name="read_file",
            description="Read a file",
            parameters={
                "file_path": ToolParameter(type="string", required=True),
                "encoding": ToolParameter(type="string", default="utf-8"),
            },
        )
        assert schema.name == "read_file"
        assert len(schema.parameters) == 2

    def test_to_openai_schema(self) -> None:
        schema = ToolSchema(
            name="read_file",
            description="Read a file",
            parameters={
                "file_path": ToolParameter(
                    type="string", description="Path", required=True
                ),
                "limit": ToolParameter(type="integer", minimum=1),
            },
        )
        result = schema.to_openai_schema()
        assert result["type"] == "object"
        assert "file_path" in result["properties"]
        assert "limit" in result["properties"]
        assert result["required"] == ["file_path"]
        assert result["properties"]["limit"]["minimum"] == 1

    def test_to_openai_schema_no_required(self) -> None:
        schema = ToolSchema(
            name="list_dir",
            description="List directory",
            parameters={
                "path": ToolParameter(type="string"),
            },
        )
        result = schema.to_openai_schema()
        assert "required" not in result

    def test_to_openai_tool(self) -> None:
        schema = ToolSchema(
            name="read_file",
            description="Read a file",
            strict=True,
            parameters={
                "path": ToolParameter(type="string", required=True),
            },
        )
        result = schema.to_openai_tool()
        assert result["type"] == "function"
        assert result["function"]["name"] == "read_file"
        assert result["function"]["strict"] is True
        assert result["function"]["parameters"]["type"] == "object"

    def test_to_openai_schema_with_enum_and_default(self) -> None:
        schema = ToolSchema(
            name="test",
            description="test",
            parameters={
                "encoding": ToolParameter(
                    type="string",
                    enum=["utf-8", "ascii"],
                    default="utf-8",
                ),
            },
        )
        result = schema.to_openai_schema()
        prop = result["properties"]["encoding"]
        assert prop["enum"] == ["utf-8", "ascii"]
        assert prop["default"] == "utf-8"

    def test_to_openai_schema_with_array_items(self) -> None:
        schema = ToolSchema(
            name="test",
            description="test",
            parameters={
                "items": ToolParameter(
                    type="array",
                    items=ToolParameter(type="integer"),
                ),
            },
        )
        result = schema.to_openai_schema()
        assert result["properties"]["items"]["type"] == "array"
        assert result["properties"]["items"]["items"]["type"] == "integer"

    def test_empty_parameters(self) -> None:
        schema = ToolSchema(name="noop", description="Does nothing")
        result = schema.to_openai_schema()
        assert result["properties"] == {}
        assert "required" not in result


class TestImplementationDef:
    def test_builtin(self) -> None:
        impl = ImplementationDef(type="builtin", handler="read_file")
        assert impl.type == "builtin"
        assert impl.handler == "read_file"

    def test_python(self) -> None:
        impl = ImplementationDef(
            type="python", entrypoint="execute", source="async def execute(): pass"
        )
        assert impl.entrypoint == "execute"

    def test_wasm(self) -> None:
        impl = ImplementationDef(type="wasm", module_ref="ghrah_fs_read")
        assert impl.module_ref == "ghrah_fs_read"

    def test_sandbox(self) -> None:
        impl = ImplementationDef(type="sandbox")
        assert impl.handler is None

    def test_extra_forbid(self) -> None:
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            ImplementationDef(type="builtin", unknown="x")
