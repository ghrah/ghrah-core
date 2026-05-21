# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""MessageStore 单元测试。"""

from __future__ import annotations

from ghrah.context import MessageStore


class TestMessageStore:
    """MessageStore 消息存储测试。"""

    def test_initial_state(self) -> None:
        """初始状态：空消息，无快照。"""
        store = MessageStore()
        assert store.count == 0
        assert store.current_messages == []
        assert store.last_snapshot is None
        assert store.last_snapshot_iteration is None

    def test_append_single(self) -> None:
        """追加单条消息。"""
        store = MessageStore()
        store.append("msg1")
        assert store.count == 1
        assert store.current_messages == ["msg1"]

    def test_extend_multiple(self) -> None:
        """追加多条消息。"""
        store = MessageStore()
        store.extend(["msg1", "msg2", "msg3"])
        assert store.count == 3
        assert store.current_messages == ["msg1", "msg2", "msg3"]

    def test_append_and_extend(self) -> None:
        """混合使用 append 和 extend。"""
        store = MessageStore()
        store.append("msg1")
        store.extend(["msg2", "msg3"])
        store.append("msg4")
        assert store.count == 4
        assert store.current_messages == ["msg1", "msg2", "msg3", "msg4"]

    def test_current_messages_returns_copy(self) -> None:
        """返回的是副本，修改不影响内部。"""
        store = MessageStore()
        store.append("msg1")

        messages = store.current_messages
        messages.append("hacked")

        assert store.count == 1
        assert store.current_messages == ["msg1"]

    def test_count(self) -> None:
        """消息计数正确。"""
        store = MessageStore()
        assert store.count == 0

        store.append("msg1")
        assert store.count == 1

        store.extend(["msg2", "msg3"])
        assert store.count == 3


class TestMessageStoreDelta:
    """MessageStore delta 计算测试。"""

    def test_compute_delta_from_empty(self) -> None:
        """空 snapshot → 返回全部消息。"""
        store = MessageStore()
        store.extend(["msg1", "msg2"])

        delta = store.compute_delta_since([])
        assert delta == ["msg1", "msg2"]

    def test_compute_delta_none_equivalent(self) -> None:
        """snapshot 为空列表时，返回全部。"""
        store = MessageStore()
        store.extend(["msg1"])

        delta = store.compute_delta_since([])
        assert delta == ["msg1"]

    def test_compute_delta_partial(self) -> None:
        """有 snapshot → 返回增量部分（引用比较）。"""
        store = MessageStore()
        msg1 = "msg1"
        msg2 = "msg2"
        msg3 = "msg3"

        store.append(msg1)
        store.append(msg2)
        snapshot = [msg1, msg2]  # 同引用

        store.append(msg3)

        delta = store.compute_delta_since(snapshot)
        assert delta == ["msg3"]

    def test_compute_delta_no_new_messages(self) -> None:
        """无新消息 → 返回空列表。"""
        store = MessageStore()
        msg1 = "msg1"
        store.append(msg1)

        snapshot = [msg1]  # 同引用

        delta = store.compute_delta_since(snapshot)
        assert delta == []

    def test_compute_delta_reference_mismatch(self) -> None:
        """引用不匹配（snapshot 内容相同但对象不同）→ 回退为返回全部。"""
        store = MessageStore()

        class FakeMsg:
            def __init__(self, content: str) -> None:
                self.content = content

        store.append(FakeMsg("hello"))
        store.append(FakeMsg("world"))

        # 创建内容相同但引用不同的 snapshot（新对象）
        snapshot = [FakeMsg("hello"), FakeMsg("world")]

        delta = store.compute_delta_since(snapshot)
        # 引用比较失败，回退为返回全部
        assert len(delta) == 2

    def test_compute_delta_with_objects(self) -> None:
        """使用对象（模拟 LangChain BaseMessage）的引用比较。"""
        store = MessageStore()

        class FakeMessage:
            def __init__(self, content: str) -> None:
                self.content = content

        msg1 = FakeMessage("hello")
        msg2 = FakeMessage("world")
        msg3 = FakeMessage("!")

        store.append(msg1)
        store.append(msg2)
        snapshot = [msg1, msg2]  # 同引用

        store.append(msg3)

        delta = store.compute_delta_since(snapshot)
        assert len(delta) == 1
        assert delta[0] is msg3


