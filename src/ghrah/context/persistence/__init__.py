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
- 序列化/反序列化工具函数：处理 ContextNode ↔ dict 转换

设计要点：
- 所有后端方法为 async，支持 IO 密集型存储（文件、数据库等）
- 序列化使用 ChatMessage.to_dict() / ChatMessage.from_dict()
- InMemoryBackend 直接存储 ContextNode 对象，无需序列化开销
- JsonFileBackend 将节点打包存储在单个文件中，支持 gzip 压缩
- SqliteBackend 使用 aiosqlite 异步操作，WAL 模式支持并发读写
- RemoteBackend 通过 CoreClient 将持久化操作委托给 Subject，Core 不碰 I/O
"""

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

__all__ = [
    "PersistenceBackend",
    "InMemoryBackend",
    "JsonFileBackend",
    "SqliteBackend",
    "RemoteBackend",
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
