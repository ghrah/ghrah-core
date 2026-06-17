# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""Ability invocation identity for a single ability call."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = ["AbilityInvocation"]


@dataclass(frozen=True)
class AbilityInvocation:
    """Identity and arguments for one ability invocation."""

    ability_name: str = ""
    tool_args: dict[str, Any] = field(default_factory=dict)
    tool_call_id: str = ""
