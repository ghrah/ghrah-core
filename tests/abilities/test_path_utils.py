# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""Ability 路径工具测试：is_subpath 和 extract_paths。"""

from __future__ import annotations

import tempfile
from pathlib import Path

from ghrah.abilities._utils import extract_paths, is_subpath


class TestIsSubpath:
    """is_subpath 严格子路径检查测试。"""

    def test_subpath_is_child(self) -> None:
        assert is_subpath("/tmp/data/file.txt", "/tmp/data") is True

    def test_same_path_is_subpath(self) -> None:
        assert is_subpath("/tmp/data", "/tmp/data") is True

    def test_not_subpath_unrelated(self) -> None:
        assert is_subpath("/tmp/data", "/etc/config") is False

    def test_not_subpath_prefix_boundary(self) -> None:
        assert is_subpath("/tmp/database", "/tmp/data") is False

    def test_root_directory_is_parent(self) -> None:
        assert is_subpath("/tmp/data", "/") is True

    def test_root_directory_equals_self(self) -> None:
        assert is_subpath("/", "/") is True

    def test_root_directory_deep_path(self) -> None:
        assert is_subpath("/a/b/c/d/e", "/") is True

    def test_relative_path_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            assert is_subpath(f"{tmpdir}/sub/../sub/file.txt", tmpdir) is True

    def test_symlink_resolved(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            real_dir = Path(tmpdir) / "real"
            real_dir.mkdir()
            link_dir = Path(tmpdir) / "link"
            link_dir.symlink_to(real_dir)
            try:
                assert is_subpath(str(link_dir / "file.txt"), str(real_dir)) is True
                assert is_subpath(str(real_dir / "file.txt"), str(link_dir)) is True
            finally:
                link_dir.unlink()

    def test_path_object_input(self) -> None:
        assert is_subpath(Path("/tmp/data/file.txt"), Path("/tmp/data")) is True
        assert is_subpath("/tmp/data/file.txt", Path("/tmp/data")) is True
        assert is_subpath(Path("/tmp/data/file.txt"), "/tmp/data") is True

    def test_trailing_slash(self) -> None:
        assert is_subpath("/tmp/data/", "/tmp/data") is True

    def test_parent_trailing_slash(self) -> None:
        assert is_subpath("/tmp/data/file.txt", "/tmp/data/") is True


class TestExtractPaths:
    """extract_paths 路径提取测试。"""

    def test_known_ability(self) -> None:
        result = extract_paths("read_file", {"file_path": "/tmp/test.txt"})
        assert result == ["/tmp/test.txt"]

    def test_unknown_ability_fallback(self) -> None:
        result = extract_paths("unknown_ability", {"file_path": "/tmp/test.txt"})
        assert result == ["/tmp/test.txt"]

    def test_move_file_two_paths(self) -> None:
        result = extract_paths(
            "move_file",
            {"source_path": "/tmp/a.txt", "destination_path": "/tmp/b.txt"},
        )
        assert result == ["/tmp/a.txt", "/tmp/b.txt"]

    def test_empty_path_ignored(self) -> None:
        result = extract_paths("read_file", {"file_path": ""})
        assert result == []

    def test_non_string_ignored(self) -> None:
        result = extract_paths("read_file", {"file_path": 123})
        assert result == []
