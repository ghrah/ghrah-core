# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ghrah.manifest.errors import ManifestVersionError
from ghrah.manifest.types import (
    SUPPORTED_VERSIONS,
    HookDef,
    PermissionFlags,
)

__all__ = [
    "AgentManifest",
    "AgentMetadata",
    "ModelConfig",
    "AbilityRef",
    "WindowOverrides",
    "PersistenceOverrides",
    "ContextOverrides",
    "AgentHooks",
]


class AgentMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    namespace: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9_.]*[a-z0-9]$")
    name: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9_]*$")
    title: str = ""
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    icon: str = ""
    deprecated: bool = False


class ModelConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_config_name: str = Field(min_length=1)
    temperature: float | None = None
    max_tokens: int | None = None
    top_p: float | None = None
    top_k: int | None = None


class AbilityRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ref: str | None = None
    type: str | None = None
    permissions: PermissionFlags | None = None

    @model_validator(mode="after")
    def _check_ref_or_type(self) -> AbilityRef:
        if not self.ref and not self.type:
            raise ValueError("Either 'ref' or 'type' must be specified")
        if self.ref and self.type:
            raise ValueError("Only one of 'ref' or 'type' may be specified")
        return self


class WindowOverrides(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_tokens: int | None = None
    strategies: list[str] | None = None
    tool_call_max_length: int | None = None
    sliding_window_size: int | None = None


class PersistenceOverrides(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str | None = None
    compress: bool | None = None
    auto_persist: bool | None = None
    snapshot_interval: int | None = None


class ContextOverrides(BaseModel):
    model_config = ConfigDict(extra="forbid")

    window: WindowOverrides | None = None
    persistence: PersistenceOverrides | None = None


class AgentHooks(BaseModel):
    model_config = ConfigDict(extra="forbid")

    before_action: list[HookDef] = Field(default_factory=list)
    after_action: list[HookDef] = Field(default_factory=list)
    pre_llm_call: list[HookDef] = Field(default_factory=list)
    post_llm_call: list[HookDef] = Field(default_factory=list)
    pre_tool_execute: list[HookDef] = Field(default_factory=list)
    post_tool_execute: list[HookDef] = Field(default_factory=list)
    on_error: list[HookDef] = Field(default_factory=list)
    on_max_iterations: list[HookDef] = Field(default_factory=list)


class AgentManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manifest: Literal["agent"]
    version: str = Field(pattern=r"^\d+(\.\d+)*$")

    metadata: AgentMetadata
    model: ModelConfig
    system_prompt: str = Field(min_length=1)
    max_iterations: int = Field(default=10, ge=-1)
    communication_timeout: float = Field(default=300.0, ge=-1)
    description: str = ""
    abilities: list[AbilityRef] = Field(min_length=1)
    context: ContextOverrides | None = None
    hooks: AgentHooks = Field(default_factory=AgentHooks)

    @model_validator(mode="after")
    def _validate_version(self) -> AgentManifest:
        if self.version.split(".")[0] not in SUPPORTED_VERSIONS:
            raise ManifestVersionError(
                f"Unsupported manifest version: {self.version!r}. "
                f"Supported major versions: {sorted(SUPPORTED_VERSIONS)}"
            )
        return self

    @property
    def full_name(self) -> str:
        return f"{self.metadata.namespace}.{self.metadata.name}"
