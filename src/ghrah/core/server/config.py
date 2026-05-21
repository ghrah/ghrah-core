# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class CoreServerConfig:
    host: str = "0.0.0.0"
    port: int = 4111
    ws_path: str = "/ws"
    ping_interval: float = 30.0
    ping_timeout: float = 10.0
    command_timeout: float = 300.0
    ability_timeout: float = 120.0
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> CoreServerConfig:
        def _env(key: str, default: str) -> str:
            return os.environ.get(f"GHRAH_CORE_{key}", default)

        def _env_int(key: str, default: int) -> int:
            val = os.environ.get(f"GHRAH_CORE_{key}")
            if val is None:
                return default
            try:
                return int(val)
            except ValueError:
                raise ValueError(
                    f"Environment variable GHRAH_CORE_{key} must be an integer, got '{val}'"
                ) from None

        def _env_float(key: str, default: float) -> float:
            val = os.environ.get(f"GHRAH_CORE_{key}")
            if val is None:
                return default
            try:
                return float(val)
            except ValueError:
                raise ValueError(
                    f"Environment variable GHRAH_CORE_{key} must be a number, got '{val}'"
                ) from None

        return cls(
            host=_env("HOST", "0.0.0.0"),
            port=_env_int("PORT", 4111),
            ws_path=_env("WS_PATH", "/ws"),
            ping_interval=_env_float("PING_INTERVAL", 30.0),
            ping_timeout=_env_float("PING_TIMEOUT", 10.0),
            command_timeout=_env_float("COMMAND_TIMEOUT", 300.0),
            ability_timeout=_env_float("ABILITY_TIMEOUT", 120.0),
            log_level=_env("LOG_LEVEL", "INFO"),
        )
