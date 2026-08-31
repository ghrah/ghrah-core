# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""AbilityExecutionContext facade compatibility tests."""

from __future__ import annotations

from ghrah.abilities.context import AbilityExecutionContext
from ghrah.abilities.execution_data import LLM_RESPONSE
from ghrah.abilities.execution_services import AGENT_NAME
from ghrah.abilities.invocation import AbilityInvocation


def test_old_constructor_populates_new_structures() -> None:
    ctx = AbilityExecutionContext(
        current_ability_name="conversation",
        accumulated_data={"llm_response": "hi"},
        agent_name="agent-a",
    )

    assert ctx.invocation.ability_name == "conversation"
    assert ctx.data.get(LLM_RESPONSE) == "hi"
    assert ctx.services.get(AGENT_NAME) == "agent-a"
    assert ctx.accumulated_data["llm_response"] == "hi"
    assert ctx.current_ability_name == "conversation"


def test_old_properties_share_new_backing_objects() -> None:
    ctx = AbilityExecutionContext(
        current_ability_name="read_file",
        tool_args={"file_path": "a.txt"},
        accumulated_data={},
    )

    ctx.tool_args["encoding"] = "utf-8"
    ctx.accumulated_data["llm_response"] = "done"

    assert ctx.invocation.tool_args == {"file_path": "a.txt", "encoding": "utf-8"}
    assert ctx.data.raw == {"llm_response": "done"}


def test_new_constructor_preserved_when_old_fields_absent() -> None:
    invocation = AbilityInvocation("write_file", {"file_path": "a.txt"}, "call-1")
    ctx = AbilityExecutionContext(invocation=invocation)

    assert ctx.current_ability_name == "write_file"
    assert ctx.tool_args == {"file_path": "a.txt"}
    assert ctx.invocation.tool_call_id == "call-1"
