# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""AgentConfig 测试。"""

from ghrah.core.config import AgentConfig


class TestAgentConfig:
    """AgentConfig 数据类测试。"""

    def test_defaults(self):
        """默认值。"""
        config = AgentConfig(name="test")
        assert config.name == "test"
        assert config.agent_config_name is None
        assert config.description == ""
        assert config.system_prompt == ""
        assert config.max_iterations == 10
        assert config.communication_timeout == 300.0
        assert config.resources == {}
        assert config.window is None
        assert config.context is None

    def test_custom_values(self):
        """自定义值。"""
        config = AgentConfig(
            name="reviewer",
            description="代码审查助手",
            system_prompt="你是一个代码审查专家",
            max_iterations=5,
            communication_timeout=600.0,
        )
        assert config.name == "reviewer"
        assert config.description == "代码审查助手"
        assert config.system_prompt == "你是一个代码审查专家"
        assert config.max_iterations == 5
        assert config.communication_timeout == 600.0

    def test_communication_timeout_infinite(self):
        """communication_timeout=-1 表示无限等待。"""
        config = AgentConfig(
            name="long_task",
            communication_timeout=-1,
        )
        assert config.communication_timeout == -1

    def test_agent_config_name_default_none(self):
        """agent_config_name 默认为 None。"""
        config = AgentConfig(name="planner")
        assert config.agent_config_name is None

    def test_effective_agent_config_name_fallback_to_name(self):
        """effective_agent_config_name 在 agent_config_name 为 None 时回退到 name。"""
        config = AgentConfig(name="planner")
        assert config.effective_agent_config_name == "planner"

    def test_effective_agent_config_name_explicit(self):
        """effective_agent_config_name 在指定 agent_config_name 时使用显式值。"""
        config = AgentConfig(
            name="solve_worker_3",
            agent_config_name="solve_worker",
        )
        assert config.name == "solve_worker_3"
        assert config.agent_config_name == "solve_worker"
        assert config.effective_agent_config_name == "solve_worker"

    def test_effective_agent_config_name_empty_string_fallback(self):
        """effective_agent_config_name 在 agent_config_name 为空字符串时回退到 name。"""
        config = AgentConfig(name="planner", agent_config_name="")
        # 空字符串是 falsy，应回退到 name
        assert config.effective_agent_config_name == "planner"

    def test_worker_pool_scenario(self):
        """Worker 池场景：多个 worker 共享同一份 agentconf 配置。"""
        config = AgentConfig(
            name="solve_worker_0",
            agent_config_name="solve_worker",
            description="解题 Worker #0",
        )
        assert config.name == "solve_worker_0"
        assert config.effective_agent_config_name == "solve_worker"

    def test_role_alias_scenario(self):
        """角色别名场景：不同运行时名称，共享同一份 LLM 配置。"""
        config = AgentConfig(
            name="code_reviewer_v2",
            agent_config_name="reviewer",
            description="代码审查专家 v2",
        )
        assert config.name == "code_reviewer_v2"
        assert config.effective_agent_config_name == "reviewer"
