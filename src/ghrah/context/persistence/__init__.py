# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""持久化后端：ContextManager 链式数据的存储与恢复。

核心组件：
- PersistenceBackend ABC：统一持久化接口
- InMemoryBackend：纯内存实现（零依赖默认选项）
- JsonFileBackend：基于 JSON 文件的持久化后端（支持 gzip 压缩）
- SqliteBackend：基于 SQLite 的持久化后端（WAL 模式，支持并发读）
- RemoteBackend：远程持久化后端（通过 CoreClient 委托给 Subject）
- create_persistence()：根据 ContextConfig 创建持久化后端实例的工厂函数
- 序列化/反序列化工具函数：处理 ContextNode ↔ dict 转换

设计要点：
- 所有后端方法为 async，支持 IO 密集型存储（文件、数据库等）
- 序列化使用 ChatMessage.to_dict() / ChatMessage.from_dict()
- InMemoryBackend 直接存储 ContextNode 对象，无需序列化开销
- JsonFileBackend 将节点打包存储在单个文件中，支持 gzip 压缩
- SqliteBackend 使用 aiosqlite 异步操作，WAL 模式支持并发读写
- RemoteBackend 通过 CoreClient 将持久化操作委托给 Subject，Core 不碰 I/O
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ghrah.context.persistence.backend import PersistenceBackend
from ghrah.context.persistence.json_file import JsonFileBackend
from ghrah.context.persistence.memory import InMemoryBackend
from ghrah.context.persistence.remote_backend import RemoteBackend
from ghrah.context.persistence.serialization import (
    deserialize_action_result,
    deserialize_action_results,
    deserialize_messages,
    deserialize_node,
    deserialize_session,
    serialize_action_result,
    serialize_action_results,
    serialize_messages,
    serialize_node,
    serialize_session,
)
from ghrah.context.persistence.sqlite_backend import SqliteBackend

if TYPE_CHECKING:
    from ghrah.types.config_types import ContextConfig

PERSISTENCE_BACKEND_TYPES = ("json_file", "memory", "sqlite", "remote")


def create_persistence(config: ContextConfig) -> PersistenceBackend | None:
    """根据 ContextConfig 创建持久化后端实例。

    工厂函数：根据 persistence_type 选择对应的 PersistenceBackend 实现。
    扩展新的后端类型时，只需在此函数中添加新的分支。

    Args:
        config: ContextConfig 实例，包含持久化配置

    Returns:
        PersistenceBackend 实例，如果 persistence_type 为 None 则返回 None

    Raises:
        ValueError: persistence_type 不在支持的类型列表中，或 remote 后端缺少 command_sender
    """
    if config.persistence_type is None:
        return None

    if config.persistence_type == "json_file":
        from ghrah.context.persistence.json_file import JsonFileBackend as _JsonFileBackend

        return _JsonFileBackend(
            root_dir=config.persistence_root_dir,
            compress=config.persistence_compress,
            run_id=config.persistence_run_id,
        )

    if config.persistence_type == "memory":
        from ghrah.context.persistence.memory import InMemoryBackend as _InMemoryBackend

        return _InMemoryBackend()

    if config.persistence_type == "sqlite":
        from ghrah.context.persistence.sqlite_backend import SqliteBackend as _SqliteBackend

        db_path = config.persistence_root_dir
        if db_path is not None:
            from pathlib import Path

            db_path = str(Path(db_path) / "ghrah.db")

        return _SqliteBackend(
            db_path=db_path,
            run_id=config.persistence_run_id,
        )

    if config.persistence_type == "remote":
        from ghrah.context.persistence.remote_backend import RemoteBackend as _RemoteBackend

        if config.command_sender is not None:
            return _RemoteBackend(
                command_sender=config.command_sender,
                agent_name=config.persistence_agent_name or "",
            )

        raise ValueError(
            "command_sender is required for remote persistence backend. "
            "Set ContextConfig.command_sender before calling create_persistence()."
        )

    raise ValueError(
        f"Unsupported persistence_type: {config.persistence_type!r}. "
        f"Supported types: {PERSISTENCE_BACKEND_TYPES}"
    )

__all__ = [
    "PersistenceBackend",
    "InMemoryBackend",
    "JsonFileBackend",
    "SqliteBackend",
    "RemoteBackend",
    "PERSISTENCE_BACKEND_TYPES",
    "create_persistence",
    "serialize_node",
    "deserialize_node",
    "serialize_session",
    "deserialize_session",
    "serialize_action_result",
    "deserialize_action_result",
    "serialize_action_results",
    "deserialize_action_results",
    "serialize_messages",
    "deserialize_messages",
]
