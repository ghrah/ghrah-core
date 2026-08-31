# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""Indexed storage for hooks."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ghrah.abilities.hooks import HookPoint

if TYPE_CHECKING:
    from ghrah.abilities.hooks import Hook

__all__ = ["HookListView", "HookStore"]


@dataclass(eq=False)
class _HookEntry:
    owner: str
    hook: Hook
    legacy: bool


class HookListView:
    """Small compatibility view for legacy agent._all_hooks helpers."""

    def __init__(self, store: HookStore, owner: str) -> None:
        self._store = store
        self._owner = owner

    def __len__(self) -> int:
        return len(self._store.list_all())

    def __iter__(self) -> Iterator[Hook]:
        return iter(self._store.list_all())

    def __getitem__(self, index: int | slice) -> Hook | list[Hook]:
        return self._store.list_all()[index]

    def __eq__(self, other: object) -> bool:
        return self._store.list_all() == other

    def append(self, hook: Hook) -> None:
        self._store.add_hooks(self._owner, [hook])

    def extend(self, hooks: Iterable[Hook]) -> None:
        self._store.add_hooks(self._owner, hooks)

    def clear(self) -> None:
        self._store.remove_owner(self._owner)


class HookStore:
    """Store hooks by owner and select them by point/ability."""

    AGENT_OWNER = "__agent_hooks__"

    def __init__(self) -> None:
        self._entries: list[_HookEntry] = []
        self._global_by_point: dict[HookPoint, list[_HookEntry]] = defaultdict(list)
        self._by_point_and_ability: dict[
            tuple[HookPoint, str], list[_HookEntry]
        ] = defaultdict(list)
        self._legacy_by_point: dict[HookPoint, list[_HookEntry]] = defaultdict(list)

    def view(self, owner: str = AGENT_OWNER) -> HookListView:
        """Return a compatibility view that can append hooks for an owner."""

        return HookListView(self, owner)

    def add_hooks(self, owner: str, hooks: Iterable[Hook]) -> None:
        """Add hooks owned by an ability or agent-level owner."""

        for hook in hooks:
            entry = _HookEntry(owner=owner, hook=hook, legacy=getattr(hook, "scope", None) is None)
            self._entries.append(entry)
            self._index(entry)

    def remove_owner(self, owner: str) -> None:
        """Remove all hooks associated with an owner."""

        self._entries = [entry for entry in self._entries if entry.owner != owner]
        self._rebuild_indexes()

    def list_all(self) -> list[Hook]:
        """Return hooks in registration order."""

        return [entry.hook for entry in self._entries]

    def select(self, point: HookPoint, ability_name: str = "") -> list[Hook]:
        """Select hooks matching a point and optional ability name."""

        candidate_entries = set(self._global_by_point.get(point, []))
        candidate_entries.update(self._legacy_by_point.get(point, []))
        if ability_name:
            candidate_entries.update(self._by_point_and_ability.get((point, ability_name), []))
        return [entry.hook for entry in self._entries if entry in candidate_entries]

    def is_legacy(self, hook: Hook) -> bool:
        """Return True when a hook has no declarative scope."""

        return getattr(hook, "scope", None) is None

    def _index(self, entry: _HookEntry) -> None:
        hook = entry.hook
        scope = getattr(hook, "scope", None)
        if scope is None:
            self._legacy_by_point[hook.hook_point].append(entry)
            return

        for point in scope.points:
            if scope.target_abilities is None:
                self._global_by_point[point].append(entry)
            else:
                for ability_name in scope.target_abilities:
                    self._by_point_and_ability[(point, ability_name)].append(entry)

    def _rebuild_indexes(self) -> None:
        self._global_by_point = defaultdict(list)
        self._by_point_and_ability = defaultdict(list)
        self._legacy_by_point = defaultdict(list)
        for entry in self._entries:
            self._index(entry)
