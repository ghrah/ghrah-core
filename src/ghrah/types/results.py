# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""Action 执行结果类型 — 纯数据定义，零内部依赖。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ActionOutcome(str, Enum):
    """Action 执行结果类型。"""

    SUCCESS = "success"
    FAILURE = "failure"
    NEEDS_INPUT = "needs_input"
    DELEGATE = "delegate"


@dataclass
class ActionResult:
    """Action 执行结果。

    Attributes:
        outcome: 执行结果类型
        data: 结果数据（如工具返回的内容、错误信息等）
        next_action_hint: 建议的下一个 action 名称，为 None 表示任务完成
    """

    outcome: ActionOutcome
    data: dict[str, Any] = field(default_factory=dict)
    next_action_hint: str | None = None
