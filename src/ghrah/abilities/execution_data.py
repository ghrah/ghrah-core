# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""Typed keys and mutable data bus for ability execution."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Generic, TypeVar, cast

__all__ = [
    "COT_CONTENT",
    "CUMULATIVE_TOKEN_USAGE",
    "DataKey",
    "ExecutionData",
    "FINAL_RESPONSE",
    "LLM_RESPONSE",
    "TOOL_ARGS",
]

T = TypeVar("T")


@dataclass(frozen=True)
class DataKey(Generic[T]):
    """Typed key for values stored in ExecutionData."""

    name: str
    value_type: type[Any] | tuple[type[Any], ...]


class ExecutionData:
    """Mutable execution data shared across facade and hook contexts."""

    def __init__(self, initial: Mapping[str, Any] | None = None) -> None:
        if initial is None:
            self._raw: dict[str, Any] = {}
        elif isinstance(initial, dict):
            self._raw = initial
        else:
            self._raw = dict(initial)

    @property
    def raw(self) -> dict[str, Any]:
        """Return the backing dict for compatibility with accumulated_data."""

        return self._raw

    def get(self, key: DataKey[T], default: T | None = None) -> T | None:
        """Read a value by typed key."""

        return cast(T | None, self._raw.get(key.name, default))

    def set(self, key: DataKey[T], value: T) -> None:
        """Set a value by typed key."""

        self._raw[key.name] = value

    def update(
        self,
        values: Mapping[str, Any] | ExecutionData | None = None,
        **kwargs: Any,
    ) -> None:
        """Update the backing data with raw key/value pairs."""

        if isinstance(values, ExecutionData):
            self._raw.update(values.raw)
        elif values is not None:
            self._raw.update(values)
        if kwargs:
            self._raw.update(kwargs)

    def snapshot(self) -> dict[str, Any]:
        """Return a deep-copy snapshot of the data."""

        return copy.deepcopy(self._raw)


TOOL_ARGS = DataKey[dict[str, Any]]("tool_args", dict)
LLM_RESPONSE = DataKey[str]("llm_response", str)
COT_CONTENT = DataKey[str]("cot_content", str)
CUMULATIVE_TOKEN_USAGE = DataKey[dict[str, int]]("cumulative_token_usage", dict)
FINAL_RESPONSE = DataKey[str]("response", str)
