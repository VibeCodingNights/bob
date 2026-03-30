"""Roster data models — member profiles for team composition."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class PresentationStyle(str, Enum):
    ENERGETIC = "energetic"
    METHODICAL = "methodical"
    NARRATIVE = "narrative"
    TECHNICAL = "technical"


@dataclass
class Skill:
    name: str
    domain: str
    depth: int  # 1-5
    evidence: list[str] = field(default_factory=list)  # URLs


@dataclass
class Availability:
    timezone: str  # IANA, e.g. "America/Los_Angeles"
    commitment: str = "full"  # "full" | "partial" | "presenter-only"
    blackout_dates: list[str] = field(default_factory=list)  # ISO dates


@dataclass
class HackathonEntry:
    event_name: str
    event_url: str
    track: str
    placement: str
    role: str
    feedback: str = ""


@dataclass
class MemberProfile:
    member_id: str  # stable slug, e.g. "noot"
    display_name: str
    platform_account_ids: list[str] = field(default_factory=list)  # refs to PlatformAccount
    skills: list[Skill] = field(default_factory=list)
    interests: list[str] = field(default_factory=list)
    history: list[HackathonEntry] = field(default_factory=list)
    presentation_style: PresentationStyle = PresentationStyle.TECHNICAL
    availability: Availability = field(default_factory=lambda: Availability(timezone="UTC"))
    attributes: dict[str, str] = field(default_factory=dict)
    notes: str = ""
