# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""ExecutionData tests."""

from __future__ import annotations

from ghrah.abilities.execution_data import (
    CUMULATIVE_TOKEN_USAGE,
    LLM_RESPONSE,
    TOOL_ARGS,
    ExecutionData,
)


def test_get_set_update_and_raw_share_backing_dict() -> None:
    raw = {"llm_response": "hello"}
    data = ExecutionData(raw)

    assert data.get(LLM_RESPONSE) == "hello"

    data.set(TOOL_ARGS, {"file_path": "a.txt"})
    data.update({"extra": True})

    assert raw["tool_args"] == {"file_path": "a.txt"}
    assert raw["extra"] is True
    assert data.raw is raw


def test_snapshot_is_deep_copy() -> None:
    data = ExecutionData()
    data.set(CUMULATIVE_TOKEN_USAGE, {"input": 1})

    snapshot = data.snapshot()
    snapshot["cumulative_token_usage"]["input"] = 99

    assert data.get(CUMULATIVE_TOKEN_USAGE) == {"input": 1}
