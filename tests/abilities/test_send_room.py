# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""SendAbility + SerialRoomBridge 测试：解析去重 / 空 targets / 未知 room /
serial 命令契约（room_get 展开 + room_send 落账）。
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

from ghrah.abilities.base import ActionOutcome
from ghrah.abilities.builtin.send import SendAbility
from ghrah.abilities.context import AbilityExecutionContext
from ghrah.core.room_protocol import ROOM_BRIDGE_UNAVAILABLE_ERROR, SerialRoomBridge


def _make_context(
    supervisor: Any,
    tool_args: dict[str, Any],
    agent_name: str = "architect",
) -> AbilityExecutionContext:
    return AbilityExecutionContext(
        supervisor=supervisor, agent_name=agent_name, tool_args=tool_args
    )


def _make_supervisor(room_bridge: Any) -> MagicMock:
    supervisor = MagicMock()
    supervisor.send = AsyncMock(return_value="ok")
    supervisor.room_bridge = room_bridge
    return supervisor


class _FakeBridge:
    """RoomBridge 假件：记录调用并返回可控结果。"""

    def __init__(
        self,
        rooms: dict[str, list[dict[str, Any]]] | None = None,
        fail_room: str | None = None,
    ) -> None:
        self.rooms = rooms or {}
        self.fail_room = fail_room
        self.resolve_calls: list[tuple[list[str], list[str] | None]] = []
        self.append_calls: list[tuple[str, str, dict[str, Any] | None]] = []

    async def resolve_recipients(
        self, room_ids: list[str], extra_targets: list[str] | None = None
    ) -> dict[str, Any]:
        self.resolve_calls.append((list(room_ids), extra_targets))
        recipients: list[str] = []
        seen: set[str] = set()
        for room_id in room_ids:
            if room_id == self.fail_room:
                return {"success": False, "error": f"room not found: {room_id}"}
            for member in self.rooms.get(room_id, []):
                if member["subject_type"] == "agent" and member["subject"] not in seen:
                    seen.add(member["subject"])
                    recipients.append(member["subject"])
        for t in extra_targets or []:
            if t not in seen:
                seen.add(t)
                recipients.append(t)
        return {"success": True, "data": {"recipients": recipients, "rooms": []}}

    async def append_room_log(
        self, room_id: str, author: str, data: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        self.append_calls.append((room_id, author, data))
        return {"success": True, "data": {"entry": {"room_id": room_id, "seq": 1}}}


# ── SendAbility ──


class TestSendAbility:
    def test_name_and_tool(self) -> None:
        ability = SendAbility()
        assert ability.name == "send"
        tool = ability.bind_tool()
        assert tool["function"]["name"] == "send"
        params = tool["function"]["parameters"]["properties"]
        assert set(params) == {"room_ids", "message", "targets"}

    async def test_no_supervisor(self) -> None:
        ctx = AbilityExecutionContext(
            supervisor=None, agent_name="a", tool_args={}
        )
        result = await SendAbility().execute(ctx)
        assert result.outcome == ActionOutcome.FAILURE
        assert "No supervisor" in result.data["error"]

    async def test_no_room_bridge(self) -> None:
        supervisor = _make_supervisor(room_bridge=None)
        ctx = _make_context(
            supervisor,
            {"room_ids": ["r1"], "message": "hi"},
        )
        result = await SendAbility().execute(ctx)
        assert result.outcome == ActionOutcome.FAILURE
        assert result.data["error"] == ROOM_BRIDGE_UNAVAILABLE_ERROR

    async def test_resolve_union_dedup_and_delivery(self) -> None:
        bridge = _FakeBridge(
            rooms={
                "r1": [
                    {"subject": "architect", "subject_type": "agent"},
                    {"subject": "frontend-dev", "subject_type": "agent"},
                    {"subject": "human:yuki", "subject_type": "human"},
                ],
                "r2": [
                    {"subject": "architect", "subject_type": "agent"},
                    {"subject": "tester", "subject_type": "agent"},
                ],
            }
        )
        supervisor = _make_supervisor(bridge)
        ctx = _make_context(
            supervisor,
            {"room_ids": ["r1", "r2"], "message": "hello", "targets": ["extern"]},
        )
        result = await SendAbility().execute(ctx)
        assert result.outcome == ActionOutcome.SUCCESS
        # human 成员不计；跨 room 去重；targets 并入
        assert result.data["recipients"] == [
            "architect", "frontend-dev", "tester", "extern",
        ]
        # 投递排除发送者自身
        assert result.data["delivered_to"] == ["frontend-dev", "tester", "extern"]
        # 逐 room 落账，data = {message, targets}
        assert [(c[0], c[1]) for c in bridge.append_calls] == [
            ("r1", "architect"), ("r2", "architect"),
        ]
        assert bridge.append_calls[0][2] == {
            "message": "hello", "targets": ["extern"],
        }

    async def test_empty_targets_broadcast_semantics(self) -> None:
        bridge = _FakeBridge(rooms={"r1": [{"subject": "a", "subject_type": "agent"}]})
        supervisor = _make_supervisor(bridge)
        ctx = _make_context(
            supervisor, {"room_ids": ["r1"], "message": "broadcast"}, agent_name="human"
        )
        result = await SendAbility().execute(ctx)
        assert result.outcome == ActionOutcome.SUCCESS
        assert result.data["delivered_to"] == ["a"]
        # 无 targets 时 data 不含 targets 键
        assert bridge.append_calls[0][2] == {"message": "broadcast"}

    async def test_unknown_room_fails(self) -> None:
        bridge = _FakeBridge(fail_room="missing")
        supervisor = _make_supervisor(bridge)
        ctx = _make_context(
            supervisor, {"room_ids": ["missing"], "message": "hi"}
        )
        result = await SendAbility().execute(ctx)
        assert result.outcome == ActionOutcome.FAILURE
        assert "room not found: missing" in result.data["error"]
        assert bridge.append_calls == []

    async def test_append_failure_reports_partial(self) -> None:
        class _PartialBridge(_FakeBridge):
            async def append_room_log(self, room_id, author, data=None):
                self.append_calls.append((room_id, author, data))
                if room_id == "r2":
                    return {"success": False, "error": "boom"}
                return {"success": True}

        bridge = _PartialBridge(rooms={
            "r1": [{"subject": "a", "subject_type": "agent"}],
            "r2": [{"subject": "b", "subject_type": "agent"}],
        })
        supervisor = _make_supervisor(bridge)
        ctx = _make_context(
            supervisor, {"room_ids": ["r1", "r2"], "message": "hi"}
        )
        result = await SendAbility().execute(ctx)
        assert result.outcome == ActionOutcome.FAILURE
        assert "failed to append room log" in result.data["error"]
        assert result.data["appended_rooms"] == ["r1"]

    async def test_invalid_args(self) -> None:
        bridge = _FakeBridge()
        supervisor = _make_supervisor(bridge)
        ctx = _make_context(supervisor, {"room_ids": [], "message": "hi"})
        result = await SendAbility().execute(ctx)
        assert result.outcome == ActionOutcome.FAILURE
        assert "invalid send args" in result.data["error"]


# ── SerialRoomBridge ──


class TestSerialRoomBridge:
    @staticmethod
    def _serial_router(routes: dict[str, Any]) -> AsyncMock:
        async def serial(name: str, payload: dict[str, Any]) -> Any:
            handler = routes.get(name)
            return handler(payload) if handler else None

        return serial

    async def test_resolve_via_room_get(self) -> None:
        calls: list[tuple[str, dict[str, Any]]] = []

        def room_get(payload: dict[str, Any]) -> dict[str, Any]:
            calls.append(("room_get", payload))
            members = (
                [
                    {"subject": "architect", "subject_type": "agent"},
                    {"subject": "tester", "subject_type": "agent"},
                    {"subject": "human:yuki", "subject_type": "human"},
                ]
                if payload["room_id"] == "r1"
                else [{"subject": "architect", "subject_type": "agent"}]
            )
            return {
                "success": True,
                "data": {"room": {"room_id": payload["room_id"], "members": members}},
            }

        serial = self._serial_router({"command/room_get": room_get})
        bridge = SerialRoomBridge(serial)  # type: ignore[arg-type]
        result = await bridge.resolve_recipients(["r1", "r2"], ["extern"])
        assert result["success"]
        assert result["data"]["recipients"] == ["architect", "tester", "extern"]
        assert len(calls) == 2

    async def test_resolve_missing_room(self) -> None:
        def room_get(payload: dict[str, Any]) -> dict[str, Any]:
            return {"success": False, "error": f"room not found: {payload['room_id']}"}

        serial = self._serial_router({"command/room_get": room_get})
        bridge = SerialRoomBridge(serial)  # type: ignore[arg-type]
        result = await bridge.resolve_recipients(["missing"])
        assert not result["success"]
        assert "room not found" in result["error"]

    async def test_append_via_room_send_contract(self) -> None:
        calls: list[tuple[str, dict[str, Any]]] = []

        def room_send(payload: dict[str, Any]) -> dict[str, Any]:
            calls.append(("room_send", payload))
            return {"success": True, "data": {"entry": {"seq": 1}}}

        serial = self._serial_router({"command/room_send": room_send})
        bridge = SerialRoomBridge(serial)  # type: ignore[arg-type]
        result = await bridge.append_room_log(
            "r1", author="architect", data={"message": "hi"}
        )
        assert result["success"]
        # D3 契约：command/room_send + author_type 固定 agent
        name, payload = calls[0]
        assert name == "room_send"
        assert payload == {
            "room_id": "r1",
            "author": "architect",
            "author_type": "agent",
            "data": {"message": "hi"},
        }
