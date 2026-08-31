# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""Ability 路径工具：路径参数规格与路径安全检查。

提供 Core 和 Subject 共享的路径处理逻辑：
- AbilityPathSpec: Ability 路径参数规格声明
- ABILITY_PATH_SPECS: 已知 Ability 的路径参数映射表
- is_subpath: 严格子路径检查（防止 /tmp/data 匹配 /tmp/database）
- extract_paths: 从 tool_args 中提取 Ability 涉及的路径

此模块为公共 API，可供 ghrah.abilities 包内外直接导入。
"""

from __future__ import annotations

import os
from collections.abc import Mapping
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
    path_resolved = Path(os.path.normcase(Path(path).resolve()))
    parent_resolved = Path(os.path.normcase(Path(parent).resolve()))
    if parent_resolved == path_resolved:
        return True
    return path_resolved.is_relative_to(parent_resolved)


def resolve_fs_permission_paths(
    allowed_paths: list[str] | None,
    denied_paths: list[str] | None,
    template_vars: Mapping[str, str],
    workspace: str,
) -> tuple[list[str] | None, list[str] | None]:
    """解析 FS 权限路径：模板变量展开 + "." → workspace 重写。

    供本地实例化路径（runner）与分布式 spawn params 生成路径共用，避免两处
    各自重复实现模板展开（``{{workspace}}``/``{{persistence_dir}}``/``{{session_id}}``）
    与相对路径 ``"."`` 重写而漂移。

    Args:
        allowed_paths: 原始 allowed_paths（可能含模板变量或 "."），None 表示未配置
        denied_paths: 原始 denied_paths，None 表示未配置
        template_vars: 模板变量映射，如 ``{"workspace": "/tmp/ws", ...}``
        workspace: 工作区绝对路径，用于将 "." 重写为实际工作区

    Returns:
        ``(resolved_allowed, resolved_denied)`` 元组：
        - allowed 为空列表或 None 时返回 None（保持 FSPermissionChecker 的
          "未配置白名单"语义）
        - denied 为空列表或 None 时返回 None
    """

    def _resolve(paths: list[str] | None) -> list[str] | None:
        if not paths:
            return None
        resolved = [_expand(p, template_vars) for p in paths]
        return [workspace if p == "." else p for p in resolved]

    return _resolve(allowed_paths), _resolve(denied_paths)


def _expand(raw: str, template_vars: Mapping[str, str]) -> str:
    """展开字符串中的 ``{{var}}`` 模板变量。"""
    result = raw
    for key, value in template_vars.items():
        result = result.replace("{{" + key + "}}", value)
    return result


def resolve_relative_path(workspace: str, value: str) -> str:
    """统一相对路径解析入口：相对路径（含 ``.``）解析到 workspace 根，绝不泄漏 $PWD。

    - 绝对路径（``os.path.isabs`` 判定，含 POSIX ``/`` 与 Windows 盘符/UNC）
      原样返回（裁决归 Foxtrail/sandbox cwd 限制）；
    - ``"."`` → workspace 根（避免 os.path.join(ws, ".") 产生 ws/. 残留）；
    - 其他相对路径 → ``os.path.join(workspace, value)``。

    供 Subject AbilityRunner._resolve_paths 与 ghrah-core FS 能力共享路径解析归一，
    使相对路径永不解析到进程 $PWD。
    """
    if os.path.isabs(value):
        return value
    if value == ".":
        return workspace
    return os.path.join(workspace, value)


__all__ = [
    "is_subpath",
    "AbilityPathSpec",
    "ABILITY_PATH_SPECS",
    "extract_paths",
    "resolve_fs_permission_paths",
    "resolve_relative_path",
]
