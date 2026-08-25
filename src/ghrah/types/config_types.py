# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""配置纯数据类型 — 零内部依赖。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class WindowConfig:
    """窗口管理策略配置。

    控制如何将对话历史压缩到 LLM 的 token 预算内。

    Attributes:
        max_tokens: LLM 上下文窗口大小（token 预算）
        strategies: 策略名称列表，按执行顺序排列
            可选值: "tool_call_fold", "sliding_window", "truncation", "llm_summary"
        tool_call_max_length: ToolCallFoldStrategy 的最大 content 长度
        sliding_window_size: SlidingWindowStrategy 的窗口大小
    """

    max_tokens: int = 4096
    strategies: list[str] = field(default_factory=lambda: ["tool_call_fold", "truncation"])
    tool_call_max_length: int = 500
    sliding_window_size: int = 20


@dataclass
class ModelOverrides:
    """Manifest 模型配置覆盖值。

    这些值来自 AgentManifest.model，优先级高于 agentconf 解析结果。
    在 _ensure_llm() 中创建 ChatFormat 后覆盖对应属性。
    """

    temperature: float | None = None
    max_tokens: int | None = None
    top_p: float | None = None
    top_k: int | None = None


@dataclass
class ContextConfig:
    """ContextManager 配置。

    控制 ActorAgent 的上下文管理行为，包括持久化后端的选择。

    持久化后端通过 persistence_type 选择：
    - "json_file": JsonFileBackend（基于 JSON 文件，支持 gzip 压缩）
    - "memory": InMemoryBackend（纯内存，不持久化到磁盘）
    - "sqlite": SqliteBackend（基于 SQLite 数据库，WAL 模式支持并发读）
    - None: 不启用持久化

    Attributes:
        snapshot_interval: 消息快照间隔（每 N 次迭代存储一次完整快照），默认 5
        auto_persist: 是否在每次 commit/rollback 后自动持久化节点，默认 False
        persistence_type: 持久化后端类型，None 表示不启用持久化
        persistence_root_dir: 持久化存储根目录路径（json_file/sqlite 后端使用）
        persistence_compress: 是否启用 gzip 压缩持久化文件（json_file 后端），默认 True
        persistence_run_id: 持久化运行 ID，None 表示自动生成（格式：run_{ISO8601}）
    """

    snapshot_interval: int = 5
    auto_persist: bool = False
    persistence_type: str | None = None
    persistence_root_dir: str | None = None
    persistence_compress: bool = True
    persistence_run_id: str | None = None


@dataclass
class AgentConfig:
    """Agent 框架层配置。

    LLM 配置（provider、model、api_key 等）通过 agentconf SDK 管理，
    ActorAgent 初始化时会调用 `AgentsConfig().resolve_agent(effective_agent_config_name)`
    获取完整 LLM 配置。

    当多个运行时 Agent 共享同一份 LLM 配置时（如 worker 池场景），
    可通过 agent_config_name 指定 agentconf 中的配置名称，
    而 name 仅作为运行时唯一标识。

    Agent 的行为完全由注册的 Ability 组合决定（组合优于继承），
    不再通过 agent_type 隐式关联默认 Ability。

    Attributes:
        name: Agent 运行时唯一名称（用于 Actor 注册、消息路由、持久化路径）
        agent_config_name: agentconf 中的配置名称，None 时回退到 name（向后兼容）
        description: Agent 能力描述（用于 Agent 发现和路由）
        system_prompt: 系统提示词
        max_iterations: 最大推理迭代次数（生命周期语义，防止死循环的安全阀）
        communication_timeout: Agent 间通信超时时间（秒），-1 表示无限等待
        resources: 资源配置，如 {"CPU": 2, "GPU": 1}
        window: 窗口管理配置，None 表示不启用窗口管理
        context: ContextManager 配置，None 表示使用默认值
        model_overrides: Manifest 模型配置覆盖值
        workspace_root: 工作区根目录，用于将相对路径解析到沙盒内（None 表示不限制）
    """

    name: str
    agent_config_name: str | None = None
    description: str = ""
    system_prompt: str = ""
    max_iterations: int = 10
    communication_timeout: float = 300.0
    resources: dict[str, Any] = field(default_factory=dict)
    window: WindowConfig | None = None
    context: ContextConfig | None = None
    model_overrides: ModelOverrides | None = None
    workspace_root: str | None = None

    @property
    def effective_agent_config_name(self) -> str:
        """获取有效的 agentconf 查找名称。

        优先使用 agent_config_name，未指定时回退到 name（向后兼容）。
        """
        return self.agent_config_name or self.name

