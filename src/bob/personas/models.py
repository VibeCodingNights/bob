"""Persona data models — event-scoped identity for a team member."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from enum import Enum


@dataclass
class WritingStyle:
    readme_voice: str       # e.g. "concise, technical, lots of code blocks"
    commit_style: str       # e.g. "conventional-commits, short subjects"
    communication_tone: str # e.g. "enthusiastic, uses exclamation marks"
    vocabulary_notes: str   # e.g. "says 'ship it' not 'deploy'"


@dataclass
class Persona:
    persona_id: str           # e.g. "alice-chen-ethglobal-2026"
    member_id: str            # FK to MemberProfile
    account_ids: list[str]    # FK to PlatformAccount(s) used for this event
    writing_style: WritingStyle
    bio_short: str            # 1-2 sentence event bio
    bio_long: str             # paragraph bio for profile pages
    avatar_url: str = ""
    event_context: str = ""   # hackathon-specific context for voice tuning


# ── YAML serialization helpers ───────────────────────────────────────


def persona_to_dict(persona: Persona) -> dict:
    """Convert a Persona to a plain dict safe for yaml.safe_dump."""
    obj = dataclasses.asdict(persona)
    return _sanitize(obj)


def persona_from_dict(data: dict) -> Persona:
    """Reconstruct a Persona from a plain dict (loaded from YAML)."""
    return Persona(
        persona_id=data["persona_id"],
        member_id=data["member_id"],
        account_ids=data.get("account_ids", []),
        writing_style=WritingStyle(**data["writing_style"]),
        bio_short=data.get("bio_short", ""),
        bio_long=data.get("bio_long", ""),
        avatar_url=data.get("avatar_url", ""),
        event_context=data.get("event_context", ""),
    )


def _sanitize(obj: object) -> object:
    """Recursively convert Enum values to their plain .value for YAML safety."""
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    return obj
