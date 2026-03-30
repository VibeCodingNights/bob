"""Platform field registry — tracks what fields each platform requires for registration."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from platformdirs import user_data_dir

log = logging.getLogger(__name__)


@dataclass
class PlatformField:
    name: str  # normalized key, e.g. "wallet_address"
    label: str  # human-readable, e.g. "Ethereum wallet address"
    required: bool = False
    discovered: str = ""  # ISO date when first encountered
    selector_hint: str = ""  # CSS selector or label text the agent saw


def _safe_filename(name: str) -> str:
    """Sanitize a platform name for filesystem safety."""
    safe = name.replace("/", "_").replace("\\", "_").replace("..", "_")
    if not safe or safe.startswith("."):
        safe = "_" + safe
    return safe


def _field_to_dict(f: PlatformField) -> dict:
    d: dict = {"name": f.name, "label": f.label, "required": f.required}
    if f.discovered:
        d["discovered"] = f.discovered
    if f.selector_hint:
        d["selector_hint"] = f.selector_hint
    return d


def _dict_to_field(d: dict) -> PlatformField:
    return PlatformField(
        name=d["name"],
        label=d.get("label", d["name"]),
        required=d.get("required", False),
        discovered=d.get("discovered", ""),
        selector_hint=d.get("selector_hint", ""),
    )


class PlatformFieldRegistry:
    """Registry of fields that each hackathon platform asks for during registration.

    Each platform gets one YAML file: ``{platform}.yaml`` containing a list of fields.
    """

    def __init__(self, base_dir: str | Path | None = None) -> None:
        self._dir = (
            Path(base_dir) if base_dir else Path(user_data_dir("bob")) / "platform_fields"
        )
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, platform: str) -> Path:
        return self._dir / f"{_safe_filename(platform)}.yaml"

    def _load(self, platform: str) -> list[PlatformField]:
        p = self._path(platform)
        if not p.exists():
            return []
        data = yaml.safe_load(p.read_text())
        if not data or "fields" not in data:
            return []
        return [_dict_to_field(d) for d in data["fields"]]

    def _save(self, platform: str, fields: list[PlatformField]) -> None:
        p = self._path(platform)
        data = {"fields": [_field_to_dict(f) for f in fields]}
        p.write_text(yaml.safe_dump(data, sort_keys=False))

    def get_fields(self, platform: str) -> list[PlatformField]:
        """Load all known fields for a platform."""
        return self._load(platform)

    def add_field(self, platform: str, field: PlatformField) -> None:
        """Append a field (dedup by name), then save."""
        fields = self._load(platform)
        existing_names = {f.name for f in fields}
        if field.name not in existing_names:
            fields.append(field)
            self._save(platform, fields)

    def get_required_fields(self, platform: str) -> list[PlatformField]:
        """Return only the required fields for a platform."""
        return [f for f in self._load(platform) if f.required]

    def has_field(self, platform: str, field_name: str) -> bool:
        """Check whether a named field is already registered for a platform."""
        return any(f.name == field_name for f in self._load(platform))
