# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""Agent 配置定义 — re-export from ghrah.types + config builders。

LLM 相关配置由 agentconf SDK 管理（Provider → LLM → Agent 层级继承），
本模块只定义框架层面的 Agent 行为配置。

所有配置数据类已提取到 ghrah.types.config_types，本模块仅保留 re-export
以保持向后兼容。

Builder 函数从各种输入源（dict / manifest dataclass）构建配置对象。
"""

from __future__ import annotations

from ghrah.types.config_types import (
    AgentConfig,
    ContextConfig,
    ModelOverrides,
    WindowConfig,
)

__all__ = [
    "AgentConfig",
    "ContextConfig",
    "ModelOverrides",
    "WindowConfig",
    ]
