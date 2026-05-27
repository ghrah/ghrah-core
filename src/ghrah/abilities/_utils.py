# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""Ability 路径工具：路径参数规格与路径安全检查。

提供 Core 和 Subject 共享的路径处理逻辑：
- AbilityPathSpec: Ability 路径参数规格声明
- ABILITY_PATH_SPECS: 已知 Ability 的路径参数映射表
- is_subpath: 严格子路径检查（防止 /tmp/data 匹配 /tmp/database）
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class AbilityPathSpec:
    """Ability 的路径参数规格，用于路径提取和权限检查。

    Attributes:
        path_keys: 文件/目录路径参数名（有序），
                    如 ("file_path",) 或 ("source_path", "destination_path")
        working_dir_keys: 工作目录参数名，如 ("working_dir",)
        alt_keys: 主参数名到备选参数名的映射，如 {"source_path": "file_path"}
                    表示先找 source_path，找不到则找 file_path
    """

    path_keys: tuple[str, ...] = ()
    working_dir_keys: tuple[str, ...] = ()
    alt_keys: dict[str, str] | None = None


ABILITY_PATH_SPECS: dict[str, AbilityPathSpec] = {
    "read_file": AbilityPathSpec(path_keys=("file_path",)),
    "write_file": AbilityPathSpec(path_keys=("file_path",)),
    "edit_file": AbilityPathSpec(path_keys=("file_path",)),
    "delete_file": AbilityPathSpec(path_keys=("file_path",)),
    "list_directory": AbilityPathSpec(path_keys=("dir_path",)),
    "move_file": AbilityPathSpec(
        path_keys=("source_path", "destination_path"),
        alt_keys={"source_path": "file_path"},
    ),
    "execute_command": AbilityPathSpec(working_dir_keys=("working_dir",)),
}

_FALLBACK_PATH_KEYS = ("file_path", "dir_path", "working_dir")


def extract_paths(ability_name: str, tool_args: dict[str, Any]) -> list[str]:
    """从 tool_args 中提取 Ability 涉及的所有路径（文件路径 + 工作目录路径）。

    已知 Ability 使用 ABILITY_PATH_SPECS 注册表提取；
    未知 Ability 回退到常见路径参数名（file_path, dir_path, working_dir）。

    Args:
        ability_name: Ability 名称
        tool_args: 工具调用参数

    Returns:
        提取到的路径列表（不含空值）
    """
    spec = ABILITY_PATH_SPECS.get(ability_name)
    if spec is not None:
        paths: list[str] = []
        alt_keys = spec.alt_keys or {}
        for key in spec.path_keys:
            value = tool_args.get(key) or tool_args.get(alt_keys.get(key, ""))
            if value and isinstance(value, str):
                paths.append(value)
        for key in spec.working_dir_keys:
            value = tool_args.get(key)
            if value and isinstance(value, str):
                paths.append(value)
        return paths
    paths = []
    for key in _FALLBACK_PATH_KEYS:
        value = tool_args.get(key)
        if value and isinstance(value, str):
            paths.append(value)
            break
    return paths


def is_subpath(path: str | Path, parent: str | Path) -> bool:
    """检查 path 是否在 parent 目录下（严格前缀匹配，防止 /tmp/data 匹配 /tmp/database）。

    使用 pathlib.Path.resolve() 解析符号链接，并用 is_relative_to() 做子路径判断，
    正确处理根目录场景（如 parent="/"）。

    Args:
        path: 待检查的路径
        parent: 父目录路径

    Returns:
        True 如果 path 是 parent 或 parent 的子路径
    """
    path_resolved = Path(path).resolve()
    parent_resolved = Path(parent).resolve()
    if parent_resolved == path_resolved:
        return True
    return path_resolved.is_relative_to(parent_resolved)


__all__ = ["is_subpath", "AbilityPathSpec", "ABILITY_PATH_SPECS", "extract_paths"]
