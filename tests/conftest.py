# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import pytest

from ghrah.core.config import AgentConfig


@pytest.fixture
def sample_config() -> AgentConfig:
    """创建示例 AgentConfig。"""
    return AgentConfig(
        name="test-agent",
        description="Test agent",
        system_prompt="You are a test agent.",
    )
