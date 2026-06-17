# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""ExecutionServices tests."""

from __future__ import annotations

import pytest

from ghrah.abilities.execution_services import AGENT_NAME, CONTEXT_MANAGER, ExecutionServices


def test_get_set_and_require() -> None:
    context_manager = object()
    services = ExecutionServices({AGENT_NAME: "agent-a"})
    services.set(CONTEXT_MANAGER, context_manager)

    assert services.get(AGENT_NAME) == "agent-a"
    assert services.require(CONTEXT_MANAGER) is context_manager


def test_require_missing_raises_clear_error() -> None:
    services = ExecutionServices()

    with pytest.raises(RuntimeError, match="context_manager"):
        services.require(CONTEXT_MANAGER)


def test_snapshot_is_shallow_copy() -> None:
    services = ExecutionServices({AGENT_NAME: "agent-a"})

    snapshot = services.snapshot()
    snapshot["agent_name"] = "changed"

    assert services.get(AGENT_NAME) == "agent-a"
