# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""序列化/反序列化工具函数：处理 ContextNode ↔ dict 转换。

核心函数：
- serialize_node / deserialize_node: ContextNode ↔ dict
- serialize_session / deserialize_session: Session ↔ dict
- serialize_action_result / deserialize_action_result: ActionResult ↔ dict
- serialize_action_results / deserialize_action_results: action_results 列表 ↔ dict 列表
- serialize_messages / deserialize_messages: ChatMessage 列表 ↔ dict 列表

设计要点：
- 序列化使用 ChatMessage.to_dict() / ChatMessage.from_dict()
- datetime 统一转为 ISO 8601 字符串
- 所有函数为纯函数，无副作用
"""

from __future__ import annotations

import json
import warnings
from datetime import datetime
from typing import Any

from ghrah.abilities.base import ActionOutcome, ActionResult
from ghrah.chat.message import ChatMessage
from ghrah.chat.serialization import (
    deserialize_messages as _chat_deserialize_messages,
)
from ghrah.context.node import ContextNode
from ghrah.context.session import Session

__all__ = [
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


def serialize_action_result(result: ActionResult | None) -> dict[str, Any] | None:
    """将 ActionResult 序列化为 JSON 兼容的 dict。

    Args:
        result: ActionResult 实例，None 返回 None

    Returns:
        序列化后的 dict，或 None
    """
    if result is None:
        return None
    return {
        "outcome": result.outcome.value,
        "data": result.data,
        "next_action_hint": result.next_action_hint,
    }


def deserialize_action_result(data: dict[str, Any] | None) -> ActionResult | None:
    """从 dict 反序列化为 ActionResult。

    Args:
        data: 序列化后的 dict，None 返回 None

    Returns:
        ActionResult 实例，或 None
    """
    if data is None:
        return None
    return ActionResult(
        outcome=ActionOutcome(data["outcome"]),
        data=data.get("data", {}),
        next_action_hint=data.get("next_action_hint"),
    )


def serialize_action_results(results: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    """将 action_results 列表序列化为 JSON 兼容的 dict 列表。

    每个项包含 "ability_name" 和 "action_result" 键。

    Args:
        results: action_results 列表，None 返回 None

    Returns:
        序列化后的 dict 列表，或 None

    Raises:
        TypeError: results 中的项不是 dict 类型
    """
    if results is None:
        return None
    serialized: list[dict[str, Any]] = []
    for i, item in enumerate(results):
        if not isinstance(item, dict):
            raise TypeError(f"action_results[{i}] must be a dict, got {type(item).__name__}")
        serialized.append(
            {
                "ability_name": item.get("ability_name", ""),
                "action_result": serialize_action_result(item.get("action_result")),
            }
        )
    return serialized


def deserialize_action_results(data: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    """从 dict 列表反序列化为 action_results。

    Args:
        data: 序列化后的 dict 列表，None 返回 None

    Returns:
        反序列化后的 action_results 列表，或 None

    Raises:
        TypeError: data 中的项不是 dict 类型
    """
    if data is None:
        return None
    results: list[dict[str, Any]] = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            raise TypeError(f"action_results[{i}] must be a dict, got {type(item).__name__}")
        results.append(
            {
                "ability_name": item.get("ability_name", ""),
                "action_result": deserialize_action_result(item.get("action_result")),
            }
        )
    return results


def _serialize_chat_messages(messages: list[Any] | None) -> list[dict[str, Any]] | None:
    """将 ChatMessage 列表序列化为 dict 列表。

    Args:
        messages: ChatMessage 列表，None 返回 None

    Returns:
        序列化后的 dict 列表，或 None

    Raises:
        RuntimeWarning: messages 中的项不是 ChatMessage 或 dict 类型时发出警告，
            可能表示传参错误或数据损坏
    """
    if messages is None:
        return None
    result: list[dict[str, Any]] = []
    for m in messages:
        if isinstance(m, ChatMessage):
            result.append(m.to_dict())
        elif isinstance(m, dict):
            result.append(m)
        else:
            warnings.warn(
                f"Non-ChatMessage object of type {type(m).__name__} passed to "
                f"serialize_messages; this may indicate incorrect arguments or "
                f"corrupted data. Attempting best-effort conversion.",
                RuntimeWarning,
                stacklevel=2,
            )
            content = getattr(m, "content", str(m))
            role = getattr(m, "type", "unknown")
            if role == "human":
                role = "user"
            elif role == "ai":
                role = "ai"
            elif role == "system":
                role = "system"
            elif role == "tool":
                role = "tool"
            result.append(
                {
                    "role": role,
                    "content_blocks": [{"type": "text", "text": str(content)}],
                    "source": None,
                    "metadata": {},
                }
            )
    return result


def _deserialize_chat_messages(
    data: list[dict[str, Any]] | None,
) -> list[ChatMessage] | None:
    """从 dict 列表反序列化为 ChatMessage 列表。

    Args:
        data: 序列化后的 dict 列表，None 返回 None

    Returns:
        ChatMessage 列表，或 None
    """
    if data is None:
        return None
    result = _chat_deserialize_messages(data)
    if result is None:
        return []
    return result


def serialize_messages(messages: list[Any] | None) -> list[dict[str, Any]] | None:
    """将消息列表序列化为 dict 列表。

    兼容 ChatMessage 格式。

    Args:
        messages: 消息列表，None 返回 None

    Returns:
        序列化后的 dict 列表，或 None
    """
    return _serialize_chat_messages(messages)


def deserialize_messages(data: list[dict[str, Any]] | None) -> list[ChatMessage] | None:
    """从 dict 列表反序列化为 ChatMessage 列表。

    Args:
        data: 序列化后的 dict 列表，None 返回 None

    Returns:
        ChatMessage 列表，或 None
    """
    return _deserialize_chat_messages(data)


def serialize_node(node: ContextNode) -> dict[str, Any]:
    """将 ContextNode 序列化为 JSON 兼容的 dict。

    处理以下特殊类型：
    - datetime → ISO 8601 字符串
    - ChatMessage 列表 → dict 格式
    - action_results → 序列化列表

    Args:
        node: ContextNode 实例

    Returns:
        JSON 兼容的 dict
    """
    return {
        "id": node.id,
        "parent_id": node.parent_id,
        "agent_name": node.agent_name,
        "timestamp": node.timestamp.isoformat(),
        "iteration": node.iteration,
        "ability_names": node.ability_names,
        "agent_state": node.agent_state,
        "messages_delta": serialize_messages(node.messages_delta),
        "messages_snapshot": serialize_messages(node.messages_snapshot),
        "is_snapshot": node.is_snapshot,
        "action_results": serialize_action_results(node.action_results),
        "metadata": node.metadata,
        "branch_name": node.branch_name,
        "session_id": node.session_id,
    }


def deserialize_node(data: dict[str, Any]) -> ContextNode:
    """从 dict 反序列化为 ContextNode。

    Args:
        data: serialize_node 产出的 dict

    Returns:
        ContextNode 实例
    """
    timestamp = data["timestamp"]
    if isinstance(timestamp, str):
        timestamp = datetime.fromisoformat(timestamp)

    return ContextNode(
        id=data["id"],
        parent_id=data["parent_id"],
        agent_name=data["agent_name"],
        timestamp=timestamp,
        iteration=data["iteration"],
        ability_names=data["ability_names"],
        agent_state=data["agent_state"],
        messages_delta=deserialize_messages(data["messages_delta"]) or [],
        messages_snapshot=deserialize_messages(data["messages_snapshot"]),
        is_snapshot=data["is_snapshot"],
        action_results=deserialize_action_results(data["action_results"]) or [],
        metadata=data["metadata"],
        branch_name=data["branch_name"],
        session_id=data.get("session_id", ""),
    )


def serialize_session(session: Session) -> dict[str, Any]:
    """将 Session 序列化为 JSON 兼容的 dict。

    Args:
        session: Session 实例

    Returns:
        JSON 兼容的 dict
    """
    return {
        "session_id": session.session_id,
        "agent_name": session.agent_name,
        "branch_name": session.branch_name,
        "parent_node_id": session.parent_node_id,
        "parent_session_id": session.parent_session_id,
        "rebase_from_agent": session.rebase_from_agent,
        "rebase_from_node_id": session.rebase_from_node_id,
        "rebase_from_session_id": session.rebase_from_session_id,
        "system_prompt": session.system_prompt,
        "created_at": session.created_at.isoformat(),
        "metadata": json.dumps(session.metadata) if session.metadata else "{}",
    }


def deserialize_session(data: dict[str, Any]) -> Session:
    """从 dict 反序列化为 Session。

    Args:
        data: serialize_session 产出的 dict

    Returns:
        Session 实例
    """
    created_at = data["created_at"]
    if isinstance(created_at, str):
        created_at = datetime.fromisoformat(created_at)

    metadata = data.get("metadata", "{}")
    if isinstance(metadata, str):
        metadata = json.loads(metadata)

    return Session(
        session_id=data["session_id"],
        agent_name=data["agent_name"],
        branch_name=data.get("branch_name", "main"),
        parent_node_id=data.get("parent_node_id"),
        parent_session_id=data.get("parent_session_id"),
        rebase_from_agent=data.get("rebase_from_agent"),
        rebase_from_node_id=data.get("rebase_from_node_id"),
        rebase_from_session_id=data.get("rebase_from_session_id"),
        system_prompt=data.get("system_prompt", ""),
        created_at=created_at,
        metadata=metadata,
    )
