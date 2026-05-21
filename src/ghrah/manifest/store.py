# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from functools import cached_property
from typing import TYPE_CHECKING

from ghrah.manifest.agent import AgentManifest
from ghrah.manifest.builtins import load_all_builtin_manifests
from ghrah.manifest.errors import ManifestNotFoundError

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ghrah.manifest.ability import AbilityManifest

__all__ = ["BuiltinManifestStore"]


class BuiltinManifestStore:
    """基于 builtins YAML 包的 ManifestStore 实现。

    仅支持 load_ability，不支持持久化写入。
    用于 P1 阶段的测试和基本集成。
    P2 的 ManifestStore 实现在 ghrah-subject 中提供完整文件系统 CRUD。

    内置 manifest 通过 cached_property 惰性加载，首次访问时解析 YAML。
    底层依赖 load_all_builtin_manifests() 的 lru_cache 缓存。
    """

    @cached_property
    def _builtins(self) -> Mapping[str, AbilityManifest]:
        return load_all_builtin_manifests()

    def load_ability(self, full_name: str) -> AbilityManifest:
        try:
            return self._builtins[full_name]
        except KeyError:
            raise ManifestNotFoundError(f"Ability manifest not found: {full_name}")

    def load_agent(self, full_name: str) -> AgentManifest:
        raise ManifestNotFoundError(f"Agent manifest not found: {full_name}")

    def list_abilities(self, namespace: str | None = None) -> list[str]:
        names = list(self._builtins.keys())
        if namespace:
            names = [n for n in names if n.startswith(f"{namespace}.")]
        return names

    def list_agents(self, namespace: str | None = None) -> list[str]:
        return []
