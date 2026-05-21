# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""Manifest 解析器：将 AgentManifest 解析为可执行的 AgentConfig + Ability 列表。

核心逻辑：
1. AgentManifest.model → ModelOverrides（覆盖 agentconf 解析的 LLM 配置）
2. AgentManifest.abilities → ResolvedAbility 列表（ref 从 store 加载，type 从 builtin 加载）
3. AgentManifest.context → WindowConfig / ContextConfig
4. 权限合并：AbilityManifest.permissions.merge(AbilityRef.permissions) → 最终权限
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass

from ghrah.core.config import AgentConfig, ContextConfig, ModelOverrides, WindowConfig
from ghrah.manifest.ability import AbilityHooks
from ghrah.manifest.agent import (
    AbilityRef,
    AgentManifest,
    PersistenceOverrides,
    WindowOverrides,
)
from ghrah.manifest.builtins import load_all_builtin_manifests
from ghrah.manifest.errors import ManifestNotFoundError, ManifestValidationError
from ghrah.manifest.protocols import ManifestStoreProtocol
from ghrah.manifest.types import ImplementationDef, PermissionFlags, ToolSchema

__all__ = [
    "ResolvedAbility",
    "ResolvedAgent",
    "ManifestResolver",
]


@dataclass
class ResolvedAbility:
    """解析后的能力：包含完整定义。"""

    ability_name: str
    tool_schema: ToolSchema | None
    permissions: PermissionFlags
    implementation: ImplementationDef
    hooks: AbilityHooks

    @classmethod
    def from_builtin(cls, ability_type: str) -> ResolvedAbility:
        """从 builtin 类型名构建 ResolvedAbility。

        1. 验证 ability_type 在 AbilityRegistry 中已注册
        2. 从 builtins 包加载对应的 AbilityManifest
        3. 构建 ResolvedAbility（权限来自 manifest，hooks 来自 manifest）

        Raises:
            ManifestValidationError: ability_type 未在 AbilityRegistry 中注册
            ManifestNotFoundError: builtin manifest 不存在
        """
        from ghrah.abilities.registry import AbilityRegistry

        if not AbilityRegistry.has(ability_type):
            raise ManifestValidationError(
                f"Unknown builtin ability type: '{ability_type}'. "
                f"Available types: {AbilityRegistry.list_types()}"
            )

        builtins = load_all_builtin_manifests()
        manifest = None
        for m in builtins.values():
            if m.implementation.handler == ability_type:
                manifest = m
                break

        if manifest is None:
            raise ManifestNotFoundError(
                f"No builtin manifest found for ability type: '{ability_type}'"
            )

        return cls(
            ability_name=manifest.full_name,
            tool_schema=manifest.tool,
            permissions=manifest.metadata.permissions,
            implementation=manifest.implementation,
            hooks=manifest.hooks,
        )


@dataclass
class ResolvedAgent:
    """解析后的 Agent：可直接用于 spawn。"""

    config: AgentConfig
    abilities: list[ResolvedAbility]


