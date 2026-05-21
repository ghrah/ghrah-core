# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""SqliteBackend：基于 SQLite 的持久化后端。

使用 aiosqlite 实现异步 SQLite 操作，WAL 模式支持并发读。
所有写入操作在事务中执行，保证原子性。

设计要点：
    - WAL 模式：支持并发读写，适合 Subject 单写多读场景
    - 事务保证：批量操作使用显式事务
    - 序列化兼容：复用 serialization.py 中的函数
    - 连接管理：支持 async with 上下文管理器
    - run_id：进程级运行标识（原 session_id，重命名避免与 branch session 混淆）
    - sessions：Agent 内的 branch session 元数据
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite

from ghrah.context.node import ContextNode
from ghrah.context.persistence.backend import PersistenceBackend
from ghrah.context.persistence.serialization import (
    deserialize_messages,
    deserialize_node,
    deserialize_session,
    serialize_messages,
    serialize_node,
    serialize_session,
)
from ghrah.context.session import Session

logger = logging.getLogger(__name__)

__all__ = ["SqliteBackend"]

# 节点表查询的列名列表，保持 SELECT 和 _row_to_dict 一致
_NODE_COLUMNS = (
    "id, parent_id, agent_name, session_id, timestamp, iteration, "
    "branch_name, is_snapshot, ability_names, agent_state, "
    "messages_delta, messages_snapshot, action_results, metadata"
)

