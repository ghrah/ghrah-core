# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""Execution frame shared by hook and drive-loop contexts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ghrah.abilities.execution_data import ExecutionData
from ghrah.abilities.execution_services import ExecutionServices

if TYPE_CHECKING:
    from ghrah.types.results import ActionResult

__all__ = ["ExecutionFrame"]


@dataclass
class ExecutionFrame:
    """Stateful frame for an execution step."""

    data: ExecutionData = field(default_factory=ExecutionData)
    services: ExecutionServices = field(default_factory=ExecutionServices)
    agent_state: dict[str, Any] = field(default_factory=dict)
    last_action_result: ActionResult | None = None
    current_node_id: str | None = None