class ManifestResolver:
    """Agent Manifest 解析器。

    将 AgentManifest 解析为 ResolvedAgent，包含 AgentConfig 和
    解析后的 ResolvedAbility 列表。
    """

    def __init__(self, ability_store: ManifestStoreProtocol) -> None:
        self._store = ability_store

    def resolve(
        self, manifest: AgentManifest, runtime_name: str | None = None
    ) -> ResolvedAgent:
        """将 AgentManifest 解析为 ResolvedAgent。

        Args:
            manifest: 已校验的 AgentManifest 对象
            runtime_name: 运行时名称，覆盖 manifest.metadata.name

        Returns:
            包含 AgentConfig 和 ResolvedAbility 列表的 ResolvedAgent

        Raises:
            ManifestNotFoundError: ref 引用的能力不存在
            ManifestValidationError: type 引用的能力未注册
        """
        config = self._build_config(manifest, runtime_name)
        abilities = self._resolve_abilities(manifest.abilities)
        return ResolvedAgent(config=config, abilities=abilities)

    def _build_config(
        self, manifest: AgentManifest, runtime_name: str | None
    ) -> AgentConfig:
        """从 AgentManifest 构建 AgentConfig。"""
        name = runtime_name or manifest.metadata.name
        agent_config_name = manifest.model.agent_config_name
        system_prompt = manifest.system_prompt
        max_iterations = manifest.max_iterations
        communication_timeout = manifest.communication_timeout

        window: WindowConfig | None = None
        context: ContextConfig | None = None

        if manifest.context:
            if manifest.context.window:
                window = _build_window_config(manifest.context.window)
            if manifest.context.persistence:
                context = _build_context_config(manifest.context.persistence)

        model_overrides = _build_model_overrides(manifest.model)

        return AgentConfig(
            name=name,
            agent_config_name=agent_config_name,
            system_prompt=system_prompt,
            max_iterations=max_iterations,
            communication_timeout=communication_timeout,
            window=window,
            context=context,
            model_overrides=model_overrides,
        )

    def _resolve_abilities(
        self, ability_refs: list[AbilityRef]
    ) -> list[ResolvedAbility]:
        """解析 AbilityRef 列表为 ResolvedAbility 列表。

        对于 ref 引用：从 store 加载 AbilityManifest，合并权限。
        对于 type 引用：从 builtin 加载。
        """
        resolved: list[ResolvedAbility] = []
        for ref in ability_refs:
            if ref.ref:
                ability_manifest = self._store.load_ability(ref.ref)
                permissions = ability_manifest.metadata.permissions.merge(
                    ref.permissions
                )
                r = ResolvedAbility(
                    ability_name=ability_manifest.full_name,
                    tool_schema=ability_manifest.tool,
                    permissions=permissions,
                    implementation=ability_manifest.implementation,
                    hooks=ability_manifest.hooks,
                )
            elif ref.type:
                r = ResolvedAbility.from_builtin(ref.type)
                if ref.permissions:
                    r = dataclasses.replace(
                        r, permissions=r.permissions.merge(ref.permissions)
                    )
            else:
                raise ManifestValidationError(
                    "AbilityRef must have either 'ref' or 'type'"
                )
            resolved.append(r)
        return resolved


def _build_window_config(overrides: WindowOverrides) -> WindowConfig:
    """从 WindowOverrides 构建 WindowConfig。"""
    return WindowConfig(
        max_tokens=overrides.max_tokens if overrides.max_tokens is not None else 4096,
        strategies=overrides.strategies if overrides.strategies is not None else ["tool_call_fold", "truncation"],
        tool_call_max_length=overrides.tool_call_max_length if overrides.tool_call_max_length is not None else 500,
        sliding_window_size=overrides.sliding_window_size if overrides.sliding_window_size is not None else 20,
    )


def _build_context_config(overrides: PersistenceOverrides) -> ContextConfig:
    """从 PersistenceOverrides 构建 ContextConfig。"""
    return ContextConfig(
        persistence_type=overrides.type,
        persistence_compress=overrides.compress if overrides.compress is not None else True,
        auto_persist=overrides.auto_persist if overrides.auto_persist is not None else False,
        snapshot_interval=overrides.snapshot_interval if overrides.snapshot_interval is not None else 5,
    )


def _build_model_overrides(model: ModelConfig) -> ModelOverrides | None:
    """从 AgentManifest.model 构建 ModelOverrides。

    仅在至少一个覆盖字段非 None 时返回 ModelOverrides，
    否则返回 None（表示无覆盖）。
    """
    if not any(
        v is not None
        for v in [model.temperature, model.max_tokens, model.top_p, model.top_k]
    ):
        return None
    return ModelOverrides(
        temperature=model.temperature,
        max_tokens=model.max_tokens,
        top_p=model.top_p,
        top_k=model.top_k,
    )
