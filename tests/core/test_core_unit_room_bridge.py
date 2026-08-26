# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""CoreUnit room bridge 接线测试：ctx.serial 存在 → SupervisorActor 持 bridge；
standalone（无 serial）→ bridge 为 None（send 工具明确报错）。"""

from __future__ import annotations

from typing import Any

from ghrah.core.room_protocol import SerialRoomBridge
from ghrah.core.unit import CoreUnit, CoreUnitConfig


def _config() -> CoreUnitConfig:
    return CoreUnitConfig(cluster_id="test-cluster")


class _FakeCtx:
    """宿主 ctx duck-type：emit/provide/serial 可控。"""

    def __init__(self, *, with_serial: bool = True) -> None:
        self.provided: dict[str, Any] = {}
        self._serial_enabled = with_serial

    def emit(self, name: str, payload: dict[str, Any]) -> None:
        pass

    def provide(self, name: str, value: Any) -> None:
        self.provided[name] = value

    def serial(self, name: str, payload: dict[str, Any]) -> Any:
        return {"success": True, "data": {}}


class _NoSerialCtx:
    """宿主 ctx duck-type：仅 emit/provide（standalone 场景，无 serial）。"""

    def __init__(self) -> None:
        self.provided: dict[str, Any] = {}

    def emit(self, name: str, payload: dict[str, Any]) -> None:
        pass

    def provide(self, name: str, value: Any) -> None:
        self.provided[name] = value


async def test_init_wires_room_bridge_from_ctx_serial() -> None:
    unit = CoreUnit(_config())
    await unit.init(_FakeCtx(with_serial=True))
    supervisor = unit.supervisor
    assert supervisor is not None
    assert isinstance(supervisor.room_bridge, SerialRoomBridge)


async def test_init_without_serial_leaves_bridge_none() -> None:
    unit = CoreUnit(_config())
    await unit.init(_NoSerialCtx())
    supervisor = unit.supervisor
    assert supervisor is not None
    assert supervisor.room_bridge is None