class TestMessageStoreSnapshot:
    """MessageStore 快照管理测试。"""

    def test_should_snapshot_iteration_0(self) -> None:
        """iteration 0 → True（根节点总是快照）。"""
        store = MessageStore(snapshot_interval=5)
        assert store.should_snapshot(0) is True

    def test_should_snapshot_at_interval(self) -> None:
        """iter 5, 10 → True; iter 1,2,3,4 → False。"""
        store = MessageStore(snapshot_interval=5)

        assert store.should_snapshot(1) is False
        assert store.should_snapshot(2) is False
        assert store.should_snapshot(3) is False
        assert store.should_snapshot(4) is False
        assert store.should_snapshot(5) is True
        assert store.should_snapshot(10) is True

    def test_should_snapshot_custom_interval(self) -> None:
        """interval=3 → iter 3, 6 → True; iter 1, 2, 4 → False。"""
        store = MessageStore(snapshot_interval=3)

        assert store.should_snapshot(0) is True
        assert store.should_snapshot(1) is False
        assert store.should_snapshot(2) is False
        assert store.should_snapshot(3) is True
        assert store.should_snapshot(4) is False
        assert store.should_snapshot(6) is True

    def test_should_snapshot_disabled(self) -> None:
        """snapshot_interval=0 → 禁用定期快照（但 iter 0 仍然 True）。"""
        store = MessageStore(snapshot_interval=0)

        assert store.should_snapshot(0) is True
        assert store.should_snapshot(5) is False
        assert store.should_snapshot(10) is False

    def test_should_snapshot_negative(self) -> None:
        """snapshot_interval=-1 → 禁用定期快照。"""
        store = MessageStore(snapshot_interval=-1)

        assert store.should_snapshot(0) is True
        assert store.should_snapshot(5) is False

    def test_take_snapshot(self) -> None:
        """返回完整消息的深拷贝。"""
        store = MessageStore()
        store.extend(["msg1", "msg2"])

        snapshot = store.take_snapshot(iteration=0)

        assert snapshot == ["msg1", "msg2"]
        # 是深拷贝，修改不影响内部
        snapshot.append("hacked")
        assert store.current_messages == ["msg1", "msg2"]

    def test_take_snapshot_updates_last(self) -> None:
        """更新 last_snapshot 和 last_snapshot_iteration。"""
        store = MessageStore()
        store.extend(["msg1"])

        assert store.last_snapshot is None
        assert store.last_snapshot_iteration is None

        store.take_snapshot(iteration=5)

        assert store.last_snapshot == ["msg1"]
        assert store.last_snapshot_iteration == 5

    def test_take_snapshot_with_nested_data(self) -> None:
        """深拷贝确保嵌套数据隔离。"""
        store = MessageStore()
        store.append({"content": "msg1", "tags": ["a"]})

        snapshot = store.take_snapshot(iteration=0)
        snapshot[0]["tags"].append("b")

        # 内部不受影响
        assert store.current_messages[0]["tags"] == ["a"]

    def test_snapshot_interval_property(self) -> None:
        """snapshot_interval 属性正确。"""
        store = MessageStore(snapshot_interval=10)
        assert store.snapshot_interval == 10

    def test_last_snapshot_returns_copy(self) -> None:
        """last_snapshot 返回副本。"""
        store = MessageStore()
        store.append("msg1")
        store.take_snapshot(iteration=0)

        snap = store.last_snapshot
        assert snap is not None
        snap.append("hacked")

        # 再次获取仍然是原值
        assert store.last_snapshot == ["msg1"]


