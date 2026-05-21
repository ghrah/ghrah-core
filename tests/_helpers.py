# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""共享测试辅助工厂函数。"""

from __future__ import annotations

from ghrah.abilities.base import ActionOutcome, ActionResult
from ghrah.context.node import ContextNode


def make_node(**overrides) -> ContextNode:
    """创建测试用 ContextNode。"""
    defaults = {
        "parent_id": None,
        "agent_name": "test-agent",
        "iteration": 0,
        "ability_names": ["init"],
        "agent_state": {"key": "value"},
        "messages_delta": [],
        "is_snapshot": True,
        "branch_name": "main",
    }
    defaults.update(overrides)
    return ContextNode(**defaults)


def make_action_result(
    outcome: ActionOutcome = ActionOutcome.SUCCESS,
    data: dict | None = None,
    hint: str | None = None,
) -> ActionResult:
    """创建测试用 ActionResult。"""
    return ActionResult(outcome=outcome, data=data or {}, next_action_hint=hint)
