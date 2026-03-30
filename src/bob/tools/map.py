"""Semantic map file operation tools.

Provides tools for reading, writing, listing, and appending to
markdown files with YAML frontmatter in a semantic map directory.
"""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import yaml


# ---------------------------------------------------------------------------
# Path security
# ---------------------------------------------------------------------------

def _validate_path(path: str) -> str | None:
    """Validate a relative path. Returns error string or None if valid."""
    if "\x00" in path:
        return f"Invalid path (null byte): {path}"
    if ".." in path.split("/") or ".." in path.split(os.sep):
        return f"Invalid path (directory traversal): {path}"
    if path.startswith("/"):
        return f"Invalid path (absolute): {path}"
    return None


def _validate_resolved_path(map_root: str, path: str) -> str | None:
    """Validate that the resolved full path stays within map_root."""
    full_path = Path(map_root) / path
    root_resolved = Path(map_root).resolve()
    try:
        if full_path.exists():
            resolved = full_path.resolve()
        else:
            # For new files, resolve the parent instead
            resolved = full_path.parent.resolve() / full_path.name
        if not resolved.is_relative_to(root_resolved):
            return f"Invalid path (escapes map root): {path}"
    except (OSError, ValueError):
        return f"Invalid path (cannot resolve): {path}"
    return None


# ---------------------------------------------------------------------------
# Frontmatter helpers
# ---------------------------------------------------------------------------