# 数据库建表 DDL
_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS runs (
    run_id        TEXT PRIMARY KEY,
    created_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    metadata      TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS agents (
    agent_name   TEXT PRIMARY KEY,
    run_id       TEXT NOT NULL REFERENCES runs(run_id),
    created_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id        TEXT PRIMARY KEY,
    agent_name        TEXT NOT NULL,
    branch_name       TEXT NOT NULL DEFAULT 'main',
    parent_node_id    TEXT,
    parent_session_id TEXT,
    rebase_from_agent TEXT,
    rebase_from_node_id TEXT,
    rebase_from_session_id TEXT,
    system_prompt     TEXT DEFAULT '',
    created_at        TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at        TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    metadata          TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS nodes (
    id                TEXT PRIMARY KEY,
    parent_id         TEXT,
    agent_name        TEXT NOT NULL REFERENCES agents(agent_name),
    session_id        TEXT NOT NULL DEFAULT '',
    timestamp         TEXT NOT NULL,
    iteration         INTEGER NOT NULL DEFAULT 0,
    branch_name       TEXT NOT NULL DEFAULT 'main',
    is_snapshot       INTEGER NOT NULL DEFAULT 0,
    ability_names     TEXT NOT NULL DEFAULT '[]',
    agent_state       TEXT NOT NULL DEFAULT '{}',
    messages_delta    TEXT NOT NULL DEFAULT '[]',
    messages_snapshot TEXT,
    action_results    TEXT NOT NULL DEFAULT '[]',
    metadata          TEXT NOT NULL DEFAULT '{}',
    created_at        TEXT NOT NULL DEFAULT CURRENT_timestamp
);

CREATE TABLE IF NOT EXISTS chain_meta (
    agent_name        TEXT PRIMARY KEY REFERENCES agents(agent_name),
    branches          TEXT NOT NULL DEFAULT '{}',
    active_session_id TEXT NOT NULL DEFAULT '',
    current_state     TEXT NOT NULL DEFAULT '{}',
    updated_at        TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS messages (
    agent_name    TEXT PRIMARY KEY REFERENCES agents(agent_name),
    messages      TEXT NOT NULL DEFAULT '[]',
    updated_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_nodes_agent ON nodes(agent_name);
CREATE INDEX IF NOT EXISTS idx_nodes_parent ON nodes(parent_id);
CREATE INDEX IF NOT EXISTS idx_nodes_branch ON nodes(agent_name, branch_name);
CREATE INDEX IF NOT EXISTS idx_nodes_iteration ON nodes(agent_name, iteration);
CREATE INDEX IF NOT EXISTS idx_nodes_session ON nodes(session_id);
CREATE INDEX IF NOT EXISTS idx_agents_run ON agents(run_id);
CREATE INDEX IF NOT EXISTS idx_sessions_agent ON sessions(agent_name);
"""


def _generate_run_id() -> str:
    """生成基于当前时间的 run ID。

    格式：run_{ISO8601 时间戳}
    示例：run_2026-04-21T16-30-00
    """
    now = datetime.now(UTC)
    ts = now.strftime("%Y-%m-%dT%H-%M-%S")
    return f"run_{ts}"


class SqliteBackend(PersistenceBackend):
    """基于 SQLite 的持久化后端，使用 aiosqlite 异步操作。

    适用于 Subject 层的本地持久化，使用 WAL 模式支持并发读。
    所有写入操作在事务中执行，保证原子性。

    数据按 run_id 隔离，每个 run 创建独立的 agents 记录。

    Args:
        db_path: SQLite 数据库文件路径，默认为 ~/.ghrah/data/ghrah.db
        run_id: 运行 ID，默认自动生成（格式：run_{ISO8601}）
    """
    def __init__(
        self,
        db_path: str | Path | None = None,
        run_id: str | None = None,
    ) -> None:
        if db_path is None:
            db_path = Path.home() / ".ghrah" / "data" / "ghrah.db"
        self._db_path = Path(db_path)
        self._run_id = run_id or _generate_run_id()
        self._db: aiosqlite.Connection | None = None
        self._initialized = False

    @property
    def db_path(self) -> Path:
        """数据库文件路径。"""
        return self._db_path

    @property
    def run_id(self) -> str:
        """当前运行 ID。"""
        return self._run_id

    # ----------------------------------------------------------------
    # 连接管理
    # ----------------------------------------------------------------

    async def _ensure_db(self) -> aiosqlite.Connection:
        """确保数据库连接已建立并初始化。

        Returns:
            aiosqlite 连接对象

        Raises:
            RuntimeError: 数据库未通过 connect() 打开
        """
        if self._db is None:
            raise RuntimeError(
                "Database not connected. Use 'async with backend:' or call connect() first."
            )
        if not self._initialized:
            await self._initialize_schema()
            self._initialized = True
        return self._db

    async def connect(self) -> None:
        """打开数据库连接并启用 WAL 模式。

        Raises:
            RuntimeError: 数据库连接已建立
        """
        if self._db is not None:
            raise RuntimeError("Database already connected.")

        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        # isolation_level=None 启用手动事务控制，避免隐式事务冲突
        self._db = await aiosqlite.connect(str(self._db_path), isolation_level=None)
        # 启用 Row 工厂，支持列名访问
        self._db.row_factory = aiosqlite.Row
        # 启用 WAL 模式，支持并发读写
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA foreign_keys=ON")
        logger.debug("SQLite database connected: %s", self._db_path)

    async def close(self) -> None:
        """关闭数据库连接。"""
        if self._db is not None:
            await self._db.close()
            self._db = None
            logger.debug("SQLite database closed: %s", self._db_path)

    async def _initialize_schema(self) -> None:
        """初始化数据库表结构和索引。"""
        assert self._db is not None
        await self._db.executescript(_SCHEMA_SQL)
        # 确保当前 run 存在
        await self._db.execute(
            "INSERT OR IGNORE INTO runs (run_id) VALUES (?)",
            (self._run_id,),
        )
        await self._db.commit()
        logger.debug("Database schema initialized for run: %s", self._run_id)

    # ----------------------------------------------------------------
    # 上下文管理器
    # ----------------------------------------------------------------

    async def __aenter__(self) -> SqliteBackend:
        """异步上下文管理器入口：打开连接。"""
        await self.connect()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """异步上下文管理器出口：关闭连接。"""
        await self.close()

    # ----------------------------------------------------------------
    # 辅助方法
    # ----------------------------------------------------------------

    async def _ensure_agent(self, db: aiosqlite.Connection, agent_name: str) -> None:
        """确保 agent 记录存在。

        Args:
            db: 数据库连接
            agent_name: Agent 名称
        """
        await db.execute(
            "INSERT OR IGNORE INTO agents (agent_name, run_id) VALUES (?, ?)",
            (agent_name, self._run_id),
        )

    @staticmethod
    def _serialize_node_params(serialized: dict[str, Any]) -> tuple[Any, ...]:
        """将序列化后的节点 dict 转换为 SQL 参数元组。

        Args:
            serialized: serialize_node() 的输出 dict

        Returns:
            INSERT OR REPLACE 语句的参数元组
        """
        return (
            serialized["id"],
            serialized["parent_id"],
            serialized["agent_name"],
            serialized.get("session_id", ""),
            serialized["timestamp"],
            serialized["iteration"],
            serialized["branch_name"],
            1 if serialized["is_snapshot"] else 0,
            json.dumps(serialized["ability_names"], ensure_ascii=False),
            json.dumps(serialized["agent_state"], ensure_ascii=False),
            json.dumps(serialized["messages_delta"], ensure_ascii=False),
            json.dumps(serialized["messages_snapshot"], ensure_ascii=False)
            if serialized["messages_snapshot"] is not None
            else None,
            json.dumps(serialized["action_results"], ensure_ascii=False),
            json.dumps(serialized["metadata"], ensure_ascii=False),
        )

    # ----------------------------------------------------------------
    # PersistenceBackend 接口实现
    # ----------------------------------------------------------------

    async def save_node(self, node: ContextNode) -> None:
        """保存单个节点到 SQLite。

        如果节点已存在则更新（UPSERT）。

        Args:
            node: 要保存的 ContextNode
        """
        db = await self._ensure_db()
        await self._ensure_agent(db, node.agent_name)

        serialized = serialize_node(node)
        await db.execute(
            f"""
            INSERT OR REPLACE INTO nodes (
                {_NODE_COLUMNS}
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            self._serialize_node_params(serialized),
        )
        await db.commit()

    async def load_node(self, node_id: str) -> ContextNode | None:
        """从 SQLite 加载单个节点。

        Args:
            node_id: 节点 ID

        Returns:
            对应的 ContextNode，不存在则返回 None
        """
        db = await self._ensure_db()
        cursor = await db.execute(
            f"""
            SELECT {_NODE_COLUMNS}
            FROM nodes WHERE id = ?
            """,
            (node_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None

        data = self._row_to_dict(row)
        return deserialize_node(data)

    async def load_chain(self, agent_name: str) -> list[ContextNode]:
        """加载指定 agent 的所有节点（按 iteration 升序排列）。

        Args:
            agent_name: Agent 名称

        Returns:
            节点列表（按 iteration 升序排列）
        """
        db = await self._ensure_db()
        cursor = await db.execute(
            f"""
            SELECT {_NODE_COLUMNS}
            FROM nodes WHERE agent_name = ?
            ORDER BY iteration ASC
            """,
            (agent_name,),
        )
        rows = await cursor.fetchall()
        return [deserialize_node(self._row_to_dict(row)) for row in rows]

    async def save_chain_meta(
        self,
        agent_name: str,
        branches: dict[str, str],
        current_state: dict[str, Any],
        active_session_id: str = "",
    ) -> None:
        """保存链的元信息：分支映射 + 活跃 session ID + 当前状态。

        Args:
            agent_name: Agent 名称
            branches: 分支名 → head node ID 的映射
            current_state: 当前 Agent 状态快照
            active_session_id: 当前活跃 session 的 ID
        """
        db = await self._ensure_db()
        await self._ensure_agent(db, agent_name)

        await db.execute(
            """
            INSERT OR REPLACE INTO chain_meta (
                agent_name, branches, active_session_id, current_state, updated_at
            ) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (
                agent_name,
                json.dumps(branches, ensure_ascii=False),
                active_session_id,
                json.dumps(current_state, ensure_ascii=False),
            ),
        )
        await db.commit()

    async def load_chain_meta(
        self, agent_name: str
    ) -> tuple[dict[str, str], str, dict[str, Any]] | None:
        """加载链的元信息。

        Args:
            agent_name: Agent 名称

        Returns:
            (branches, active_session_id, current_state) 三元组，不存在则返回 None
        """
        db = await self._ensure_db()
        cursor = await db.execute(
            """
            SELECT branches, active_session_id, current_state
            FROM chain_meta WHERE agent_name = ?
            """,
            (agent_name,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        branches = json.loads(row["branches"])
        active_session_id = row["active_session_id"]
        current_state = json.loads(row["current_state"])
        return (branches, active_session_id, current_state)

    async def save_messages(self, agent_name: str, messages: list[Any]) -> None:
        """保存当前完整消息列表。

        Args:
            agent_name: Agent 名称
            messages: ChatMessage 列表
        """
        db = await self._ensure_db()
        await self._ensure_agent(db, agent_name)

        serialized = serialize_messages(messages)
        await db.execute(
            """
            INSERT OR REPLACE INTO messages (agent_name, messages, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            """,
            (
                agent_name,
                json.dumps(serialized, ensure_ascii=False),
            ),
        )
        await db.commit()

    async def load_messages(self, agent_name: str) -> list[Any]:
        """加载消息列表。

        Args:
            agent_name: Agent 名称

        Returns:
            ChatMessage 列表，不存在则返回空列表
        """
        db = await self._ensure_db()
        cursor = await db.execute(
            "SELECT messages FROM messages WHERE agent_name = ?",
            (agent_name,),
        )
        row = await cursor.fetchone()
        if row is None:
            return []
        data = json.loads(row["messages"])
        result = deserialize_messages(data)
        return result if result is not None else []

    async def delete_chain(self, agent_name: str) -> None:
        """删除指定 agent 的所有持久化数据。

        按外键依赖顺序删除：messages → chain_meta → sessions → nodes → agents。

        Args:
            agent_name: Agent 名称
        """
        db = await self._ensure_db()
        await db.execute("DELETE FROM messages WHERE agent_name = ?", (agent_name,))
        await db.execute("DELETE FROM chain_meta WHERE agent_name = ?", (agent_name,))
        await db.execute("DELETE FROM sessions WHERE agent_name = ?", (agent_name,))
        await db.execute("DELETE FROM nodes WHERE agent_name = ?", (agent_name,))
        await db.execute("DELETE FROM agents WHERE agent_name = ?", (agent_name,))
        await db.commit()

    async def list_agents(self) -> list[str]:
        """列出所有有持久化数据的 agent 名称。

        Returns:
            agent 名称列表（按字母排序）
        """
        db = await self._ensure_db()
        cursor = await db.execute("SELECT agent_name FROM agents ORDER BY agent_name")
        rows = await cursor.fetchall()
        return [row["agent_name"] for row in rows]

    # ----------------------------------------------------------------
    # Session 管理
    # ----------------------------------------------------------------

    async def save_session(self, session: Session) -> None:
        """保存或更新 session 到 SQLite。

        Args:
            session: Session 实例
        """
        db = await self._ensure_db()
        serialized = serialize_session(session)

        await db.execute(
            """
            INSERT OR REPLACE INTO sessions (
                session_id, agent_name, branch_name,
                parent_node_id, parent_session_id,
                rebase_from_agent, rebase_from_node_id, rebase_from_session_id,
                system_prompt, metadata, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (
                serialized["session_id"],
                serialized["agent_name"],
                serialized["branch_name"],
                serialized["parent_node_id"],
                serialized["parent_session_id"],
                serialized["rebase_from_agent"],
                serialized["rebase_from_node_id"],
                serialized["rebase_from_session_id"],
                serialized["system_prompt"],
                serialized["metadata"],
            ),
        )
        await db.commit()

    async def load_session(self, session_id: str) -> Session | None:
        """按 ID 加载 session。

        Args:
            session_id: session ID

        Returns:
            Session 实例，不存在则返回 None
        """
        db = await self._ensure_db()
        cursor = await db.execute(
            """
            SELECT session_id, agent_name, branch_name,
                   parent_node_id, parent_session_id,
                   rebase_from_agent, rebase_from_node_id, rebase_from_session_id,
                   system_prompt, created_at, metadata
            FROM sessions WHERE session_id = ?
            """,
            (session_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        data = {
            "session_id": row["session_id"],
            "agent_name": row["agent_name"],
            "branch_name": row["branch_name"],
            "parent_node_id": row["parent_node_id"],
            "parent_session_id": row["parent_session_id"],
            "rebase_from_agent": row["rebase_from_agent"],
            "rebase_from_node_id": row["rebase_from_node_id"],
            "rebase_from_session_id": row["rebase_from_session_id"],
            "system_prompt": row["system_prompt"],
            "created_at": row["created_at"],
            "metadata": row["metadata"],
        }
        return deserialize_session(data)

    async def list_sessions(self, agent_name: str) -> list[Session]:
        """列出 Agent 的所有 session。

        Args:
            agent_name: Agent 名称

        Returns:
            Session 列表
        """
        db = await self._ensure_db()
        cursor = await db.execute(
            """
            SELECT session_id, agent_name, branch_name,
                   parent_node_id, parent_session_id,
                   rebase_from_agent, rebase_from_node_id, rebase_from_session_id,
                   system_prompt, created_at, metadata
            FROM sessions WHERE agent_name = ?
            ORDER BY created_at ASC
            """,
            (agent_name,),
        )
        rows = await cursor.fetchall()
        sessions = []
        for row in rows:
            data = {
                "session_id": row["session_id"],
                "agent_name": row["agent_name"],
                "branch_name": row["branch_name"],
                "parent_node_id": row["parent_node_id"],
                "parent_session_id": row["parent_session_id"],
                "rebase_from_agent": row["rebase_from_agent"],
                "rebase_from_node_id": row["rebase_from_node_id"],
                "rebase_from_session_id": row["rebase_from_session_id"],
                "system_prompt": row["system_prompt"],
                "created_at": row["created_at"],
                "metadata": row["metadata"],
            }
            sessions.append(deserialize_session(data))
        return sessions

    async def delete_sessions(self, agent_name: str) -> None:
        """删除 Agent 的所有 session 数据。

        Args:
            agent_name: Agent 名称
        """
        db = await self._ensure_db()
        await db.execute("DELETE FROM sessions WHERE agent_name = ?", (agent_name,))
        await db.commit()

    # ----------------------------------------------------------------
    # 批量操作接口
    # ----------------------------------------------------------------

    async def save_nodes_batch(self, nodes: list[ContextNode]) -> None:
        """批量保存节点，在单个事务中执行。

        使用显式事务保证原子性：要么全部成功，要么全部回滚。

        Args:
            nodes: 要保存的 ContextNode 列表
        """
        if not nodes:
            return
        db = await self._ensure_db()

        # 确保所有相关 agent 都存在
        agent_names = {n.agent_name for n in nodes}
        for agent_name in agent_names:
            await self._ensure_agent(db, agent_name)

        # 显式事务：保证批量写入的原子性
        await db.execute("BEGIN")
        try:
            for node in nodes:
                serialized = serialize_node(node)
                await db.execute(
                    f"""
                    INSERT OR REPLACE INTO nodes (
                        {_NODE_COLUMNS}
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    self._serialize_node_params(serialized),
                )
            await db.commit()
        except Exception:
            await db.rollback()
            raise

    # ----------------------------------------------------------------
    # 内部辅助
    # ----------------------------------------------------------------

    @staticmethod
    def _row_to_dict(row: aiosqlite.Row) -> dict[str, Any]:
        """将数据库行转换为 dict，反序列化 JSON 字段。

        使用列名访问（而非硬编码索引），提高可维护性。

        Args:
            row: aiosqlite 查询结果行（需启用 row_factory）

        Returns:
            反序列化后的 dict，兼容 serialize_node 输出格式
        """
        return {
            "id": row["id"],
            "parent_id": row["parent_id"],
            "agent_name": row["agent_name"],
            "session_id": row["session_id"] if "session_id" in row.keys() else "",
            "timestamp": row["timestamp"],
            "iteration": row["iteration"],
            "branch_name": row["branch_name"],
            "is_snapshot": bool(row["is_snapshot"]),
            "ability_names": json.loads(row["ability_names"]),
            "agent_state": json.loads(row["agent_state"]),
            "messages_delta": json.loads(row["messages_delta"]),
            "messages_snapshot": json.loads(row["messages_snapshot"])
            if row["messages_snapshot"] is not None
            else None,
            "action_results": json.loads(row["action_results"]),
            "metadata": json.loads(row["metadata"]),
        }
