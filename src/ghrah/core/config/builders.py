# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""Config builder 函数 — 从各种输入源构建配置对象。

两组 builder：
1. `*_from_dict`：从 raw wire payload dict 构建（供 core/server/router 使用）
2. `*_from_overrides`：从 manifest dataclass 构建（供 manifest/resolver 使用）
"""

from __future__ import annotations

from typing import Any

from ghrah.types.config_types import ContextConfig, ModelOverrides, WindowConfig

__all__ = [
    "build_window_from_dict",
    "build_context_from_dict",
    "build_model_overrides_from_dict",
    "build_window_from_overrides",
    "build_context_from_overrides",
    "build_model_overrides_from_config",
]


def build_window_from_dict(data: dict[str, Any]) -> WindowConfig:
    """从 dict 构建 WindowConfig（wire payload 格式）。"""
    return WindowConfig(
        max_tokens=data.get("max_tokens", 4096),
        strategies=data.get("strategies", ["tool_call_fold", "truncation"]),
        tool_call_max_length=data.get("tool_call_max_length", 500),
        sliding_window_size=data.get("sliding_window_size", 20),
    )


def build_context_from_dict(data: dict[str, Any]) -> ContextConfig:
    """从 dict 构建 ContextConfig（wire payload 格式）。"""
    return ContextConfig(
        persistence_type=data.get("persistence_type"),
        persistence_root_dir=data.get("persistence_root_dir"),
        persistence_compress=data.get("persistence_compress", True),
        auto_persist=data.get("auto_persist", False),
        snapshot_interval=data.get("snapshot_interval", 5),
        persistence_run_id=data.get("persistence_run_id"),
    )


def build_model_overrides_from_dict(data: dict[str, Any]) -> ModelOverrides:
    """从 dict 构建 ModelOverrides（wire payload 格式）。"""
    return ModelOverrides(
        temperature=data.get("temperature"),
        max_tokens=data.get("max_tokens"),
        top_p=data.get("top_p"),
        top_k=data.get("top_k"),
    )


def build_window_from_overrides(overrides: Any) -> WindowConfig:
    """从 WindowOverrides (manifest dataclass) 构建 WindowConfig。"""
    return WindowConfig(
        max_tokens=overrides.max_tokens if overrides.max_tokens is not None else 4096,
        strategies=overrides.strategies if overrides.strategies is not None else ["tool_call_fold", "truncation"],
        tool_call_max_length=overrides.tool_call_max_length if overrides.tool_call_max_length is not None else 500,
        sliding_window_size=overrides.sliding_window_size if overrides.sliding_window_size is not None else 20,
    )


def build_context_from_overrides(overrides: Any) -> ContextConfig:
    """从 PersistenceOverrides (manifest dataclass) 构建 ContextConfig。"""
    return ContextConfig(
        persistence_type=overrides.type,
        persistence_compress=overrides.compress if overrides.compress is not None else True,
        auto_persist=overrides.auto_persist if overrides.auto_persist is not None else False,
        snapshot_interval=overrides.snapshot_interval if overrides.snapshot_interval is not None else 5,
    )


def build_model_overrides_from_config(model: Any) -> ModelOverrides | None:
    """从 ModelConfig (manifest dataclass) 构建 ModelOverrides。

    仅在至少一个覆盖字段非 None 时返回 ModelOverrides，
    否则返回 None（表示无覆盖）。
    """
    if not any(
        v is not None
        for v in [model.temperature, model.max_tokens, model.top_p, model.top_k]
    ):
        return None
    return ModelOverrides(
        temperature=model.temperature,
        max_tokens=model.max_tokens,
        top_p=model.top_p,
        top_k=model.top_k,
    )
