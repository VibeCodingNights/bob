"""Tests for semantic map file operation tools."""

from __future__ import annotations

from pathlib import Path

import yaml

from hackathon_finder.tools.map import (
    append_log,
    execute_map_tool,
    list_sections,
    read_section,
    write_section,
    _parse_frontmatter,
)


# ---------------------------------------------------------------------------
# write_section
# ---------------------------------------------------------------------------


class TestWriteSection:
    def test_create_new_file(self, tmp_path: Path):
        result = write_section(str(tmp_path), "test.md", {"status": "draft"}, "Hello world", "alice")
        assert result == "Written: test.md"

        text = (tmp_path / "test.md").read_text()
        fm, body = _parse_frontmatter(text)
        assert fm["status"] == "draft"
        assert fm["owner"] == "alice"
        assert "created_at" in fm
        assert "updated_at" in fm
        assert body.strip() == "Hello world"

    def test_ownership_enforcement(self, tmp_path: Path):
        write_section(str(tmp_path), "owned.md", {}, "content", "alice")
        result = write_section(str(tmp_path), "owned.md", {}, "new content", "bob")
        assert "Ownership conflict" in result
        assert "alice" in result
        assert "bob" in result

    def test_update_same_owner(self, tmp_path: Path):
        write_section(str(tmp_path), "doc.md", {"v": 1}, "first", "alice")
        result = write_section(str(tmp_path), "doc.md", {"v": 2}, "second", "alice")
        assert result == "Written: doc.md"

        text = (tmp_path / "doc.md").read_text()
        fm, body = _parse_frontmatter(text)
        assert fm["v"] == 2
        assert fm["owner"] == "alice"
        assert body.strip() == "second"

    def test_frontmatter_merge(self, tmp_path: Path):
        write_section(str(tmp_path), "merge.md", {"a": 1, "b": 2}, "body", "alice")
        write_section(str(tmp_path), "merge.md", {"b": 99, "c": 3}, "body2", "alice")

        text = (tmp_path / "merge.md").read_text()
        fm, _ = _parse_frontmatter(text)
        assert fm["a"] == 1       # preserved from original
        assert fm["b"] == 99      # overwritten by update
        assert fm["c"] == 3       # added by update

    def test_atomic_write_creates_valid_file(self, tmp_path: Path):
        # Ensure the file is written atomically (not partially)
        write_section(str(tmp_path), "atomic.md", {"key": "value"}, "body", "alice")
        text = (tmp_path / "atomic.md").read_text()
        assert text.startswith("---")
        fm, body = _parse_frontmatter(text)
        assert fm["key"] == "value"
        assert body.strip() == "body"
        # No temp files left behind
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert len(tmp_files) == 0

    def test_creates_parent_directories(self, tmp_path: Path):
        result = write_section(str(tmp_path), "deep/nested/dir/file.md", {}, "deep", "alice")
        assert result == "Written: deep/nested/dir/file.md"
        assert (tmp_path / "deep" / "nested" / "dir" / "file.md").exists()


# ---------------------------------------------------------------------------
# read_section
# ---------------------------------------------------------------------------


class TestReadSection:
    def test_read_valid_file(self, tmp_path: Path):
        write_section(str(tmp_path), "read.md", {"status": "done"}, "Some body", "alice")
        result = read_section(str(tmp_path), "read.md")
        assert "status: done" in result
        assert "owner: alice" in result
        assert "Some body" in result

    def test_read_missing_file(self, tmp_path: Path):
        result = read_section(str(tmp_path), "nope.md")
        assert result == "Section not found: nope.md"

    def test_read_malformed_yaml(self, tmp_path: Path):
        bad = "---\n: [invalid yaml\n---\n\nbody here"
        (tmp_path / "bad.md").write_text(bad)
        result = read_section(str(tmp_path), "bad.md")
        assert "Warning: malformed frontmatter" in result
        assert "body here" in result


# ---------------------------------------------------------------------------
# list_sections
# ---------------------------------------------------------------------------


class TestListSections:
    def test_list_files(self, tmp_path: Path):
        write_section(str(tmp_path), "a.md", {}, "a", "alice")
        write_section(str(tmp_path), "b.md", {}, "b", "bob")
        result = list_sections(str(tmp_path))
        assert "a.md" in result
        assert "b.md" in result
        assert "alice" in result
        assert "bob" in result

    def test_prefix_filter(self, tmp_path: Path):
        write_section(str(tmp_path), "plans/goal.md", {}, "goal", "alice")
        write_section(str(tmp_path), "logs/log.md", {}, "log", "bob")
        result = list_sections(str(tmp_path), "plans")
        assert "goal.md" in result
        assert "log.md" not in result

    def test_empty_directory(self, tmp_path: Path):
        result = list_sections(str(tmp_path))
        assert result == "No sections found"

    def test_nonexistent_prefix(self, tmp_path: Path):
        result = list_sections(str(tmp_path), "nonexistent")
        assert result == "No sections found"


# ---------------------------------------------------------------------------
# append_log
# ---------------------------------------------------------------------------


