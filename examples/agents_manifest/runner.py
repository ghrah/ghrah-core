# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""ManifestRunner：基于系统 ManifestResolver 的示例运行时桥接。

负责 ManifestResolver 之后的"最后一英里"：
1. 加载 YAML manifest 文件，替换模板变量
2. 调用 ManifestResolver.resolve() 获取 ResolvedAgent（AgentConfig + ResolvedAbility[]）
3. 将 ResolvedAbility 实例化为 Ability 对象（含权限配置）
4. 补充运行时上下文（persistence_root_dir、session_id）

模板变量：
    YAML 中的 {{workspace}}、{{persistence_dir}}、{{session_id}} 占位符
    在加载时进行字符串替换。

用法：
    runner = ManifestRunner(
        workspace=Path("/tmp/workspace"),
        persistence_dir=Path("/tmp/persistence"),
        session_id="session_2026-04-29",
    )
    config, abilities = runner.resolve(manifest)
    await supervisor.spawn_agent(config, abilities=abilities)
"""

from __future__ import annotations

import logging
from pathlib import Path

from ghrah.abilities.base import Ability
from ghrah.abilities.builtin import (
    ConversationAbility,
    EndTaskAbility,
    FSPermissionChecker,
    ListDirectoryAbility,
    ReadFileAbility,
    WriteFileAbility,
)
from ghrah.core.config import AgentConfig
from ghrah.manifest.agent import AgentManifest
from ghrah.manifest.parser import parse_agent_manifest
from ghrah.manifest.resolver import ManifestResolver, ResolvedAbility, ResolvedAgent
from ghrah.manifest.store import BuiltinManifestStore
from ghrah.manifest.types import PermissionFlags

logger = logging.getLogger(__name__)

_HANDLER_TO_ABILITY: dict[str, type[Ability]] = {
    "conversation": ConversationAbility,
    "end_task": EndTaskAbility,
    "read_file": ReadFileAbility,
    "write_file": WriteFileAbility,
    "list_directory": ListDirectoryAbility,
}


class ManifestRunner:
    def __init__(
        self,
        workspace: Path,
        persistence_dir: Path,
        session_id: str,
    ) -> None:
        self._workspace = workspace
        self._persistence_dir = persistence_dir
        self._session_id = session_id
        self._template_vars: dict[str, str] = {
            "workspace": str(workspace),
            "persistence_dir": str(persistence_dir),
            "session_id": session_id,
        }
        store = BuiltinManifestStore()
        self._resolver = ManifestResolver(store)

    @property
    def workspace(self) -> Path:
        return self._workspace

    @property
    def persistence_dir(self) -> Path:
        return self._persistence_dir

    @property
    def session_id(self) -> str:
        return self._session_id

    def load_manifest(self, yaml_path: Path) -> AgentManifest:
        raw = yaml_path.read_text(encoding="utf-8")
        raw = self._apply_template_vars(raw)
        return parse_agent_manifest(raw)

    def load_manifests_from_dir(self, agents_dir: Path) -> list[AgentManifest]:
        manifests: list[AgentManifest] = []
        for yaml_file in sorted(agents_dir.glob("*.yaml")):
            manifest = self.load_manifest(yaml_file)
            manifests.append(manifest)
            logger.info(
                "Loaded agent manifest: %s from %s",
                manifest.full_name,
                yaml_file.name,
            )
        return manifests

    def resolve(self, manifest: AgentManifest) -> tuple[AgentConfig, list[Ability]]:
        resolved = self._resolver.resolve(manifest)
        self._patch_context(resolved)
        abilities = self._instantiate_abilities(resolved.abilities)
        return resolved.config, abilities

    def _apply_template_vars(self, raw: str) -> str:
        for key, value in self._template_vars.items():
            raw = raw.replace("{{" + key + "}}", value)
        return raw

    def _patch_context(self, resolved: ResolvedAgent) -> None:
        config = resolved.config
        if config.context is not None and config.context.persistence_type is not None:
            config.context.persistence_root_dir = str(self._persistence_dir)
            config.context.persistence_run_id = self._session_id

    def _instantiate_abilities(
        self, resolved_abilities: list[ResolvedAbility]
    ) -> list[Ability]:
        abilities: list[Ability] = []
        for ra in resolved_abilities:
            ability = self._instantiate_ability(ra)
            abilities.append(ability)
        return abilities

    def _instantiate_ability(self, ra: ResolvedAbility) -> Ability:
        handler = ra.implementation.handler
        if handler is None:
            raise ValueError(
                f"ResolvedAbility {ra.ability_name} has no implementation.handler"
            )

        ability_cls = _HANDLER_TO_ABILITY.get(handler)
        if ability_cls is None:
            raise ValueError(
                f"Unknown builtin handler: {handler!r} (from {ra.ability_name}). "
                f"Known handlers: {sorted(_HANDLER_TO_ABILITY)}"
            )

        if handler in ("conversation",):
            return ability_cls()
        if handler == "end_task":
            return ability_cls(mode="toolcall")

        checker = self._make_permission_checker(ra.permissions)
        if handler == "read_file":
            return ReadFileAbility(permission_checker=checker)
        if handler == "write_file":
            return WriteFileAbility(permission_checker=checker)
        if handler == "list_directory":
            return ListDirectoryAbility(permission_checker=checker)

        raise ValueError(f"Unhandled builtin handler with checker: {handler!r}")

    def _make_permission_checker(self, permissions: PermissionFlags) -> FSPermissionChecker:
        if not permissions.allowed_paths:
            return FSPermissionChecker(require_approval=permissions.require_hitl)
        resolved_paths = [
            self._apply_template_vars(p) for p in permissions.allowed_paths
        ]
        return FSPermissionChecker(
            allowed_paths=resolved_paths,
            require_approval=permissions.require_hitl,
        )
