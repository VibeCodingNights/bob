"""YAML-based persistence for team roster profiles."""

from __future__ import annotations

import dataclasses
import tempfile
from pathlib import Path

import yaml
from platformdirs import user_data_dir

from .models import (
    Availability,
    HackathonEntry,
    MemberProfile,
    PresentationStyle,
    Skill,
)

BOB_DATA = user_data_dir("bob")


class RosterStore:
    """Read/write MemberProfile objects as individual YAML files."""

    def __init__(self, base_dir: str | Path | None = None) -> None:
        self._dir = Path(base_dir) if base_dir else Path(BOB_DATA) / "roster"
        self._dir.mkdir(parents=True, exist_ok=True)

    # ── write ────────────────────────────────────────────────────────

    @staticmethod
    def _safe_filename(member_id: str) -> str:
        """Sanitize member_id to prevent path traversal."""
        safe = member_id.replace("/", "_").replace("\\", "_").replace("..", "_")
        if not safe or safe.startswith("."):
            safe = "_" + safe
        return safe

    def save_member(self, profile: MemberProfile) -> Path:
        """Serialize *profile* to YAML and write atomically."""
        dest = self._dir / f"{self._safe_filename(profile.member_id)}.yaml"
        data = _sanitize(dataclasses.asdict(profile))
        raw = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
        # Atomic write: write to temp file then rename
        tmp = tempfile.NamedTemporaryFile(
            mode="w", dir=self._dir, suffix=".tmp", delete=False
        )
        try:
            tmp.write(raw)
            tmp.flush()
            tmp.close()
            Path(tmp.name).replace(dest)
        except BaseException:
            tmp.close()
            Path(tmp.name).unlink(missing_ok=True)
            raise
        return dest

    # ── read ─────────────────────────────────────────────────────────

    def load_member(self, member_id: str) -> MemberProfile | None:
        """Load a single member by ID, or return None if not found."""
        path = self._dir / f"{self._safe_filename(member_id)}.yaml"
        if not path.exists():
            return None
        data = yaml.safe_load(path.read_text())
        return _dict_to_profile(data)

    def list_members(self) -> list[MemberProfile]:
        """Return all stored member profiles."""
        profiles: list[MemberProfile] = []
        for path in sorted(self._dir.glob("*.yaml")):
            data = yaml.safe_load(path.read_text())
            if data:
                profiles.append(_dict_to_profile(data))
        return profiles

    # ── query ────────────────────────────────────────────────────────

    def get_available_members(
        self, start_date: str, end_date: str
    ) -> list[MemberProfile]:
        """Members whose blackout_dates do not overlap [start_date, end_date]."""
        results: list[MemberProfile] = []
        for profile in self.list_members():
            blackouts = set(profile.availability.blackout_dates)
            if not blackouts.intersection(_date_range(start_date, end_date)):
                results.append(profile)
        return results

    def get_members_by_skill(self, domain: str) -> list[MemberProfile]:
        """Members who have at least one skill in *domain*."""
        domain_lower = domain.lower()
        return [
            p
            for p in self.list_members()
            if any(s.domain.lower() == domain_lower for s in p.skills)
        ]

    # ── delete ───────────────────────────────────────────────────────

    def delete_member(self, member_id: str) -> bool:
        """Remove a member file. Returns True if it existed."""
        path = self._dir / f"{self._safe_filename(member_id)}.yaml"
        if path.exists():
            path.unlink()
            return True
        return False


# ── helpers ──────────────────────────────────────────────────────────


def _sanitize(obj: object) -> object:
    """Recursively convert Enum values to their plain .value for YAML safety."""
    from enum import Enum as _Enum

    if isinstance(obj, _Enum):
        return obj.value
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    return obj


def _dict_to_profile(data: dict) -> MemberProfile:
    """Reconstruct a MemberProfile from a plain dict (loaded from YAML)."""
    return MemberProfile(
        member_id=data["member_id"],
        display_name=data["display_name"],
        platform_account_ids=data.get("platform_account_ids", []),
        skills=[Skill(**s) for s in data.get("skills", [])],
        interests=data.get("interests", []),
        history=[HackathonEntry(**h) for h in data.get("history", [])],
        presentation_style=PresentationStyle(data.get("presentation_style", "technical")),
        availability=Availability(**data.get("availability", {"timezone": "UTC"})),
        attributes={k: str(v) for k, v in data.get("attributes", {}).items()},
        notes=data.get("notes", ""),
    )


def _date_range(start: str, end: str) -> set[str]:
    """Generate the set of ISO date strings between *start* and *end* inclusive."""
    from datetime import date, timedelta

    cur = date.fromisoformat(start)
    stop = date.fromisoformat(end)
    dates: set[str] = set()
    while cur <= stop:
        dates.add(cur.isoformat())
        cur += timedelta(days=1)
    return dates