class TestAppendLog:
    def test_create_new_log(self, tmp_path: Path):
        result = append_log(str(tmp_path), "log.md", "First entry", "alice")
        assert result == "Appended to: log.md"

        text = (tmp_path / "log.md").read_text()
        fm, _ = _parse_frontmatter(text)
        assert fm["type"] == "log"
        assert fm["owner"] == "alice"
        assert "First entry" in text

    def test_append_to_existing(self, tmp_path: Path):
        append_log(str(tmp_path), "log.md", "First", "alice")
        append_log(str(tmp_path), "log.md", "Second", "bob")

        text = (tmp_path / "log.md").read_text()
        assert "First" in text
        assert "Second" in text
        assert text.count("## ") == 2  # Two timestamped headers

    def test_timestamps_present(self, tmp_path: Path):
        append_log(str(tmp_path), "log.md", "Entry", "alice")
        text = (tmp_path / "log.md").read_text()
        # ISO timestamp format: YYYY-MM-DDTHH:MM:SS
        assert "202" in text  # Year prefix check
        assert "(alice)" in text


# ---------------------------------------------------------------------------
# Path security
# ---------------------------------------------------------------------------


class TestPathSecurity:
    def test_reject_directory_traversal(self, tmp_path: Path):
        result = write_section(str(tmp_path), "../escape.md", {}, "bad", "alice")
        assert "Invalid path" in result
        assert "directory traversal" in result

    def test_reject_absolute_path(self, tmp_path: Path):
        result = write_section(str(tmp_path), "/etc/passwd", {}, "bad", "alice")
        assert "Invalid path" in result
        assert "absolute" in result

    def test_reject_null_byte(self, tmp_path: Path):
        result = write_section(str(tmp_path), "bad\x00.md", {}, "bad", "alice")
        assert "Invalid path" in result
        assert "null byte" in result

    def test_read_rejects_traversal(self, tmp_path: Path):
        result = read_section(str(tmp_path), "../secret.md")
        assert "Invalid path" in result

    def test_read_rejects_absolute(self, tmp_path: Path):
        result = read_section(str(tmp_path), "/etc/passwd")
        assert "Invalid path" in result

    def test_append_rejects_traversal(self, tmp_path: Path):
        result = append_log(str(tmp_path), "../escape.md", "bad", "alice")
        assert "Invalid path" in result

    def test_list_rejects_traversal(self, tmp_path: Path):
        result = list_sections(str(tmp_path), "../escape")
        assert "Invalid path" in result


# ---------------------------------------------------------------------------
# execute_map_tool dispatcher
# ---------------------------------------------------------------------------


class TestExecuteMapTool:
    def test_dispatch_write(self, tmp_path: Path):
        result = execute_map_tool("write_section", {
            "path": "test.md",
            "frontmatter": {"k": "v"},
            "body": "hello",
            "owner": "alice",
        }, str(tmp_path))
        assert result == "Written: test.md"

    def test_dispatch_read(self, tmp_path: Path):
        write_section(str(tmp_path), "r.md", {}, "content", "alice")
        result = execute_map_tool("read_section", {"path": "r.md"}, str(tmp_path))
        assert "content" in result

    def test_dispatch_list(self, tmp_path: Path):
        write_section(str(tmp_path), "a.md", {}, "a", "alice")
        result = execute_map_tool("list_sections", {}, str(tmp_path))
        assert "a.md" in result

    def test_dispatch_append(self, tmp_path: Path):
        result = execute_map_tool("append_log", {
            "path": "log.md",
            "entry": "test entry",
            "owner": "alice",
        }, str(tmp_path))
        assert result == "Appended to: log.md"

    def test_dispatch_unknown(self, tmp_path: Path):
        result = execute_map_tool("nonexistent", {}, str(tmp_path))
        assert "Unknown map tool" in result


# ---------------------------------------------------------------------------
# Symlink protection — _validate_resolved_path
# ---------------------------------------------------------------------------


class TestSymlinkProtection:
    def test_rejects_symlink_escape(self, tmp_path: Path):
        """A symlink inside map_root pointing outside should be blocked."""
        outside = tmp_path / "outside"
        outside.mkdir()

        map_root = tmp_path / "map"
        map_root.mkdir()

        # Create a symlink inside map_root pointing outside
        symlink = map_root / "escape"
        symlink.symlink_to(outside)

        result = write_section(str(map_root), "escape/secret.md", {}, "bad", "alice")
        assert "Invalid path" in result or "escapes map root" in result

    def test_rejects_read_through_symlink(self, tmp_path: Path):
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "secret.md").write_text("secret data")

        map_root = tmp_path / "map"
        map_root.mkdir()
        symlink = map_root / "escape"
        symlink.symlink_to(outside)

        result = read_section(str(map_root), "escape/secret.md")
        assert "Invalid path" in result or "escapes map root" in result

    def test_rejects_append_through_symlink(self, tmp_path: Path):
        """append_log through a symlink pointing outside should be blocked."""
        outside = tmp_path / "outside"
        outside.mkdir()

        map_root = tmp_path / "map"
        map_root.mkdir()

        symlink = map_root / "escape"
        symlink.symlink_to(outside)

        result = append_log(str(map_root), "escape/log.md", "bad entry", "alice")
        assert "Invalid path" in result or "escapes map root" in result

    def test_rejects_list_through_symlink(self, tmp_path: Path):
        """list_sections with a symlink prefix pointing outside should be blocked."""
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "secret.md").write_text("---\nowner: eve\n---\nsecret")

        map_root = tmp_path / "map"
        map_root.mkdir()

        symlink = map_root / "escape"
        symlink.symlink_to(outside)

        result = list_sections(str(map_root), "escape")
        # Should either return "No sections found" or block the path
        assert "Invalid path" in result or "escapes map root" in result or result == "No sections found"
