# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""Ability 工厂注册表。

全局注册表，管理 Ability 类型名 → Ability 类的映射。
支持内置 Ability 和用户自定义 Ability 的动态注册。

设计原则：
- 显式优先于隐式：必须显式注册才能使用
- 组合优先于继承：Ability 通过组合注入 Agent，不依赖继承链

注意：AbilityRegistry 是进程本地注册表。在多进程场景下，
每个进程拥有独立的 _registry 副本，_register_builtin_abilities()
在每个进程中都会执行（幂等）。动态注册/反注册仅在当前进程生效，
不会自动同步到其他进程。
"""

from __future__ import annotations

import importlib
import logging
from typing import TYPE_CHECKING, Any

from ghrah.abilities.base import Ability

if TYPE_CHECKING:
    from ghrah.manifest.resolver import ResolvedAbility

logger = logging.getLogger(__name__)

__all__ = ["AbilityRegistry"]


class AbilityRegistry:
    """Ability 工厂注册表。

    管理类型名 → Ability 类的映射，支持：
    1. 内置 Ability 自动注册
    2. 用户自定义 Ability 动态注册
    3. Ability 实例化（带参数）

    注意：此类为进程本地注册表，不应被实例化。
    在多进程场景下，每个进程拥有独立副本。

    用法::

        # 注册内置 Ability（通常在 __init__.py 中自动完成）
        AbilityRegistry.register("conversation", ConversationAbility)
        AbilityRegistry.register("write_file", WriteFileAbility)

        # 注册自定义 Ability
        AbilityRegistry.register("my_ability", MyAbility)

        # 创建实例
        ability = AbilityRegistry.create("conversation")
        ability_with_params = AbilityRegistry.create("write_file", hooks=[my_hook])
    """

    _registry: dict[str, type[Ability]] = {}

    def __init__(self) -> None:
        raise TypeError("AbilityRegistry is a class-level registry and should not be instantiated")

    @classmethod
    def register(cls, ability_type: str, ability_class: type[Ability]) -> None:
        """注册 Ability 类型。

        Args:
            ability_type: Ability 类型名（唯一标识）
            ability_class: Ability 类

        Raises:
            ValueError: 如果类型名已被注册且类不同
        """
        existing = cls._registry.get(ability_type)
        if existing is not None and existing is not ability_class:
            raise ValueError(
                f"Ability type '{ability_type}' already registered "
                f"to {existing.__name__}, cannot re-register to {ability_class.__name__}"
            )
        cls._registry[ability_type] = ability_class
        logger.debug(f"Registered ability type: {ability_type} -> {ability_class.__name__}")

    @classmethod
    def unregister(cls, ability_type: str) -> None:
        """取消注册 Ability 类型。

        Args:
            ability_type: 要取消注册的类型名
        """
        cls._registry.pop(ability_type, None)
        logger.debug(f"Unregistered ability type: {ability_type}")

    @classmethod
    def create(cls, ability_type: str, **params: Any) -> Ability:
        """创建 Ability 实例。

        Args:
            ability_type: Ability 类型名
            **params: 传递给 Ability 构造函数的参数

        Returns:
            Ability 实例

        Raises:
            KeyError: 如果类型名未注册
        """
        ability_class = cls._registry.get(ability_type)
        if ability_class is None:
            available = list(cls._registry.keys())
            raise KeyError(f"Unknown ability type: '{ability_type}'. Available types: {available}")
        return ability_class(**params)

    @classmethod
    def has(cls, ability_type: str) -> bool:
        """检查 Ability 类型是否已注册。

        Args:
            ability_type: Ability 类型名

        Returns:
            是否已注册
        """
        return ability_type in cls._registry

    @classmethod
    def list_types(cls) -> list[str]:
        """列出所有已注册的 Ability 类型名。

        Returns:
            类型名列表
        """
        return list(cls._registry.keys())

    @classmethod
    def get_class(cls, ability_type: str) -> type[Ability] | None:
        """获取 Ability 类（不实例化）。

        Args:
            ability_type: Ability 类型名

        Returns:
            Ability 类，如果未注册则返回 None
        """
        return cls._registry.get(ability_type)

    @classmethod
    def clear(cls) -> None:
        """清空所有注册（主要用于测试）。"""
        cls._registry.clear()

    @classmethod
    def register_from_resolved(cls, resolved: ResolvedAbility) -> None:
        """从 ResolvedAbility 验证注册状态。

        对于 builtin 类型：验证 type 已注册（幂等）。
        对于 python 类型：验证 module_ref 可导入（不注册，延迟到实际创建时）。
        对于 sandbox/wasm 类型：暂不支持，抛出 ManifestValidationError。

        注意：
            python 类型验证会实际 import 目标模块（触发模块级代码执行）。
            如需仅检查模块是否存在而不导入，可改用 importlib.util.find_spec。

        Args:
            resolved: 解析后的能力定义

        Raises:
            ManifestValidationError: builtin type 未注册，或 sandbox/wasm 类型
        """
        from ghrah.manifest.errors import ManifestValidationError

        impl = resolved.implementation
        if impl.type == "builtin":
            if impl.handler is not None and not cls.has(impl.handler):
                raise ManifestValidationError(
                    f"Unknown builtin ability type: '{impl.handler}'. "
                    f"Available types: {cls.list_types()}"
                )
            logger.debug(
                f"Validated builtin ability: {resolved.ability_name} "
                f"(handler={impl.handler})"
            )
        elif impl.type == "python":
            if impl.module_ref:
                try:
                    importlib.import_module(impl.module_ref)
                    logger.debug(
                        f"Validated python ability module: {resolved.ability_name} "
                        f"(module={impl.module_ref})"
                    )
                except ImportError as e:
                    raise ManifestValidationError(
                        f"Cannot import module '{impl.module_ref}' "
                        f"for ability '{resolved.ability_name}': {e}"
                    ) from e
        else:
            raise ManifestValidationError(
                f"Unsupported implementation type: '{impl.type}' "
                f"for ability '{resolved.ability_name}'. "
                f"Only 'builtin' and 'python' are supported in P1."
            )
