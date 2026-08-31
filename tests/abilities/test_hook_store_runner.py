# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""HookStore and HookRunner tests."""

from __future__ import annotations

import pytest

from ghrah.abilities.context import AbilityExecutionContext
from ghrah.abilities.hook_context import HookContext
from ghrah.abilities.hook_runner import HookRunner
from ghrah.abilities.hook_store import HookStore
from ghrah.abilities.hooks import Hook, HookPoint, HookResult, HookScope
from ghrah.types.results import ActionResult


class CountingHook(Hook):
    def __init__(
        self,
        point: HookPoint,
        result: HookResult | None = None,
        *,
        scope: HookScope | None = None,
        should_trigger: bool = True,
    ) -> None:
        self.hook_point = point
        self.scope = scope
        self._result = result or HookResult.continue_()
        self._should_trigger = should_trigger
        self.should_trigger_count = 0
        self.execute_count = 0

    async def should_trigger(self, context: AbilityExecutionContext) -> bool:
        self.should_trigger_count += 1
        return self._should_trigger

    async def execute(
        self, context: AbilityExecutionContext, result: ActionResult | None
    ) -> HookResult:
        self.execute_count += 1
        return self._result


def test_hook_store_add_select_and_remove_owner() -> None:
    store = HookStore()
    global_hook = CountingHook(HookPoint.BEFORE_ACTION)
    targeted_hook = CountingHook(
        HookPoint.PRE_EXECUTE,
        scope=HookScope.for_abilities(HookPoint.PRE_EXECUTE, ["read_file"]),
    )

    store.add_hooks("global", [global_hook])
    store.add_hooks("read_file", [targeted_hook])

    assert store.select(HookPoint.BEFORE_ACTION) == [global_hook]
    assert store.select(HookPoint.PRE_EXECUTE, "read_file") == [targeted_hook]
    assert store.select(HookPoint.PRE_EXECUTE, "write_file") == []

    store.remove_owner("read_file")
    assert store.select(HookPoint.PRE_EXECUTE, "read_file") == []
    assert store.list_all() == [global_hook]


@pytest.mark.asyncio
async def test_hook_runner_legacy_hooks_call_should_trigger() -> None:
    store = HookStore()
    hook = CountingHook(
        HookPoint.PRE_EXECUTE,
        HookResult(data_updates={"hook_modified": True}),
    )
    store.add_hooks("legacy", [hook])
    runner = HookRunner(store)
    context = AbilityExecutionContext(current_ability_name="read_file", accumulated_data={})

    result = await runner.run(HookContext.from_ability_context(HookPoint.PRE_EXECUTE, context))

    assert result is not None
    assert hook.should_trigger_count == 1
    assert hook.execute_count == 1
    assert context.accumulated_data == {"hook_modified": True}
    assert result.modified_context == {"hook_modified": True}
    assert result.data_updates == {"hook_modified": True}


@pytest.mark.asyncio
async def test_hook_runner_scoped_hooks_skip_should_trigger() -> None:
    store = HookStore()
    hook = CountingHook(
        HookPoint.PRE_EXECUTE,
        scope=HookScope.for_abilities(HookPoint.PRE_EXECUTE, ["read_file"]),
        should_trigger=False,
    )
    store.add_hooks("read_file", [hook])
    runner = HookRunner(store)
    context = AbilityExecutionContext(current_ability_name="read_file")

    result = await runner.run(HookContext.from_ability_context(HookPoint.PRE_EXECUTE, context))

    assert result is not None
    assert hook.should_trigger_count == 0
    assert hook.execute_count == 1
