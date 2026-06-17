# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""Single hook execution path for agents and local ability execution."""

from __future__ import annotations

from ghrah.abilities.hook_context import HookContext
from ghrah.abilities.hook_store import HookStore
from ghrah.abilities.hooks import HookResult
from ghrah.core.exceptions import HookError

__all__ = ["HookRunner"]


class HookRunner:
    """Run hooks selected from a HookStore."""

    def __init__(self, store: HookStore) -> None:
        self._store = store

    async def run(self, context: HookContext) -> HookResult | None:
        """Run matching hooks and merge their results."""

        merged: HookResult | None = None
        ability_context = context.to_ability_context()
        hooks = self._store.select(context.point, context.invocation.ability_name)

        for hook in hooks:
            if self._store.is_legacy(hook):
                try:
                    should_fire = await hook.should_trigger(ability_context)
                except Exception as e:
                    raise HookError(
                        context.point.value,
                        f"should_trigger failed for {type(hook).__name__}: {e}",
                    ) from e

                if not should_fire:
                    continue

            try:
                hook_result = await hook.execute(ability_context, context.result)
            except Exception as e:
                raise HookError(
                    context.point.value,
                    f"execute failed for {type(hook).__name__}: {e}",
                ) from e

            if merged is None:
                merged = hook_result
            else:
                merged = merged.merge(hook_result)

        if merged is not None and merged.modified_context:
            context.frame.data.update(merged.modified_context)

        return merged
