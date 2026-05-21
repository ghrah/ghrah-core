# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SUPPORTED_VERSIONS: frozenset[str] = frozenset({"1"})
"""Supported major versions. Minor versions are always accepted."""


class PermissionFlags(BaseModel):
    model_config = ConfigDict(extra="forbid")

    require_hitl: bool = False
    fs_read_only: bool = False
    fs_write: bool = False
    net_access: bool = False
    shell_access: bool = False
    allowed_paths: list[str] = Field(default_factory=list)
    denied_paths: list[str] = Field(default_factory=list)
    allowed_commands: list[str] = Field(default_factory=list)
    denied_commands: list[str] = Field(default_factory=list)

    def merge(self, overrides: PermissionFlags | None = None) -> PermissionFlags:
        """合并权限标志。

        合并策略：
        - 布尔字段：使用 OR（任一为 True 则结果为 True）= 收紧语义
        - allowed_paths/allowed_commands：替换语义（override 非空则替换，否则继承 base）
        - denied_paths/denied_commands：追加语义（始终叠加）
        """
        if overrides is None:
            return self.model_copy()
        return PermissionFlags(
            require_hitl=overrides.require_hitl or self.require_hitl,
            fs_read_only=overrides.fs_read_only or self.fs_read_only,
            fs_write=overrides.fs_write or self.fs_write,
            net_access=overrides.net_access or self.net_access,
            shell_access=overrides.shell_access or self.shell_access,
            allowed_paths=(
                overrides.allowed_paths
                if overrides.allowed_paths
                else self.allowed_paths
            ),
            denied_paths=self.denied_paths + overrides.denied_paths,
            allowed_commands=(
                overrides.allowed_commands
                if overrides.allowed_commands
                else self.allowed_commands
            ),
            denied_commands=self.denied_commands + overrides.denied_commands,
        )


class HookDef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["builtin", "python"] = "builtin"
    handler: str | None = None
    source: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)


class ToolParameter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["string", "integer", "number", "boolean", "array", "object"]
    description: str = ""
    required: bool = False
    default: Any = None
    enum: list[str] | None = None
    minimum: float | int | None = None
    maximum: float | int | None = None
    items: ToolParameter | None = None
    sensitive: bool = False


def _param_to_json_schema(param: ToolParameter) -> dict[str, Any]:
    prop: dict[str, Any] = {"type": param.type}
    if param.description:
        prop["description"] = param.description
    if param.enum is not None:
        prop["enum"] = param.enum
    if param.minimum is not None:
        prop["minimum"] = param.minimum
    if param.maximum is not None:
        prop["maximum"] = param.maximum
    if param.items is not None:
        prop["items"] = _param_to_json_schema(param.items)
    if param.default is not None:
        prop["default"] = param.default
    return prop


class ToolSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    strict: bool = False
    parameters: dict[str, ToolParameter] = Field(default_factory=dict)

    def to_openai_schema(self) -> dict[str, Any]:
        properties: dict[str, Any] = {}
        required: list[str] = []

        for name, param in self.parameters.items():
            properties[name] = _param_to_json_schema(param)
            if param.required:
                required.append(name)

        result: dict[str, Any] = {
            "type": "object",
            "properties": properties,
        }
        if required:
            result["required"] = required
        return result

    def to_openai_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "strict": self.strict,
                "parameters": self.to_openai_schema(),
            },
        }


class ImplementationDef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["builtin", "python", "sandbox", "wasm"]
    handler: str | None = None
    entrypoint: str | None = None
    source: str | None = None
    module_ref: str | None = None


ToolParameter.model_rebuild()
