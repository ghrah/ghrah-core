# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""AbilityRegistry 单元测试。

测试 Ability 工厂注册表的核心功能：
- 注册/取消注册 Ability 类型
- 创建 Ability 实例
- 重复注册保护
- 未注册类型错误
- 内置 Ability 自动注册
"""

import pytest

from ghrah.abilities.base import Ability, ActionOutcome, ActionResult
from ghrah.abilities.context import AbilityExecutionContext
from ghrah.abilities.hooks import Hook
from ghrah.abilities.registry import AbilityRegistry

# ---- 测试用自定义 Ability ----


class MockAbility(Ability):
    """测试用 Ability。"""

    @property
    def name(self) -> str:
        return "mock"

    async def execute(self, context: AbilityExecutionContext) -> ActionResult:
        return ActionResult(outcome=ActionOutcome.SUCCESS, data={"mock": True})

    def get_hooks(self) -> list[Hook]:
        return []


class AnotherMockAbility(Ability):
    """另一个测试用 Ability。"""

    @property
    def name(self) -> str:
        return "another_mock"

    async def execute(self, context: AbilityExecutionContext) -> ActionResult:
        return ActionResult(outcome=ActionOutcome.SUCCESS, data={"another": True})

    def get_hooks(self) -> list[Hook]:
        return []


class ParamAbility(Ability):
    """带参数的测试用 Ability。"""

    def __init__(self, prefix: str = "", suffix: str = "") -> None:
        self._prefix = prefix
        self._suffix = suffix

    @property
    def name(self) -> str:
        return f"{self._prefix}param{self._suffix}"

    async def execute(self, context: AbilityExecutionContext) -> ActionResult:
        return ActionResult(outcome=ActionOutcome.SUCCESS)

    def get_hooks(self) -> list[Hook]:
        return []


# ---- 测试类 ----


class TestAbilityRegistry:
    """AbilityRegistry 核心功能测试。"""

    def setup_method(self) -> None:
        """每个测试前清空注册表。"""
        AbilityRegistry.clear()

    def test_register_and_create(self) -> None:
        """测试注册并创建 Ability 实例。"""
        AbilityRegistry.register("mock", MockAbility)

        ability = AbilityRegistry.create("mock")
        assert isinstance(ability, MockAbility)
        assert ability.name == "mock"

    def test_register_same_class_twice_is_idempotent(self) -> None:
        """测试同一类型名注册同一类两次是幂等的。"""
        AbilityRegistry.register("mock", MockAbility)
        AbilityRegistry.register("mock", MockAbility)  # 不应报错

        assert AbilityRegistry.has("mock")

    def test_register_different_class_raises_value_error(self) -> None:
        """测试同一类型名注册不同类抛出 ValueError。"""
        AbilityRegistry.register("mock", MockAbility)

        with pytest.raises(ValueError, match="already registered"):
            AbilityRegistry.register("mock", AnotherMockAbility)

    def test_create_with_params(self) -> None:
        """测试带参数创建 Ability 实例。"""
        AbilityRegistry.register("param", ParamAbility)

        ability = AbilityRegistry.create("param", prefix="pre_", suffix="_post")
        assert isinstance(ability, ParamAbility)
        assert ability.name == "pre_param_post"

    def test_create_unknown_type_raises_key_error(self) -> None:
        """测试创建未注册类型抛出 KeyError。"""
        with pytest.raises(KeyError, match="Unknown ability type"):
            AbilityRegistry.create("nonexistent")

    def test_has(self) -> None:
        """测试 has() 方法。"""
        assert not AbilityRegistry.has("mock")

        AbilityRegistry.register("mock", MockAbility)
        assert AbilityRegistry.has("mock")

    def test_list_types(self) -> None:
        """测试 list_types() 方法。"""
        assert AbilityRegistry.list_types() == []

        AbilityRegistry.register("mock", MockAbility)
        AbilityRegistry.register("another", AnotherMockAbility)

        types = AbilityRegistry.list_types()
        assert sorted(types) == ["another", "mock"]

    def test_get_class(self) -> None:
        """测试 get_class() 方法。"""
        assert AbilityRegistry.get_class("mock") is None

        AbilityRegistry.register("mock", MockAbility)
        assert AbilityRegistry.get_class("mock") is MockAbility

    def test_unregister(self) -> None:
        """测试取消注册。"""
        AbilityRegistry.register("mock", MockAbility)
        assert AbilityRegistry.has("mock")

        AbilityRegistry.unregister("mock")
        assert not AbilityRegistry.has("mock")

    def test_unregister_nonexistent_is_noop(self) -> None:
        """测试取消注册不存在的类型名是空操作。"""
        AbilityRegistry.unregister("nonexistent")  # 不应报错

    def test_clear(self) -> None:
        """测试清空注册表。"""
        AbilityRegistry.register("mock", MockAbility)
        AbilityRegistry.register("another", AnotherMockAbility)

        AbilityRegistry.clear()
        assert AbilityRegistry.list_types() == []
        assert not AbilityRegistry.has("mock")
        assert not AbilityRegistry.has("another")


class TestBuiltinAbilityRegistration:
    """测试内置 Ability 自动注册。"""

    def setup_method(self) -> None:
        """每个测试前清空注册表，然后重新注册内置 Ability。"""
        AbilityRegistry.clear()
        # 重新注册内置 Ability（模拟 import 时的自动注册）
        from ghrah.abilities import _register_builtin_abilities

        _register_builtin_abilities()

    def test_all_builtin_abilities_registered(self) -> None:
        """测试所有内置 Ability 都已注册。"""
        expected_types = [
            "conversation",
            "end_task",
            "read_file",
            "list_directory",
            "write_file",
            "edit_file",
            "move_file",
            "delete_file",
            "execute_command",
        ]
        for ability_type in expected_types:
            assert AbilityRegistry.has(ability_type), f"Missing builtin: {ability_type}"

    def test_create_conversation_ability(self) -> None:
        """测试通过 Registry 创建 ConversationAbility。"""
        from ghrah.abilities.builtin.conversation import ConversationAbility

        ability = AbilityRegistry.create("conversation")
        assert isinstance(ability, ConversationAbility)

    def test_create_end_task_ability(self) -> None:
        """测试通过 Registry 创建 EndTaskAbility。"""
        from ghrah.abilities.builtin.end_task import EndTaskAbility

        ability = AbilityRegistry.create("end_task")
        assert isinstance(ability, EndTaskAbility)

    def test_create_read_file_ability(self) -> None:
        """测试通过 Registry 创建 ReadFileAbility。"""
        from ghrah.abilities.builtin.read_file import ReadFileAbility

        ability = AbilityRegistry.create("read_file")
        assert isinstance(ability, ReadFileAbility)

    def test_create_write_file_ability(self) -> None:
        """测试通过 Registry 创建 WriteFileAbility。"""
        from ghrah.abilities.builtin.write_file import WriteFileAbility

        ability = AbilityRegistry.create("write_file")
        assert isinstance(ability, WriteFileAbility)

    def test_create_edit_file_ability(self) -> None:
        """测试通过 Registry 创建 EditFileAbility。"""
        from ghrah.abilities.builtin.edit_file import EditFileAbility

        ability = AbilityRegistry.create("edit_file")
        assert isinstance(ability, EditFileAbility)

    def test_create_list_directory_ability(self) -> None:
        """测试通过 Registry 创建 ListDirectoryAbility。"""
        from ghrah.abilities.builtin.list_directory import ListDirectoryAbility

        ability = AbilityRegistry.create("list_directory")
        assert isinstance(ability, ListDirectoryAbility)

    def test_create_move_file_ability(self) -> None:
        """测试通过 Registry 创建 MoveFileAbility。"""
        from ghrah.abilities.builtin.move_file import MoveFileAbility

        ability = AbilityRegistry.create("move_file")
        assert isinstance(ability, MoveFileAbility)

    def test_create_delete_file_ability(self) -> None:
        """测试通过 Registry 创建 DeleteFileAbility。"""
        from ghrah.abilities.builtin.delete_file import DeleteFileAbility

        ability = AbilityRegistry.create("delete_file")
        assert isinstance(ability, DeleteFileAbility)

    def test_create_execute_command_ability(self) -> None:
        """测试通过 Registry 创建 ExecuteCommandAbility。"""
        from ghrah.abilities.builtin.execute_command import ExecuteCommandAbility

        ability = AbilityRegistry.create("execute_command")
        assert isinstance(ability, ExecuteCommandAbility)

    def test_custom_ability_registration_after_builtins(self) -> None:
        """测试在内置 Ability 之后注册自定义 Ability。"""
        AbilityRegistry.register("custom", MockAbility)
        assert AbilityRegistry.has("custom")

        ability = AbilityRegistry.create("custom")
        assert isinstance(ability, MockAbility)

        # 内置 Ability 仍然可用
        assert AbilityRegistry.has("conversation")