def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Parse YAML frontmatter from markdown text.

    Returns (frontmatter_dict, body). If frontmatter is missing or
    malformed, returns ({}, full_text).
    """
    if not text.startswith("---"):
        return {}, text

    end = text.find("\n---", 3)
    if end == -1:
        return {}, text

    yaml_str = text[3:end].strip()
    body = text[end + 4:].lstrip("\n")

    try:
        fm = yaml.safe_load(yaml_str)
        if not isinstance(fm, dict):
            return {}, text
        return fm, body
    except yaml.YAMLError:
        return {}, text


def _render(frontmatter: dict, body: str) -> str:
    """Render frontmatter dict and body into a markdown string."""
    fm_str = yaml.dump(frontmatter, default_flow_style=False, sort_keys=False).rstrip("\n")
    return f"---\n{fm_str}\n---\n\n{body}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def write_section(map_root: str, path: str, frontmatter: dict, body: str, owner: str) -> str:
    """Write a section of the semantic map as a markdown file with YAML frontmatter."""
    err = _validate_path(path)
    if err:
        return err

    full_path = Path(map_root) / path

    err = _validate_resolved_path(map_root, path)
    if err:
        return err

    now = _now_iso()

    if full_path.exists():
        existing_text = full_path.read_text()
        existing_fm, existing_body = _parse_frontmatter(existing_text)
        existing_owner = existing_fm.get("owner")
        if existing_owner and existing_owner != owner:
            return f"Ownership conflict: {path} owned by {existing_owner}, not {owner}"
        # Merge: existing keys preserved, new keys added/overwritten
        merged = {**existing_fm, **frontmatter}
        merged["owner"] = owner
        merged["updated_at"] = now
    else:
        merged = dict(frontmatter)
        merged["owner"] = owner
        merged["created_at"] = now
        merged["updated_at"] = now

    content = _render(merged, body)

    # Atomic write
    os.makedirs(full_path.parent, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=full_path.parent, suffix=".tmp")
    try:
        os.write(fd, content.encode())
        os.close(fd)
        os.rename(tmp_path, full_path)
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    return f"Written: {path}"


def read_section(map_root: str, path: str) -> str:
    """Read a section of the semantic map."""
    err = _validate_path(path)
    if err:
        return err

    full_path = Path(map_root) / path

    err = _validate_resolved_path(map_root, path)
    if err:
        return err

    if not full_path.exists():
        return f"Section not found: {path}"

    text = full_path.read_text()
    fm, body = _parse_frontmatter(text)

    if not fm and text.startswith("---"):
        # Malformed frontmatter
        return f"Warning: malformed frontmatter\n{text}"

    lines = [f"{k}: {v}" for k, v in fm.items()]
    lines.append("")
    lines.append(body)
    return "\n".join(lines)


def list_sections(map_root: str, prefix: str = "") -> str:
    """List all .md files under map_root/prefix with their frontmatter metadata."""
    err = _validate_path(prefix) if prefix else None
    if err:
        return err

    root = Path(map_root) / prefix if prefix else Path(map_root)

    if prefix:
        err = _validate_resolved_path(map_root, prefix)
        if err:
            return err

    if not root.exists():
        return "No sections found"

    entries = []
    for md_file in sorted(root.rglob("*.md")):
        rel = str(md_file.relative_to(Path(map_root)))
        try:
            text = md_file.read_text()
            fm, _ = _parse_frontmatter(text)
            owner = fm.get("owner", "unknown")
            updated = fm.get("updated_at", "unknown")
            entries.append(f"- {rel} (owner: {owner}, updated: {updated})")
        except Exception:
            entries.append(f"- {rel} (owner: unknown, updated: unknown)")

    if not entries:
        return "No sections found"

    return "\n".join(entries)


def append_log(map_root: str, path: str, entry: str, owner: str) -> str:
    """Append a timestamped log entry to a semantic map file."""
    err = _validate_path(path)
    if err:
        return err

    full_path = Path(map_root) / path

    err = _validate_resolved_path(map_root, path)
    if err:
        return err

    now = _now_iso()

    if not full_path.exists():
        os.makedirs(full_path.parent, exist_ok=True)
        fm = {"type": "log", "owner": owner, "created_at": now}
        content = _render(fm, "")
        full_path.write_text(content)

    log_entry = f"\n## {now} ({owner})\n\n{entry}\n"
    with open(full_path, "a") as f:
        f.write(log_entry)

    return f"Appended to: {path}"


# ---------------------------------------------------------------------------
# Anthropic tool definitions
# ---------------------------------------------------------------------------

WRITE_SECTION_TOOL = {
    "name": "write_section",
    "description": "Write a section of the semantic map as a markdown file with YAML frontmatter. Creates parent directories as needed. Enforces ownership — only the original owner can update a file.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Relative path within the map root (e.g. 'plans/goal.md')"},
            "frontmatter": {
                "type": "object",
                "description": "Key-value pairs for the YAML frontmatter block",
            },
            "body": {"type": "string", "description": "Markdown body content"},
            "owner": {"type": "string", "description": "Identity of the writer (e.g. 'situation-room')"},
        },
        "required": ["path", "frontmatter", "body", "owner"],
    },
}

READ_SECTION_TOOL = {
    "name": "read_section",
    "description": "Read a section of the semantic map. Returns frontmatter fields and body content.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Relative path within the map root"},
        },
        "required": ["path"],
    },
}

LIST_SECTIONS_TOOL = {
    "name": "list_sections",
    "description": "List all markdown sections under a prefix in the semantic map, showing owner and last-updated metadata.",
    "input_schema": {
        "type": "object",
        "properties": {
            "prefix": {
                "type": "string",
                "description": "Directory prefix to filter by (empty string for all)",
                "default": "",
            },
        },
        "required": [],
    },
}

APPEND_LOG_TOOL = {
    "name": "append_log",
    "description": "Append a timestamped log entry to a semantic map file. Creates the file with log-type frontmatter if it doesn't exist.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Relative path within the map root (e.g. 'logs/research.md')"},
            "entry": {"type": "string", "description": "The log entry text to append"},
            "owner": {"type": "string", "description": "Identity of the writer"},
        },
        "required": ["path", "entry", "owner"],
    },
}

MAP_TOOLS = [WRITE_SECTION_TOOL, READ_SECTION_TOOL, LIST_SECTIONS_TOOL, APPEND_LOG_TOOL]


def execute_map_tool(name: str, input_data: dict, map_root: str) -> str:
    """Dispatch a map tool call by name."""
    if name == "write_section":
        return write_section(
            map_root,
            input_data["path"],
            input_data.get("frontmatter", {}),
            input_data.get("body", ""),
            input_data["owner"],
        )
    elif name == "read_section":
        return read_section(map_root, input_data["path"])
    elif name == "list_sections":
        return list_sections(map_root, input_data.get("prefix", ""))
    elif name == "append_log":
        return append_log(map_root, input_data["path"], input_data["entry"], input_data["owner"])
    else:
        return f"Unknown map tool: {name}"
