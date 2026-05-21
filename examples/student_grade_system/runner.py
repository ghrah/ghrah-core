# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""StudentGradeRunner：ManifestRunner 扩展版 — 学生成绩管理系统示例。

扩展功能：
1. CompositeManifestStore：组合 builtin + 自定义 abilities 的 manifest store
2. 注册自定义 Ability (InitProjectAbility)
3. Git 辅助方法：init / commit / log / diff
4. 扩展 _instantiate_ability 支持自定义 handler

基于 ghrah-core/examples/agents_manifest/runner.py 扩展。
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from abilities_impl.init_project import InitProjectAbility
from abilities_impl.list_directory import StudentGradeListDirectoryAbility

from ghrah.abilities.base import Ability
from ghrah.abilities.builtin import (
    ConversationAbility,
    EditFileAbility,
    EndTaskAbility,
    FSPermissionChecker,
    ReadFileAbility,
    WriteFileAbility,
)
from ghrah.core.config import AgentConfig
from ghrah.manifest.ability import AbilityManifest
from ghrah.manifest.agent import AgentManifest
from ghrah.manifest.errors import ManifestNotFoundError
from ghrah.manifest.parser import parse_ability_manifest
from ghrah.manifest.protocols import ManifestStoreProtocol
from ghrah.manifest.resolver import ManifestResolver, ResolvedAbility
from ghrah.manifest.store import BuiltinManifestStore
from ghrah.manifest.types import PermissionFlags

logger = logging.getLogger(__name__)

_HANDLER_TO_ABILITY: dict[str, type[Ability]] = {
    "conversation": ConversationAbility,
    "end_task": EndTaskAbility,
    "read_file": ReadFileAbility,
    "write_file": WriteFileAbility,
    "edit_file": EditFileAbility,
    "list_directory": StudentGradeListDirectoryAbility,
    "init_project": InitProjectAbility,
}


class CompositeManifestStore(ManifestStoreProtocol):
    """组合 ManifestStore：builtin stores + 自定义 abilities。

    支持从 builtin 加载标准 abilities，同时允许注册自定义 ability manifests，
    使得 Agent Manifest 可以通过 ref 引用自定义 abilities。
    """

    def __init__(self) -> None:
        self._builtin = BuiltinManifestStore()
        self._custom_abilities: dict[str, AbilityManifest] = {}

    def register_ability(self, manifest: AbilityManifest) -> None:
        full_name = manifest.full_name
        self._custom_abilities[full_name] = manifest
        logger.info("Registered custom ability manifest: %s", full_name)

    def register_ability_from_file(self, yaml_path: Path) -> None:
        raw = yaml_path.read_text(encoding="utf-8")
        manifest = parse_ability_manifest(raw)
        self.register_ability(manifest)

    def load_ability(self, full_name: str) -> AbilityManifest:
        if full_name in self._custom_abilities:
            return self._custom_abilities[full_name]
        return self._builtin.load_ability(full_name)

    def load_agent(self, full_name: str) -> AgentManifest:
        raise ManifestNotFoundError(f"Agent manifest not found: {full_name}")

    def list_abilities(self, namespace: str | None = None) -> list[str]:
        builtin_list = self._builtin.list_abilities(namespace)
        custom_list = [
            name
            for name in self._custom_abilities
            if namespace is None or name.startswith(namespace)
        ]
        return builtin_list + custom_list


@dataclass
class GitLogEntry:
    commit_hash: str
    message: str
    timestamp: str
    author: str


class StudentGradeRunner:
    """ManifestRunner 扩展版，支持自定义 abilities 和 Git 管理。"""

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
        self._store = CompositeManifestStore()
        self._resolver = ManifestResolver(self._store)

    @property
    def workspace(self) -> Path:
        return self._workspace

    @property
    def persistence_dir(self) -> Path:
        return self._persistence_dir

    @property
    def session_id(self) -> str:
        return self._session_id

    def register_ability_manifest(self, yaml_path: Path) -> None:
        self._store.register_ability_from_file(yaml_path)

    def load_manifest(self, yaml_path: Path) -> AgentManifest:
        from ghrah.manifest.parser import parse_agent_manifest

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

    def _patch_context(self, resolved: Any) -> None:
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

        if handler == "init_project":
            return InitProjectAbility(workspace_root=str(self._workspace))

        if handler in ("conversation",):
            return ability_cls()
        if handler == "end_task":
            return ability_cls(mode="toolcall")

        checker = self._make_permission_checker(ra.permissions)
        if handler == "read_file":
            return ReadFileAbility(permission_checker=checker)
        if handler == "write_file":
            return WriteFileAbility(permission_checker=checker)
        if handler == "edit_file":
            return EditFileAbility(permission_checker=checker)
        if handler == "list_directory":
            return StudentGradeListDirectoryAbility(permission_checker=checker)

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

    @staticmethod
    def git_init(directory: Path) -> None:
        if not directory.exists():
            directory.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init"], cwd=directory, capture_output=True, check=True)
        subprocess.run(
            ["git", "config", "user.email", "agent@ghrah.local"],
            cwd=directory,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "ghrah-agent"],
            cwd=directory,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "commit.gpgsign", "false"],
            cwd=directory,
            capture_output=True,
            check=True,
        )
        marker = directory / ".gitkeep"
        marker.touch()
        subprocess.run(["git", "add", "-A"], cwd=directory, capture_output=True, check=True)
        result = subprocess.run(
            ["git", "commit", "-m", "Initial commit"],
            cwd=directory,
            capture_output=True,
        )
        if result.returncode != 0:
            logger.warning("Initial commit failed (may be empty): %s", result.stderr.decode())

    @staticmethod
    def git_commit(directory: Path, message: str) -> str:
        subprocess.run(["git", "add", "-A"], cwd=directory, capture_output=True, check=True)
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=directory,
            capture_output=True,
            text=True,
        )
        if not status.stdout.strip():
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=directory,
                capture_output=True,
                text=True,
                check=True,
            )
            return result.stdout.strip()

        result = subprocess.run(
            ["git", "commit", "-m", message],
            cwd=directory,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            logger.error("Git commit failed: %s", result.stderr)
            raise RuntimeError(f"Git commit failed: {result.stderr}")

        hash_result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=directory,
            capture_output=True,
            text=True,
            check=True,
        )
        commit_hash = hash_result.stdout.strip()
        logger.info("Committed %s: %s", commit_hash[:8], message)
        return commit_hash

    @staticmethod
    def git_log(directory: Path, max_count: int = 10) -> list[GitLogEntry]:
        result = subprocess.run(
            ["git", "log", f"-n{max_count}", "--format=%H|%s|%ai|%an"],
            cwd=directory,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return []

        entries: list[GitLogEntry] = []
        for line in result.stdout.strip().splitlines():
            if not line:
                continue
            parts = line.split("|", 3)
            if len(parts) == 4:
                entries.append(
                    GitLogEntry(
                        commit_hash=parts[0],
                        message=parts[1],
                        timestamp=parts[2],
                        author=parts[3],
                    )
                )
        return entries

    @staticmethod
    def git_diff(directory: Path, from_commit: str | None = None) -> str:
        args = ["git", "diff"]
        if from_commit:
            args.append(from_commit)
        result = subprocess.run(
            args,
            cwd=directory,
            capture_output=True,
            text=True,
        )
        return result.stdout

    @staticmethod
    def git_status(directory: Path) -> str:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=directory,
            capture_output=True,
            text=True,
        )
        return result.stdout
