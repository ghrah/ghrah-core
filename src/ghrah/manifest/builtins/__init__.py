# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import functools
from collections.abc import Mapping
from importlib import resources

from ghrah.manifest.ability import AbilityManifest
from ghrah.manifest.parser import parse_ability_manifest

_BUILTIN_YAML_NAMES: tuple[str, ...] = (
    "ghrah.core.conversation",
    "ghrah.core.end_task",
    "ghrah.fs.read_file",
    "ghrah.fs.write_file",
    "ghrah.fs.edit_file",
    "ghrah.fs.delete_file",
    "ghrah.fs.move_file",
    "ghrah.fs.list_directory",
    "ghrah.shell.execute_command",
    "ghrah.cluster.query_agents",
    "ghrah.cluster.send_message",
    "ghrah.cluster.broadcast_message",
    "ghrah.cluster.spawn_agent",
)


def load_builtin_manifest(full_name: str) -> AbilityManifest:
    yaml_name = f"{full_name}.yaml"
    raw = resources.files(__package__).joinpath(yaml_name).read_text(encoding="utf-8")
    return parse_ability_manifest(raw)


@functools.lru_cache(maxsize=1)
def load_all_builtin_manifests() -> Mapping[str, AbilityManifest]:
    return {name: load_builtin_manifest(name) for name in _BUILTIN_YAML_NAMES}
