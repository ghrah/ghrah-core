# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import Protocol

from ghrah.manifest.ability import AbilityManifest
from ghrah.manifest.agent import AgentManifest

__all__ = ["ManifestStoreProtocol"]


class ManifestStoreProtocol(Protocol):
    """Manifest 存储能力接口（Core 侧不关心具体实现）。"""

    def load_ability(self, full_name: str) -> AbilityManifest:
        """根据 full_name 加载 AbilityManifest。"""
        ...

    def load_agent(self, full_name: str) -> AgentManifest:
        """根据 full_name 加载 AgentManifest。"""
        ...

    def list_abilities(self, namespace: str | None = None) -> list[str]:
        """列出所有能力 full_name，可选按 namespace 过滤。"""
        ...

    def list_agents(self, namespace: str | None = None) -> list[str]:
        """列出所有 agent full_name，可选按 namespace 过滤。"""
        ...
