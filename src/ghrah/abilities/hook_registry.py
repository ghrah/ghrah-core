# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""内建 Hook 类型名 → Hook 类的注册表。

将 manifest 中声明式的 HookDef.handler 映射到具体的 Hook 类。
与 AbilityRegistry 类似，是进程级别的类方法注册表。

当前注册的内建 Hook：
- "conversation_done" → ConversationDoneHook
- "write_approval" → WriteApprovalHook
- "command_approval" → CommandApprovalHook

注意：
    注册在 ghrah.abilities.builtin.__init__ 模块加载时通过
    _register_builtin_hooks() 执行，属于模块级副作用。
    仅 import ghrah.abilities.builtin 即会触发全局状态修改。
    测试中可通过 clear() 清空注册，但需手动重新注册所需 Hook。
"""

from __future__ import annotations

import logging
from typing import Any

from ghrah.abilities.hooks import Hook

logger = logging.getLogger(__name__)

__all__ = ["BuiltinHookRegistry"]


class BuiltinHookRegistry:
    """内建 Hook 类型名 → Hook 类的注册表。"""

    _registry: dict[str, type[Hook]] = {}

    def __init__(self) -> None:
        raise TypeError(
            "BuiltinHookRegistry is a class-level registry and should not be instantiated"
        )

    @classmethod
    def register(cls, handler: str, hook_class: type[Hook]) -> None:
        """注册 Hook 类型名到 Hook 类的映射。

        Args:
            handler: Hook 类型名（如 "conversation_done"）
            hook_class: Hook 类

        Raises:
            ValueError: 如果 handler 已注册到不同的 Hook 类
        """
        existing = cls._registry.get(handler)
        if existing is not None and existing is not hook_class:
            raise ValueError(
                f"Hook handler '{handler}' already registered "
                f"to {existing.__name__}, cannot re-register to {hook_class.__name__}"
            )
        cls._registry[handler] = hook_class
        logger.debug(f"Registered hook handler: {handler} -> {hook_class.__name__}")

    @classmethod
    def create(cls, handler: str, **params: Any) -> Hook:
        """根据 Hook 类型名创建 Hook 实例。

        Args:
            handler: Hook 类型名
            **params: 传递给 Hook 构造函数的参数

        Returns:
            Hook 实例

        Raises:
            KeyError: handler 未注册
        """
        hook_class = cls._registry.get(handler)
        if hook_class is None:
            available = list(cls._registry.keys())
            raise KeyError(
                f"Unknown hook handler: '{handler}'. Available handlers: {available}"
            )
        return hook_class(**params)

    @classmethod
    def has(cls, handler: str) -> bool:
        """检查 Hook 类型名是否已注册。"""
        return handler in cls._registry

    @classmethod
    def list_handlers(cls) -> list[str]:
        """列出所有已注册的 Hook 类型名。"""
        return list(cls._registry.keys())

    @classmethod
    def clear(cls) -> None:
        """清空所有注册。

        主要用于测试。清空后需重新调用 register() 或重新 import
        ghrah.abilities.builtin 以恢复注册。
        """
        cls._registry.clear()
