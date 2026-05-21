# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""Agent 配置定义。

LLM 相关配置由 agentconf SDK 管理（Provider → LLM → Agent 层级继承），
本模块只定义框架层面的 Agent 行为配置。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ghrah.context.persistence.backend import PersistenceBackend

# 支持的持久化后端类型
PERSISTENCE_BACKEND_TYPES = ("json_file", "memory", "sqlite", "remote")


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
class ContextConfig:
    """ContextManager 配置。

    控制 ActorAgent 的上下文管理行为，包括持久化后端的选择。

    持久化后端通过 persistence_type 选择：
    - "json_file": JsonFileBackend（基于 JSON 文件，支持 gzip 压缩）
    - "memory": InMemoryBackend（纯内存，不持久化到磁盘）
    - "sqlite": SqliteBackend（基于 SQLite 数据库，WAL 模式支持并发读）
    - "remote": RemoteBackend（通过 CommandSender 将持久化操作委托给 Subject）
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
    _command_sender: Any = field(default=None, repr=False)
    _persistence_agent_name: str | None = field(default=None, repr=False)

    def set_command_sender(self, command_sender: Any, agent_name: str = "") -> None:
        """注入 CommandSender 实例供远程持久化后端使用。

        在新架构中，Core 服务器启动时应将 MessageRouter（实现 CommandSender 协议）
        注入到 ContextConfig，供 RemoteBackend 使用。

        Args:
            command_sender: CommandSender 实例（通常为 MessageRouter）
            agent_name: Agent 名称（用于远程持久化标识）
        """
        self._command_sender = command_sender
        self._persistence_agent_name = agent_name

    def set_core_client(self, core_client: Any, agent_name: str = "") -> None:
        """注入 CoreClient 实例供远程持久化后端使用（向后兼容，委托到 set_command_sender）。

        Args:
            core_client: CoreClient 实例（已废弃，请使用 set_command_sender）
            agent_name: Agent 名称（用于远程持久化标识）
        """
        self.set_command_sender(core_client, agent_name=agent_name)

    def create_persistence(self) -> PersistenceBackend | None:
        """根据配置创建持久化后端实例。

        工厂方法：根据 persistence_type 选择对应的 PersistenceBackend 实现。
        扩展新的后端类型时，只需在此方法中添加新的分支。

        Returns:
            PersistenceBackend 实例，如果 persistence_type 为 None 则返回 None

        Raises:
            ValueError: persistence_type 不在支持的类型列表中
        """
        if self.persistence_type is None:
            return None

        if self.persistence_type == "json_file":
            from ghrah.context.persistence.json_file import JsonFileBackend

            return JsonFileBackend(
                root_dir=self.persistence_root_dir,
                compress=self.persistence_compress,
                run_id=self.persistence_run_id,
            )

        if self.persistence_type == "memory":
            from ghrah.context.persistence.memory import InMemoryBackend

            return InMemoryBackend()

        if self.persistence_type == "sqlite":
            from ghrah.context.persistence.sqlite_backend import SqliteBackend

            db_path = self.persistence_root_dir
            if db_path is not None:
                # 如果指定了 root_dir，sqlite 后端将数据库文件放在该目录下
                from pathlib import Path

                db_path = str(Path(db_path) / "ghrah.db")

            return SqliteBackend(
                db_path=db_path,
                run_id=self.persistence_run_id,
            )

        if self.persistence_type == "remote":
            from ghrah.context.persistence.remote_backend import RemoteBackend

            if self._command_sender is not None:
                return RemoteBackend(
                    command_sender=self._command_sender,
                    agent_name=self._persistence_agent_name or "",
                )

            raise ValueError(
                "command_sender is required for remote persistence backend. "
                "Call ContextConfig.set_command_sender() before create_persistence()."
            )

        raise ValueError(
            f"Unsupported persistence_type: {self.persistence_type!r}. "
            f"Supported types: {PERSISTENCE_BACKEND_TYPES}"
        )


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

    @property
    def effective_agent_config_name(self) -> str:
        """获取有效的 agentconf 查找名称。

        优先使用 agent_config_name，未指定时回退到 name（向后兼容）。

        Returns:
            用于在 agentconf 中查找 LLM 配置的名称
        """
        return self.agent_config_name or self.name

    @property
    def num_cpus(self) -> float | None:
        """获取配置的 CPU 资源数。"""
        return self.resources.get("CPU")

    @property
    def num_gpus(self) -> float | None:
        """获取配置的 GPU 资源数。"""
        return self.resources.get("GPU")
