# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""Ability 领域异常。"""

from __future__ import annotations

from ghrah.core._base_error import ActorAgentError

__all__ = ["AbilityError", "AbilityNotFoundError"]


class AbilityError(ActorAgentError):
    """Ability 执行相关错误"""

    def __init__(self, ability_name: str, message: str):
        self.ability_name = ability_name
        super().__init__(f"Ability[{ability_name}]: {message}")


class AbilityNotFoundError(AbilityError):
    """Ability 未找到"""

    def __init__(self, ability_name: str):
        super().__init__(ability_name, f"Ability not found: {ability_name}")