class TestMessageStoreRebuild:
    """MessageStore rebuild 测试。"""

    def test_rebuild_from_basic(self) -> None:
        """snapshot + deltas 正确重建。"""
        store = MessageStore()
        store.rebuild_from(
            snapshot=["msg1", "msg2"],
            deltas=[["msg3"], ["msg4", "msg5"]],
        )

        assert store.current_messages == ["msg1", "msg2", "msg3", "msg4", "msg5"]
        assert store.count == 5

    def test_rebuild_from_empty_snapshot(self) -> None:
        """空 snapshot + deltas 正确重建。"""
        store = MessageStore()
        store.rebuild_from(
            snapshot=[],
            deltas=[["msg1"], ["msg2"]],
        )

        assert store.current_messages == ["msg1", "msg2"]

    def test_rebuild_from_no_deltas(self) -> None:
        """snapshot + 空 deltas。"""
        store = MessageStore()
        store.rebuild_from(
            snapshot=["msg1"],
            deltas=[],
        )

        assert store.current_messages == ["msg1"]

    def test_rebuild_from_updates_last_snapshot(self) -> None:
        """rebuild 更新 last_snapshot。"""
        store = MessageStore()
        store.rebuild_from(
            snapshot=["msg1", "msg2"],
            deltas=[["msg3"]],
        )

        assert store.last_snapshot == ["msg1", "msg2"]

    def test_rebuild_clears_previous(self) -> None:
        """rebuild 覆盖之前的消息。"""
        store = MessageStore()
        store.extend(["old_msg1", "old_msg2"])

        store.rebuild_from(snapshot=["new_msg1"], deltas=[["new_msg2"]])

        assert store.current_messages == ["new_msg1", "new_msg2"]


class TestMessageStoreClear:
    """MessageStore clear 测试。"""

    def test_clear(self) -> None:
        """清空后为空。"""
        store = MessageStore()
        store.extend(["msg1", "msg2"])
        store.take_snapshot(iteration=0)

        store.clear()

        assert store.count == 0
        assert store.current_messages == []
        assert store.last_snapshot is None
        assert store.last_snapshot_iteration is None


class TestMessageStoreIntegration:
    """MessageStore 完整流程集成测试。"""

    def test_full_snapshot_flow(self) -> None:
        """模拟完整流程：append → delta → snapshot → append → delta。"""
        store = MessageStore(snapshot_interval=3)

        # iter 0: 初始化（快照）
        store.extend(["sys_prompt", "user_msg"])
        assert store.should_snapshot(0) is True
        snap0 = store.take_snapshot(0)

        # iter 1: 新增 delta（非快照）
        store.append("assistant_reply")
        assert store.should_snapshot(1) is False
        delta1 = store.compute_delta_since(snap0)
        assert delta1 == ["assistant_reply"]

        # iter 2: 新增 delta（非快照）
        store.append("tool_call")
        assert store.should_snapshot(2) is False
        snap_after_1 = snap0 + delta1  # 等效于 iter 1 后的完整消息
        delta2 = store.compute_delta_since(snap_after_1)
        assert delta2 == ["tool_call"]

        # iter 3: 快照节点
        assert store.should_snapshot(3) is True
        snap3 = store.take_snapshot(3)
        assert snap3 == ["sys_prompt", "user_msg", "assistant_reply", "tool_call"]

        # iter 4: 新增 delta
        store.append("tool_result")
        delta4 = store.compute_delta_since(snap3)
        assert delta4 == ["tool_result"]

        # 验证最终状态
        assert store.count == 5
        assert store.last_snapshot_iteration == 3

    def test_rebuild_scenario(self) -> None:
        """模拟重建场景：从快照恢复 + delta 重建。"""
        store = MessageStore(snapshot_interval=5)

        # 模拟 iter 5 的快照
        snap5 = ["m1", "m2", "m3", "m4", "m5"]
        # 模拟 iter 6-7 的 delta
        delta6 = ["m6"]
        delta7 = ["m7", "m8"]

        # 重建
        store.rebuild_from(snapshot=snap5, deltas=[delta6, delta7])

        assert store.count == 8
        assert store.current_messages == ["m1", "m2", "m3", "m4", "m5", "m6", "m7", "m8"]

        # 重建后可以继续 append
        store.append("m9")
        assert store.count == 9
