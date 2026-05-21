# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""JsonFileBackend：基于 JSON 文件的持久化后端。

数据按 run_id/agent_name 分区存储在文件系统中，
支持 gzip 压缩以减少重复数据占用。

目录结构：
    {root_dir}/
    └── {run_id}/
        └── {agent_name}/
            ├── meta.json.gz
            ├── messages.json.gz
            ├── nodes.json.gz
            └── sessions.json

设计要点：
    - 所有节点打包存储在单个 nodes.json(.gz) 文件中
    - 使用临时文件 + rename 实现原子写入
    - 支持 gzip 压缩（默认开启）
    - 不需要多进程并发安全（actor 模型保证无数据竞争）
    - session 数据存储在 {agent_name}/sessions.json 中
"""

from __future__ import annotations

import gzip
import json
import logging
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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

__all__ = ["JsonFileBackend"]


def _generate_run_id() -> str:
    """生成基于当前时间的 run ID。

    格式：run_{ISO8601 时间戳}
    示例：run_2026-04-21T16-30-00
    """
    now = datetime.now(UTC)
    ts = now.strftime("%Y-%m-%dT%H-%M-%S")
    return f"run_{ts}"


class JsonFileBackend(PersistenceBackend):
    """基于 JSON 文件的持久化后端，支持 gzip 压缩。

    数据按 run_id/agent_name 分区存储在文件系统中。
    每次创建实例时自动生成新的 run_id，确保不同运行实例的数据隔离。

    所有节点打包存储在单个 nodes.json(.gz) 文件中，减少文件数量。

    Args:
        root_dir: 存储根目录路径，默认为 ~/.ghrah/data
        compress: 是否启用 gzip 压缩，默认 True
        run_id: 运行 ID，默认自动生成（格式：run_{ISO8601}）
    """

    def __init__(
        self,
        root_dir: str | Path | None = None,
        compress: bool = True,
        run_id: str | None = None,
    ) -> None:
        if root_dir is None:
            root_dir = Path.home() / ".ghrah" / "data"
        self._root_dir = Path(root_dir)
        self._compress = compress
        self._run_id = run_id or _generate_run_id()
        self._run_dir = self._root_dir / self._run_id

        self._node_to_agent: dict[str, str] = {}

    @property
    def root_dir(self) -> Path:
        return self._root_dir

    @property
    def run_id(self) -> str:
        return self._run_id

    @property
    def run_dir(self) -> Path:
        return self._run_dir

    # ----------------------------------------------------------------
    # 路径辅助
    # ----------------------------------------------------------------

    def _agent_dir(self, agent_name: str) -> Path:
        return self._run_dir / agent_name

    def _nodes_path(self, agent_name: str) -> Path:
        ext = ".json.gz" if self._compress else ".json"
        return self._agent_dir(agent_name) / f"nodes{ext}"

    def _meta_path(self, agent_name: str) -> Path:
        ext = ".json.gz" if self._compress else ".json"
        return self._agent_dir(agent_name) / f"meta{ext}"

    def _messages_path(self, agent_name: str) -> Path:
        ext = ".json.gz" if self._compress else ".json"
        return self._agent_dir(agent_name) / f"messages{ext}"

    def _sessions_path(self, agent_name: str) -> Path:
        return self._agent_dir(agent_name) / "sessions.json"

    # ----------------------------------------------------------------
    # IO 辅助
    # ----------------------------------------------------------------

    def _write_json(self, path: Path, data: dict[str, Any] | list[Any]) -> None:
        """原子写入 JSON 文件（先写临时文件再重命名）。

        Args:
            path: 目标文件路径
            data: 要写入的数据

        Raises:
            OSError: 文件写入失败
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        try:
            if self._compress and path.suffix == ".gz":
                with gzip.open(tmp_path, "wt", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
            else:
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
            tmp_path.rename(path)  # POSIX 原子操作
        except Exception as e:
            logger.error("Failed to write %s: %s", path, e)
            tmp_path.unlink(missing_ok=True)
            raise

    def _read_json(self, path: Path) -> dict[str, Any] | list[Any]:
        """读取 JSON 文件。

        Args:
            path: 文件路径

        Returns:
            解析后的数据

        Raises:
            FileNotFoundError: 文件不存在
            json.JSONDecodeError: JSON 解析失败
        """
        if self._compress and path.suffix == ".gz":
            with gzip.open(path, "rt", encoding="utf-8") as f:
                return json.load(f)
        else:
            with open(path, encoding="utf-8") as f:
                return json.load(f)

    # ----------------------------------------------------------------
    # 节点批量 IO
    # ----------------------------------------------------------------

    def _load_nodes(self, agent_name: str) -> dict[str, dict[str, Any]]:
        path = self._nodes_path(agent_name)
        if not path.exists():
            return {}
        data = self._read_json(path)
        if not isinstance(data, dict):
            raise TypeError(f"Expected dict from {path}, got {type(data).__name__}")
        return data

    def _save_nodes(self, agent_name: str, nodes: dict[str, dict[str, Any]]) -> None:
        path = self._nodes_path(agent_name)
        self._write_json(path, nodes)

    # ----------------------------------------------------------------
    # PersistenceBackend 接口实现
    # ----------------------------------------------------------------

    async def save_node(self, node: ContextNode) -> None:
        self._node_to_agent[node.id] = node.agent_name
        nodes = self._load_nodes(node.agent_name)
        nodes[node.id] = serialize_node(node)
        self._save_nodes(node.agent_name, nodes)

    async def load_node(self, node_id: str) -> ContextNode | None:
        agent_name = self._node_to_agent.get(node_id)
        if agent_name is None:
            return None
        nodes = self._load_nodes(agent_name)
        data = nodes.get(node_id)
        if data is None:
            return None
        return deserialize_node(data)

    async def load_chain(self, agent_name: str) -> list[ContextNode]:
        nodes_data = self._load_nodes(agent_name)
        nodes = [deserialize_node(d) for d in nodes_data.values()]
        nodes.sort(key=lambda n: n.iteration)

        for n in nodes:
            self._node_to_agent[n.id] = n.agent_name

        return nodes

    async def save_chain_meta(
        self,
        agent_name: str,
        branches: dict[str, str],
        current_state: dict[str, Any],
        active_session_id: str = "",
    ) -> None:
        data = {
            "branches": dict(branches),
            "active_session_id": active_session_id,
            "current_state": current_state,
        }
        self._write_json(self._meta_path(agent_name), data)

    async def load_chain_meta(
        self, agent_name: str
    ) -> tuple[dict[str, str], str, dict[str, Any]] | None:
        path = self._meta_path(agent_name)
        if not path.exists():
            return None
        data = self._read_json(path)
        if not isinstance(data, dict):
            raise TypeError(f"Expected dict from {path}, got {type(data).__name__}")
        branches = data["branches"]
        active_session_id = data.get("active_session_id", "")
        current_state = data["current_state"]
        return (branches, active_session_id, current_state)

    async def save_messages(self, agent_name: str, messages: list[Any]) -> None:
        data = serialize_messages(messages)
        self._write_json(self._messages_path(agent_name), data)

    async def load_messages(self, agent_name: str) -> list[Any]:
        path = self._messages_path(agent_name)
        if not path.exists():
            return []
        data = self._read_json(path)
        if not isinstance(data, list):
            raise TypeError(f"Expected list from {path}, got {type(data).__name__}")
        return deserialize_messages(data) or []

    async def delete_chain(self, agent_name: str) -> None:
        agent_dir = self._agent_dir(agent_name)
        if agent_dir.exists():
            shutil.rmtree(agent_dir)
        self._node_to_agent = {
            nid: aname for nid, aname in self._node_to_agent.items() if aname != agent_name
        }

    async def list_agents(self) -> list[str]:
        if not self._run_dir.exists():
            return []
        return sorted(
            d.name for d in self._run_dir.iterdir() if d.is_dir() and any(d.iterdir())
        )

    # ----------------------------------------------------------------
    # Session 管理
    # ----------------------------------------------------------------

    async def save_session(self, session: Session) -> None:
        agent_name = session.agent_name
        path = self._sessions_path(agent_name)

        if path.exists():
            all_sessions = self._read_json(path)
            if not isinstance(all_sessions, dict):
                all_sessions = {}
        else:
            all_sessions = {}

        all_sessions[session.session_id] = serialize_session(session)
        self._write_json(path, all_sessions)

    async def load_session(self, session_id: str) -> Session | None:
        """按 ID 加载 session。

        注意：此实现遍历所有 agent 目录搜索 session，时间复杂度 O(n)。
        JsonFileBackend 主要用于验证性场合，不适用于生产环境。
        如需高效按 ID 查询，请使用 SqliteBackend 或 RemoteBackend。

        Args:
            session_id: session ID

        Returns:
            Session 实例，不存在则返回 None
        """
        if not self._run_dir.exists():
            return None

        for agent_dir in self._run_dir.iterdir():
            if not agent_dir.is_dir():
                continue
            sessions_path = agent_dir / "sessions.json"
            if not sessions_path.exists():
                continue
            all_sessions = self._read_json(sessions_path)
            if not isinstance(all_sessions, dict):
                continue
            if session_id in all_sessions:
                return deserialize_session(all_sessions[session_id])

        return None

    async def list_sessions(self, agent_name: str) -> list[Session]:
        path = self._sessions_path(agent_name)
        if not path.exists():
            return []
        all_sessions = self._read_json(path)
        if not isinstance(all_sessions, dict):
            return []
        return [deserialize_session(s) for s in all_sessions.values()]

    async def delete_sessions(self, agent_name: str) -> None:
        path = self._sessions_path(agent_name)
        if path.exists():
            path.unlink()
